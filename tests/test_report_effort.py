"""The reasoning effort a run asked with: recorded in run.json, shown in the report, index and comparison, with
the same model at two efforts kept apart and runs from before it was recorded shown as "–"."""

import json

from click.testing import CliRunner

from cbioportal_mcp_qa import cli
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


def _cli_run(monkeypatch, runner: str, args: list[str], client) -> dict:
    monkeypatch.setattr("cbioportal_mcp_qa.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_MCP_URL", "http://localhost:18081/db/mcp")
    monkeypatch.setenv("DATABASE_MCP_ENV", "beta")
    monkeypatch.setattr(cli, "fetch_agent_prompt", lambda agent_id, ctx=None: {"instructions": "AGENT"})
    monkeypatch.setattr(cli, "describe_agents", lambda *a: {})
    monkeypatch.setattr(cli, "collect_versions", lambda *a: {})
    monkeypatch.setattr(cli, "write_report", lambda bench: bench.dir / "report.html")
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
    result = CliRunner().invoke(
        cli.cli,
        ["run", "--runner", runner, "--target", "beta", "--questions", "1", "--no-grade", "--no-render"]
        + args,
    )
    assert result.exit_code == 0, result.output
    return seen


class FakeOpenAI:
    stops = []

    def __init__(self, effort):
        self.effort = effort

    async def start(self):
        pass

    def describe(self):
        return {"reasoning_effort": self.effort}

    async def aclose(self):
        pass


def test_openai_run_records_its_effort(monkeypatch, results_dir):
    seen = _cli_run(
        monkeypatch, "openai", ["--models", MODEL, "--reasoning-effort", "low"], FakeOpenAI("low")
    )
    # The request is unchanged: the client is given the same effort it was before.
    assert seen["reasoning_effort"] == "low"
    (run_json,) = results_dir.glob("*/run.json")
    assert json.loads(run_json.read_text())["reasoning_effort"] == "low"


def test_openai_run_without_an_effort_records_the_default(monkeypatch, results_dir):
    seen = _cli_run(monkeypatch, "openai", ["--models", MODEL], FakeOpenAI(None))
    assert seen["reasoning_effort"] is None
    (run_json,) = results_dir.glob("*/run.json")
    assert json.loads(run_json.read_text())["reasoning_effort"] == "default"


class FakeClaudeCode:
    stops = []
    setup = type("Setup", (), {"connector": None})()

    def describe(self):
        return {}

    async def aclose(self):
        pass


def test_claude_code_run_records_thinking_off(monkeypatch, results_dir):
    monkeypatch.setattr(cli, "prompt_parity", lambda *a: {})
    _cli_run(monkeypatch, "claude-code", ["--models", "haiku"], FakeClaudeCode())
    (run_json,) = results_dir.glob("*/run.json")
    assert json.loads(run_json.read_text())["reasoning_effort"] == "thinking off"
