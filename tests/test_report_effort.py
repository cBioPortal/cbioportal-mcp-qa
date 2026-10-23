"""The reasoning effort a run asked with: recorded in run.json, shown in the report, index and comparison, with
the same model at two efforts kept apart and runs from before it was recorded shown as "–"."""

import asyncio
import json

import pytest
from click.testing import CliRunner

from cbioportal_mcp_qa import agent_prompt, claude_code, cli
from cbioportal_mcp_qa import report as report_mod
from cbioportal_mcp_qa.compare import compare, to_markdown, write_compare
from cbioportal_mcp_qa.report import reasoning_effort, summarize, write_report
from cbioportal_mcp_qa.run import Run, record_key

JUDGE = "us.anthropic.claude-sonnet-4-6"
MODEL = "qwen3.8-27b"


def _rec(qid: int, model: str, passed: bool = True) -> dict:
    return {
        "question": {
            "id": qid,
            "category": "Cohort & clinical counts",
            "study": "s",
            "question": f"Q{qid}?",
            "expected_answer": "42",
        },
        "model": model,
        "repeat": 1,
        "reply": {
            "answer": "42",
            "status": 200,
            "latency_s": 5.0,
            "prompt_tokens": 100,
            "completion_tokens": 10,
        },
        "grade": {"passed": passed, "declined": False, "rationale": "", "links": []},
    }


def _run(run_id: str, results_dir, extra: dict, model: str = MODEL, runner: str = "openai") -> Run:
    created = Run.create("beta", [model], 1, JUDGE, "input/questions.yaml", runner, extra)
    created.path.unlink()
    created.path.parent.rmdir()
    bench = Run(results_dir / run_id / "run.json", created.data | {"run_id": run_id})
    bench.path.parent.mkdir(parents=True)
    for qid in (1, 2):
        bench.records[record_key(qid, model, 1)] = _rec(qid, model, passed=qid == 1 or "high" in run_id)
    bench.save()
    return bench


def test_reasoning_effort_from_run_metadata():
    assert reasoning_effort({"runner": "openai", "reasoning_effort": "high"}) == "high"
    assert reasoning_effort({"runner": "claude-code", "reasoning_effort": "high"}) == "high"
    # openai runs from before the top-level field: the endpoint record, None meaning none was sent.
    assert reasoning_effort({"runner": "openai", "openai": {"reasoning_effort": "none"}}) == "none"
    assert reasoning_effort({"runner": "openai", "openai": {"reasoning_effort": None}}) == "default"
    # Not recorded: older runs, the deployed agent.
    assert reasoning_effort({"runner": "openai"}) is None
    assert reasoning_effort({"runner": "claude-code"}) is None
    assert reasoning_effort({}) is None


def test_report_shows_the_effort_in_every_model_table(results_dir):
    bench = _run("20261020-0000", results_dir, {"reasoning_effort": "high"})
    assert summarize(bench)["models"][0].reasoning_effort == "high"
    out = write_report(bench)
    html = out.read_text()
    assert html.count("<th>Reasoning effort</th>") == 3
    # The headline tile and the three tables.
    assert html.count("<td>high</td>") == 3 and "<span>high</span>" in html
    headline = json.loads((out.parent / "summary.json").read_text())
    assert headline["reasoning_effort"] == "high"
    assert headline["models"][MODEL]["reasoning_effort"] == "high"


def test_effort_is_escaped(results_dir):
    bench = _run("20261020-0000", results_dir, {"reasoning_effort": "<b>x</b>"})
    html = write_report(bench).read_text()
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "<b>x</b>" not in html


