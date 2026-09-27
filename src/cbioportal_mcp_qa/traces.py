"""Per-answer execution details (LLM calls, tool calls, tool errors) from Langfuse."""

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from .config import price_for

SCHEMA_ERROR = "did not match expected schema"
# LibreChat (@librechat/agents) gives a router one tool per handoff edge, named after the destination agent id.
TRANSFER_PREFIX = "lc_transfer_to_"
# ...and names each agent's model node `agent=<agent id>` (LangGraph's `langgraph_node` metadata).
AGENT_NODE_PREFIX = "agent="


@dataclass
class ToolCall:
    name: str
    ok: bool
    error: str | None = None
    input: str | None = None  # arguments, truncated
    result: str | None = None  # result excerpt, truncated


TOOL_EXCERPT_CHARS = 1500


def excerpt(text: str, limit: int = TOOL_EXCERPT_CHARS) -> str:
    return text if len(text) <= limit else f"{text[:limit]} … ({len(text) - limit} more chars)"


@dataclass
class Generation:
    """One LLM call. `input_tokens` excludes cache reads and writes; `cost` is at list price (None if unpriced)."""

    model: str | None
    agent: str | None  # agent id whose node made the call, when Langfuse recorded it
    name: str | None
    start: str | None
    end: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost: float | None = None
    tool_calls: list[str] = field(default_factory=list)


@dataclass
class TraceStats:
    trace_id: str
    url: str
    llm_calls: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    generations: list[Generation] = field(default_factory=list)
    tool_rounds: int = 0  # tool_batch executions, excluding handoff-only batches
    handoffs: int = 0
    routed_to: str | None = None  # the agent that wrote the answer

    @property
    def tool_errors(self) -> list[ToolCall]:
        return [t for t in self.tool_calls if not t.ok]

    def to_dict(self) -> dict:
        return asdict(self)


def short_tool_name(name: str) -> str:
    for suffix in ("_mcp_cbioportal-navigator", "_mcp_cbioportal-database", "_mcp_cbioportal-navigator-beta"):
        name = name.removesuffix(suffix)
    return name


class Langfuse:
    def __init__(self, host: str, public_key: str, secret_key: str):
        self.host = host.rstrip("/")
        self.enabled = bool(public_key and secret_key)
        self.http = httpx.Client(
            base_url=f"{self.host}/api/public", auth=(public_key, secret_key), timeout=120
        )
        self._project_id: str | None = None

    def _get(self, path: str, retries: int = 6, **params) -> dict:
        for attempt in range(retries + 1):
            resp = self.http.get(path, params=params)
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == retries:
                resp.raise_for_status()
                return resp.json()
            retry_after = resp.headers.get("retry-after", "")
            time.sleep(float(retry_after) if retry_after.isdigit() else min(2 ** (attempt + 1), 60))
        raise AssertionError("unreachable")

    def _pages(self, path: str, **params):
        page = 1
        while True:
            data = self._get(path, page=page, limit=100, **params)
            yield from data["data"]
            if page >= data["meta"]["totalPages"] or not data["data"]:
                return
            page += 1

    def trace_ids_by_message(self, start: float, end: float) -> dict[str, str]:
        """Map messageId -> trace id for agent runs in a time window."""
        window_start = datetime.fromtimestamp(start, UTC) - timedelta(minutes=2)
        window_end = datetime.fromtimestamp(end, UTC) + timedelta(minutes=10)
        found: dict[str, str] = {}
        for trace in self._pages(
            "/traces",
            name="AgentRun",
            fromTimestamp=window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            toTimestamp=window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ):
            message_id = (trace.get("metadata") or {}).get("messageId")
            if message_id:
                found[message_id] = trace["id"]
        return found

    def project_id(self) -> str:
        if self._project_id is None:
            self._project_id = self._get("/projects")["data"][0]["id"]
        return self._project_id

    def stats(self, trace_id: str) -> TraceStats:
        return trace_stats(
            trace_id,
            f"{self.host}/project/{self.project_id()}/traces/{trace_id}",
            self._pages("/observations", traceId=trace_id),
        )


