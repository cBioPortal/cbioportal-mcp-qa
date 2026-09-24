"""Just enough of the MCP streamable-HTTP protocol to read a server's identity and call one tool."""

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
        """The server's `serverInfo` (name, version)."""
        result = self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cbioportal-mcp-qa", "version": "0"},
            },
        ).get("result", {})
        self._post("notifications/initialized", notify=True)
        return result.get("serverInfo", {})

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._post("tools/call", {"name": name, "arguments": arguments}).get("result", {})
        return "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