def test_same_model_at_two_efforts_stays_two_rows_on_the_index(results_dir):
    _run("20261020-0000-low", results_dir, {"reasoning_effort": "low"})
    high = _run("20261020-0000-high", results_dir, {"reasoning_effort": "high"})
    write_report(Run.load(str(results_dir / "20261020-0000-low")))
    write_report(high)
    html = (results_dir / "index.html").read_text()
    assert "<th>Reasoning effort</th>" in html
    rows = [r for r in html.split("<tr ")[1:] if "Qwen3.8 27B" in r]
    assert len(rows) == 2
    by_effort = {("low" if "<td>low</td>" in r else "high"): r for r in rows}
    assert set(by_effort) == {"low", "high"}
    assert "<td>50%</td>" in by_effort["low"] and "<td>100%</td>" in by_effort["high"]


def test_legacy_runs_without_an_effort_render(results_dir):
    # A summary.json and run.json from before reasoning effort was recorded.
    for run_id, run_json in {
        "20260101-0000": {"runner": "agents-api"},
        "20260102-0000": {"runner": "openai", "openai": {"reasoning_effort": None}},
    }.items():
        (results_dir / run_id).mkdir()
        summary = {
            "run_id": run_id,
            "target": "beta",
            "runner": run_json["runner"],
            "n_questions": 1,
            "n_gradeable": 1,
            "models": {
                "haiku": {
                    "label": "Haiku 4.5",
                    "pass_rate": 50.0,
                    "errors": 0,
                    "by_track": {},
                    "cost_per_pass": None,
                    "median_latency": None,
                }
            },
        }
        (results_dir / run_id / "summary.json").write_text(json.dumps(summary))
        (results_dir / run_id / "run.json").write_text(json.dumps(run_json))
    # And one whose run.json is gone.
    (results_dir / "20260103-0000").mkdir()
    (results_dir / "20260103-0000" / "summary.json").write_text(
        (results_dir / "20260101-0000" / "summary.json").read_text().replace("20260101", "20260103")
    )
    html = report_mod.write_index().read_text()
    newest, middle, oldest = (
        html.index(f"{r}-0000/report.html") for r in ("20260103", "20260102", "20260101")
    )
    # The cell after the model's (other cells can be "–" too).
    effort_cell = '<td><span class="swatch model"></span>Haiku 4.5</td>\n      <td>{}</td>'
    assert effort_cell.format("–") in html[newest:middle]
    assert effort_cell.format("default") in html[middle:oldest]
    assert effort_cell.format("–") in html[oldest:]

    # A report from a legacy run.json (no reasoning_effort, no openai record) renders "–".
    legacy = _run("20260104-0000", results_dir, {}, model="haiku", runner="agents-api")
    html = write_report(legacy).read_text()
    assert (
        html.count("Haiku 4.5</td><td>–</td>") == 3 and "<span>Reasoning effort</span><span>–</span>" in html
    )


def test_compare_names_each_sides_effort(results_dir):
    low = _run("20261020-0000-low", results_dir, {"reasoning_effort": "low"})
    high = _run("20261020-0000-high", results_dir, {"reasoning_effort": "high"})
    result = compare(low, high, MODEL, MODEL)
    assert (result["a"]["reasoning_effort"], result["b"]["reasoning_effort"]) == ("low", "high")
    md = to_markdown(result)
    assert "reasoning effort low)" in md and "reasoning effort high)" in md
    assert "| A | low |" in md and "| B | high |" in md
    html = write_compare(result, results_dir / "compare" / "x").read_text()
    assert "<td>low</td>" in html and "<td>high</td>" in html
    # A legacy side without one.
    legacy = _run("20260101-0000", results_dir, {})
    assert "| A | – |" in to_markdown(compare(legacy, high, MODEL, MODEL))


def test_tool_table_headers_name_each_models_effort(results_dir):
    bench = _run("20261020-0000", results_dir, {"reasoning_effort": "<i>high</i>"})
    for rec in bench.records.values():
        rec["trace"] = {"llm_calls": 1, "tool_calls": [{"name": "run_sql", "ok": True}]}
    html = write_report(bench).read_text()
    assert "<th>Qwen3.8 27B (&lt;i&gt;high&lt;/i&gt;) calls</th>" in html
    legacy = _run("20260101-0000", results_dir, {}, model="haiku", runner="agents-api")
    for rec in legacy.records.values():
        rec["trace"] = {"llm_calls": 1, "tool_calls": [{"name": "run_sql", "ok": True}]}
    assert "<th>Haiku 4.5 (–) calls</th>" in write_report(legacy).read_text()


