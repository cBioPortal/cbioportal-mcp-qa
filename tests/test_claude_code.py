import json

import httpx

from cbioportal_mcp_qa import versions
from cbioportal_mcp_qa.agent_prompt import prompt_fingerprint
from cbioportal_mcp_qa.claude_code import (
    ClaudeCodeClient,
    claude_args,
    format_transcript,
    mcp_config,
    parse_stream,
)
from cbioportal_mcp_qa.mcp_http import _message


def _events(*events: dict) -> list[str]:
    return [json.dumps(e) for e in events]


def _tool_use(msg_id: str, use_id: str, name: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": msg_id,
            "model": "claude-haiku-4-5-20251001",
            "content": [{"type": "tool_use", "id": use_id, "name": name, "input": {}}],
        },
    }


def _tool_result(use_id: str, is_error: bool, content: str) -> dict:
    return {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": use_id, "is_error": is_error, "content": content}
            ]
        },
    }


STREAM = _events(
    {"type": "system", "subtype": "init", "model": "claude-haiku-4-5-20251001"},
    _tool_use("m1", "t1", "mcp__cbioportal-database__read_guide"),
    _tool_result("t1", False, "# Clinical Data Query Guide"),
    _tool_use("m2", "t2", "mcp__cbioportal-database__clickhouse_run_select_query"),
    _tool_result("t2", True, "Code: 47. Unknown identifier"),
    _tool_use("m3", "t3", "mcp__cbioportal-navigator__navigate_to_study_view"),
    _tool_result("t3", False, "{}"),
    {
        "type": "assistant",
        "message": {
            "id": "m4",
            "model": "claude-haiku-4-5-20251001",
            "content": [{"type": "text", "text": "15.2"}],
        },
    },
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "Median age: 15.2 years",
        "usage": {
            "input_tokens": 40,
            "cache_creation_input_tokens": 1000,
            "cache_read_input_tokens": 9000,
            "output_tokens": 300,
        },
    },
)


def test_parse_stream_builds_reply_and_trace():
    reply = parse_stream(STREAM, started=1.0, latency_s=20.0)

    assert reply.status == 200 and reply.error is None
    assert reply.answer == "Median age: 15.2 years"
    assert reply.prompt_tokens == 10_040
    assert reply.cache_read_tokens == 9000 and reply.cache_write_tokens == 1000
    assert reply.completion_tokens == 300
    assert reply.trace["llm_calls"] == 4
    assert [(t["name"], t["ok"]) for t in reply.trace["tool_calls"]] == [
        ("read_guide", True),
        ("clickhouse_run_select_query", False),
        ("navigate_to_study_view", True),
    ]
    assert "Unknown identifier" in reply.trace["tool_calls"][1]["error"]


def test_parse_stream_reports_errors_and_missing_results():
    failed = parse_stream(
        _events({"type": "result", "subtype": "error_max_turns", "is_error": True}), started=0, latency_s=1
    )
    assert failed.status is None and failed.error == "error_max_turns"
    assert parse_stream([], started=0, latency_s=1).error == "no result event"


def test_claude_args_expose_only_the_mcp_servers():
    args = claude_args("q?", "haiku", "PROMPT", "/tmp/mcp.json")

    assert args[:3] == ["claude", "-p", "q?"]
    assert args[args.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert args[args.index("--system-prompt") + 1] == "PROMPT"
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args
    assert args[args.index("--allowedTools") + 1 : args.index("--allowedTools") + 3] == [
        "mcp__cbioportal-database",
        "mcp__cbioportal-navigator",
    ]
    assert args[args.index("--output-format") + 1] == "stream-json"


def test_client_writes_mcp_config_and_disables_thinking(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/home/x/.claude-work")
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    try:
        with open(client.mcp_config_path) as f:
            assert json.load(f) == mcp_config("http://db/mcp", "http://nav/mcp")
        assert client.env["MAX_THINKING_TOKENS"] == "0"
        assert client.env["CLAUDE_CONFIG_DIR"] == "/home/x/.claude-work"
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_mcp_message_reads_json_and_sse():
    body = {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "x", "version": "1"}}}
    as_json = httpx.Response(200, json=body)
    as_sse = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(body)}\n\n",
    )
    assert _message(as_json) == body
    assert _message(as_sse) == body


def test_prompt_fingerprint_and_failed_version_probe():
    fp = prompt_fingerprint("abc")
    assert fp["chars"] == 3 and len(fp["sha256"]) == 12

    def boom():
        raise ConnectionError("refused")

    assert versions._probe(boom) == {"error": "ConnectionError: refused"}


def test_format_transcript_shows_calls_results_and_answer():
    text = format_transcript(
        _events(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "mcp__cbioportal-database__clickhouse_run_select_query",
                            "input": {"query": "SELECT 1\nFROM x"},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": [{"type": "text", "text": "a\nb"}],
                        }
                    ]
                },
            },
            {"type": "result", "subtype": "success", "result": "done"},
        )
    )
    assert "▶ clickhouse_run_select_query" in text
    assert "SELECT 1\nFROM x" in text
    assert "◀ result\na\nb" in text
    assert text.rstrip().endswith("═ answer (success)\ndone")