def trace_stats(trace_id: str, url: str, observations) -> TraceStats:
    stats = TraceStats(trace_id, url)
    transfers: list[str] = []
    for obs in sorted(observations, key=lambda o: o.get("startTime") or ""):
        if obs["type"] == "GENERATION":
            stats.generations.append(generation(obs))
        elif obs["type"] == "TOOL" and obs.get("name") == "tool_batch":
            calls = _tool_calls(obs)
            batch_transfers = [c.name for c in calls if c.name.startswith(TRANSFER_PREFIX)]
            transfers += batch_transfers
            stats.tool_calls.extend(c for c in calls if not c.name.startswith(TRANSFER_PREFIX))
            stats.tool_rounds += len(batch_transfers) < len(calls) or not calls
    stats.llm_calls = len(stats.generations)
    stats.models = sorted({g.model for g in stats.generations if g.model})
    # A handoff shows up as the router's tool call; count it from there too in case its batch wasn't traced.
    called = [t for g in stats.generations for t in g.tool_calls if t.startswith(TRANSFER_PREFIX)]
    transfers = transfers if len(transfers) >= len(called) else called
    stats.handoffs = len(transfers)
    last_agent = next((g.agent for g in reversed(stats.generations) if g.agent), None)
    stats.routed_to = transfers[-1].removeprefix(TRANSFER_PREFIX) if transfers else last_agent
    return stats


CACHE_READ_KEYS = ("input_cache_read", "cache_read_input_tokens", "cache_read")
CACHE_WRITE_KEYS = (
    "input_cache_creation",
    "cache_creation_input_tokens",
    "input_cache_write",
    "cache_creation",
)


def _first(d: dict, keys: tuple[str, ...]) -> int | None:
    return next((int(d[k]) for k in keys if d.get(k) is not None), None)


def usage_split(obs: dict) -> tuple[int | None, int | None, int | None, int | None]:
    """(uncached input, output, cache read, cache write) from a Langfuse generation's usage.

    Langfuse's own convention keeps cache tokens out of `input`; LangChain's usage_metadata counts them in. When
    `total` shows `input` already includes the cache, the cache is subtracted."""
    usage = obs.get("usageDetails") or obs.get("usage") or {}
    inp, out = usage.get("input"), usage.get("output")
    if inp is None and out is None:
        return None, None, None, None
    inp, out = int(inp or 0), int(out or 0)
    read, write = _first(usage, CACHE_READ_KEYS), _first(usage, CACHE_WRITE_KEYS)
    cache = (read or 0) + (write or 0)
    total = usage.get("total")
    if cache and total is not None and int(total) == inp + out and inp >= cache:
        inp -= cache
    return inp, out, read, write


def generation(obs: dict) -> Generation:
    metadata = obs.get("metadata") or {}
    node = metadata.get("langgraph_node") or ""
    agent = metadata.get("agent_id") or (
        node.removeprefix(AGENT_NODE_PREFIX) if node.startswith(AGENT_NODE_PREFIX) else None
    )
    inp, out, read, write = usage_split(obs)
    price = price_for(obs.get("model"))
    cost = price.cost(inp or 0, out or 0, write or 0, read or 0) if price and inp is not None else None
    return Generation(
        model=obs.get("model"),
        agent=agent,
        name=obs.get("name"),
        start=obs.get("startTime"),
        end=obs.get("endTime"),
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=read,
        cache_write_tokens=write,
        cost=cost,
        tool_calls=_output_tool_calls(obs.get("output")),
    )


def _output_tool_calls(output) -> list[str]:
    """Names of the tool calls a generation made (LangChain AIMessage, serialized or plain)."""
    if not isinstance(output, dict):
        return []
    msg = output.get("kwargs") or output
    calls = msg.get("tool_calls") or []
    return [c.get("name") for c in calls if isinstance(c, dict) and c.get("name")]


def _tool_calls(obs: dict) -> list[ToolCall]:
    args = {
        call.get("id"): call.get("args")
        for msg in (obs.get("input") or {}).get("messages") or []
        for call in (msg.get("kwargs") or {}).get("tool_calls") or []
    }
    calls = []
    for msg in (obs.get("output") or {}).get("messages") or []:
        if (msg.get("id") or [None])[-1] != "ToolMessage":
            continue
        kwargs = msg.get("kwargs") or {}
        content = kwargs.get("content")
        text = content if isinstance(content, str) else json.dumps(content)
        failed = kwargs.get("status") == "error"
        call_args = args.get(kwargs.get("tool_call_id"))
        calls.append(
            ToolCall(
                short_tool_name(kwargs.get("name") or "?"),
                not failed,
                text[:500] if failed else None,
                excerpt(json.dumps(call_args, ensure_ascii=False)) if call_args is not None else None,
                excerpt(text),
            )
        )
    return calls