# claude-code: an explicit --reasoning-effort passed to every session through --settings, or unknown. Thinking
# (MAX_THINKING_TOKENS=0) is recorded apart.


@pytest.fixture
def claude_home(tmp_path):
    home = tmp_path / "claude-home"
    home.mkdir(exist_ok=True)
    return home


def _write(path, doc):
    path.write_text(json.dumps(doc))


def _client(**kwargs):
    return claude_code.ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp", **kwargs)


def test_an_explicit_effort_goes_to_every_session_through_settings():
    client = _client(effort="high")
    try:
        assert client.settings["env"] == {"CLAUDE_CODE_EFFORT_LEVEL": "high"}
        args = claude_code.claude_args("q", "sonnet-5.5", "P", client.setup, "m.json", True, client.settings)
        assert json.loads(args[args.index("--settings") + 1])["env"] == {"CLAUDE_CODE_EFFORT_LEVEL": "high"}
    finally:
        asyncio.run(client.aclose())


def test_without_an_effort_the_sessions_settings_are_unchanged():
    client = _client()
    try:
        assert client.settings == claude_code.no_plugins_settings() and client.effort is None
    finally:
        asyncio.run(client.aclose())


def test_settings_that_would_change_an_explicit_effort_refuse(claude_home, tmp_path, monkeypatch):
    # A user cap applies over --settings: refused when user settings are loaded, not when they aren't.
    _write(
        claude_home / "settings.json", {"modelSettings": {"claude-sonnet-5-5": {"maxEffortLevel": "medium"}}}
    )
    with pytest.raises(RuntimeError, match=r"settings.json: modelSettings.claude-sonnet-5-5.maxEffortLevel"):
        _client(effort="high", isolate_settings=False)
    asyncio.run(_client(effort="high", isolate_settings=True).aclose())
    # The user's own level, env value and the inherited variable all rank below --settings: no refusal.
    _write(claude_home / "settings.json", {"effortLevel": "low", "env": {"CLAUDE_CODE_EFFORT_LEVEL": "low"}})
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "low")
    asyncio.run(_client(effort="high", isolate_settings=False).aclose())
    # Managed settings rank above --settings.
    managed = tmp_path / "managed"
    managed.mkdir()
    _write(managed / "managed-settings.json", {"env": {"CLAUDE_CODE_EFFORT_LEVEL": "medium"}})
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (managed,))
    with pytest.raises(RuntimeError, match="managed-settings.json: env.CLAUDE_CODE_EFFORT_LEVEL"):
        _client(effort="high")
    # Without an explicit effort nothing is refused: the run records the effort as unknown.
    asyncio.run(_client().aclose())


def test_configured_effort_lists_hints_not_effective_values(claude_home, monkeypatch):
    _write(
        claude_home / "settings.json",
        {"effortLevel": "low", "modelSettings": {"claude-sonnet-5": {"effortLevel": "xhigh"}}},
    )
    env = {"CLAUDE_CONFIG_DIR": str(claude_home), "CLAUDE_CODE_EFFORT_LEVEL": "medium"}
    hints = claude_code.configured_effort(env, isolate_settings=False)
    assert {"source": "environment", "key": "CLAUDE_CODE_EFFORT_LEVEL", "value": "medium"} in hints
    assert {
        "source": str(claude_home / "settings.json"),
        "key": "modelSettings.claude-sonnet-5.effortLevel",
        "value": "xhigh",
    } in hints
    # Isolated sessions don't load user settings.
    assert [h["source"] for h in claude_code.configured_effort(env, isolate_settings=True)] == ["environment"]


