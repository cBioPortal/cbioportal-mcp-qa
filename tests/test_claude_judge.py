"""The claude-code judge, against a fake `claude` binary on PATH (no model calls)."""

import json
import os
import stat
import sys

import pytest
from click.testing import CliRunner
from test_review_fixes import JUDGE, _rec, _run

from cbioportal_mcp_qa import claude_code
from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa.claude_judge import ClaudeCodeJudge, claude_code_model
from cbioportal_mcp_qa.compare import compare
from cbioportal_mcp_qa.dataset import Question
from cbioportal_mcp_qa.grade import JUDGE_PROMPT, JUDGE_SCHEMA, JudgeStopped, judge_prompt
from cbioportal_mcp_qa.report import outcome_of
from cbioportal_mcp_qa.run import Run, grade_answers, record_key

CC_JUDGE = "claude-code:claude-sonnet-4-6"
VERDICT = {"rationale": "States the reference count.", "passed": True, "declined": False}
USAGE = {
    "input_tokens": 100,
    "cache_read_input_tokens": 20,
    "cache_creation_input_tokens": 5,
    "output_tokens": 30,
}

FAKE_CLAUDE = """#!{python}
import json, os, sys
log, script = os.environ["FAKE_CLAUDE_LOG"], os.environ["FAKE_CLAUDE_SCRIPT"]
prompt = sys.stdin.read()
with open(log, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "stdin": prompt, "env": dict(os.environ), "cwd": os.getcwd()}}) + "\\n")
outputs = json.load(open(script))
n = sum(1 for _ in open(log)) - 1
out = outputs[min(n, len(outputs) - 1)]
sys.stdout.write("\\n".join(out.get("lines", [])) + "\\n")
sys.stderr.write(out.get("stderr", ""))
sys.exit(out.get("exit", 0))
"""


def _init(source="none", tools=("StructuredOutput",)) -> str:
    return json.dumps({"type": "system", "subtype": "init", "tools": list(tools), "apiKeySource": source})


def _result(**fields) -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "usage": USAGE} | fields)


