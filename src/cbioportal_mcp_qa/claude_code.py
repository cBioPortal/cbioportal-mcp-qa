"""Answer questions with headless Claude Code standing in for the deployed agent.

The deployed agent's own instructions are the system prompt, the only tools are the same two MCP servers
(no Claude Code built-ins), and extended thinking is off to match the deployment. It runs on the Claude
subscription of the configured Claude home (CLAUDE_CONFIG_DIR) instead of per-token Bedrock billing, so it
is the cheap loop for iterating on prompts and guides; the Agents API runner remains the release check.
"""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent import AgentReply
from .config import MODELS
from .traces import ToolCall, TraceStats

# Deliberately unlike the database connector's "claude_ai_cBioPortal_MCP": with two cBioPortal-looking tool
# prefixes the model mixes them up and calls navigator tools under the connector's name.
NAVIGATOR_SERVER = "navigator"
PROBE_ATTEMPTS = 4
CONNECTOR_ATTEMPTS = 4
HEADERS = {"x-user-id": "cbioportal-mcp-qa", "x-user-email": "cbioportal-mcp-qa@localhost"}


@dataclass
class ToolSetup:
    """The MCP servers Claude Code gets. `servers` are plain URLs written to an --mcp-config file: the navigator
    always (its public endpoint needs no login), and the database too when it's reached by URL (port-forward).
    `connector` is a claude.ai connector used for the database instead: its public endpoint needs the OAuth
    login that only the connector holds. The other claude.ai connectors go in `disallowed`."""

    servers: dict[str, str]
    connector: str | None = None
    disallowed: list[str] = field(default_factory=list)

    def mcp_config(self) -> dict:
        return {
            "mcpServers": {n: {"type": "http", "url": u, "headers": HEADERS} for n, u in self.servers.items()}
        }

    @property
    def allowed(self) -> list[str]:
        prefixes = [f"mcp__{name}" for name in self.servers]
        return prefixes + ([f"mcp__{connector_tool_prefix(self.connector)}"] if self.connector else [])