def _agent(agent_id, ctx=None):
    return {"instructions": "AGENT", "model_parameters": {"thinking": False}}


def _cli(monkeypatch, args: list[str], client, exit_code: int = 0, specs=None, fetch_agent=_agent):
    monkeypatch.setattr("cbioportal_mcp_qa.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_MCP_URL", "http://localhost:18081/db/mcp")
    monkeypatch.setenv("DATABASE_MCP_ENV", "beta")
    monkeypatch.setattr(cli, "fetch_agent_prompt", fetch_agent)
    monkeypatch.setattr(cli, "collect_versions", lambda *a: {})
    monkeypatch.setattr(cli, "prompt_parity", lambda *a: {})
    monkeypatch.setattr(cli, "write_report", lambda bench: bench.dir / "report.html")
    monkeypatch.setattr(cli, "wait_for_ingestion", lambda: None)
    monkeypatch.setattr(cli, "attach_traces", lambda bench, langfuse: 0)
    monkeypatch.setattr(cli, "_langfuse", lambda settings: None)
    if specs is not None:
        monkeypatch.setattr(cli, "fetch_model_specs", specs)
    seen = {}

    def fake_client(*a, **kwargs):
        seen.update(kwargs)
        return client

    monkeypatch.setattr(cli, "_client", fake_client)

    async def answer_all(bench, questions, client, concurrency):
        for q in questions:
            for model in bench.data["models"]:
                bench.records[record_key(q.id, model, 1)] = _rec(q.id, model)

    monkeypatch.setattr(cli, "collect_answers", answer_all)
    result = CliRunner().invoke(cli.cli, ["run", "--questions", "1", "--no-grade", "--no-render", *args])
    assert result.exit_code == exit_code, result.output
    return seen, result


def _run_json(results_dir, run_id=None) -> dict:
    if run_id:
        return json.loads((results_dir / run_id / "run.json").read_text())
    (path,) = results_dir.glob("*/run.json")
    return json.loads(path.read_text())


class FakeOpenAI:
    stops = []

    def __init__(self, effort=None):
        self.effort = effort

    async def start(self):
        pass

    def describe(self):
        return {"reasoning_effort": self.effort}

    async def aclose(self):
        pass


class FakeClaudeCode:
    stops = []
    setup = type("Setup", (), {"connector": None})()
    env = {"CLAUDE_CODE_EFFORT_LEVEL": "low"}
    isolate_settings = True

    def describe(self):
        return {}

    async def aclose(self):
        pass


class FakeAgent:
    stops = []

    async def aclose(self):
        pass


OPENAI = ["--runner", "openai", "--target", "beta", "--models", MODEL]


def test_openai_run_records_its_effort(monkeypatch, results_dir):
    seen, _ = _cli(monkeypatch, [*OPENAI, "--reasoning-effort", "low"], FakeOpenAI("low"))
    # The request is unchanged: the client is given the same effort it was before.
    assert seen["reasoning_effort"] == "low"
    assert _run_json(results_dir)["reasoning_effort"] == "low"


def test_openai_run_without_an_effort_records_the_default(monkeypatch, results_dir):
    seen, _ = _cli(monkeypatch, OPENAI, FakeOpenAI())
    assert seen["reasoning_effort"] is None
    assert _run_json(results_dir)["reasoning_effort"] == "default"


CLAUDE = ["--runner", "claude-code", "--target", "beta", "--models", "sonnet,haiku"]


def test_claude_code_run_records_the_explicit_effort(monkeypatch, results_dir):
    seen, _ = _cli(monkeypatch, [*CLAUDE, "--reasoning-effort", "high"], FakeClaudeCode())
    assert seen["reasoning_effort"] == "high"
    recorded = _run_json(results_dir)
    # Haiku 4.5 has no effort levels: Claude Code sends it none.
    assert recorded["reasoning_efforts"] == {"sonnet": "high", "haiku": "n/a"}
    # No thinking claim: MAX_THINKING_TOKENS=0 doesn't turn thinking off on every model.
    assert "thinking" not in recorded


