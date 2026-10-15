import asyncio
import json
import time
from types import SimpleNamespace

import click
import httpx
import pytest

from cbioportal_mcp_qa import mcp_oauth
from cbioportal_mcp_qa.cli import _check_runner_options, _models, _record_openai_setup
from cbioportal_mcp_qa.mcp_http import AsyncMCPSession, MCPAuthError, MCPToolError
from cbioportal_mcp_qa.mcp_oauth import OAuthTokens, _code_from
from cbioportal_mcp_qa.openai_chat import OpenAIChatClient, answer_text, openai_tools
from cbioportal_mcp_qa.persist import write_secret_json
from cbioportal_mcp_qa.redact import add_secret
from cbioportal_mcp_qa.report import record_cost
from cbioportal_mcp_qa.run import run_order


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


def test_a_non_json_reply_fails_the_answer_not_the_run(tmp_path):
    client = _client(tmp_path, [], [])
    client.retries = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/version"):
            return httpx.Response(404)
        return httpx.Response(200, text="<html>proxy error</html>")

    client.http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert reply.status is None and "without JSON" in reply.error


def test_a_reply_without_usage_is_not_called_truncated(tmp_path):
    reply_body = {"choices": [{"message": {"content": "Fine."}, "finish_reason": "stop"}]}
    client = _client(tmp_path, [reply_body], [])
    client.agent_prompt = "x" * 10_000

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert reply.error is None and reply.answer == "Fine."


def test_context_window_is_read_for_each_model(tmp_path):
    shown = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/version"):
            return httpx.Response(200, json={"version": "0.35.1"})
        if request.url.path.endswith("/api/show"):
            shown.append(json.loads(request.content)["model"])
            return httpx.Response(200, json={"parameters": "num_ctx                        32768"})
        return httpx.Response(200, json=_completion({"content": "cut"}, prompt_tokens=32_768))

    client = _client(tmp_path, [], [])
    client.served_model = None
    client.http = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert shown == ["llama3.1:8b"]
    assert "window 32768" in reply.error and reply.trace["context_window"] == 32768
    assert client.describe()["context_windows"] == {"llama3.1:8b": 32768}


def test_a_refused_login_fails_the_answer(tmp_path):
    class Refused(FakeMCP):
        async def call_tool(self, name, args):
            raise MCPAuthError("https://db refused the request (HTTP 401) after renewing the login")

    call = {"id": "c", "function": {"name": "clickhouse_run_select_query", "arguments": "{}"}}
    client = _client(tmp_path, [_completion({"content": "", "tool_calls": [call]})], [])
    client.servers["cbioportal-database"] = Refused(
        [_tool("clickhouse_run_select_query")], {}, instructions="SERVER INSTRUCTIONS"
    )

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert reply.status is None and "after renewing the login" in reply.error


class _Token:
    def __init__(self):
        self.renewals = 0

    def get(self, renew=False):
        self.renewals += renew
        return f"token-{self.renewals}"


def _mcp_server(state):
    """A streamable-HTTP MCP server that forgets its session when `state["restart"]` is set."""

    def handler(request: httpx.Request) -> httpx.Response:
        if state.get("status"):
            return httpx.Response(state["status"])
        body = json.loads(request.content)
        sid = request.headers.get("mcp-session-id")
        if body["method"] == "initialize":
            state["inits"] = state.get("inits", 0) + 1
            state["session"] = f"s{state['inits']}"
            return httpx.Response(200, json={"result": {}}, headers={"mcp-session-id": state["session"]})
        if not sid:
            return httpx.Response(400)
        if sid != state["session"]:
            return httpx.Response(404)
        if body["method"].startswith("notifications/"):
            return httpx.Response(202)
        if state.get("html"):
            return httpx.Response(200, text="<html>gateway</html>", headers={"content-type": "text/html"})
        return httpx.Response(200, json={"result": {"content": [{"type": "text", "text": "ok"}]}})

    return handler


def _session(state, token=None):
    mcp = AsyncMCPSession("http://db/mcp", token=token)
    mcp.http = httpx.AsyncClient(transport=httpx.MockTransport(_mcp_server(state)))
    return mcp


def test_a_lost_session_is_reopened_once_for_concurrent_calls():
    state = {}
    mcp = _session(state)

    async def go():
        await mcp.initialize()
        state["session"] = "gone"
        return await asyncio.gather(*(mcp.call_tool("t", {}) for _ in range(3)))

    assert asyncio.run(go()) == [("ok", False)] * 3
    assert state["inits"] == 2


def test_mcp_refusing_a_renewed_token_raises_auth_error():
    state, token = {}, _Token()
    mcp = _session(state, token)

    async def go():
        await mcp.initialize()
        state["status"] = 401
        await mcp.call_tool("t", {})

    with pytest.raises(MCPAuthError, match="mcp-login"):
        asyncio.run(go())
    assert token.renewals == 1