GOOD = {"lines": [_init(), _result(result="", structured_output=VERDICT)]}
MALFORMED = {"lines": [_init(), _result(result="I think it passes.")]}
WRONG_SCHEMA = {"lines": [_init(), _result(structured_output={"passed": "yes"})]}
LIMIT = {
    "lines": [
        _init(),
        _result(is_error=True, subtype="error", result="You've hit your session limit · resets 5pm"),
    ],
    "exit": 1,
}


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """A `claude` on PATH that logs each call and replays `set(outputs)` in order (the last one repeats)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "claude"
    exe.write_text(FAKE_CLAUDE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log, script = tmp_path / "calls.jsonl", tmp_path / "outputs.json"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-judgetestjudgetest")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")

    class Fake:
        def set(self, *outputs):
            script.write_text(json.dumps(list(outputs)))
            log.unlink(missing_ok=True)

        @property
        def calls(self) -> list[dict]:
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    fake = Fake()
    fake.set(GOOD)
    return fake


@pytest.fixture
def ungraded(results_dir):
    return _run("U", "haiku", 1, [_rec(q, "haiku", 1, graded=False) for q in (1, 2, 3)])


def test_success_records_the_bedrock_grade_fields_and_the_judge_id(fake_claude, ungraded):
    judge = ClaudeCodeJudge(JUDGE)
    grade_answers(ungraded, judge)
    judge.close()
    run = Run.load(str(ungraded.dir))
    grades = [r["grade"] for r in run.records.values()]
    assert len(grades) == 3 and {g["judge_model"] for g in grades} == {CC_JUDGE}
    assert run.data["judge_models"] == [CC_JUDGE] and run.data["judge_model"] == CC_JUDGE
    g = grades[0]
    assert (g["passed"], g["declined"], g["rationale"]) == (True, False, VERDICT["rationale"])
    assert (g["judge_input_tokens"], g["judge_output_tokens"]) == (125, 30)
    # The same fields as a Bedrock grade.
    assert set(g) == {
        "passed", "declined", "rationale", "number_match", "links", "invalid_studies",
        "judge_input_tokens", "judge_output_tokens", "judge_model", "graded",
    }  # fmt: skip
    assert all(outcome_of(r) == "pass" for r in run.records.values())


def test_the_judge_session_has_no_tools_no_mcp_and_the_same_prompt(fake_claude, ungraded):
    judge = ClaudeCodeJudge("sonnet-4.6")
    rec = ungraded.records[record_key(1, "haiku", 1)]
    q = Question.from_dict(rec["question"])
    judge.grade(q, "x", studies=None)
    call = fake_claude.calls[0]
    argv = call["argv"]
    assert argv[:1] == ["-p"] and argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    # All built-in tools off, and only the (empty) MCP config, so no MCP servers or claude.ai connectors.
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert json.loads(open(argv[argv.index("--mcp-config") + 1]).read()) == {"mcpServers": {}}
    assert call["env"]["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert "--allowedTools" not in argv
    # User settings excluded; structured output with the Bedrock judge's schema.
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert json.loads(argv[argv.index("--json-schema") + 1]) == JUDGE_SCHEMA
    assert "--no-session-persistence" in argv
    # The Bedrock judge's prompt and rubric, on stdin.
    assert call["stdin"] == judge_prompt(q, "x", [], None, "")
    assert JUDGE_PROMPT.split("\n")[0] in call["stdin"]
    # An empty working directory: no project CLAUDE.md.
    assert os.listdir(call["cwd"]) == ["no-mcp.json"]
    judge.close()


def test_billing_variables_never_reach_the_judge(fake_claude, ungraded):
    judge = ClaudeCodeJudge(JUDGE)
    grade_answers(ungraded, judge)
    for call in fake_claude.calls:
        assert "ANTHROPIC_API_KEY" not in call["env"] and "CLAUDE_CODE_USE_BEDROCK" not in call["env"]
        assert call["env"]["MAX_THINKING_TOKENS"] == "0"
    assert judge.stripped_env == ["ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK"]


def test_the_billing_guard_runs_before_any_judge_call(fake_claude, ungraded, monkeypatch):
    team = {"mode": "subscription", "auth_method": "claude.ai", "api_provider": "firstParty"}
    monkeypatch.setattr(claude_code, "auth_status", lambda env: team | {"subscription_type": "team"})
    with pytest.raises(RuntimeError, match="--claude-code-trust-org-policy"):
        ClaudeCodeJudge(JUDGE)
    result = CliRunner().invoke(cli_mod.cli, ["grade", str(ungraded.dir), "--judge-runner", "claude-code"])
    assert result.exit_code != 0 and "--claude-code-trust-org-policy" in result.output
    assert fake_claude.calls == [] and not any(
        r.get("grade") for r in Run.load(str(ungraded.dir)).records.values()
    )
    ClaudeCodeJudge(JUDGE, trust_org_policy=True).close()  # trusted: allowed

    monkeypatch.setattr(claude_code, "auth_status", lambda env: {"mode": "api-key", "auth_method": "api_key"})
    with pytest.raises(RuntimeError, match="confirmed subscription login"):
        ClaudeCodeJudge(JUDGE, trust_org_policy=True)


def test_a_session_billed_per_token_stops_grading(fake_claude, ungraded):
    fake_claude.set({"lines": [_init("ANTHROPIC_API_KEY"), GOOD["lines"][1]]})
    with pytest.raises(JudgeStopped, match="billed this session per token"):
        grade_answers(ungraded, ClaudeCodeJudge(JUDGE))
    assert len(fake_claude.calls) == 1
    assert not any(r.get("grade") for r in Run.load(str(ungraded.dir)).records.values())


def test_a_session_with_tools_stops_grading(fake_claude, ungraded):
    fake_claude.set({"lines": [_init(tools=("StructuredOutput", "mcp__navigator__x")), GOOD["lines"][1]]})
    with pytest.raises(JudgeStopped, match="must have none"):
        grade_answers(ungraded, ClaudeCodeJudge(JUDGE))


def test_malformed_output_is_retried_once(fake_claude, ungraded):
    fake_claude.set(MALFORMED, GOOD)
    run = _run("M", "haiku", 1, [_rec(1, "haiku", 1, graded=False)])
    grade_answers(run, ClaudeCodeJudge(JUDGE))
    assert len(fake_claude.calls) == 2
    assert run.records[record_key(1, "haiku", 1)]["grade"]["passed"] is True


def test_a_verdict_wrong_twice_is_left_ungraded_and_graded_next_time(fake_claude, results_dir):
    fake_claude.set(MALFORMED, WRONG_SCHEMA)
    run = _run("M", "haiku", 1, [_rec(1, "haiku", 1, graded=False)])
    grade_answers(run, ClaudeCodeJudge(JUDGE))  # doesn't raise
    assert len(fake_claude.calls) == 2
    rec = Run.load(str(run.dir)).records[record_key(1, "haiku", 1)]
    assert "grade" not in rec and outcome_of(rec) == "ungraded"
    assert (
        rec["judge_error"]["judge_model"] == CC_JUDGE
        and "not the judge schema" in rec["judge_error"]["error"]
    )

    fake_claude.set(GOOD)
    run = Run.load(str(run.dir))
    grade_answers(run, ClaudeCodeJudge(JUDGE))
    rec = run.records[record_key(1, "haiku", 1)]
    assert rec["grade"]["passed"] is True and "judge_error" not in rec


def test_usage_limit_stops_cleanly_and_grade_resumes(fake_claude, ungraded):
    fake_claude.set(GOOD, LIMIT)
    result = CliRunner().invoke(
        cli_mod.cli,
        ["grade", str(ungraded.dir), "--judge-runner", "claude-code", "--claude-code-trust-org-policy"],
    )
    assert result.exit_code == 1
    assert "hit your session limit" in result.output
    assert (
        f"grade {ungraded.data['run_id']} --judge-runner claude-code --claude-code-trust-org-policy"
        in result.output
    )
    # One graded; the limit stopped the rest without marking them, and no call was made after it.
    assert len(fake_claude.calls) == 2
    run = Run.load(str(ungraded.dir))
    assert sum("grade" in r for r in run.records.values()) == 1
    assert not any("judge_error" in r for r in run.records.values())
    assert (run.dir / "report.html").exists()

    fake_claude.set(GOOD)
    result = CliRunner().invoke(cli_mod.cli, ["grade", str(ungraded.dir), "--judge-runner", "claude-code"])
    assert result.exit_code == 0, result.output
    assert len(fake_claude.calls) == 2  # only the two left
    assert all(r["grade"]["judge_model"] == CC_JUDGE for r in Run.load(str(ungraded.dir)).records.values())


def test_concurrency_grades_everything(fake_claude, results_dir):
    run = _run("C", "haiku", 1, [_rec(q, "haiku", 1, graded=False) for q in range(1, 9)])
    grade_answers(run, ClaudeCodeJudge(JUDGE), concurrency=4)
    assert len(fake_claude.calls) == 8
    assert all(r["grade"]["passed"] for r in Run.load(str(run.dir)).records.values())


def test_compare_keeps_claude_code_and_bedrock_grades_apart(fake_claude, results_dir):
    bedrock = _run("A", "haiku", 1, [_rec(q, "haiku", 1) for q in (1, 2)])
    local = _run("B", "haiku", 1, [_rec(q, "haiku", 1, graded=False) for q in (1, 2)])
    grade_answers(local, ClaudeCodeJudge(JUDGE))
    with pytest.raises(ValueError, match=f"judge model differs: A {JUDGE}, B {CC_JUDGE}"):
        compare(bedrock, local, "haiku", "haiku")


def test_secrets_in_the_rationale_are_scrubbed(fake_claude, ungraded):
    leaky = VERDICT | {"rationale": "Leaked sk-ant-api03-judgetestjudgetest in the answer."}
    fake_claude.set({"lines": [_init(), _result(structured_output=leaky)]})
    grade_answers(ungraded, ClaudeCodeJudge(JUDGE))
    assert "sk-ant-api03-judgetestjudgetest" not in (ungraded.dir / "run.json").read_text()


def test_run_records_the_claude_code_judge(fake_claude, results_dir, monkeypatch):
    fake_client = type("C", (), {"aclose": lambda self: _noop(), "transcript_dir": None})()
    monkeypatch.setattr(cli_mod, "_client", lambda *a, **k: fake_client)
    monkeypatch.setattr(cli_mod, "fetch_agent_prompt", lambda *a: {"instructions": "p"})
    monkeypatch.setattr(cli_mod, "describe_agents", lambda *a: {})
    monkeypatch.setattr(cli_mod, "collect_versions", lambda *a: {})
    monkeypatch.setattr(cli_mod, "_langfuse", lambda s: None)
    monkeypatch.setattr(cli_mod, "wait_for_ingestion", lambda: None)
    monkeypatch.setattr(cli_mod, "attach_traces", lambda *a: 0)

    async def collect(bench, questions, client, concurrency):
        for q in questions:
            rec = _rec(q.id, "haiku", 1, graded=False)
            bench.records[record_key(q.id, "haiku", 1)] = rec | {"question": rec["question"] | {"id": q.id}}
        bench.save()

    monkeypatch.setattr(cli_mod, "collect_answers", collect)
    result = CliRunner().invoke(
        cli_mod.cli,
        ["run", "--models", "haiku", "--questions", "1-2", "--no-render", "--judge-runner", "claude-code"],
    )
    assert result.exit_code == 0, result.output
    run = Run.load(next(p for p in results_dir.iterdir() if (p / "run.json").exists()).name)
    assert run.data["judge_model"] == CC_JUDGE
    assert {r["grade"]["judge_model"] for r in run.records.values()} == {CC_JUDGE}


async def _noop():
    return None


def test_claude_code_model_resolution():
    assert claude_code_model("us.anthropic.claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert claude_code_model("sonnet-4.6") == "claude-sonnet-4-6"
    assert claude_code_model("haiku") == "claude-haiku-4-5-20251001"
    assert claude_code_model("claude-opus-5-5") == "claude-opus-5-5"
    with pytest.raises(ValueError):
        claude_code_model("router")