def test_claude_code_run_without_an_effort_records_it_as_unknown(monkeypatch, results_dir):
    seen, _ = _cli(monkeypatch, CLAUDE, FakeClaudeCode())
    assert seen["reasoning_effort"] is None
    recorded = _run_json(results_dir)
    assert recorded["reasoning_efforts"] == {"sonnet": None, "haiku": "n/a"}
    # Configured hints, labelled as such, for debugging.
    assert recorded["claude_code_configured_effort"] == [
        {"source": "environment", "key": "CLAUDE_CODE_EFFORT_LEVEL", "value": "low"}
    ]
    assert (reasoning_effort(recorded, "sonnet"), reasoning_effort(recorded, "haiku")) == (None, "n/a")
    bench = Run.load(str(results_dir / recorded["run_id"]))
    html = write_report(bench).read_text()
    assert "Sonnet 5</td><td>–</td>" in html and "Haiku 4.5</td><td>n/a</td>" in html


@pytest.mark.parametrize("effort", ["bogus", "auto", "none"])
def test_claude_code_refuses_an_unknown_effort_before_starting(monkeypatch, results_dir, effort):
    seen, result = _cli(monkeypatch, [*CLAUDE, "--reasoning-effort", effort], FakeClaudeCode(), exit_code=2)
    assert "isn't a Claude Code effort level" in result.output
    assert seen == {} and not list(results_dir.glob("*/run.json"))


def test_claude_code_refuses_a_level_a_model_lacks(monkeypatch):
    monkeypatch.setitem(
        cli.MODELS,
        "sonnet",
        cli.MODELS["sonnet"].__class__(
            **{**cli.MODELS["sonnet"].__dict__, "effort_levels": ("low", "medium", "high", "max")}
        ),
    )
    with pytest.raises(cli.click.UsageError, match="isn't a level of sonnet"):
        cli._check_claude_code_effort("claude-code", ["sonnet", "haiku"], "xhigh")
    cli._check_claude_code_effort("claude-code", ["sonnet", "haiku"], "high")
    # Other runners keep their own values.
    cli._check_claude_code_effort("openai", [MODEL], "none")


# --resume keeps a run at one effort.


def test_resume_at_another_effort_is_refused(monkeypatch, results_dir):
    _cli(monkeypatch, [*OPENAI, "--reasoning-effort", "low"], FakeOpenAI("low"))
    run_id = _run_json(results_dir)["run_id"]
    before = (results_dir / run_id / "run.json").read_text()
    seen, result = _cli(
        monkeypatch, ["--resume", run_id, "--reasoning-effort", "high"], FakeOpenAI("high"), exit_code=1
    )
    assert f"{MODEL}: 'low' → 'high'" in result.output
    # Refused before anything is asked or recorded.
    assert (results_dir / run_id / "run.json").read_text() == before
    # The run's own effort (restored when not given) resumes.
    seen, _ = _cli(monkeypatch, ["--resume", run_id], FakeOpenAI("low"))
    assert seen["reasoning_effort"] == "low"


def test_claude_code_resume_compares_the_explicit_effort(monkeypatch, results_dir):
    _cli(monkeypatch, [*CLAUDE, "--reasoning-effort", "high"], FakeClaudeCode())
    run_id = _run_json(results_dir)["run_id"]
    before = (results_dir / run_id / "run.json").read_text()
    _, result = _cli(
        monkeypatch, ["--resume", run_id, "--reasoning-effort", "low"], FakeClaudeCode(), exit_code=1
    )
    assert "sonnet: 'high' → 'low'" in result.output and "haiku:" not in result.output
    assert (results_dir / run_id / "run.json").read_text() == before
    # Not given again: the run's own effort is restored.
    seen, _ = _cli(monkeypatch, ["--resume", run_id], FakeClaudeCode())
    assert seen["reasoning_effort"] == "high"


