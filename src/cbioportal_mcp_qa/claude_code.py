"""Answer questions with headless Claude Code standing in for the deployed agent.

The deployed agent's own instructions are the system prompt, the only tools are the same two MCP servers
(no Claude Code built-ins), and extended thinking is off to match the deployment. It runs on the Claude
subscription of the configured Claude home (CLAUDE_CONFIG_DIR) instead of per-token Bedrock billing, so it
is the cheap loop for iterating on prompts and guides; the Agents API runner remains the release check.
"""

import asyncio
import json
import os
import tempfile
import time

from .agent import AgentReply
from .config import MODELS
from .traces import ToolCall, TraceStats

SERVER_NAMES = ("cbioportal-database", "cbioportal-navigator")


def mcp_config(database_url: str, navigator_url: str) -> dict:
    headers = {"x-user-id": "cbioportal-mcp-qa", "x-user-email": "cbioportal-mcp-qa@localhost"}
    return {
        "mcpServers": {
            "cbioportal-database": {"type": "http", "url": database_url, "headers": headers},
            "cbioportal-navigator": {"type": "http", "url": navigator_url, "headers": headers},
        }
    }


def claude_args(question: str, model: str, system_prompt: str, mcp_config_path: str) -> list[str]:
    return [
        "claude",
        "-p",
        question,
        "--model",
        MODELS[model].claude_code_id,
        "--system-prompt",
        system_prompt,
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        mcp_config_path,
        "--allowedTools",
        *(f"mcp__{name}" for name in SERVER_NAMES),
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]


def short_tool_name(name: str) -> str:
    for server in SERVER_NAMES:
        name = name.removeprefix(f"mcp__{server}__")
    return name


def parse_stream(lines: list[str], started: float, latency_s: float) -> AgentReply:
    """Turn `claude -p --output-format stream-json` events into a reply with its tool-call trace."""
    events = [json.loads(line) for line in lines if line.strip().startswith("{")]
    calls: dict[str, ToolCall] = {}
    message_ids: set[str] = set()
    models: set[str] = set()
    for event in events:
        message = event.get("message") or {}
        if event.get("type") == "assistant":
            message_ids.add(message.get("id") or str(len(message_ids)))
            if message.get("model"):
                models.add(message["model"])
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    calls[block["id"]] = ToolCall(short_tool_name(block["name"]), True)
        elif event.get("type") == "user":
            for block in message.get("content") or []:
                if (
                    block.get("type") == "tool_result"
                    and block.get("is_error")
                    and block["tool_use_id"] in calls
                ):
                    content = block.get("content")
                    text = content if isinstance(content, str) else json.dumps(content)
                    calls[block["tool_use_id"]].ok = False
                    calls[block["tool_use_id"]].error = text[:500]
    result = next((e for e in events if e.get("type") == "result"), None)
    trace = TraceStats("", "", len(message_ids), list(calls.values()), sorted(models))
    if result is None or result.get("is_error"):
        error = (result or {}).get("result") or (result or {}).get("subtype") or "no result event"
        return AgentReply("", None, None, str(error)[:2000], latency_s, started, trace=trace.to_dict())
    usage = result.get("usage") or {}
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    return AgentReply(
        answer=result.get("result") or "",
        response_id=None,
        status=200,
        error=None,
        latency_s=latency_s,
        started_at=started,
        prompt_tokens=(usage.get("input_tokens") or 0) + cache_read + cache_write,
        completion_tokens=usage.get("output_tokens"),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        trace=trace.to_dict(),
    )


class ClaudeCodeClient:
    """Same interface as AgentClient: `await ask(question, model)` returns an AgentReply (with its trace)."""

    def __init__(
        self,
        system_prompt: str,
        database_url: str,
        navigator_url: str,
        timeout_s: float = 900.0,
        retries: int = 1,
    ):
        self.system_prompt = system_prompt
        self.timeout_s = timeout_s
        self.retries = retries
        self._workdir = tempfile.TemporaryDirectory(prefix="mcp-qa-claude-")
        self.mcp_config_path = os.path.join(self._workdir.name, "mcp.json")
        with open(self.mcp_config_path, "w") as f:
            json.dump(mcp_config(database_url, navigator_url), f)
        # Thinking off to match the deployed agent (thinking=false); CLAUDE_CONFIG_DIR passes through.
        self.env = {**os.environ, "MAX_THINKING_TOKENS": "0"}

    async def aclose(self) -> None:
        self._workdir.cleanup()

    async def ask(self, question: str, model: str) -> AgentReply:
        started = time.time()
        for attempt in range(self.retries + 1):
            reply = await self._run(question, model, started)
            if reply.error is None:
                return reply
            if attempt < self.retries:
                await asyncio.sleep(10)
        return reply

    async def _run(self, question: str, model: str, started: float) -> AgentReply:
        t0 = time.monotonic()
        # An empty working directory keeps project CLAUDE.md files out of the context.
        proc = await asyncio.create_subprocess_exec(
            *claude_args(question, model, self.system_prompt, self.mcp_config_path),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workdir.name,
            env=self.env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return AgentReply(
                "", None, None, f"timed out after {self.timeout_s:.0f}s", time.monotonic() - t0, started
            )
        reply = parse_stream(stdout.decode().splitlines(), started, time.monotonic() - t0)
        if reply.error and proc.returncode:
            reply.error = f"{reply.error} (exit {proc.returncode}: {stderr.decode()[-500:]})"
        return reply
