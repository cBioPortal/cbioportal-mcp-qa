"""Answer questions with a model behind an OpenAI-compatible chat endpoint (Ollama's /v1, vLLM), running the
tool-calling loop here against the same two MCP servers the deployed agent uses.

The system prompt is the deployed agent's instructions followed by the MCP servers' own instructions (LibreChat's
order with `serverInstructions: true`). Tools are the servers' tools as listed by them, under their own names.
Self-hosted models are priced at $0.
"""

import asyncio
import hashlib
import json
import re
import time
from urllib.parse import urlparse

import httpx

from .agent import RETRYABLE_STATUS, AgentReply
from .agent_prompt import prompt_fingerprint
from .claude_code import HEADERS, NAVIGATOR_SERVER, RESULT_CHARS
from .config import MODELS
from .mcp_http import AsyncMCPSession, MCPToolError
from .persist import write_text
from .redact import describe_error, redact
from .traces import ToolCall, TraceStats, excerpt

DATABASE_SERVER = "cbioportal-database"
# Tool rounds before the model must answer without tools (LibreChat's agents stop at a recursion limit too).
MAX_TOOL_ROUNDS = 25
# No tokenizer reads more than this many characters per token on average (prompts and JSON run ~3-4.5): a
# smaller count than the characters sent allow means the server truncated the prompt.
MAX_CHARS_PER_TOKEN = 6
THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
SERVER_INSTRUCTIONS_DELIVERY = "openai runner (appended to the system prompt, LibreChat order)"


def system_prompt_with_servers(system_prompt: str, instructions: list[str]) -> str:
    """The agent instructions, then each server's instructions, separated by blank lines."""
    return "\n\n".join([system_prompt, *instructions])


def openai_tools(servers: dict[str, list[dict]]) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """OpenAI function tools for every MCP tool, and the server and MCP name behind each function name. A name
    two servers share is prefixed with its server."""
    names = [t["name"] for tools in servers.values() for t in tools]
    tools, route = [], {}
    for server, listed in servers.items():
        for t in listed:
            name = t["name"] if names.count(t["name"]) == 1 else f"{server}__{t['name']}"
            name = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64]
            route[name] = (server, t["name"])
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": t.get("description") or "",
                        "parameters": schema,
                    },
                }
            )
    return tools, route


def answer_text(message: dict) -> str:
    """The reply's text without any inline reasoning (`<think>` blocks)."""
    return THINK_BLOCK.sub("", message.get("content") or "").strip()


def format_turns(turns: list[tuple[str, str, str]], answer: str, status: str) -> str:
    """A transcript in the claude-code runner's format: ▶ tool + arguments, ◀ result / ✗ error, ═ answer."""
    out = []
    for name, args, (result, is_error) in turns:
        out.append(f"▶ {name}\n{args}\n")
        more = f" … ({len(result) - RESULT_CHARS} more chars)" if len(result) > RESULT_CHARS else ""
        out.append(f"{'✗ error' if is_error else '◀ result'}\n{result[:RESULT_CHARS]}{more}\n")
    out.append(f"═ answer ({status})\n{answer}\n")
    return redact("\n".join(out))


