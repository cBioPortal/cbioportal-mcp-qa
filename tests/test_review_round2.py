"""Second review of #70: short password flags, regrading against refreshed references, and judge models."""

import copy
import json
import subprocess

import pytest
from click.testing import CliRunner
from test_review_fixes import JUDGE, _question, _rec, _run

from cbioportal_mcp_qa import agent_prompt
from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa.compare import compare, to_markdown, write_compare
from cbioportal_mcp_qa.dataset import Question
from cbioportal_mcp_qa.grade import Grade
from cbioportal_mcp_qa.redact import describe_error, redact
from cbioportal_mcp_qa.report import write_report
from cbioportal_mcp_qa.run import Run, grade_answers, record_key

SECRET = "SYNTHETIC_SECRET_x9"
OTHER_JUDGE = "us.anthropic.claude-opus-other"

# --- 1. Short password flags ------------------------------------------------------------------------------------

LEAKY_COMMANDS = [
    ["mongosh", "-p", SECRET],
    ["mongosh", f"-p{SECRET}"],
    ["mongosh", f"-p={SECRET}", "--quiet"],
    [
        "kubectl",
        "exec",
        "cbioagent-mongodb-0",
        "-c",
        "mongodb",
        "--",
        "mongosh",
        "-u",
        "cbioagent",
        "-p",
        SECRET,
    ],
    ["/usr/bin/mysql", "-u", "root", f"-p{SECRET}", "-h", "db"],
    ["redis-cli", "-h", "redis", "-p", "6379", "-a", SECRET],
    ["curl", "-u", f"admin:{SECRET}", "https://example.org"],
    ["sh", "-c", f"PGPASSWORD={SECRET} psql -h db -p 5432"],
]


@pytest.mark.parametrize("cmd", LEAKY_COMMANDS, ids=lambda c: " ".join(c[:2]))
def test_short_password_flags_do_not_reach_saved_results(results_dir, cmd):
    def fetch(agent_id, context):
        raise subprocess.CalledProcessError(1, cmd)

    agents = agent_prompt.describe_agents("agent_cbiobeta_router", None, fetch)
    assert "CalledProcessError" in agents["agent_cbiobeta_router"]["error"]
    bench = Run.create("beta-router", ["router"], 1, JUDGE, "input/questions.yaml", extra={"agents": agents})
    write_report(bench)
    for name in ("run.json", "summary.json"):
        text = (bench.dir / name).read_text()
        assert "agent_cbiobeta_router" in text and SECRET not in text, name
    assert all(SECRET not in p.read_text() for p in results_dir.rglob("*") if p.is_file())


@pytest.mark.parametrize(
    "text",
    [
        "Command '['kubectl', '-n', 'cbioagent', 'get', 'pods']' returned non-zero exit status 1.",
        "kubectl -n cbioagent port-forward svc/cbioagent-clickhouse-mcp 18080:80 -p 8080",
        "psql -h db -p 5432 -U reader",
        "redis-cli -h redis -p 6379 ping",
        "mysql -P 3306 -p -h db",  # -P is the port; a bare -p prompts
        "ssh -p 2222 -u me host",
        "Error: tokens: 1200, max_tokens=4096",
    ],
)
def test_harmless_flags_are_kept(text):
    assert redact(text) == text


def test_the_db_client_rule_stops_at_the_end_of_the_command():
    text = f"mongosh -p {SECRET}; ssh -p 2222 host | grep -p x"
    assert redact(text) == "mongosh -p ***; ssh -p 2222 host | grep -p x"
    assert SECRET not in describe_error(subprocess.CalledProcessError(1, ["mongosh", "-p", SECRET]))


# --- 2. Refreshing references keeps the asked text, and compare checks what was graded ----------------------------


class FakeJudge:
    """Records what it was asked to grade."""

    def __init__(self, model: str = JUDGE):
        self.model = model
        self.seen: list[Question] = []

    def grade(self, q, answer, studies, renders=None, tool_log=""):
        self.seen.append(q)
        return Grade(passed=True, declined=False, rationale="", number_match=None)


