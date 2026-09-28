"""Third review of #70: quoted command-line values, and runs refreshed before references-only refreshes."""

import subprocess

import pytest
from click.testing import CliRunner
from test_review_fixes import JUDGE, _question, _rec, _run
from test_review_round2 import FakeJudge

from cbioportal_mcp_qa import agent_prompt
from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa.compare import compare, to_markdown
from cbioportal_mcp_qa.dataset import Question
from cbioportal_mcp_qa.redact import redact
from cbioportal_mcp_qa.report import write_report
from cbioportal_mcp_qa.run import Run, grade_answers, record_key

# Two halves, so a value masked only up to a space or delimiter still shows.
HEAD, TAIL = "SYNTH_HEAD_q4", "SYNTH_TAIL_k8"
BOTH = f"{HEAD} {TAIL}"

# --- 1. Quoted values and quoted delimiters --------------------------------------------------------------------

QUOTED_COMMANDS = {
    "double-quoted value": ["sh", "-c", f'mongosh -p "{BOTH}"'],
    "single-quoted delimiter": ["sh", "-c", f"mongosh -p '{HEAD};{TAIL}'"],
    "bracket in an earlier arg": ["sh", "-c", f'mongosh --eval "x[0]" -p {HEAD}'],
    "delimiters in an earlier arg": ["sh", "-c", f"mongosh --eval 'a; b | c & d]' -p '{BOTH}'"],
    "both quote kinds": ["sh", "-c", f"mongosh -p '{BOTH}' --eval \"db.x.find()\""],
    "attached quoted": ["sh", "-c", f'mysql -u root -p"{BOTH}" -h db'],
    "attached with =": ["sh", "-c", f"mongosh -p='{HEAD}|{TAIL}' --quiet"],
    "redis-cli -a": ["sh", "-c", f"redis-cli -h redis -p 6379 -a '{BOTH}' ping"],
    "long flag": ["sh", "-c", f'mongosh --password "{BOTH}" --quiet'],
    "long flag with =": ["sh", "-c", f"mongosh --password='{HEAD}&{TAIL}'"],
    "user:pass": ["sh", "-c", f'curl -u "admin:{BOTH}" https://example.org'],
    "env password": ["sh", "-c", f'PGPASSWORD="{BOTH}" psql -h db -p 5432'],
    "unclosed quote": ["sh", "-c", f'mongosh -p "{BOTH}'],
    "argv item with a space": ["mongosh", "--eval", "x[0]; y", "-p", BOTH],
    "argv attached": ["/usr/bin/mysql", f"-p{BOTH}"],
    "argv long flag": ["mongosh", f"--password={BOTH}"],
    "string command": f"mongosh -p '{HEAD};{TAIL}'",
    "string command, unquoted": f'mongosh --eval "x[0]" -p {HEAD} --quiet',
}


@pytest.mark.parametrize("cmd", QUOTED_COMMANDS.values(), ids=QUOTED_COMMANDS.keys())
def test_quoted_values_do_not_reach_saved_results(results_dir, cmd):
    def fetch(agent_id, context):
        raise subprocess.CalledProcessError(1, cmd)

    agents = agent_prompt.describe_agents("agent_cbiobeta_router", None, fetch)
    assert "CalledProcessError" in agents["agent_cbiobeta_router"]["error"]
    bench = Run.create("beta-router", ["router"], 1, JUDGE, "input/questions.yaml", extra={"agents": agents})
    write_report(bench)
    files = [p for p in results_dir.rglob("*") if p.is_file()]
    assert {p.name for p in files} >= {"run.json", "summary.json", "report.html"}
    for path in files:
        text = path.read_text()
        assert HEAD not in text and TAIL not in text, path.name


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('mongosh -p "alpha beta"', "mongosh -p ***"),
        ("mongosh -p 'alpha;omega' --quiet", "mongosh -p *** --quiet"),
        ('mongosh --eval "x[0]" -p SECRET', 'mongosh --eval "x[0]" -p ***'),
        (
            "mongosh --eval 'db.x.find({a: \"; -p\"})' -p S3",
            "mongosh --eval 'db.x.find({a: \"; -p\"})' -p ***",
        ),
        (
            "Command '['sh', '-c', 'mongosh -p \"alpha beta\"']' returned non-zero exit status 1.",
            "Command '['sh', '-c', 'mongosh -p ***']' returned non-zero exit status 1.",
        ),
        ("['mongosh', '-p', 'alpha beta', '--quiet']", "['mongosh', '-p', '***', '--quiet']"),
        (
            "Command 'mongosh -p SECRET' returned non-zero exit status 1.",
            "Command 'mongosh -p ***' returned non-zero exit status 1.",
        ),
        ('mongosh -p "alpha beta\nnext line', "mongosh -p ***\nnext line"),  # unclosed: the rest of the line
        ('curl -u "admin:alpha beta" x', 'curl -u "admin:***" x'),
        ('PGPASSWORD="alpha beta" psql -p 5432', 'PGPASSWORD="***" psql -p 5432'),
        ("mongosh -p alpha; ssh -p 2222 host", "mongosh -p ***; ssh -p 2222 host"),
    ],
)
def test_quoted_values_are_masked_in_full(text, expected):
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        'kubectl -n cbioagent exec pod -c mongodb -- mongosh --quiet --eval "db.x.find({a: 1}).toArray()"',
        "mongosh --eval 'print(\"-p 1\")' --quiet",
        "ssh -p 2222 'host;x' -- ls",
        "psql -h db -p 5432 -c \"select 'a;b'\"",
        "redis-cli -h redis -p 6379 ping",
        "Command '['kubectl', '-n', 'cbioagent', 'get', 'pods']' returned non-zero exit status 1.",
        "it can't connect: mysql -P 3306 -h db",
    ],
)
def test_harmless_quoted_commands_are_kept(text):
    assert redact(text) == text