def test_claude_code_resume_of_an_unknown_effort(monkeypatch, results_dir):
    _cli(monkeypatch, CLAUDE, FakeClaudeCode())
    run_id = _run_json(results_dir)["run_id"]
    # Unknown vs unknown resumes.
    _cli(monkeypatch, ["--resume", run_id], FakeClaudeCode())
    # Unknown vs an explicit level doesn't: the earlier answers' effort isn't known.
    _, result = _cli(
        monkeypatch, ["--resume", run_id, "--reasoning-effort", "high"], FakeClaudeCode(), exit_code=1
    )
    assert "sonnet: 'unknown' → 'high'" in result.output


def test_resume_of_a_legacy_run_without_an_effort_is_not_refused(monkeypatch, results_dir):
    _cli(monkeypatch, [*OPENAI, "--reasoning-effort", "low"], FakeOpenAI("low"))
    run_id = _run_json(results_dir)["run_id"]
    path = results_dir / run_id / "run.json"
    data = json.loads(path.read_text())
    del data["reasoning_effort"], data["openai"]
    path.write_text(json.dumps(data))
    _cli(monkeypatch, ["--resume", run_id, "--reasoning-effort", "high"], FakeOpenAI("high"))


# agents-api: the deployed agent's model parameters, overridden by the model's modelSpec preset.


def test_describe_effort_and_deployed_effort():
    assert agent_prompt.describe_effort({}) == "default"
    assert agent_prompt.describe_effort({"thinking": False}) == "thinking off"
    assert (
        agent_prompt.describe_effort({"thinking": True, "thinkingBudget": 2000}) == "thinking on, budget 2000"
    )
    assert agent_prompt.describe_effort({"effort": "high", "thinking": True}) == "high, thinking on"
    assert agent_prompt.describe_effort({"reasoning_effort": "low"}) == "low"
    specs = {"Sonnet": {"thinking": True}, "Plain": {}}
    assert agent_prompt.deployed_effort({"thinking": False}, None, None) == "thinking off"
    assert agent_prompt.deployed_effort({"thinking": False}, "Sonnet", specs) == "thinking on"
    assert agent_prompt.deployed_effort({"thinking": False}, "Plain", specs) == "thinking off"
    # Unknown when the agent or the spec couldn't be read.
    assert agent_prompt.deployed_effort(None, None, specs) is None
    assert agent_prompt.deployed_effort({}, "Sonnet", None) is None
    assert agent_prompt.deployed_effort({}, "Missing", specs) is None


def test_fetch_model_specs_keeps_only_effort_parameters(monkeypatch):
    config = """
endpoints: {anthropic: {apiKey: sk-secret}}
modelSpecs:
  list:
    - name: cBioPortalChatBeta
      preset: {endpoint: agents, agent_id: a, thinking: false, temperature: 0}
    - name: cBioPortalChatBetaSonnet
      preset: {endpoint: agents, agent_id: a, thinking: true, thinkingBudget: 4000}
"""
    calls = []
    monkeypatch.setattr(agent_prompt, "_kubectl", lambda args, ctx: calls.append(args) or config)
    assert agent_prompt.fetch_model_specs("cbioagent-librechat-beta") == {
        "cBioPortalChatBeta": {"thinking": False},
        "cBioPortalChatBetaSonnet": {"thinking": True, "thinkingBudget": 4000},
    }
    assert calls[0][:2] == ["exec", "deploy/cbioagent-librechat-beta"]
    monkeypatch.setattr(agent_prompt, "_kubectl", lambda args, ctx: "a: [sk-secret")
    with pytest.raises(RuntimeError) as exc:
        agent_prompt.fetch_model_specs("d")
    assert "sk-secret" not in str(exc.value)


