import json

import httpx

from cbioportal_mcp_qa import versions
from cbioportal_mcp_qa.agent_prompt import prompt_fingerprint
from cbioportal_mcp_qa.claude_code import (
    ClaudeCodeClient,
    ToolSetup,
    claude_args,
    connector_tool_prefix,
    find_connector,
    format_transcript,
    loaded_servers,
    parse_stream,
    short_tool_name,
    tool_setup,
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
    _tool_use("m3", "t3", "mcp__navigator__navigate_to_study_view"),
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
    setup = ToolSetup({"cbioportal-database": "http://db/mcp", "navigator": "http://nav/mcp"})
    args = claude_args("q?", "haiku", "PROMPT", setup, "/tmp/mcp.json")

    assert args[:3] == ["claude", "-p", "q?"]
    assert args[args.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert args[args.index("--system-prompt") + 1] == "PROMPT"
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--disallowedTools" not in args
    assert args[args.index("--allowedTools") + 1 : args.index("--allowedTools") + 3] == [
        "mcp__cbioportal-database",
        "mcp__navigator",
    ]
    assert args[args.index("--output-format") + 1] == "stream-json"


def test_database_through_a_claude_ai_connector_hides_other_connectors(monkeypatch):
    loaded = {
        "navigator",
        "claude_ai_cBioPortal_MCP",
        "claude_ai_Google_Drive",
        "claude_ai_Claude_Docs",
    }
    monkeypatch.setattr("cbioportal_mcp_qa.claude_code.probe_mcp_servers", lambda *a: loaded)
    setup = tool_setup("unused", "https://nav/mcp", "claude.ai cBioPortal MCP", "/tmp", {})
    args = claude_args("q?", "sonnet", "PROMPT", setup, "/tmp/mcp.json")

    assert setup.mcp_config() == {
        "mcpServers": {
            "navigator": {
                "type": "http",
                "url": "https://nav/mcp",
                "headers": setup.mcp_config()["mcpServers"]["navigator"]["headers"],
            }
        }
    }
    assert "--strict-mcp-config" not in args
    assert setup.allowed == ["mcp__navigator", "mcp__claude_ai_cBioPortal_MCP"]
    assert args[args.index("--disallowedTools") + 1 :] == [
        "mcp__claude_ai_Claude_Docs",
        "mcp__claude_ai_Google_Drive",
    ]


def test_missing_connector_is_an_error(monkeypatch):
    monkeypatch.setattr("cbioportal_mcp_qa.claude_code.probe_mcp_servers", lambda *a: {"navigator"})
    try:
        tool_setup("unused", "https://nav/mcp", "claude.ai cBioPortal MCP", "/tmp", {})
    except RuntimeError as exc:
        assert "not connected" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_tool_names_are_shortened_for_urls_and_connectors():
    assert connector_tool_prefix("claude.ai cBioPortal MCP") == "claude_ai_cBioPortal_MCP"
    assert short_tool_name("mcp__claude_ai_cBioPortal_MCP__read_guide") == "read_guide"
    assert short_tool_name("mcp__navigator__resolve_and_route") == "resolve_and_route"


def test_client_writes_mcp_config_and_disables_thinking(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/home/x/.claude")
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    try:
        with open(client.mcp_config_path) as f:
            assert set(json.load(f)["mcpServers"]) == {"cbioportal-database", "navigator"}
        assert client.env["MAX_THINKING_TOKENS"] == "0"
        assert client.env["CLAUDE_CONFIG_DIR"] == "/home/x/.claude"
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


def test_loaded_servers_reads_the_init_event():
    lines = _events(
        {
            "type": "system",
            "subtype": "init",
            "tools": ["mcp__claude_ai_cBioPortal_MCP__read_guide", "mcp__navigator__x"],
        },
        {"type": "result", "subtype": "success", "result": "ok"},
    )
    assert loaded_servers(lines) == {"claude_ai_cBioPortal_MCP", "navigator"}
    assert loaded_servers(_events({"type": "result"})) is None


def test_answers_without_the_connector_are_retried(monkeypatch):
    monkeypatch.setattr(
        "cbioportal_mcp_qa.claude_code.probe_mcp_servers", lambda *a: {"claude_ai_cBioPortal_MCP"}
    )
    client = ClaudeCodeClient(
        "PROMPT", "unused", "https://nav/mcp", database_connector="claude.ai cBioPortal MCP"
    )
    with_connector = _events(
        {"type": "system", "subtype": "init", "tools": ["mcp__claude_ai_cBioPortal_MCP__read_guide"]},
        *[json.loads(line) for line in STREAM[1:]],
    )
    without = _events(
        {"type": "system", "subtype": "init", "tools": []}, *[json.loads(line) for line in STREAM[1:]]
    )
    outputs = iter([without, without, with_connector])

    class Proc:
        returncode = 0

        async def communicate(self):
            return ("\n".join(next(outputs)).encode(), b"")

    async def fake_exec(*args, **kwargs):
        return Proc()

    import asyncio

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    try:
        reply = asyncio.run(client.ask("q?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    assert reply.error is None and reply.answer == "Median age: 15.2 years"


def test_find_connector_matches_by_url_not_name(monkeypatch):
    listing = "\n".join(
        [
            "Checking MCP server health…",
            "claude.ai MSK cBioPortal DB: https://chat.cbioportal.aws.mskcc.org/db/mcp - ✘ Failed to connect",
            "claude.ai My cBio DB: https://mcp.cbioportal.org/db/mcp - ✔ Connected",
            "claude.ai cBioPortal Navigator: https://mcp.cbioportal.org/navigator/mcp - ✔ Connected",
        ]
    )

    class Out:
        stdout = listing

    monkeypatch.setattr("cbioportal_mcp_qa.claude_code.subprocess.run", lambda *a, **k: Out())
    assert find_connector("https://mcp.cbioportal.org/db/mcp") == "claude.ai My cBio DB"
    assert find_connector("https://example.org/mcp") is None