def _copy_run(run: Run, run_id: str) -> Run:
    import cbioportal_mcp_qa.run as run_mod

    copied = Run(run_mod.RESULTS_DIR / run_id / "run.json", copy.deepcopy(run.data) | {"run_id": run_id})
    copied.path.parent.mkdir(parents=True, exist_ok=True)
    copied.save()
    return copied


def _refresh(monkeypatch, run: Run, current: list[dict], judge: FakeJudge):
    monkeypatch.setattr(cli_mod, "load_questions", lambda path: [Question.from_dict(q) for q in current])
    monkeypatch.setattr(cli_mod, "_judge", lambda settings: judge)
    result = CliRunner().invoke(cli_mod.cli, ["grade", str(run.dir), "--refresh-questions"])
    assert result.exit_code == 0, result.output
    return Run.load(str(run.dir)), result


OLD_Q1 = {"question": "Old wording?", "notes": "old rubric"}
NEW_QUESTIONS = [
    _question(
        1, question="New wording?", notes="A correct answer must: give the new count", expected_answer="7"
    ),
    _question(2, notes="A correct answer must: also link the study"),
]


@pytest.fixture
def original(results_dir):
    """A run as recorded before the questions changed; its grades predate per-turn judges."""
    return _run("A", "haiku", 1, [_rec(1, "haiku", 1, **OLD_Q1), _rec(2, "haiku", 1)])


def test_refresh_updates_references_only_and_the_judge_sees_the_asked_text(original, monkeypatch):
    refreshed = _copy_run(original, "R")
    judge = FakeJudge()
    refreshed, result = _refresh(monkeypatch, refreshed, NEW_QUESTIONS, judge)
    seen = {q.id: q for q in judge.seen}
    assert seen[1].question == "Old wording?"  # what the agent answered
    assert seen[1].notes == "A correct answer must: give the new count" and seen[1].expected_answer == "7"
    assert seen[2].notes == "A correct answer must: also link the study"
    rec = refreshed.records[record_key(1, "haiku", 1)]
    assert rec["question"]["question"] == "Old wording?" and rec["question"]["expected_answer"] == "7"
    assert rec["grade"]["graded"]["question"] == "Old wording?"
    assert rec["grade"]["graded"]["notes"] == "A correct answer must: give the new count"
    assert "asked" not in rec
    assert "1 questions were reworded since this run asked them (1)" in result.output


def test_refreshed_run_is_flagged_against_the_original_and_the_new_wording(original, monkeypatch):
    refreshed, _ = _refresh(monkeypatch, _copy_run(original, "R"), NEW_QUESTIONS, FakeJudge())
    # Against the original: same text asked, different references graded.
    with pytest.raises(ValueError, match=r"2 questions changed.*Q1 \(expected_answer, notes\), Q2 \(notes\)"):
        compare(original, refreshed, "haiku", "haiku")
    # Against a run that asked the new text with the same references: only the wording differs.
    new = _run("B", "router", 1, [_rec(q["id"], "router", 1, **q) for q in NEW_QUESTIONS])
    grade_answers(new, FakeJudge())
    with pytest.raises(ValueError, match=r"1 questions changed.*Q1 \(question\)"):
        compare(refreshed, new, "haiku")
    result = compare(refreshed, new, "haiku", allow_mismatch=True)
    assert {q["id"]: q["mismatch"] for q in result["questions"]} == {1: ["question"], 2: []}