def test_describe_agents_records_effort_parameters():
    agents = agent_prompt.describe_agents(
        "root",
        fetch=lambda agent_id, ctx: {
            "instructions": "x",
            "model_parameters": {"thinking": True, "thinkingBudget": 2000, "temperature": 1, "maxTokens": 9},
        },
    )
    assert agents["root"]["effort_parameters"] == {"thinking": True, "thinkingBudget": 2000}


def test_agents_api_run_records_each_models_deployed_effort(monkeypatch, results_dir):
    specs = {"cBioPortalChatBeta": {}, "cBioPortalChatBetaSonnet": {"thinking": True, "thinkingBudget": 4000}}
    _cli(
        monkeypatch,
        ["--target", "beta", "--models", "haiku,sonnet"],
        FakeAgent(),
        specs=lambda deployment, ctx: specs,
    )
    recorded = _run_json(results_dir)
    assert recorded["reasoning_efforts"] == {"haiku": "thinking off", "sonnet": "thinking on, budget 4000"}
    assert reasoning_effort(recorded, "sonnet") == "thinking on, budget 4000"
    assert reasoning_effort(recorded) is None


def test_agents_api_effort_is_unknown_when_the_specs_cant_be_read(monkeypatch, results_dir):
    def refused(deployment, ctx):
        raise RuntimeError("kubectl: forbidden")

    _cli(monkeypatch, ["--target", "beta", "--models", "haiku"], FakeAgent(), specs=refused)
    recorded = _run_json(results_dir)
    assert recorded["reasoning_efforts"] == {"haiku": None}
    assert "forbidden" in recorded["model_specs"]["error"]


def test_agents_api_effort_without_a_spec_is_the_agents_own(monkeypatch, results_dir):
    def never(deployment, ctx):
        raise AssertionError("no spec, no librechat.yaml")

    _cli(monkeypatch, ["--target", "beta-unified", "--models", "unified"], FakeAgent(), specs=never)
    assert _run_json(results_dir)["reasoning_efforts"] == {"unified": "thinking off"}


def test_report_and_index_show_per_model_deployed_effort(results_dir):
    bench = _run("20261020-0000", results_dir, {}, model="haiku", runner="agents-api")
    bench.data["models"] = ["haiku", "sonnet"]
    bench.data["reasoning_efforts"] = {"haiku": "thinking off", "sonnet": None}
    for qid in (1, 2):
        bench.records[record_key(qid, "sonnet", 1)] = _rec(qid, "sonnet")
    bench.save()
    html = write_report(bench).read_text()
    assert "Haiku 4.5</td><td>thinking off</td>" in html and "Sonnet 5</td><td>–</td>" in html
    index = (results_dir / "index.html").read_text()
    assert "Haiku 4.5</td>\n      <td>thinking off</td>" in index
    assert "Sonnet 5</td>\n      <td>–</td>" in index


# An agents-api resume reads the deployed configuration again (kubectl mocked) before anything is asked.


def _agents_run(monkeypatch, results_dir, sonnet_spec):
    monkeypatch.setattr(cli, "_current_deployed_efforts", REAL_CURRENT_DEPLOYED_EFFORTS)
    specs = {"cBioPortalChatBeta": {}, "cBioPortalChatBetaSonnet": sonnet_spec}
    _cli(monkeypatch, ["--target", "beta", "--models", "haiku,sonnet"], FakeAgent(), specs=lambda d, c: specs)
    run_json = results_dir / _run_json(results_dir)["run_id"] / "run.json"
    return run_json.parent.name, run_json.read_text()


REAL_CURRENT_DEPLOYED_EFFORTS = cli._current_deployed_efforts


