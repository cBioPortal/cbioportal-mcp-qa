import asyncio
import time
from dataclasses import dataclass

import httpx

from .config import Target

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass
class AgentReply:
    answer: str
    response_id: str | None
    status: int | None
    error: str | None
    latency_s: float
    started_at: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    trace: dict | None = None


class AgentClient:
    """Calls a deployed LibreChat agent through its OpenAI-compatible Agents API."""

    def __init__(self, target: Target, api_key: str, timeout_s: float = 900.0, retries: int = 2):
        if not api_key:
            raise ValueError("LIBRECHAT_API_KEY is not set (create one under Settings → Agent API Keys)")
        self.target = target
        self.retries = retries
        self.http = httpx.AsyncClient(
            base_url=target.url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=30.0),
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def ask(self, question: str, model: str, history: tuple[dict, ...] = ()) -> AgentReply:
        body = {
            "model": self.target.agent_id,
            "spec": self.target.specs[model],
            "messages": [*history, {"role": "user", "content": question}],
            "stream": False,
        }
        started = time.time()
        for attempt in range(self.retries + 1):
            reply = await self._post(body, started)
            if reply.error is None or reply.status not in RETRYABLE_STATUS | {None}:
                return reply
            if attempt < self.retries:
                await asyncio.sleep(10 * (attempt + 1))
        return reply

    async def _post(self, body: dict, started: float) -> AgentReply:
        t0 = time.monotonic()
        try:
            resp = await self.http.post("/api/agents/v1/chat/completions", json=body)
        except httpx.HTTPError as exc:
            return AgentReply("", None, None, f"{type(exc).__name__}: {exc}", time.monotonic() - t0, started)
        latency = time.monotonic() - t0
        if resp.status_code != 200:
            return AgentReply("", None, resp.status_code, resp.text[:2000], latency, started)
        data = resp.json()
        choices = data.get("choices") or [{}]
        usage = data.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        return AgentReply(
            answer=(choices[0].get("message") or {}).get("content") or "",
            response_id=data.get("id"),
            status=200,
            error=None,
            latency_s=latency,
            started_at=started,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cache_read_tokens=details.get("cached_tokens"),
            cache_write_tokens=details.get("cache_creation_tokens"),
        )
