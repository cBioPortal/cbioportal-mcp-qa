"""The api runner (Claude through the Anthropic SDK, the tool loop run here) and judge: the CI mode."""

import asyncio
from types import SimpleNamespace

import pytest

from cbioportal_mcp_qa.anthropic_api import (
    AnthropicAPIClient,
    APIJudge,
    NoCredentials,
    anthropic_tools,
    detect_provider,
    model_id,
)
from cbioportal_mcp_qa.cli import _models


@pytest.mark.parametrize(
    ("env", "requested", "expected"),
    [
        ({"ANTHROPIC_API_KEY": "k"}, None, "anthropic"),
        ({"ANTHROPIC_API_KEY": "k", "AWS_ACCESS_KEY_ID": "a"}, None, "anthropic"),
        ({"AWS_ACCESS_KEY_ID": "a"}, None, "bedrock"),
        ({"AWS_WEB_IDENTITY_TOKEN_FILE": "/t", "AWS_ROLE_ARN": "arn"}, None, "bedrock"),  # GitHub OIDC
        ({"AWS_PROFILE": "p"}, None, "bedrock"),
        ({"ANTHROPIC_API_KEY": "k"}, "bedrock", "bedrock"),
        ({"QA_PROVIDER": "bedrock", "ANTHROPIC_API_KEY": "k"}, None, "bedrock"),
        ({"QA_PROVIDER": "auto", "AWS_PROFILE": "p"}, None, "bedrock"),
    ],
)
def test_detect_provider(env, requested, expected):
    assert detect_provider(requested, env) == expected


def test_detect_provider_without_credentials():
    with pytest.raises(NoCredentials, match="ANTHROPIC_API_KEY"):
        detect_provider(None, {"ANTHROPIC_API_KEY": ""})
    with pytest.raises(ValueError):
        detect_provider("vertex", {})


def test_model_ids_per_provider():
    assert model_id("haiku", "anthropic") == "claude-haiku-4-5-20251001"
    assert model_id("haiku", "bedrock") == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert model_id("sonnet-4.6", "bedrock") == "us.anthropic.claude-sonnet-4-6"
    assert model_id("haiku-5.5", "anthropic") == "claude-haiku-5-5"
    with pytest.raises(ValueError, match="no bedrock model id"):
        model_id("haiku-5.5", "bedrock")
    assert model_id("claude-some-new-model", "anthropic") == "claude-some-new-model"


def test_api_runner_models_default_to_haiku():
    assert _models(None, "prod", "api") == ["haiku"]
    assert _models("haiku-5.5,sonnet-4.6", "prod", "api") == ["haiku-5.5", "sonnet-4.6"]
    with pytest.raises(Exception, match="no model"):
        _models("llama3.1-8b", "prod", "api")


def _tool(name):
    return {"name": name, "description": f"{name} tool", "inputSchema": {"type": "object", "properties": {}}}


def test_anthropic_tools_shape_and_cache_breakpoint():
    tools, route = anthropic_tools(
        {"cbioportal-database": [_tool("a"), _tool("b")], "navigator": [_tool("a")]}
    )
    assert [t["name"] for t in tools] == ["cbioportal-database__a", "b", "navigator__a"]
    assert tools[0]["input_schema"] == {"type": "object", "properties": {}}
    assert "cache_control" not in tools[0] and tools[-1]["cache_control"] == {"type": "ephemeral"}
    assert route["navigator__a"] == ("navigator", "a")


class FakeMCP:
    def __init__(self, tools, results, instructions=None):
        self.tools, self.results, self.instructions, self.calls = tools, results, instructions, []

    async def initialize(self):
        return {"name": "fake", "version": "1"}

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return self.results[name]

    async def aclose(self):
        pass


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=False):
        return {k: v for k, v in vars(self).items() if not (exclude_none and v is None)}


def _response(content, stop_reason, input_tokens=100, output_tokens=10, cache_read=1000, cache_write=0):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    async def create(self, **kwargs):
        # The loop appends to its messages list after the call: keep a snapshot of what was sent.
        self.sent.append(kwargs | {"messages": list(kwargs["messages"])})
        return self.replies.pop(0)


class FakeAsyncAnthropic:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)

    async def close(self):
        pass


