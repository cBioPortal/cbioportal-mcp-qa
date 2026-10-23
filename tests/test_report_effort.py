"""The reasoning effort a run asked with: recorded in run.json, shown in the report, index and comparison, with
the same model at two efforts kept apart and runs from before it was recorded shown as "–"."""

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
    assert reasoning_effort({"runner": "claude-code", "reasoning_effort": "thinking off"}) == "thinking off"
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


# claude-code: the effort level sessions resolve themselves (Claude Code doesn't report it), per model, recorded
# apart from thinking (always off).

SONNET5, SONNET55, OPUS55, OPUS46 = (
    "claude-sonnet-5",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-opus-4-6",
)


@pytest.fixture
def claude_home(tmp_path):
    home = tmp_path / "claude-home"
    home.mkdir(exist_ok=True)
    return home


@pytest.fixture
def managed(tmp_path, monkeypatch):
    d = tmp_path / "managed"
    (d / "managed-settings.d").mkdir(parents=True)
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (d,))
    return d


def _effort(model, home, isolate=False, extra_env=None):
    env = {"CLAUDE_CONFIG_DIR": str(home), **(extra_env or {})}
    return claude_code.effort_for(model, env, isolate)


def _write(path, doc):
    path.write_text(json.dumps(doc))


def test_effort_defaults_per_model(claude_home):
    assert _effort(SONNET5, claude_home) == "high"
    assert _effort(SONNET55, claude_home) == "medium"
    # A model without effort levels, matched through its dated id.
    assert _effort("claude-haiku-4-5-20251001", claude_home) == claude_code.NO_EFFORT
    assert claude_code.canonical_model("us.anthropic.claude-sonnet-5-v1:0") == SONNET5
    assert claude_code.canonical_model("claude-opus-4-7-20260101[1m]") == "claude-opus-4-7"


def test_user_settings_at_different_levels_are_told_apart(claude_home):
    for level in ("low", "high"):
        _write(claude_home / "settings.json", {"effortLevel": level})
        assert _effort(SONNET5, claude_home) == level
        # Isolated sessions don't load user settings.
        assert _effort(SONNET5, claude_home, isolate=True) == "high"
    # A user-settings top-level effortLevel doesn't apply to Opus 5.5.
    assert _effort(OPUS55, claude_home) == "medium"


def test_settings_env_wins_over_the_inherited_variable(claude_home):
    inherited = {"CLAUDE_CODE_EFFORT_LEVEL": "low"}
    assert _effort(SONNET5, claude_home, extra_env=inherited) == "low"
    _write(
        claude_home / "settings.json", {"env": {"CLAUDE_CODE_EFFORT_LEVEL": "xhigh"}, "effortLevel": "medium"}
    )
    assert _effort(SONNET5, claude_home, extra_env=inherited) == "xhigh"
    # Isolated: the user file's env isn't applied, so the inherited value is.
    assert _effort(SONNET5, claude_home, isolate=True, extra_env=inherited) == "low"
    # An empty settings value unsets it; `auto` is the model's default, not the settings' level.
    _write(claude_home / "settings.json", {"env": {"CLAUDE_CODE_EFFORT_LEVEL": ""}, "effortLevel": "medium"})
    assert _effort(SONNET5, claude_home, extra_env=inherited) == "medium"
    _write(claude_home / "settings.json", {"effortLevel": "medium"})
    assert _effort(SONNET5, claude_home, extra_env={"CLAUDE_CODE_EFFORT_LEVEL": "auto"}) == "high"


def test_managed_env_wins_over_user_env(claude_home, managed):
    _write(claude_home / "settings.json", {"env": {"CLAUDE_CODE_EFFORT_LEVEL": "low"}})
    _write(managed / "managed-settings.json", {"env": {"CLAUDE_CODE_EFFORT_LEVEL": "xhigh"}})
    assert _effort(SONNET5, claude_home) == "xhigh"


def test_managed_drop_ins_merge_over_the_base_file(claude_home, managed):
    _write(managed / "managed-settings.json", {"effortLevel": "low"})
    _write(managed / "managed-settings.d" / "20-effort.json", {"effortLevel": "high"})
    _write(managed / "managed-settings.d" / ".hidden.json", {"effortLevel": "medium"})
    assert _effort(SONNET5, claude_home) == "high"
    # Alphabetical: a later drop-in replaces an earlier one.
    _write(managed / "managed-settings.d" / "30-effort.json", {"effortLevel": "medium"})
    assert _effort(SONNET5, claude_home) == "medium"
    # Nested blocks merge key by key.
    _write(
        managed / "managed-settings.d" / "40-models.json",
        {"modelSettings": {SONNET55: {"effortLevel": "low"}}},
    )
    _write(
        managed / "managed-settings.d" / "50-models.json", {"modelSettings": {OPUS46: {"effortLevel": "low"}}}
    )
    assert (_effort(SONNET55, claude_home), _effort(OPUS46, claude_home)) == ("low", "low")
    # Managed outranks user settings, which still can't override it.
    _write(claude_home / "settings.json", {"effortLevel": "xhigh"})
    assert _effort(SONNET5, claude_home) == "medium"