def test_agents_api_resume_refuses_a_changed_deployed_effort(monkeypatch, results_dir):
    run_id, before = _agents_run(monkeypatch, results_dir, {"thinking": False})
    changed = {
        "cBioPortalChatBeta": {},
        "cBioPortalChatBetaSonnet": {"thinking": True, "thinkingBudget": 4000},
    }
    _, result = _cli(monkeypatch, ["--resume", run_id], FakeAgent(), exit_code=1, specs=lambda d, c: changed)
    assert "sonnet: 'thinking off' → 'thinking on, budget 4000'" in result.output
    assert "haiku:" not in result.output
    # Refused before anything is planned, saved or asked.
    assert (results_dir / run_id / "run.json").read_text() == before


def test_agents_api_resume_at_the_same_deployed_effort_continues(monkeypatch, results_dir):
    run_id, _ = _agents_run(monkeypatch, results_dir, {"thinking": False})
    same = {"cBioPortalChatBeta": {}, "cBioPortalChatBetaSonnet": {"thinking": False}}
    _, result = _cli(monkeypatch, ["--resume", run_id], FakeAgent(), specs=lambda d, c: same)
    assert "Warning: couldn't read" not in result.output


def test_agents_api_resume_warns_when_the_configuration_cant_be_read(monkeypatch, results_dir):
    run_id, _ = _agents_run(monkeypatch, results_dir, {"thinking": False})
    # Sonnet's spec is gone from librechat.yaml: only Haiku is checked.
    only_haiku = {"cBioPortalChatBeta": {}}
    _, result = _cli(monkeypatch, ["--resume", run_id], FakeAgent(), specs=lambda d, c: only_haiku)
    assert "couldn't read the deployed reasoning effort of sonnet again" in result.output

    def refused(deployment, ctx):
        raise RuntimeError("kubectl: forbidden")

    def no_agent(agent_id, ctx=None):
        raise RuntimeError("no cbioagent-mongodb pod")

    # Neither librechat.yaml nor the agent can be read: every model is unchecked, the resume still runs.
    for fetch_agent in (_agent, no_agent):
        _, result = _cli(
            monkeypatch, ["--resume", run_id], FakeAgent(), specs=refused, fetch_agent=fetch_agent
        )
        assert "couldn't read the deployed reasoning effort of haiku, sonnet again" in result.output


@pytest.mark.parametrize("allow_api_billing", [False, True])
def test_a_managed_policy_helper_refuses_an_explicit_effort(tmp_path, monkeypatch, allow_api_billing):
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "managed-settings.json").write_text(
        json.dumps({"policyHelper": {"command": "/usr/bin/policy"}})
    )
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (managed,))
    # Refused either way: by the billing guard, or (with per-token billing allowed) by the effort guard.
    with pytest.raises(RuntimeError, match="policyHelper") as exc:
        _client(effort="high", allow_api_billing=allow_api_billing)
    if allow_api_billing:
        assert "--reasoning-effort high would not be the effort" in str(exc.value)
        # Without an explicit effort the policyHelper doesn't matter to the effort record (unknown).
        asyncio.run(_client(allow_api_billing=True).aclose())


def test_report_notes_the_requested_effort_only_for_explicit_claude_code_runs(results_dir):
    note = "the level the benchmark requested of every Claude Code session"
    explicit = _run(
        "20261020-0000",
        results_dir,
        {"reasoning_efforts": {"sonnet": "high"}},
        model="sonnet",
        runner="claude-code",
    )
    explicit.data["options"] = {"reasoning_effort": "high"}
    explicit.save()
    html = write_report(explicit).read_text()
    assert note in html and "thinking off" not in html
    unset = _run(
        "20261020-0001",
        results_dir,
        {"reasoning_efforts": {"sonnet": None}},
        model="sonnet",
        runner="claude-code",
    )
    unset.data["options"] = {"reasoning_effort": None}
    unset.save()
    assert note not in write_report(unset).read_text()
    openai = _run("20261020-0002", results_dir, {"reasoning_effort": "high"})
    openai.data["options"] = {"reasoning_effort": "high"}
    openai.save()
    assert note not in write_report(openai).read_text()