def _client(tmp_path, replies, agent_prompt="AGENT PROMPT", **kw):
    client = AnthropicAPIClient(
        agent_prompt,
        "http://db",
        "http://nav",
        "anthropic",
        transcript_dir=tmp_path / "transcripts",
        client=FakeAsyncAnthropic(replies),
        **kw,
    )
    client.servers = {
        "cbioportal-database": FakeMCP(
            [_tool("clickhouse_run_select_query"), _tool("read_guide")],
            {"clickhouse_run_select_query": ('{"rows":[{"n":1}]}', False), "read_guide": ("bad uri", True)},
            instructions="DB SERVER INSTRUCTIONS",
        ),
        "navigator": FakeMCP([_tool("navigate_to_study_view")], {}, instructions="NAV INSTRUCTIONS"),
    }
    return client


def test_tool_loop_answers_with_trace_usage_and_transcript(tmp_path):
    replies = [
        _response(
            [
                Block(type="text", text="Let me check."),
                Block(
                    type="tool_use", id="t1", name="clickhouse_run_select_query", input={"query": "SELECT 1"}
                ),
                Block(type="tool_use", id="t2", name="read_guide", input={"uri": "x"}),
            ],
            "tool_use",
            cache_write=5000,
            cache_read=0,
        ),
        _response([Block(type="text", text="There is 1 study.")], "end_turn"),
    ]
    client = _client(tmp_path, replies)

    async def go():
        await client.start()
        return await client.ask("How many?", "haiku")

    reply = asyncio.run(go())
    assert reply.status == 200 and reply.error is None
    assert reply.answer == "There is 1 study."
    sent = client.client.messages.sent
    assert sent[0]["model"] == "claude-haiku-4-5-20251001"
    # The agent prompt, then the servers' instructions (LibreChat's serverInstructions order), cached.
    system = sent[0]["system"][0]
    assert system["text"] == "AGENT PROMPT\n\nDB SERVER INSTRUCTIONS\n\nNAV INSTRUCTIONS"
    assert system["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in sent[0]
    # Both results in one user message, the error marked as such.
    results = sent[1]["messages"][-1]["content"]
    assert [(r["tool_use_id"], r["is_error"]) for r in results] == [("t1", False), ("t2", True)]
    assert sent[1]["messages"][-2]["role"] == "assistant"
    trace = reply.trace
    assert trace["llm_calls"] == 2 and trace["tool_rounds"] == 1
    assert [(c["name"], c["ok"]) for c in trace["tool_calls"]] == [
        ("clickhouse_run_select_query", True),
        ("read_guide", False),
    ]
    # Totals like the Agents API: prompt tokens include cache reads and writes.
    assert reply.prompt_tokens == 200 + 1000 + 5000
    assert (reply.cache_read_tokens, reply.cache_write_tokens, reply.completion_tokens) == (1000, 5000, 20)
    transcript = (tmp_path / trace["url"]).read_text()
    assert "▶ clickhouse_run_select_query" in transcript and "There is 1 study." in transcript


def test_server_instructions_only_without_agent_prompt(tmp_path):
    client = _client(tmp_path, [_response([Block(type="text", text="ok")], "end_turn")], agent_prompt="")

    async def go():
        await client.start()
        return await client.ask("q", "haiku")

    asyncio.run(go())
    assert client.client.messages.sent[0]["system"][0]["text"] == "DB SERVER INSTRUCTIONS\n\nNAV INSTRUCTIONS"
    assert client.describe()["prompt"]["system_prompt"] is None


def test_last_round_disables_tools(tmp_path):
    call = Block(type="tool_use", id="t", name="clickhouse_run_select_query", input={})
    replies = [_response([call], "tool_use"), _response([Block(type="text", text="done")], "end_turn")]
    client = _client(tmp_path, replies, max_tool_rounds=1)

    async def go():
        await client.start()
        return await client.ask("q", "haiku")

    assert asyncio.run(go()).answer == "done"
    assert client.client.messages.sent[1]["tool_choice"] == {"type": "none"}


def test_api_error_is_a_failed_answer_not_a_crash(tmp_path):
    class Boom(FakeMessages):
        async def create(self, **kwargs):
            exc = RuntimeError("overloaded")
            exc.status_code = 529
            raise exc

    client = _client(tmp_path, [])
    client.client.messages = Boom([])

    async def go():
        await client.start()
        return await client.ask("q", "haiku")

    reply = asyncio.run(go())
    assert reply.status == 529 and "overloaded" in reply.error and reply.answer == ""


def test_api_judge_uses_provider_model_and_schema():
    sent = []

    class Messages:
        def create(self, **kwargs):
            sent.append(kwargs)
            text = '{"rationale": "ok", "passed": true, "declined": false}'
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)],
                usage=SimpleNamespace(input_tokens=5, output_tokens=3),
            )

    judge = APIJudge("sonnet-4.6", "bedrock", client=SimpleNamespace(messages=Messages()))
    assert judge.model == "us.anthropic.claude-sonnet-4-6"
    result, i, o = judge.verdict("prompt")
    assert result["passed"] is True and (i, o) == (5, 3)
    assert sent[0]["output_config"]["format"]["type"] == "json_schema"
    assert sent[0]["extra_body"] == {"temperature": 0}
    assert APIJudge("sonnet-4.6", "anthropic", client=object()).model == "claude-sonnet-4-6"


