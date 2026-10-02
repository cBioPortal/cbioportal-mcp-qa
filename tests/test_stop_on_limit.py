"""A stop (the usage limit, a plugin, per-token billing) ends a batch of answers at once: in-flight answers finish,
queued ones never start a session and get no record, and `--resume` asks exactly those. A fake `claude` process
(no model calls)."""

import asyncio
import json
import shlex

import pytest
from click.testing import CliRunner
from test_review_fixes import _question, _run

from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa.claude_code import ClaudeCodeClient
from cbioportal_mcp_qa.dataset import Question
from cbioportal_mcp_qa.run import Run, collect_answers, record_key

LIMIT_MESSAGE = "You've hit your session limit · resets 9:50pm (Pacific/Honolulu)"


def _init() -> str:
    return json.dumps(
        {"type": "system", "subtype": "init", "tools": [], "plugins": [], "apiKeySource": "none"}
    )


def answered(text="the answer"):
    return [_init(), json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text})]


def limited(message=LIMIT_MESSAGE):
    return [json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": message})]


class FakeClaude:
    """Stands in for `claude -p` processes: `script(question, n)` gives (stream lines, seconds to take) for the
    n-th session started; `asked` lists each session's question in start order."""

    def __init__(self, monkeypatch, script):
        self.script = script
        self.asked: list[str] = []
        fake = self

        class Proc:
            def __init__(self, lines, delay):
                self.lines, self.delay = lines, delay
                self.returncode = 0

            async def communicate(self):
                await asyncio.sleep(self.delay)
                return ("\n".join(self.lines).encode(), b"")

        async def fake_exec(*args, **kwargs):
            question = args[args.index("-p") + 1]
            fake.asked.append(question)
            lines, delay = fake.script(question, len(fake.asked))
            return Proc(lines, delay)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr("cbioportal_mcp_qa.claude_code.probe_mcp_servers", lambda *a: set())

    def client(self) -> ClaudeCodeClient:
        return ClaudeCodeClient("PROMPT", "http://db/mcp", "https://nav/mcp")


QUESTIONS = [Question.from_dict(_question(q)) for q in range(1, 11)]


def _collect(run, client, concurrency):
    async def go():
        try:
            return await collect_answers(run, QUESTIONS, client, concurrency)
        finally:
            await client.aclose()

    return asyncio.run(go())


def test_a_limit_mid_batch_stops_queued_answers_and_resume_asks_exactly_them(monkeypatch, results_dir):
    run = _run("L", "haiku", 1, [])

    # Q1 and Q3 are slow and in flight when Q2 hits the limit at once; Q4–Q10 are queued behind them.
    def script(question, n):
        if question == "Question 2?":
            return limited(), 0.0
        return answered(), 0.2

    fake = FakeClaude(monkeypatch, script)
    unasked = _collect(run, fake.client(), concurrency=3)
    assert fake.asked == ["Question 1?", "Question 2?", "Question 3?"]  # no session after the limit
    saved = Run.load(str(run.dir)).records
    # In-flight answers finished and were saved; the limited one and the queued ones have no record.
    assert sorted(saved) == [record_key(1, "haiku", 1), record_key(3, "haiku", 1)]
    assert all(r["reply"]["status"] == 200 for r in saved.values())
    assert unasked == 8

    fake = FakeClaude(monkeypatch, lambda question, n: (answered(), 0.0))
    assert _collect(Run.load(str(run.dir)), fake.client(), concurrency=3) == 0
    assert sorted(fake.asked) == sorted(f"Question {q}?" for q in (2, 4, 5, 6, 7, 8, 9, 10))
    saved = Run.load(str(run.dir)).records
    assert len(saved) == 10 and all(r["reply"]["status"] == 200 for r in saved.values())


def test_another_in_flight_limit_and_ordinary_failures(monkeypatch, results_dir):
    """Two sessions in flight hit the limit: neither is recorded. An ordinary failure in flight is saved."""
    run = _run("M", "haiku", 1, [])

    def script(question, n):
        if question == "Question 1?":
            return limited(), 0.0
        if question == "Question 2?":
            return limited("You've hit your limit · resets 3pm"), 0.1
        if question == "Question 3?":
            return [_init(), json.dumps({"type": "result", "is_error": True, "result": "boom"})], 0.1
        return answered(), 0.0

    fake = FakeClaude(monkeypatch, script)
    client = fake.client()
    client.retries = 0
    _collect(run, client, concurrency=3)
    saved = Run.load(str(run.dir)).records
    assert list(saved) == [record_key(3, "haiku", 1)]
    assert saved[record_key(3, "haiku", 1)]["reply"]["error"] == "boom"
    assert len(fake.asked) == 3


def test_a_plugin_stop_leaves_the_rest_unrecorded(monkeypatch, results_dir):
    run = _run("P", "haiku", 1, [])
    plugin = json.dumps(
        {"type": "system", "subtype": "init", "tools": [], "plugins": [{"name": "late@builtin"}]}
    )

    def script(question, n):
        if question == "Question 1?":
            return [plugin, *answered()[1:]], 0.0
        return answered(), 0.2

    fake = FakeClaude(monkeypatch, script)
    client = fake.client()
    _collect(run, client, concurrency=2)
    assert client.plugins_error and "late@builtin" in client.plugins_error
    assert len(fake.asked) == 2
    assert list(Run.load(str(run.dir)).records) == [record_key(2, "haiku", 1)]


def test_concurrent_stops_are_each_left_unrecorded_and_all_reported(monkeypatch, results_dir):
    """Q1 hits the usage limit; Q2, already in flight, then loads an unexpected plugin. Each reply is classified
    by its own content, so neither is recorded; the limit stays the reason, and the plugin is reported too."""
    run = _run("C", "haiku", 1, [])
    plugin = json.dumps(
        {"type": "system", "subtype": "init", "tools": [], "plugins": [{"name": "late@builtin"}]}
    )

    def script(question, n):
        if question == "Question 1?":
            return limited(), 0.0
        return [plugin, *answered()[1:]], 0.1

    fake = FakeClaude(monkeypatch, script)
    client = fake.client()
    _collect(run, client, concurrency=2)
    assert Run.load(str(run.dir)).records == {}
    assert [kind for kind, _ in client.stops] == ["usage_limit", "plugins_error"]
    assert client.stop_reason() == LIMIT_MESSAGE
    message = cli_mod._stop_message(client, client.stops, "RESUME")
    assert message.startswith("Claude subscription limit: " + LIMIT_MESSAGE)
    assert "Also stopped: the claude session loaded plugins ['late@builtin']" in message


@pytest.fixture
def cli_run(monkeypatch, results_dir):
    """`run --runner claude-code --models haiku` with the deployment lookups stubbed; `fake` is set by each test."""
    monkeypatch.setattr(cli_mod, "fetch_agent_prompt", lambda *a: {"instructions": "PROMPT", "id": "x"})
    monkeypatch.setattr(cli_mod, "_check_database_mcp", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "describe_agents", lambda *a: {})
    monkeypatch.setattr(cli_mod, "collect_versions", lambda *a, **k: {})
    monkeypatch.setattr(cli_mod, "prompt_parity", lambda *a, **k: {})
    holder = {}
    monkeypatch.setattr(cli_mod, "_client", lambda *a, **k: holder["fake"].client())

    def invoke(fake, *args):
        holder["fake"] = fake
        return CliRunner().invoke(cli_mod.cli, ["run", "--runner", "claude-code", "--models", "haiku", *args])

    return invoke


def _only_run(results_dir) -> Run:
    return Run.load(next(p for p in results_dir.iterdir() if (p / "run.json").exists()).name)


def _resume_command(output: str) -> list[str]:
    start = output.index("`cbioportal-mcp-qa run --resume")
    return shlex.split(output[start + 1 : output.index("`", start + 1)])


def test_run_stops_on_the_limit_with_the_resume_command(monkeypatch, results_dir, cli_run):
    fake = FakeClaude(monkeypatch, lambda q, n: (limited(), 0.0) if n == 2 else (answered(), 0.1))
    out = cli_run(
        fake, "--questions", "1-8", "--concurrency", "2", "--no-grade", "--no-render",
        "--claude-code-trust-org-policy",
    )  # fmt: skip
    assert out.exit_code == 1, out.output
    assert "Claude subscription limit: You've hit your session limit" in out.output
    assert "Stopped before grading" in out.output
    run = _only_run(results_dir)
    cmd = _resume_command(out.output)
    assert cmd[:4] == ["cbioportal-mcp-qa", "run", "--resume", run.data["run_id"]]
    assert "--claude-code-trust-org-policy" in cmd
    assert len(fake.asked) == 2 and len(run.records) == 1
    assert "failed" not in out.output

    fake = FakeClaude(monkeypatch, lambda q, n: (answered(), 0.0))
    out = cli_run(fake, *cmd[2:])
    assert out.exit_code == 0, out.output
    assert len(fake.asked) == 7
    assert len(Run.load(run.data["run_id"]).records) == 8


def test_the_resume_command_and_resume_keep_the_selection_and_no_grade(monkeypatch, results_dir, cli_run):
    """`--questions 2-4 --no-grade`: the printed command keeps them, and a bare `--resume <run>` restores them
    from run.json (it doesn't ask every question, or grade)."""
    fake = FakeClaude(monkeypatch, lambda q, n: (limited(), 0.0) if n == 2 else (answered(), 0.0))
    out = cli_run(
        fake, "--questions", "2-4", "--concurrency", "1", "--no-grade", "--no-render", "--wait-on-limit",
        "--max-wait", "1", "--claude-code-trust-org-policy",
    )  # fmt: skip
    assert out.exit_code == 1, out.output
    run = _only_run(results_dir)
    cmd = _resume_command(out.output)
    for option in (["--questions", "2-4"], ["--no-grade"], ["--no-render"], ["--concurrency", "1"],
                   ["--wait-on-limit"], ["--max-wait", "1.0"], ["--claude-code-trust-org-policy"]):  # fmt: skip
        at = cmd.index(option[0])
        assert cmd[at : at + len(option)] == option, cmd
    assert run.data["options"]["selection"] == "2-4" and run.data["options"]["no_grade"] is True

    def grading(*a, **k):
        raise AssertionError("resume graded although the run was --no-grade")

    monkeypatch.setattr(cli_mod, "_grade", grading)
    monkeypatch.setattr(cli_mod, "render_navigation_links", grading)
    fake = FakeClaude(monkeypatch, lambda q, n: (answered(), 0.0))
    out = cli_run(fake, "--resume", run.data["run_id"], "--claude-code-trust-org-policy")
    assert out.exit_code == 0, out.output
    assert len(fake.asked) == 2  # Q3 and Q4 only, not the whole questions file
    assert sorted(r["question"]["id"] for r in Run.load(run.data["run_id"]).records.values()) == [2, 3, 4]


def test_a_billing_stop_prints_the_resume_command(monkeypatch, results_dir, cli_run):
    billed = [json.dumps({"type": "system", "subtype": "init", "tools": [], "plugins": [],
                          "apiKeySource": "ANTHROPIC_API_KEY"}), *answered()[1:]]  # fmt: skip
    fake = FakeClaude(monkeypatch, lambda q, n: (billed, 0.0))
    out = cli_run(fake, "--questions", "1-3", "--no-grade", "--no-render")
    assert out.exit_code == 1, out.output
    assert "Stopped before grading" in out.output
    cmd = _resume_command(out.output)
    assert cmd[2:4] == ["--resume", _only_run(results_dir).data["run_id"]] and "--no-grade" in cmd
    assert _only_run(results_dir).records == {}


def test_unasked_turns_count_as_missing_in_the_report_and_compare(monkeypatch, results_dir, cli_run):
    """A run stopped after Q1 of 1-4 is incomplete: the report counts 4 questions (3 failed requests, as their
    failure records did), and `compare` warns that it has 3 missing turns."""
    from cbioportal_mcp_qa.compare import compare
    from cbioportal_mcp_qa.report import summarize

    fake = FakeClaude(monkeypatch, lambda q, n: (limited(), 0.0) if n == 2 else (answered(), 0.0))
    out = cli_run(fake, "--questions", "1-4", "--concurrency", "1", "--no-grade", "--no-render")
    assert out.exit_code == 1, out.output
    stopped = _only_run(results_dir)
    assert len(stopped.records) == 1
    summary = summarize(stopped)
    assert summary["n_questions"] == 4
    (stats,) = summary["models"]
    assert stats.answers == 1 and stats.outcomes["error"] == 3

    planned = stopped.data["planned_questions"]
    complete = _run(
        "full", "haiku", 1,
        [{"question": q, "model": "haiku", "repeat": 1, "reply": {"answer": "x", "status": 200, "error": None,
          "latency_s": 1.0, "started_at": 0.0}} for q in planned],
    )  # fmt: skip
    complete.data["questions_file"] = stopped.data["questions_file"]
    result = compare(complete, stopped, "haiku", "haiku", allow_mismatch=True)
    assert [q["id"] for q in sorted(result["questions"], key=lambda q: q["id"])] == [q["id"] for q in planned]
    warning = next(
        w for w in result["warnings"] if w.startswith(f"B ({stopped.data['run_id']}) is incomplete")
    )
    assert "1 of 4 expected turns completed" in warning and "3 missing" in warning


def test_runs_without_planned_questions_report_as_before(results_dir):
    from test_review_fixes import _rec

    from cbioportal_mcp_qa.report import summarize

    old = _run("old", "haiku", 1, [_rec(1, "haiku", 1)])
    assert "planned_questions" not in old.data and old.missing_records() == []
    assert summarize(old)["n_questions"] == 1
