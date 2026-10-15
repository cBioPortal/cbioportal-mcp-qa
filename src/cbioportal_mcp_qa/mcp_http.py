"""Just enough of the MCP streamable-HTTP protocol to read a server's identity and call one tool."""

import asyncio
import json

import httpx

PROTOCOL_VERSION = "2025-06-18"


def _message(resp: httpx.Response) -> dict:
    """The JSON-RPC response, whether the server answered with JSON or a single SSE event."""
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:])
        return {}
    return resp.json()


class MCPSession:
    def __init__(self, url: str, timeout_s: float = 30.0):
        self.url = url
        self.http = httpx.Client(
            timeout=timeout_s,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
        self.session_id: str | None = None
        self.instructions: str | None = None
        self._id = 0

    def __enter__(self) -> "MCPSession":
        return self

    def __exit__(self, *exc) -> None:
        self.http.close()

    def _post(self, method: str, params: dict | None = None, notify: bool = False) -> dict:
        body: dict = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self._id += 1
            body["id"] = self._id
        headers = {"mcp-session-id": self.session_id} if self.session_id else {}
        resp = self.http.post(self.url, json=body, headers=headers)
        resp.raise_for_status()
        self.session_id = resp.headers.get("mcp-session-id", self.session_id)
        return {} if notify else _message(resp)

    def initialize(self) -> dict:
        """The server's `serverInfo` (name, version). Its `instructions`, if any, are kept in `self.instructions`."""
        result = self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cbioportal-mcp-qa", "version": "0"},
            },
        ).get("result", {})
        self._post("notifications/initialized", notify=True)
        self.instructions = result.get("instructions") or None
        return result.get("serverInfo", {})

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._post("tools/call", {"name": name, "arguments": arguments}).get("result", {})
        return "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


class MCPToolError(Exception):
    """A tool call the server answered with a JSON-RPC error (unknown tool, invalid arguments), or with something
    that isn't a JSON-RPC response."""


class MCPAuthError(RuntimeError):
    """The server still refuses the request after the token was renewed: the login needs fixing, not the model."""


class AsyncMCPSession:
    """An MCP streamable-HTTP client for an agent loop: list the tools, call them. `token` returns the bearer
    token for each request (an object with `get(force=False)`, e.g. `OAuthTokens`; None for a server without
    auth). A session the server forgot (404) is opened again, once for all the requests that found it gone; on a
    401 the token is renewed once, and a refusal after that raises MCPAuthError."""

    def __init__(self, url: str, headers: dict | None = None, token=None, timeout_s: float = 300.0):
        self.url = url
        self.token = token
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=30.0),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **(headers or {}),
            },
        )
        self.session_id: str | None = None
        self.server_info: dict = {}
        self.instructions: str | None = None
        self._id = 0
        self._reopen = asyncio.Lock()
        # Bumped each time the session is opened, so requests that failed on the same lost session reopen it once.
        self._generation = 0

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _post(
        self, method: str, params: dict | None = None, notify: bool = False, session_id: str | None = None
    ) -> httpx.Response:
        body: dict = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self._id += 1
            body["id"] = self._id
        resp = await self._send(body, session_id)
        if resp.status_code == 401 and self.token:
            resp = await self._send(body, session_id, renew=True)
        if resp.status_code in (401, 403) and self.token:
            raise MCPAuthError(
                f"{self.url} refused the request (HTTP {resp.status_code}) after renewing the login: "
                "run `cbioportal-mcp-qa mcp-login` again"
            )
        resp.raise_for_status()
        return resp

    async def _send(self, body: dict, session_id: str | None, renew: bool = False) -> httpx.Response:
        headers = {"mcp-session-id": session_id} if session_id else {}
        if self.token:
            token = await asyncio.to_thread(self.token.get, renew)
            headers["Authorization"] = f"Bearer {token}"
        return await self.http.post(self.url, json=body, headers=headers)

    @staticmethod
    def _parse(resp: httpx.Response) -> dict:
        try:
            return _message(resp)
        except ValueError as exc:
            raise MCPToolError(
                f"the server's reply isn't JSON-RPC (HTTP {resp.status_code}, "
                f"{resp.headers.get('content-type') or 'no content type'})"
            ) from exc

    async def initialize(self) -> dict:
        init = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "cbioportal-mcp-qa", "version": "0"},
        }
        resp = await self._post("initialize", init)
        session_id = resp.headers.get("mcp-session-id")
        result = self._parse(resp).get("result", {})
        await self._post("notifications/initialized", notify=True, session_id=session_id)
        self.session_id = session_id
        self._generation += 1
        self.server_info = result.get("serverInfo", {})
        self.instructions = result.get("instructions") or None
        return self.server_info

    async def _request(self, method: str, params: dict) -> dict:
        generation = self._generation
        try:
            return self._parse(await self._post(method, params, session_id=self.session_id))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404 or not self.session_id:
                raise
        async with self._reopen:
            if self._generation == generation:
                await self.initialize()
        return self._parse(await self._post(method, params, session_id=self.session_id))

    async def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        while True:
            msg = await self._request("tools/list", {"cursor": cursor} if cursor else {})
            result = msg.get("result", {})
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    async def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        """The tool's text content and whether it is an error result."""
        msg = await self._request("tools/call", {"name": name, "arguments": arguments})
        if "error" in msg:
            raise MCPToolError(json.dumps(msg["error"], ensure_ascii=False))
        result = msg.get("result", {})
        text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        if not text and result.get("structuredContent") is not None:
            text = json.dumps(result["structuredContent"], ensure_ascii=False)
        return text, bool(result.get("isError"))
