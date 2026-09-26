"""Per-answer execution details (LLM calls, tool calls, tool errors) from Langfuse."""

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

SCHEMA_ERROR = "did not match expected schema"


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
class TraceStats:
    trace_id: str
    url: str
    llm_calls: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    models: list[str] = field(default_factory=list)

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
        stats = TraceStats(trace_id, f"{self.host}/project/{self.project_id()}/traces/{trace_id}")
        models: set[str] = set()
        for obs in self._pages("/observations", traceId=trace_id):
            if obs["type"] == "GENERATION":
                stats.llm_calls += 1
                if obs.get("model"):
                    models.add(obs["model"])
            elif obs["type"] == "TOOL" and obs.get("name") == "tool_batch":
                stats.tool_calls.extend(_tool_calls(obs))
        stats.models = sorted(models)
        return stats


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