def test_compare_checks_the_graded_snapshot_not_later_edits(results_dir):
    a = _run("A", "haiku", 1, [_rec(1, "haiku", 1, graded=False)])
    b = _run("B", "router", 1, [_rec(1, "router", 1, graded=False)])
    for run in (a, b):
        grade_answers(run, FakeJudge())
    # Editing B's question after grading doesn't change what B was graded against...
    b.records[record_key(1, "router", 1)]["question"]["notes"] = "edited later"
    assert compare(a, b, "haiku")["mismatched_questions"] == []
    # ...but a different graded snapshot is a mismatch.
    b.records[record_key(1, "router", 1)]["grade"]["graded"]["notes"] = "graded differently"
    with pytest.raises(ValueError, match=r"Q1 \(notes\)"):
        compare(a, b, "haiku")


# --- 3. Judge models per graded turn ------------------------------------------------------------------------------


def test_regrading_with_another_judge_is_recorded_and_refused(original, monkeypatch):
    regraded, _ = _refresh(
        monkeypatch, _copy_run(original, "R"), [_question(1, **OLD_Q1), _question(2)], FakeJudge(OTHER_JUDGE)
    )
    grades = [r["grade"] for r in regraded.records.values()]
    assert {g["judge_model"] for g in grades} == {OTHER_JUDGE}
    assert regraded.data["judge_models"] == [OTHER_JUDGE] and regraded.data["judge_model"] == OTHER_JUDGE
    with pytest.raises(ValueError, match=f"judge model differs: A {JUDGE}, B {OTHER_JUDGE}"):
        compare(original, regraded, "haiku", "haiku")
    result = compare(original, regraded, "haiku", "haiku", allow_mismatch=True)
    assert any(f"judge model differs: A {JUDGE}, B {OTHER_JUDGE}" in w for w in result["warnings"])
    assert result["b"]["judge_models"] == [OTHER_JUDGE]
    assert f"judge `{OTHER_JUDGE}`" in to_markdown(result)


def test_mixed_judges_in_one_run_are_refused(original, results_dir):
    mixed = _copy_run(original, "M")
    mixed.records[record_key(2, "haiku", 1)].pop("grade")
    grade_answers(mixed, FakeJudge(OTHER_JUDGE))
    # The grade from before per-turn judges is attributed to the run's judge at the time.
    assert mixed.records[record_key(1, "haiku", 1)]["grade"]["judge_model"] == JUDGE
    assert mixed.records[record_key(2, "haiku", 1)]["grade"]["judge_model"] == OTHER_JUDGE
    assert mixed.data["judge_models"] == sorted([JUDGE, OTHER_JUDGE]) and mixed.data["judge_model"] == JUDGE
    with pytest.raises(ValueError, match="B was graded by more than one judge model"):
        compare(original, mixed, "haiku", "haiku")
    with pytest.raises(ValueError, match="A was graded by more than one judge model"):
        compare(mixed, original, "haiku", "haiku")
    headline = json.loads((write_report(mixed).parent / "summary.json").read_text())
    assert headline["judge_models"] == sorted([JUDGE, OTHER_JUDGE])


# --- Non-blocking: attempt rate and failure-inclusive latency in the breakdowns ------------------------------------


def test_breakdowns_show_attempt_rate_and_latency_with_failures(results_dir):
    a = _run("A", "haiku", 1, [_rec(1, "haiku", 1, latency=4.0), _rec(3, "haiku", 1, latency=4.0)])
    b = _run(
        "B",
        "router",
        2,
        [
            _rec(1, "router", 1, latency=4.0),
            _rec(1, "router", 2, status=504, latency=300.0),
            _rec(3, "router", 1, passed=False, declined=True, latency=6.0),
            _rec(3, "router", 2, latency=8.0),
        ],
    )
    result = compare(a, b, "haiku")
    md = to_markdown(result)
    assert "Attempt rate A" in md and "Median incl. failed A" in md and "p90 incl. failed A" in md
    row = next(line for line in md.splitlines() if line.startswith("| Study discovery |"))
    assert "50.0%" in row and "300.0s" in row  # B: attempt rate 1/2; p90 with the failed turn at 300s
    html = write_compare(result).read_text()
    assert "Attempt rate A" in html and "Median incl. failed A" in html and "300.0s" in html
