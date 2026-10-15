import asyncio
import json
import time

import httpx
import pytest

from cbioportal_mcp_qa import mcp_oauth
from cbioportal_mcp_qa.cli import _models
from cbioportal_mcp_qa.mcp_oauth import OAuthTokens, _code_from
from cbioportal_mcp_qa.openai_chat import OpenAIChatClient, answer_text, openai_tools
from cbioportal_mcp_qa.report import record_cost


class FakeMCP:
    def __init__(self, tools, results, instructions=None):
        self.tools = tools
        self.results = results
        self.instructions = instructions
        self.calls = []

    async def initialize(self):
        return {"name": "fake", "version": "1"}

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return self.results[name]

    async def aclose(self):
        pass


def _tool(name):
    return {"name": name, "description": f"{name} tool", "inputSchema": {"type": "object", "properties": {}}}


def _completion(message, prompt_tokens=10_000, completion_tokens=20):
    return {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _client(tmp_path, replies, sent):
    """A client whose chat endpoint returns `replies` in order and whose MCP servers are fakes."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/version"):
            return httpx.Response(404)
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=queue.pop(0))

    client = OpenAIChatClient(
        "AGENT PROMPT",
        "http://127.0.0.1:1/v1",
        "http://db",
        "http://nav",
        served_model="m:1",
        transcript_dir=tmp_path / "transcripts",
    )
    client.http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    client.servers = {
        "cbioportal-database": FakeMCP(
            [_tool("clickhouse_run_select_query"), _tool("read_guide")],
            {"clickhouse_run_select_query": ('{"rows":[{"n":1}]}', False), "read_guide": ("# Guide", False)},
            instructions="SERVER INSTRUCTIONS",
        ),
        "navigator": FakeMCP([_tool("navigate_to_study_view")], {"navigate_to_study_view": ("{}", False)}),
    }
    return client


def test_tool_loop_records_calls_tokens_and_transcript(tmp_path):
    sent = []
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "clickhouse_run_select_query", "arguments": '{"query": "SELECT 1"}'},
    }
    client = _client(
        tmp_path,
        [
            _completion({"role": "assistant", "content": "", "tool_calls": [call]}),
            _completion({"role": "assistant", "content": "<think>hmm</think>There is 1."}, 10_050, 30),
        ],
        sent,
    )

    async def go():
        await client.start()
        return await client.ask("How many?", "llama3.1-8b", ({"role": "user", "content": "earlier"},))

    reply = asyncio.run(go())
    assert reply.status == 200 and reply.error is None
    assert reply.answer == "There is 1."
    assert (reply.prompt_tokens, reply.completion_tokens, reply.cache_write_tokens) == (20_050, 50, 0)
    assert reply.trace["llm_calls"] == 2 and reply.trace["tool_rounds"] == 1
    assert reply.trace["models"] == ["m:1"]
    [rec] = reply.trace["tool_calls"]
    assert rec["name"] == "clickhouse_run_select_query" and rec["ok"] and "SELECT 1" in rec["input"]
    assert client.servers["cbioportal-database"].calls == [
        ("clickhouse_run_select_query", {"query": "SELECT 1"})
    ]
    first, second = sent
    assert first["model"] == "m:1"
    assert first["messages"][0] == {"role": "system", "content": "AGENT PROMPT\n\nSERVER INSTRUCTIONS"}
    assert [m["role"] for m in first["messages"]] == ["system", "user", "user"]
    assert {t["function"]["name"] for t in first["tools"]} == {
        "clickhouse_run_select_query",
        "read_guide",
        "navigate_to_study_view",
    }
    assert second["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"rows":[{"n":1}]}'}
    transcript = (tmp_path / reply.trace["url"]).read_text()
    assert "▶ clickhouse_run_select_query" in transcript and "═ answer (success)\nThere is 1." in transcript


def test_bad_arguments_and_unknown_tools_go_back_to_the_model(tmp_path):
    sent = []
    calls = [
        {"id": "a", "function": {"name": "read_guide", "arguments": "{not json"}},
        {"id": "b", "function": {"name": "no_such_tool", "arguments": "{}"}},
    ]
    client = _client(
        tmp_path,
        [_completion({"content": "", "tool_calls": calls}), _completion({"content": "Sorry."})],
        sent,
    )

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert reply.status == 200
    assert [c["ok"] for c in reply.trace["tool_calls"]] == [False, False]
    tool_messages = [m for m in sent[1]["messages"] if m["role"] == "tool"]
    assert "Invalid tool arguments" in tool_messages[0]["content"]
    assert "Unknown tool 'no_such_tool'" in tool_messages[1]["content"]


def test_max_tool_rounds_forces_an_answer_without_tools(tmp_path):
    sent = []
    call = {"id": "c", "function": {"name": "read_guide", "arguments": "{}"}}
    client = _client(
        tmp_path,
        [_completion({"content": "", "tool_calls": [call]}), _completion({"content": "Done."})],
        sent,
    )
    client.max_tool_rounds = 1

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    assert asyncio.run(go()).answer == "Done."
    assert "tools" in sent[0] and "tools" not in sent[1]


def test_silently_truncated_prompt_fails_the_answer(tmp_path):
    sent = []
    # A long system prompt reported as far fewer tokens than its characters allow: the server cut it.
    client = _client(tmp_path, [_completion({"content": "I can't access data."}, prompt_tokens=100)], sent)
    client.agent_prompt = "x" * 10_000

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert reply.status is None
    assert "prompt truncated by the server" in reply.error


def test_shared_tool_names_are_prefixed_with_their_server():
    tools, route = openai_tools({"a": [_tool("x"), _tool("y")], "b": [_tool("x")]})
    assert [t["function"]["name"] for t in tools] == ["a__x", "y", "b__x"]
    assert route == {"a__x": ("a", "x"), "y": ("a", "y"), "b__x": ("b", "x")}


def test_answer_text_drops_inline_reasoning():
    assert answer_text({"content": "<think>\nplan\n</think>\n\nAnswer"}) == "Answer"
    assert answer_text({"content": None}) == ""


def test_openai_models_and_local_price():
    assert _models(None, "beta", "openai") == ["llama3.1-8b"]
    assert _models("qwen3.8-27b", "beta", "openai") == ["qwen3.8-27b"]
    with pytest.raises(Exception, match="openai runner has no model"):
        _models("haiku", "beta", "openai")
    rec = {
        "model": "qwen3.8-27b",
        "reply": {
            "prompt_tokens": 50_000,
            "completion_tokens": 900,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
    }
    assert record_cost(rec) == (0.0, True)


def test_pasted_redirect_url_gives_the_code():
    url = "http://127.0.0.1:8976/callback?code=abc123&state=s1"
    assert _code_from(url, "s1") == "abc123"
    assert _code_from("  abc123 ", "s1") == "abc123"
    with pytest.raises(RuntimeError, match="state mismatch"):
        _code_from(url, "other")
    with pytest.raises(RuntimeError, match="access_denied"):
        _code_from("http://127.0.0.1:8976/callback?error=access_denied&state=s1", "s1")


def test_expired_token_is_refreshed_and_saved(tmp_path, monkeypatch):
    path = tmp_path / "oauth.json"
    path.write_text(
        json.dumps(
            {
                "resource": "https://mcp.example/db/mcp",
                "token_endpoint": "https://mcp.example/token",
                "client_id": "cid",
                "client_secret": "client-secret-value",
                "access_token": "old-access-token",
                "refresh_token": "refresh-token-1",
                "expires_at": time.time() - 10,
            }
        )
    )
    posted = []

    def fake_post(url, data, timeout):
        posted.append(data)
        return httpx.Response(200, json={"access_token": "new-access-token", "expires_in": 3600})

    monkeypatch.setattr(mcp_oauth.httpx, "post", fake_post)
    tokens = OAuthTokens("https://mcp.example/db/mcp", path)
    assert tokens.get() == "new-access-token"
    assert posted[0]["grant_type"] == "refresh_token" and posted[0]["refresh_token"] == "refresh-token-1"
    saved = json.loads(path.read_text())
    assert saved["access_token"] == "new-access-token" and saved["refresh_token"] == "refresh-token-1"
    assert path.stat().st_mode & 0o077 == 0
    assert tokens.get() == "new-access-token" and len(posted) == 1
    with pytest.raises(RuntimeError, match="not https://other"):
        OAuthTokens("https://other/db/mcp", path)


def test_context_overflow_error_says_so(tmp_path):
    sent = []
    client = _client(tmp_path, [], sent)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/version"):
            return httpx.Response(404)
        return httpx.Response(500, json={"error": {"message": "no user query found in messages"}})

    client.http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert reply.status is None and "exceeded the context window" in reply.error


def test_runs_started_in_the_same_minute_get_their_own_directory(tmp_path, monkeypatch):
    from cbioportal_mcp_qa import run as run_mod

    monkeypatch.setattr(run_mod, "RESULTS_DIR", tmp_path)
    a = run_mod.Run.create("beta", ["haiku"], 1, "j", "q.yaml")
    b = run_mod.Run.create("beta", ["haiku"], 1, "j", "q.yaml")
    assert b.data["run_id"] == a.data["run_id"] + "-2"
    assert a.path.parent != b.path.parent and a.path.is_file() and b.path.is_file()
