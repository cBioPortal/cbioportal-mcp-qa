"""A stop (the usage limit, a plugin, per-token billing) ends a batch of answers at once: in-flight answers finish,
queued ones never start a session and get no record, and `--resume` asks exactly those. A fake `claude` process
(no model calls)."""

import asyncio
import json

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


@pytest.fixture
def cli_run(monkeypatch, results_dir):
    """`run --runner claude-code` with the deployment lookups stubbed; `fake` is set by each test."""
    monkeypatch.setattr(cli_mod, "fetch_agent_prompt", lambda *a: {"instructions": "PROMPT", "id": "x"})
    monkeypatch.setattr(cli_mod, "_check_database_mcp", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "describe_agents", lambda *a: {})
    monkeypatch.setattr(cli_mod, "collect_versions", lambda *a, **k: {})
    monkeypatch.setattr(cli_mod, "prompt_parity", lambda *a, **k: {})
    holder = {}
    monkeypatch.setattr(cli_mod, "_client", lambda *a, **k: holder["fake"].client())

    def invoke(fake, *args):
        holder["fake"] = fake
        return CliRunner().invoke(
            cli_mod.cli,
            ["run", "--runner", "claude-code", "--models", "haiku", "--no-grade", "--no-render", *args],
        )

    return invoke


def test_run_stops_on_the_limit_with_the_resume_command(monkeypatch, results_dir, cli_run):
    fake = FakeClaude(monkeypatch, lambda q, n: (limited(), 0.0) if n == 2 else (answered(), 0.1))
    out = cli_run(fake, "--questions", "1-8", "--concurrency", "2", "--claude-code-trust-org-policy")
    assert out.exit_code == 1, out.output
    assert "Claude subscription limit: You've hit your session limit" in out.output
    assert "Stopped before grading" in out.output
    run = Run.load(next(p for p in results_dir.iterdir() if (p / "run.json").exists()).name)
    assert (
        f"`cbioportal-mcp-qa run --resume {run.data['run_id']} --claude-code-trust-org-policy`" in out.output
    )
    assert len(fake.asked) == 2 and len(run.records) == 1
    assert "failed" not in out.output

    fake = FakeClaude(monkeypatch, lambda q, n: (answered(), 0.0))
    out = cli_run(
        fake, "--questions", "1-8", "--resume", run.data["run_id"], "--claude-code-trust-org-policy"
    )
    assert out.exit_code == 0, out.output
    assert len(fake.asked) == 7
    assert len(Run.load(run.data["run_id"]).records) == 8
