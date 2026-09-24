"""Minimal synchronous wrapper around the MCP Python SDK client, for tests."""

import asyncio
import json
from dataclasses import dataclass

from mcp.client.client import Client


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolResult:
    is_error: bool
    content: list

    def normalized(self) -> str:
        """Stable JSON text for comparing results across servers."""
        return json.dumps({"is_error": self.is_error, "content": self.content}, indent=1, sort_keys=True)


def _parse(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _reports_failure(item) -> bool:
    """Both servers report tool failures as data rather than MCP errors."""
    if not isinstance(item, dict):
        return False
    return "error_message" in item or item.get("success") is False


class McpClient:
    def __init__(self, url: str, timeout_s: float = 120.0):
        self.url = url
        self.timeout_s = timeout_s

    def _run(self, fn):
        async def go():
            async with Client(self.url, read_timeout_seconds=self.timeout_s) as client:
                return await fn(client)

        return asyncio.run(go())

    def list_tools(self) -> dict[str, ToolInfo]:
        async def fn(client):
            result = await client.list_tools()
            return {t.name: ToolInfo(t.name, t.description or "", t.input_schema or {}) for t in result.tools}

        return self._run(fn)

    def call(self, tool: str, args: dict) -> ToolResult:
        async def fn(client):
            result = await client.call_tool(tool, args)
            content = [_parse(b.text) if b.type == "text" else {"type": b.type} for b in result.content]
            return ToolResult(bool(result.is_error) or any(map(_reports_failure, content)), content)

        return self._run(fn)