def find_connector(url: str, env: dict | None = None) -> str | None:
    """The claude.ai connector (by whatever name it has in this Claude home) that points at `url`."""
    out = subprocess.run(
        ["claude", "mcp", "list"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    for line in out.splitlines():
        name, sep, rest = line.partition(": ")
        if (
            sep
            and name.startswith("claude.ai ")
            and rest.split(" - ")[0].strip().rstrip("/") == url.rstrip("/")
        ):
            return name
    return None


def connector_tool_prefix(connector: str) -> str:
    """'claude.ai cBioPortal MCP' → 'claude_ai_cBioPortal_MCP', the server segment of its tool names."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", connector)


def tool_setup(
    database_url: str, navigator_url: str, connector: str | None, workdir: str, env: dict
) -> ToolSetup:
    if not connector:
        return ToolSetup({"cbioportal-database": database_url, NAVIGATOR_SERVER: navigator_url})
    setup = ToolSetup({NAVIGATOR_SERVER: navigator_url}, connector)
    wanted = connector_tool_prefix(connector)
    loaded = probe_mcp_servers(setup, workdir, env)
    if wanted not in loaded:
        raise RuntimeError(
            f"claude.ai connector {connector!r} did not load for this Claude home — it may need you to sign in "
            f"again (claude.ai → Settings → Connectors, or /mcp in claude); loaded: {sorted(loaded)}"
        )
    # Every other claude.ai connector would otherwise be visible to the model.
    setup.disallowed = [f"mcp__{s}" for s in sorted(loaded) if s.startswith("claude_ai_") and s != wanted]
    return setup


def loaded_servers(lines: list[str]) -> set[str] | None:
    """MCP servers whose tools the session actually had, from the stream-json init event (None if absent)."""
    for line in lines:
        if line.startswith("{") and '"init"' in line:
            event = json.loads(line)
            if event.get("subtype") == "init":
                return {t.split("__")[1] for t in event.get("tools", []) if t.startswith("mcp__")}
    return None


def probe_mcp_servers(setup: ToolSetup, workdir: str, env: dict) -> set[str]:
    """The MCP servers a Claude Code session loads, read from the stream-json init event of a trivial call."""
    config = os.path.join(workdir, "probe-mcp.json")
    with open(config, "w") as f:
        json.dump(setup.mcp_config(), f)
    cmd = [
        "claude",
        "-p",
        "Reply OK.",
        "--tools",
        "",
        "--mcp-config",
        config,
        "--output-format",
        "stream-json",
    ]
    cmd += ["--verbose", "--no-session-persistence", "--model", MODELS["haiku"].claude_code_id]
    # claude.ai connectors load only some of the time in headless mode, so retry until one shows up.
    seen: set[str] = set()
    for _ in range(PROBE_ATTEMPTS):
        out = subprocess.run(
            cmd, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180
        )
        servers = loaded_servers(out.stdout.splitlines())
        if servers is None:
            raise RuntimeError(f"could not start claude to probe MCP servers: {out.stderr[-500:]}")
        seen |= servers
        if any(name.startswith("claude_ai_") for name in servers):
            break
    return seen


def claude_args(
    question: str, model: str, system_prompt: str, setup: ToolSetup, mcp_config_path: str
) -> list[str]:
    args = [
        "claude",
        "-p",
        question,
        "--model",
        MODELS[model].claude_code_id,
        "--system-prompt",
        system_prompt,
        "--tools",
        "",
        "--mcp-config",
        mcp_config_path,
        "--allowedTools",
        *setup.allowed,
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]
    if setup.connector is None:
        args.insert(args.index("--mcp-config"), "--strict-mcp-config")
    if setup.disallowed:
        args += ["--disallowedTools", *setup.disallowed]
    return args


def short_tool_name(name: str) -> str:
    return name.split("__", 2)[-1] if name.startswith("mcp__") else name


RESULT_CHARS = 3000


def connector_needs_signin(lines: list[str], connector: str) -> bool:
    """Whether the claude.ai connector's login has expired: its init status or a tool error says so."""
    for line in lines:
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event.get("subtype") == "init":
            for server in event.get("mcp_servers") or []:
                if server.get("name") == connector and server.get("status") == "needs-auth":
                    return True
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                if "sign in" in json.dumps(block.get("content")):
                    return True
    return False


def format_transcript(lines: list[str]) -> str:
    """A readable transcript: every tool call with its arguments and (truncated) result, then the answer."""
    out: list[str] = []
    for line in lines:
        if not line.strip().startswith("{"):
            continue
        event = json.loads(line)
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                args = json.dumps(block.get("input"), indent=1, ensure_ascii=False)
                out.append(f"▶ {short_tool_name(block['name'])}\n{args.replace(chr(92) + 'n', chr(10))}\n")
            elif block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                else:
                    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                try:
                    wrapped = json.loads(text)
                    if isinstance(wrapped, dict) and isinstance(wrapped.get("result"), str):
                        text = wrapped["result"]
                except ValueError:
                    pass
                label = "✗ error" if block.get("is_error") else "◀ result"
                more = f" … ({len(text) - RESULT_CHARS} more chars)" if len(text) > RESULT_CHARS else ""
                out.append(f"{label}\n{text[:RESULT_CHARS]}{more}\n")
        if event.get("type") == "result":
            out.append(f"═ answer ({event.get('subtype')})\n{event.get('result') or ''}\n")
    return "\n".join(out)


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
        database_connector: str | None = None,
        timeout_s: float = 900.0,
        retries: int = 1,
        transcript_dir: Path | None = None,
    ):
        self.system_prompt = system_prompt
        self.transcript_dir = transcript_dir
        self.signin_expired = False
        self.timeout_s = timeout_s
        self.retries = retries
        self._workdir = tempfile.TemporaryDirectory(prefix="mcp-qa-claude-")
        # Thinking off to match the deployed agent (thinking=false); CLAUDE_CONFIG_DIR passes through.
        self.env = {**os.environ, "MAX_THINKING_TOKENS": "0"}
        self.setup = tool_setup(database_url, navigator_url, database_connector, self._workdir.name, self.env)
        self.mcp_config_path = os.path.join(self._workdir.name, "mcp.json")
        with open(self.mcp_config_path, "w") as f:
            json.dump(self.setup.mcp_config(), f)

    async def aclose(self) -> None:
        self._workdir.cleanup()

    def signin_message(self) -> str:
        return f"claude.ai connector {self.setup.connector!r} needs you to sign in again"

    async def ask(self, question: str, model: str) -> AgentReply:
        started = time.time()
        retries = connector_misses = 0
        while True:
            if self.signin_expired:
                return AgentReply("", None, None, self.signin_message(), 0.0, started)
            reply = await self._run(question, model, started)
            if reply.error is None:
                return reply
            if self.signin_expired:
                return reply
            if "did not load in this session" in reply.error:
                # The attempt never had the database tools; retry it without using up a regular retry.
                connector_misses += 1
                if connector_misses < CONNECTOR_ATTEMPTS:
                    continue
            elif retries < self.retries:
                retries += 1
                await asyncio.sleep(10)
                continue
            return reply

    async def _run(self, question: str, model: str, started: float) -> AgentReply:
        t0 = time.monotonic()
        # An empty working directory keeps project CLAUDE.md files out of the context.
        proc = await asyncio.create_subprocess_exec(
            *claude_args(question, model, self.system_prompt, self.setup, self.mcp_config_path),
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
        lines = stdout.decode().splitlines()
        reply = parse_stream(lines, started, time.monotonic() - t0)
        if self.setup.connector and connector_needs_signin(lines, self.setup.connector):
            self.signin_expired = True
            reply.status = None
            reply.error = self.signin_message()
            return reply
        if self.setup.connector and connector_tool_prefix(self.setup.connector) not in (
            loaded_servers(lines) or set()
        ):
            reply.status = None
            reply.error = f"claude.ai connector {self.setup.connector!r} did not load in this session"
            return reply
        if self.transcript_dir is not None and reply.trace is not None:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha1(f"{model}:{question}:{started}".encode()).hexdigest()[:12] + ".txt"
            (self.transcript_dir / name).write_text(f"Q ({model}): {question}\n\n{format_transcript(lines)}")
            reply.trace["url"] = f"{self.transcript_dir.name}/{name}"
        if reply.error and proc.returncode:
            reply.error = f"{reply.error} (exit {proc.returncode}: {stderr.decode()[-500:]})"
        return reply