# --- 2. Runs refreshed by the previous version kept the asked text in `asked` ---------------------------------

LEGACY_ASKED = {"question": "Original wording?", "history": [{"role": "user", "content": "Original context"}]}


@pytest.fixture
def legacy(results_dir):
    """A run refreshed at 7b89e32: `question` is the current file's, the asked text and history are in `asked`."""
    rec = _rec(1, "haiku", 1, question="New wording?")
    rec["asked"] = LEGACY_ASKED
    _run("L", "haiku", 1, [rec])
    return Run.load("L")


def test_legacy_asked_text_is_restored_and_compared(legacy, results_dir):
    rec = legacy.records[record_key(1, "haiku", 1)]
    assert "asked" not in rec and rec["question"]["question"] == "Original wording?"
    assert rec["question"]["history"] == LEGACY_ASKED["history"]
    new = _run("N", "router", 1, [_rec(1, "router", 1, question="New wording?")])
    with pytest.raises(ValueError, match=r"Q1 \(question, history\)"):
        compare(legacy, new, "haiku")
    assert "⚠ changed: question, history" in to_markdown(compare(legacy, new, "haiku", allow_mismatch=True))


def test_compare_reads_legacy_asked_on_records_not_loaded_from_disk(results_dir):
    rec = _rec(1, "haiku", 1, question="New wording?")
    rec["asked"] = LEGACY_ASKED
    legacy = _run("L", "haiku", 1, [rec])  # records added after the Run was made, so `asked` is still there
    new = _run("N", "router", 1, [_rec(1, "router", 1, question="New wording?")])
    with pytest.raises(ValueError, match=r"Q1 \(question, history\)"):
        compare(legacy, new, "haiku")


def test_regrading_a_legacy_run_sends_the_asked_text_to_the_judge(legacy, monkeypatch):
    judge = FakeJudge()
    current = [
        Question.from_dict(_question(1, question="New wording?", notes="A correct answer must: say 1"))
    ]
    monkeypatch.setattr(cli_mod, "load_questions", lambda path: current)
    monkeypatch.setattr(cli_mod, "_judge", lambda settings: judge)
    result = CliRunner().invoke(cli_mod.cli, ["grade", str(legacy.dir), "--refresh-questions"])
    assert result.exit_code == 0, result.output
    assert "1 questions were reworded since this run asked them (1)" in result.output
    (seen,) = judge.seen
    assert seen.question == "Original wording?" and list(seen.history) == LEGACY_ASKED["history"]
    assert seen.notes == "A correct answer must: say 1"
    rec = Run.load("L").records[record_key(1, "haiku", 1)]
    assert "asked" not in rec
    assert rec["grade"]["graded"]["question"] == "Original wording?"
    assert rec["grade"]["graded"]["history"] == LEGACY_ASKED["history"]


def test_plain_regrade_of_a_legacy_run_also_uses_the_asked_text(legacy):
    legacy.records[record_key(1, "haiku", 1)].pop("grade")
    judge = FakeJudge()
    grade_answers(legacy, judge)
    assert judge.seen[0].question == "Original wording?"