def test_first_managed_source_with_a_policy_wins(claude_home, managed):
    _write(managed / "managed-settings.json", {"effortLevel": "low"})
    # The server-managed cache ranks above the file and is selected: the file's effortLevel is skipped.
    _write(claude_home / "remote-settings.json", {"channelsEnabled": True})
    assert _effort(SONNET5, claude_home) == "high"
    # Unless the selected source merges every admin source.
    _write(claude_home / "remote-settings.json", {"channelsEnabled": True, "managedSourcesBehavior": "merge"})
    assert _effort(SONNET5, claude_home) == "low"
    # A source with only control keys isn't selected.
    _write(claude_home / "remote-settings.json", {"managedSourcesBehavior": "first-wins"})
    assert _effort(SONNET5, claude_home) == "low"


def test_model_settings_apply_per_model(claude_home):
    _write(
        claude_home / "settings.json",
        {
            "effortLevel": "low",
            "modelSettings": {SONNET55: {"effortLevel": "xhigh"}, OPUS55: {"effortLevel": "high"}},
        },
    )
    # The model's own entry wins over the file's top-level level; other models get the top-level one.
    assert _effort(SONNET55, claude_home) == "xhigh"
    assert _effort(OPUS55, claude_home) == "high"
    assert _effort(SONNET5, claude_home) == "low"
    # Matched through a dated or [1m] id.
    assert _effort(SONNET55 + "-20260901[1m]", claude_home) == "xhigh"


def test_effort_is_clamped_and_capped(claude_home, managed):
    _write(claude_home / "settings.json", {"effortLevel": "xhigh"})
    # Opus 4.6 has no xhigh: the highest level at or below it.
    assert _effort(OPUS46, claude_home) == "high"
    _write(
        managed / "managed-settings.json",
        {"maxEffortLevel": "medium", "modelSettings": {SONNET55: {"maxEffortLevel": "max"}}},
    )
    assert _effort(SONNET5, claude_home) == "medium"
    _write(claude_home / "settings.json", {"modelSettings": {SONNET55: {"effortLevel": "xhigh"}}})
    assert _effort(SONNET55, claude_home) == "xhigh"


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

    def __init__(self, efforts=None):
        self.efforts = efforts or {}

    def effort_for(self, model):
        return self.efforts.get(model, "high")

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


def test_claude_code_runs_record_each_models_effort(monkeypatch, results_dir):
    base = ["--runner", "claude-code", "--target", "beta", "--models", "sonnet,sonnet-5.5"]
    _cli(monkeypatch, base, FakeClaudeCode({"sonnet": "low", "sonnet-5.5": "xhigh"}))
    recorded = _run_json(results_dir)
    assert recorded["reasoning_efforts"] == {"sonnet": "low", "sonnet-5.5": "xhigh"}
    assert recorded["thinking"] == "off" and "reasoning_effort" not in recorded
    assert (reasoning_effort(recorded, "sonnet"), reasoning_effort(recorded, "sonnet-5.5")) == (
        "low",
        "xhigh",
    )


def test_claude_code_client_resolves_effort_from_its_settings(monkeypatch, tmp_path):
    home = tmp_path / "claude-home"
    home.mkdir(exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"modelSettings": {SONNET55: {"effortLevel": "low"}}}))
    client = claude_code.ClaudeCodeClient.__new__(claude_code.ClaudeCodeClient)
    client.env, client.settings = {"CLAUDE_CONFIG_DIR": str(home)}, {"enabledPlugins": {}}
    client.isolate_settings = False
    assert (client.effort_for("sonnet-5.5"), client.effort_for("sonnet")) == ("low", "high")
    client.isolate_settings = True
    assert client.effort_for("sonnet-5.5") == "medium"


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


def test_resume_of_a_claude_code_run_whose_effort_level_changed_is_refused(monkeypatch, results_dir):
    base = ["--runner", "claude-code", "--target", "beta", "--models", "sonnet,sonnet-5.5"]
    _cli(monkeypatch, base, FakeClaudeCode({"sonnet": "low", "sonnet-5.5": "medium"}))
    run_id = _run_json(results_dir)["run_id"]
    _, result = _cli(
        monkeypatch,
        ["--resume", run_id],
        FakeClaudeCode({"sonnet": "low", "sonnet-5.5": "high"}),
        exit_code=1,
    )
    assert "sonnet-5.5: 'medium' → 'high'" in result.output and "sonnet:" not in result.output
    _cli(monkeypatch, ["--resume", run_id], FakeClaudeCode({"sonnet": "low", "sonnet-5.5": "medium"}))


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