class OpenAIChatClient:
    """Same interface as AgentClient: `await ask(question, model)` returns an AgentReply (with its trace).

    `start()` connects the MCP servers and lists their tools; call it before asking."""

    def __init__(
        self,
        system_prompt: str,
        base_url: str,
        database_url: str,
        navigator_url: str,
        database_token=None,
        api_key: str = "",
        served_model: str | None = None,
        reasoning_effort: str | None = None,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        timeout_s: float = 3600.0,
        request_timeout_s: float = 1200.0,
        retries: int = 2,
        transcript_dir=None,
    ):
        self.agent_prompt = system_prompt
        self.base_url = base_url.rstrip("/")
        self.served_model = served_model
        self.reasoning_effort = reasoning_effort
        self.max_tool_rounds = max_tool_rounds
        self.timeout_s = timeout_s
        self.retries = retries
        self.transcript_dir = transcript_dir
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(request_timeout_s, connect=30.0),
        )
        self.servers = {
            DATABASE_SERVER: AsyncMCPSession(database_url, HEADERS, database_token),
            NAVIGATOR_SERVER: AsyncMCPSession(navigator_url, HEADERS),
        }
        self.urls = {DATABASE_SERVER: database_url, NAVIGATOR_SERVER: navigator_url}
        self.tools: list[dict] = []
        self.route: dict[str, tuple[str, str]] = {}
        self.system_prompt = system_prompt
        self.server_instructions: dict[str, str | None] = {}
        self.server_info: dict[str, dict] = {}
        self.context_window: int | None = None
        self.backend: dict = {}

    async def start(self) -> None:
        listed = {}
        for name, mcp in self.servers.items():
            self.server_info[name] = await mcp.initialize()
            self.server_instructions[name] = mcp.instructions
            listed[name] = await mcp.list_tools()
        self.tools, self.route = openai_tools(listed)
        self.system_prompt = system_prompt_with_servers(
            self.agent_prompt, [i for i in self.server_instructions.values() if i]
        )
        self.backend = await self._ollama_info()

    async def _ollama_info(self) -> dict:
        """Ollama's version and the served model's context window, when the server is Ollama (best effort)."""
        root = self.base_url.removesuffix("/v1")
        info: dict = {}
        try:
            version = await self.http.get(f"{root}/api/version")
            if version.status_code != 200:
                return info
            info["ollama"] = version.json().get("version")
            shown = await self.http.post(f"{root}/api/show", json={"model": self.served_model or ""})
            if shown.status_code == 200 and self.served_model:
                params = shown.json().get("parameters") or ""
                if m := re.search(r"^num_ctx\s+(\d+)", params, re.MULTILINE):
                    self.context_window = int(m.group(1))
        except (httpx.HTTPError, ValueError):
            pass
        return info

    def model_name(self, model: str) -> str:
        return self.served_model or MODELS[model].openai_id

    def describe(self) -> dict:
        host = urlparse(self.base_url)
        return {
            "base_url": f"{host.scheme}://{host.hostname}:{host.port or ''}{host.path}",
            "served_model": self.served_model,
            "backend": self.backend,
            "context_window": self.context_window,
            "reasoning_effort": self.reasoning_effort,
            "max_tool_rounds": self.max_tool_rounds,
            "tools": {name: f"{server}:{tool}" for name, (server, tool) in self.route.items()},
            "mcp_servers": {
                name: {
                    "url": self.urls[name],
                    **{k: self.server_info[name].get(k) for k in ("name", "version")},
                }
                for name in self.servers
            },
            "prompt": {
                "system_prompt": prompt_fingerprint(self.agent_prompt),
                "server_instructions": {
                    k: prompt_fingerprint(v) if v else None for k, v in self.server_instructions.items()
                },
                "server_instructions_delivery": SERVER_INSTRUCTIONS_DELIVERY,
                "combined": prompt_fingerprint(self.system_prompt),
            },
        }

    async def aclose(self) -> None:
        await self.http.aclose()
        for mcp in self.servers.values():
            await mcp.aclose()

    async def ask(self, question: str, model: str, history: tuple[dict, ...] = ()) -> AgentReply:
        started = time.time()
        t0 = time.monotonic()
        state = {
            "calls": [],
            "turns": [],
            "llm_calls": 0,
            "tool_rounds": 0,
            "usage": [0, 0, 0],
            "max_prompt": 0,
        }
        try:
            answer, status = await asyncio.wait_for(
                self._loop(question, model, history, state), self.timeout_s
            )
            error = None
        except TimeoutError:
            answer, status, error = "", None, f"timed out after {self.timeout_s:.0f}s"
        except _RequestFailed as exc:
            answer, status, error = "", exc.status, exc.message  # the endpoint's HTTP status, if it answered
        except (httpx.HTTPError, MCPToolError, RuntimeError) as exc:
            answer, status, error = "", None, describe_error(exc, 2000)
        latency = time.monotonic() - t0
        trace = TraceStats(
            "",
            "",
            state["llm_calls"],
            state["calls"],
            [self.model_name(model)],
            tool_rounds=state["tool_rounds"],
        ).to_dict()
        trace["max_prompt_tokens"] = state["max_prompt"]
        trace["context_window"] = self.context_window
        if self.transcript_dir is not None:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha1(f"{model}:{question}:{started}".encode()).hexdigest()[:12] + ".txt"
            text = format_turns(
                state["turns"], answer if error is None else error, "success" if error is None else "error"
            )
            write_text(self.transcript_dir / name, f"Q ({model}): {question}\n\n{text}")
            trace["url"] = f"{self.transcript_dir.name}/{name}"
        prompt_tokens, completion_tokens, cached = state["usage"]
        return AgentReply(
            answer=answer,
            response_id=None,
            status=status,
            error=error,
            latency_s=latency,
            started_at=started,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cached,
            cache_write_tokens=0,
            trace=trace,
        )

    async def _loop(
        self, question: str, model: str, history: tuple[dict, ...], state: dict
    ) -> tuple[str, int]:
        messages = [
            {"role": "system", "content": self.system_prompt},
            *({"role": t["role"], "content": t["content"]} for t in history),
            {"role": "user", "content": question},
        ]
        while True:
            with_tools = state["tool_rounds"] < self.max_tool_rounds
            message = await self._complete(model, messages, with_tools, state)
            calls = message.get("tool_calls") or []
            if not calls or not with_tools:
                return answer_text(message), 200
            state["tool_rounds"] += 1
            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
            results = await asyncio.gather(*(self._call(c, state) for c in calls))
            for call, result in zip(calls, results, strict=True):
                messages.append({"role": "tool", "tool_call_id": call.get("id") or "", "content": result})

    async def _complete(self, model: str, messages: list[dict], with_tools: bool, state: dict) -> dict:
        body: dict = {"model": self.model_name(model), "messages": messages, "stream": False}
        if with_tools and self.tools:
            body["tools"] = self.tools
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        for attempt in range(self.retries + 1):
            try:
                resp = await self.http.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                failure = _RequestFailed(None, describe_error(exc, 2000))
            else:
                if resp.status_code == 200:
                    break
                failure = _RequestFailed(resp.status_code, redact(resp.text)[:2000])
                if resp.status_code not in RETRYABLE_STATUS:
                    raise failure
            if attempt == self.retries:
                raise failure
            await asyncio.sleep(10 * (attempt + 1))
        data = resp.json()
        state["llm_calls"] += 1
        usage = data.get("usage") or {}
        prompt = usage.get("prompt_tokens") or 0
        state["usage"][0] += prompt
        state["usage"][1] += usage.get("completion_tokens") or 0
        state["usage"][2] += (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        state["max_prompt"] = max(state["max_prompt"], prompt)
        # Chat templates differ in where they render the tools (Llama 3.1's only with a user message last), so
        # they only count when every template shows them.
        sent = len(json.dumps(messages, ensure_ascii=False))
        if messages[-1]["role"] == "user":
            sent += len(json.dumps(body.get("tools", [])))
        if prompt * MAX_CHARS_PER_TOKEN < sent or (self.context_window and prompt >= self.context_window):
            # Ollama silently drops the oldest tokens (the system prompt first) to fit its window, and reports
            # the truncated count: an answer to what's left isn't comparable.
            raise RuntimeError(
                f"prompt truncated by the server: {sent} characters sent, {prompt} prompt tokens counted"
                + (f", window {self.context_window}" if self.context_window else "")
                + " (raise num_ctx)"
            )
        return (data.get("choices") or [{}])[0].get("message") or {}

    async def _call(self, call: dict, state: dict) -> str:
        """Run one tool call; the result (or the error) is what the model sees next."""
        fn = call.get("function") or {}
        name, raw = fn.get("name") or "", fn.get("arguments") or "{}"
        record = ToolCall(self.route.get(name, ("", name))[1], True, input=excerpt(redact(str(raw))))
        state["calls"].append(record)
        pretty = str(raw)
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(args, dict):
                raise ValueError("arguments are not a JSON object")
            pretty = json.dumps(args, indent=1, ensure_ascii=False)
        except ValueError as exc:
            text, is_error = f"Invalid tool arguments: {exc}", True
        else:
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
        return text


class _RequestFailed(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