def test_whole_answer_timeout_is_a_failed_answer(tmp_path):
    class Slow(FakeMessages):
        async def create(self, **kwargs):
            await asyncio.sleep(5)

    client = _client(tmp_path, [], timeout_s=0.05)
    client.client.messages = Slow([])

    async def go():
        await client.start()
        return await client.ask("q", "haiku")

    reply = asyncio.run(go())
    assert reply.status is None and reply.answer == ""
    assert "timed out" in reply.error


def test_mcp_transport_error_is_a_tool_error_the_model_sees(tmp_path):
    import httpx

    class Down(FakeMCP):
        async def call_tool(self, name, args):
            raise httpx.ConnectError("connection refused")

    call = Block(type="tool_use", id="t", name="clickhouse_run_select_query", input={"query": "SELECT 1"})
    replies = [
        _response([call], "tool_use"),
        _response([Block(type="text", text="The database is down.")], "end_turn"),
    ]
    client = _client(tmp_path, replies)

    async def go():
        await client.start()
        client.servers["cbioportal-database"] = Down(client.servers["cbioportal-database"].tools, {})
        return await client.ask("q", "haiku")

    reply = asyncio.run(go())
    assert reply.status == 200 and reply.answer == "The database is down."
    (result,) = client.client.messages.sent[1]["messages"][-1]["content"]
    assert result["is_error"] is True and "connection refused" in result["content"]
    assert reply.trace["tool_calls"][0]["ok"] is False


# --- the run command: cost caps, and a secret prompt never written -------------------------------------------

from click.testing import CliRunner  # noqa: E402

from cbioportal_mcp_qa import cli as cli_mod  # noqa: E402

SUBSET = "input/questions-subset.yaml"


def _no_client(*args, **kwargs):
    raise AssertionError("a model client was created")


@pytest.mark.parametrize(
    "args",
    [
        ["--repeats", "2", "--max-answers", "10"],  # 26 × 1 × 2 = 52
        ["--max-questions", "5"],
        ["--repeats", "0"],
    ],
)
def test_run_refuses_over_its_caps_before_any_model_call(args, monkeypatch, results_dir):
    monkeypatch.setattr(cli_mod, "_client", _no_client)
    monkeypatch.setattr(cli_mod, "_make_judge", _no_client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    out = CliRunner().invoke(
        cli_mod.cli,
        ["run", "--runner", "api", "--target", "prod", "--questions-file", SUBSET, "--no-grade", *args],
    )
    assert out.exit_code == 2, out.output
    assert not list(results_dir.iterdir())


def test_api_run_records_only_the_prompts_hash(tmp_path, monkeypatch, results_dir):
    secret = "TOP SECRET AGENT PROMPT: you are the cBioPortal chat assistant, internal rules follow.\nRule two is long enough to mask."
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text(secret)

    def fake_client(settings, target, runner, prompt=None, transcript_dir=None, **kw):
        assert prompt == secret
        # The model quotes its prompt back: the transcript and answer must not keep it.
        replies = [_response([Block(type="text", text=f"My instructions: {secret}")], "end_turn")]
        return _client(tmp_path, replies, agent_prompt=prompt)

    monkeypatch.setattr(cli_mod, "_client", fake_client)
    monkeypatch.setattr(cli_mod, "collect_versions", lambda *a: {})
    out = CliRunner().invoke(
        cli_mod.cli,
        [
            "run",
            "--runner",
            "api",
            "--target",
            "prod",
            "--questions-file",
            SUBSET,
            "--questions",
            "2001",
            "--no-grade",
            "--no-render",
            "--system-prompt-file",
            str(prompt_file),
        ],
    )
    assert out.exit_code == 0, out.output
    (run_dir,) = [p for p in results_dir.iterdir() if p.is_dir()]
    assert not (run_dir / "agent-prompt.md").exists()
    data = __import__("json").loads((run_dir / "run.json").read_text())
    assert data["agent_prompt"]["sha256"]
    files = [p for p in run_dir.rglob("*") if p.is_file()]
    assert any(p.parent.name == "transcripts" for p in files)
    for path in files:
        text = path.read_text(errors="replace")
        assert "TOP SECRET AGENT PROMPT" not in text and "Rule two is long" not in text, path
