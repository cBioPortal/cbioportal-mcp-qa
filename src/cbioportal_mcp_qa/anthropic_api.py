"""Answer and grade with Claude through the Anthropic SDK, the tool-calling loop run here: the CI runner.

No Claude Code, subscription or kubectl. Credentials are the environment's, auto-detected:

- `anthropic`: the Claude API with `ANTHROPIC_API_KEY`;
- `bedrock`: Amazon Bedrock with AWS credentials (an access key, a profile, or a web identity token / role from
  GitHub OIDC), in `AWS_REGION`.

`ANTHROPIC_API_KEY` wins when both are present; `QA_PROVIDER` (or `--provider`) picks one explicitly.

The system prompt is an agent prompt from a file (optional), followed by each MCP server's own instructions as
it serves them — LibreChat's order with `serverInstructions: true`, which is how the deployed chat gets the
database MCP's `system-prompt.md`. So a candidate server's prompt change is part of what is tested. Tools are
the servers' tools as they list them. Thinking stays off, as in the deployment.
"""

import asyncio
import hashlib
import json
import os
import time

import httpx

from .agent import AgentReply
from .agent_prompt import prompt_fingerprint
from .claude_code import HEADERS, NAVIGATOR_SERVER
from .config import MODELS, _model_family
from .grade import JUDGE_SCHEMA, BaseJudge
from .mcp_http import AsyncMCPSession, MCPToolError
from .openai_chat import (
    DATABASE_SERVER,
    MAX_TOOL_ROUNDS,
    format_turns,
    openai_tools,
    system_prompt_with_servers,
)
from .persist import write_text
from .redact import describe_error, redact
from .traces import ToolCall, TraceStats, excerpt

PROVIDERS = ("auto", "anthropic", "bedrock")
# Any of these means boto3 can find AWS credentials (static keys, a profile, GitHub OIDC's web identity, ECS/EKS).
AWS_CREDENTIAL_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_PROFILE",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
)
DEFAULT_AGENT_MODEL = "haiku"  # Haiku 4.5: the model prod's default spec runs
DEFAULT_JUDGE_MODEL = "sonnet-4.6"
MAX_TOKENS = 8192
SERVER_INSTRUCTIONS_DELIVERY = "api runner (appended to the system prompt, LibreChat order)"


class NoCredentials(RuntimeError):
    pass


def detect_provider(requested: str | None = None, env=None) -> str:
    """`anthropic` or `bedrock`: the one asked for (`--provider`, else QA_PROVIDER), else whichever the environment
    has credentials for, the Claude API first."""
    env = os.environ if env is None else env
    choice = (requested or env.get("QA_PROVIDER") or "auto").strip().lower()
    if choice not in PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}, got {choice!r}")
    if choice != "auto":
        return choice
    if env.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if any(env.get(v) for v in AWS_CREDENTIAL_VARS):
        return "bedrock"
    raise NoCredentials(
        "no model credentials: set ANTHROPIC_API_KEY (Claude API) or AWS credentials with Bedrock access "
        "(AWS_ACCESS_KEY_ID, AWS_PROFILE, or a role via GitHub OIDC)"
    )


def model_id(model: str, provider: str) -> str:
    """The provider's id for a model key (`haiku`, `sonnet-4.6`); any other string is taken as an id already."""
    if model not in MODELS:
        return model
    known = MODELS[model]
    if provider == "anthropic":
        # The Claude API id is the Bedrock id's model family (`us.anthropic.claude-sonnet-4-6` -> `claude-sonnet-4-6`).
        found = known.claude_code_id or (_model_family(known.bedrock_id) if known.bedrock_id else None)
    else:
        found = known.bedrock_id
    if not found:
        raise ValueError(f"{model} ({known.label}) has no {provider} model id")
    return found


def make_client(provider: str, aws_region: str, asynchronous: bool, max_retries: int = 4):
    import anthropic

    if provider == "anthropic":
        cls = anthropic.AsyncAnthropic if asynchronous else anthropic.Anthropic
        return cls(max_retries=max_retries)
    cls = anthropic.AsyncAnthropicBedrock if asynchronous else anthropic.AnthropicBedrock
    return cls(aws_region=aws_region, max_retries=max_retries)