def test_a_non_json_mcp_reply_is_a_tool_error():
    state = {}
    mcp = _session(state)

    async def go():
        await mcp.initialize()
        state["html"] = True
        await mcp.call_tool("t", {})

    with pytest.raises(MCPToolError, match="isn't JSON-RPC"):
        asyncio.run(go())


def test_tokens_in_tool_results_are_masked_in_transcripts(tmp_path):
    add_secret("access-token-6f1d2c9a8b7e")
    call = {"id": "c", "function": {"name": "read_guide", "arguments": "{}"}}
    client = _client(
        tmp_path,
        [_completion({"content": "", "tool_calls": [call]}), _completion({"content": "Done."})],
        [],
    )
    client.servers["cbioportal-database"].results["read_guide"] = ("echo access-token-6f1d2c9a8b7e", False)

    async def go():
        await client.start()
        return await client.ask("q", "llama3.1-8b")

    reply = asyncio.run(go())
    assert "access-token-6f1d2c9a8b7e" not in (tmp_path / reply.trace["url"]).read_text()
    assert "access-token-6f1d2c9a8b7e" not in json.dumps(reply.trace)


def test_secret_files_are_private_and_never_under_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "secret.json").with_name("secret.json.tmp").write_text("left over")
    write_secret_json(tmp_path / "secret.json", {"a": 1})
    assert (tmp_path / "secret.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="never go under results"):
        write_secret_json(tmp_path / "results" / "x.json", {})


def _token_file(path, access, expires_at):
    path.write_text(
        json.dumps(
            {
                "resource": "https://mcp.example/db/mcp",
                "token_endpoint": "https://mcp.example/token",
                "client_id": "cid",
                "access_token": access,
                "refresh_token": "refresh-1",
                "expires_at": expires_at,
            }
        )
    )


def test_processes_sharing_the_token_file_renew_once(tmp_path, monkeypatch):
    path = tmp_path / "oauth.json"
    _token_file(path, "old-access-token-1", time.time() - 10)
    posted = []

    def fake_post(url, data, timeout):
        posted.append(data["refresh_token"])
        return httpx.Response(
            200, json={"access_token": "new-access-token-2", "refresh_token": "refresh-2", "expires_in": 3600}
        )

    monkeypatch.setattr(mcp_oauth.httpx, "post", fake_post)
    a = OAuthTokens("https://mcp.example/db/mcp", path)
    b = OAuthTokens("https://mcp.example/db/mcp", path)
    assert a.get() == "new-access-token-2"
    # b still holds the old token and the rotated-away refresh token: it takes a's renewal instead of renewing.
    assert b.get() == "new-access-token-2"
    assert b.get(renew=False) == "new-access-token-2" and posted == ["refresh-1"]
    # A token the server rejected is renewed with the current refresh token.
    assert b.get(renew=True) == "new-access-token-2" and posted == ["refresh-1", "refresh-2"]


def test_a_refresh_without_an_access_token_says_so(tmp_path, monkeypatch):
    path = tmp_path / "oauth.json"
    _token_file(path, "old-access-token-1", time.time() - 10)
    monkeypatch.setattr(mcp_oauth.httpx, "post", lambda url, data, timeout: httpx.Response(200, json={}))
    with pytest.raises(RuntimeError, match="without an access token"):
        OAuthTokens("https://mcp.example/db/mcp", path).get()


def test_a_pasted_url_must_carry_the_state():
    with pytest.raises(RuntimeError, match="state mismatch"):
        _code_from("http://127.0.0.1:8976/callback?code=abc123", "s1")


def test_run_ids_sort_in_start_order():
    names = ["20261015-0338-10", "20261015-0338", "20261015-0339", "20261015-0338-2"]
    assert sorted(names, key=run_order) == [
        "20261015-0338",
        "20261015-0338-2",
        "20261015-0338-10",
        "20261015-0339",
    ]


def test_options_a_runner_would_ignore_are_refused():
    settings = SimpleNamespace(openai_served_model=None)
    with pytest.raises(click.UsageError, match="system-prompt-file needs"):
        _check_runner_options(settings, "agents-api", ["haiku"], "prompt.md")
    _check_runner_options(settings, "openai", ["llama3.1-8b", "qwen3.8-27b"], "prompt.md")
    settings.openai_served_model = "qwen3.8-c64k-t8:27b"
    with pytest.raises(click.UsageError, match="every model"):
        _check_runner_options(settings, "openai", ["llama3.1-8b", "qwen3.8-27b"], None)
    _check_runner_options(settings, "openai", ["qwen3.8-27b"], None)


def test_a_resume_keeps_the_runs_endpoint_and_records_its_own(capsys):
    bench = SimpleNamespace(data={})
    first = {"base_url": "http://127.0.0.1:1/v1", "served_model": "q-c64k:27b", "backend": {}}
    _record_openai_setup(bench, first)
    _record_openai_setup(bench, first | {"served_model": "q-c128k:27b"})
    assert bench.data["openai"] == first
    assert bench.data["openai_resumes"][0]["served_model"] == "q-c128k:27b"
    assert "differs from the run's (served_model)" in capsys.readouterr().err