def anthropic_tools(servers: dict[str, list[dict]]) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """Messages API tools for every MCP tool (same naming as the openai runner), the last one marked as the end
    of the cached prefix (tools, then system)."""
    functions, route = openai_tools(servers)
    tools = [
        {
            "name": f["function"]["name"],
            "description": f["function"]["description"],
            "input_schema": f["function"]["parameters"],
        }
        for f in functions
    ]
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools, route


class AnthropicAPIClient:
    """Same interface as AgentClient: `await ask(question, model)` returns an AgentReply (with its trace).

    `start()` connects the MCP servers and lists their tools; call it before asking."""

    def __init__(
        self,
        system_prompt: str,
        database_url: str,
        navigator_url: str,
        provider: str,
        aws_region: str = "us-east-1",
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        timeout_s: float = 900.0,
        transcript_dir=None,
        client=None,
    ):
        self.agent_prompt = system_prompt
        self.provider = provider
        self.aws_region = aws_region
        self.max_tool_rounds = max_tool_rounds
        self.timeout_s = timeout_s
        self.transcript_dir = transcript_dir
        self.client = client or make_client(provider, aws_region, asynchronous=True)
        self.servers = {
            DATABASE_SERVER: AsyncMCPSession(database_url, HEADERS),
            NAVIGATOR_SERVER: AsyncMCPSession(navigator_url, HEADERS),
        }
        self.urls = {DATABASE_SERVER: database_url, NAVIGATOR_SERVER: navigator_url}
        self.tools: list[dict] = []
        self.route: dict[str, tuple[str, str]] = {}
        self.system_prompt = system_prompt
        self.server_instructions: dict[str, str | None] = {}
        self.server_info: dict[str, dict] = {}

    async def start(self) -> None:
        listed = {}
        for name, mcp in self.servers.items():
            self.server_info[name] = await mcp.initialize()
            self.server_instructions[name] = mcp.instructions
            listed[name] = await mcp.list_tools()
        self.tools, self.route = anthropic_tools(listed)
        parts = [i for i in self.server_instructions.values() if i]
        self.system_prompt = (
            system_prompt_with_servers(self.agent_prompt, parts) if self.agent_prompt else "\n\n".join(parts)
        )

    def describe(self) -> dict:
        return {
            "provider": self.provider,
            "aws_region": self.aws_region if self.provider == "bedrock" else None,
            "max_tool_rounds": self.max_tool_rounds,
            "tools": {name: f"{server}:{tool}" for name, (server, tool) in self.route.items()},
            "mcp_servers": {
                name: {
                    "url": self.urls[name],
                    **{k: self.server_info.get(name, {}).get(k) for k in ("name", "version")},
                }
                for name in self.servers
            },
            "prompt": {
                "system_prompt": prompt_fingerprint(self.agent_prompt) if self.agent_prompt else None,
                "server_instructions": {
                    k: prompt_fingerprint(v) if v else None for k, v in self.server_instructions.items()
                },
                "server_instructions_delivery": SERVER_INSTRUCTIONS_DELIVERY,
                "combined": prompt_fingerprint(self.system_prompt),
            },
        }

    async def aclose(self) -> None:
        await self.client.close()
        for mcp in self.servers.values():
            await mcp.aclose()

    async def ask(self, question: str, model: str, history: tuple[dict, ...] = ()) -> AgentReply:
        started = time.time()
        t0 = time.monotonic()
        state = {"calls": [], "turns": [], "llm_calls": 0, "tool_rounds": 0, "usage": [0, 0, 0, 0]}
        status = None
        try:
            answer = await asyncio.wait_for(self._loop(question, model, history, state), self.timeout_s)
            status, error = 200, None
        except TimeoutError:
            answer, error = "", f"timed out after {self.timeout_s:.0f}s"
        except Exception as exc:  # noqa: BLE001 - any failure is this answer's, never the whole run's
            answer, error = "", describe_error(exc, 2000)
            status = getattr(exc, "status_code", None)
        latency = time.monotonic() - t0
        trace = TraceStats(
            "",
            "",
            state["llm_calls"],
            state["calls"],
            [model_id(model, self.provider)],
            tool_rounds=state["tool_rounds"],
        ).to_dict()
        if self.transcript_dir is not None:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha1(f"{model}:{question}:{started}".encode()).hexdigest()[:12] + ".txt"
            text = format_turns(
                state["turns"], answer if error is None else error, "success" if error is None else "error"
            )
            write_text(self.transcript_dir / name, f"Q ({model}): {question}\n\n{text}")
            trace["url"] = f"{self.transcript_dir.name}/{name}"
        uncached, output, cache_read, cache_write = state["usage"]
        return AgentReply(
            answer=answer,
            response_id=None,
            status=status,
            error=error,
            latency_s=latency,
            started_at=started,
            # Like the Agents API's prompt_tokens: every input token, cached or not.
            prompt_tokens=uncached + cache_read + cache_write,
            completion_tokens=output,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            trace=trace,
        )

    async def _loop(self, question: str, model: str, history: tuple[dict, ...], state: dict) -> str:
        messages = [
            *({"role": t["role"], "content": t["content"]} for t in history),
            {"role": "user", "content": question},
        ]
        system = [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}]
        while True:
            with_tools = state["tool_rounds"] < self.max_tool_rounds
            kwargs = {}
            if self.tools:
                # Tools stay defined once the conversation has tool calls; the last round just can't call them.
                kwargs["tools"] = self.tools
                if not with_tools:
                    kwargs["tool_choice"] = {"type": "none"}
            response = await self.client.messages.create(
                model=model_id(model, self.provider),
                max_tokens=MAX_TOKENS,
                system=system,
                messages=messages,
                **kwargs,
            )
            state["llm_calls"] += 1
            usage = response.usage
            state["usage"][0] += usage.input_tokens or 0
            state["usage"][1] += usage.output_tokens or 0
            state["usage"][2] += getattr(usage, "cache_read_input_tokens", 0) or 0
            state["usage"][3] += getattr(usage, "cache_creation_input_tokens", 0) or 0
            calls = [b for b in response.content if b.type == "tool_use"]
            text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason != "tool_use" or not calls:
                if response.stop_reason == "refusal":
                    raise RuntimeError("the model refused to answer (stop_reason refusal)")
                return text
            state["tool_rounds"] += 1
            messages.append(
                {"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in response.content]}
            )
            results = await asyncio.gather(*(self._call(c, state) for c in calls))
            # Every result in one user message, so the model keeps calling tools in parallel.
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": c.id,
                            "content": text or "(empty)",
                            "is_error": err,
                        }
                        for c, (text, err) in zip(calls, results, strict=True)
                    ],
                }
            )

    async def _call(self, call, state: dict) -> tuple[str, bool]:
        """Run one tool call; the result (or the error) is what the model sees next."""
        name, args = call.name, call.input if isinstance(call.input, dict) else {}
        pretty = json.dumps(args, indent=1, ensure_ascii=False)
        record = ToolCall(self.route.get(name, ("", name))[1], True, input=excerpt(redact(json.dumps(args))))
        state["calls"].append(record)
        if name not in self.route:
            text, is_error = f"Unknown tool {name!r}. Available: {', '.join(self.route)}", True
        else:
            server, tool = self.route[name]
            try:
                text, is_error = await self.servers[server].call_tool(tool, args)
            except (MCPToolError, httpx.HTTPError) as exc:
                text, is_error = f"Tool call failed: {describe_error(exc, 1000)}", True
        record.result = excerpt(redact(text))
        if is_error:
            record.ok = False
            record.error = redact(text)[:500]
        state["turns"].append((record.name, pretty, (text, is_error)))
        return text, is_error


class APIJudge(BaseJudge):
    """The judge through the Anthropic SDK on either provider, at temperature 0, with structured output. Its grades
    record the provider's model id (`claude-sonnet-4-6` on the Claude API, `us.anthropic.claude-sonnet-4-6` on
    Bedrock), so `compare` keeps the two apart."""

    def __init__(self, model: str, provider: str, aws_region: str = "us-east-1", client=None):
        self.provider = provider
        self.model = model_id(model, provider)
        self.client = client or make_client(provider, aws_region, asynchronous=False)

    def verdict(self, prompt: str) -> tuple[dict, int, int]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            extra_body={"temperature": 0},
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        )
        result = json.loads(next(b.text for b in response.content if b.type == "text"))
        return result, response.usage.input_tokens, response.usage.output_tokens
