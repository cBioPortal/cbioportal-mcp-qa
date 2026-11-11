"""The CI gate's pass/fail comparison of a candidate run against a baseline run."""

import json

import pytest
from click.testing import CliRunner

from cbioportal_mcp_qa.chat_eval import evaluate, render_markdown, run_metrics, verdict_json
from cbioportal_mcp_qa.cli import cli

QUESTIONS = {
    1: {"id": 1, "question": "How many studies?", "track": "data", "expected_answer": "500"},
    2: {"id": 2, "question": "Link to TCGA BRCA", "track": "navigation", "expected_links": ["https://x"]},
    3: {"id": 3, "question": "Is KRAS prognostic?", "track": "analysis", "notes": "must not invent p"},
    4: {"id": 4, "question": "What's the weather?", "track": "out_of_scope", "notes": "must decline"},
    # No reference: asked, never counted.
    5: {"id": 5, "question": "Unreferenced", "track": "data"},
}


def _rec(qid, repeat, passed, status=200, tool_errors=0, invalid=(), rationale="", model="haiku"):
    rec = {
        "question": QUESTIONS[qid],
        "model": model,
        "repeat": repeat,
        "reply": {
            "answer": "x" if status == 200 else "",
            "status": status,
            "error": None if status == 200 else "boom",
        },
        "trace": {
            "llm_calls": 2,
            "tool_calls": [{"name": "clickhouse_run_select_query", "ok": True}]
            + [{"name": "clickhouse_run_select_query", "ok": False, "error": "bad SQL"}] * tool_errors,
        },
    }
    if status == 200:
        rec["grade"] = {
            "passed": passed,
            "declined": False,
            "rationale": rationale,
            "invalid_studies": list(invalid),
        }
    return rec


def _run(run_id, outcomes, repeats=2, per_turn=None):
    """A run.json dict: `outcomes[qid]` is a list with each repeat's pass (True/False/None=ungraded/'err')."""
    records = {}
    for qid, results in outcomes.items():
        for r, passed in enumerate(results, 1):
            kw = dict((per_turn or {}).get((qid, r), {}))
            if passed == "err":
                kw["status"] = 500
            records[f"{qid}:haiku:{r}"] = _rec(qid, r, passed if passed != "err" else None, **kw)
    return {
        "run_id": run_id,
        "models": ["haiku"],
        "repeats": repeats,
        "judge_model": "claude-sonnet-4-6",
        "questions_file": "input/questions-subset.yaml",
        "planned_questions": [QUESTIONS[q] for q in outcomes],
        "records": records,
    }


ALL_PASS = {1: [True, True], 2: [True, True], 3: [True, True], 4: [True, True], 5: [None, None]}


def test_metrics_count_only_referenced_questions_and_fail_closed():
    data = _run("b", {1: [True, "err"], 2: [True, None], 3: [False, True], 4: [True, True], 5: [None, None]})
    m = run_metrics(data)
    assert m.eligible == 8  # Q5 has no reference
    assert m.passes == 5
    assert m.failed_requests == 1
    assert m.ungraded == 1
    assert m.pass_rate == pytest.approx(62.5)
    assert m.by_track["data"] == [1, 2]
    assert m.by_repeat[1] == [3, 4] and m.by_repeat[2] == [2, 4]


def test_missing_planned_turn_counts_as_not_passed():
    data = _run("b", {1: [True, True], 2: [True, True]})
    del data["records"]["2:haiku:2"]
    m = run_metrics(data)
    assert (m.passes, m.eligible) == (3, 4)
    assert "not asked" in m.rationales[2][0]


def test_identical_runs_pass():
    v = evaluate(_run("b", ALL_PASS), _run("c", ALL_PASS))
    assert v.ok
    assert v.regressions == [] and v.improvements == []


def test_pass_rate_drop_within_threshold_passes_and_beyond_fails():
    base = _run("b", ALL_PASS)
    # 1 of 8 turns lost: 12.5 points.
    one_lost = _run("c", ALL_PASS | {3: [True, False]})
    assert not evaluate(base, one_lost, max_pass_drop=10).ok
    assert evaluate(base, one_lost, max_pass_drop=12.5).ok
    v = evaluate(base, one_lost, max_pass_drop=10)
    (check,) = [c for c in v.checks if c.name.startswith("Pass rate")]
    assert (check.baseline, check.candidate, check.ok) == (100.0, 87.5, False)


def test_candidate_improvement_never_fails():
    base = _run("b", ALL_PASS | {1: [False, False], 2: [False, False]})
    v = evaluate(base, _run("c", ALL_PASS))
    assert v.ok
    assert [r["id"] for r in v.improvements] == [1, 2]


def test_failed_requests_count_against_the_candidate():
    v = evaluate(
        _run("b", ALL_PASS), _run("c", ALL_PASS | {1: ["err", "err"], 2: ["err", True]}), max_pass_drop=10
    )
    assert not v.ok
    assert v.candidate.failed_requests == 3


def test_tool_error_increase_gate():
    base = _run("b", ALL_PASS, per_turn={(1, 1): {"tool_errors": 2}})
    cand_ok = _run("c", ALL_PASS, per_turn={(1, 1): {"tool_errors": 5}})
    cand_bad = _run("c", ALL_PASS, per_turn={(1, 1): {"tool_errors": 6}})
    assert evaluate(base, cand_ok, max_tool_error_increase=3).ok
    v = evaluate(base, cand_bad, max_tool_error_increase=3)
    assert not v.ok
    assert [c.name for c in v.checks if not c.ok] == ["Tool errors"]
    assert v.candidate.tool_errors_by_tool["clickhouse_run_select_query"] == 6


def test_invalid_study_ids_counted_distinct_and_gated():
    base = _run("b", ALL_PASS, per_turn={(2, 1): {"invalid": ["fake_a"]}})
    # The same hallucinated id twice is one id; a second distinct one is an increase of 1.
    cand = _run(
        "c",
        ALL_PASS,
        per_turn={(2, 1): {"invalid": ["fake_a", "fake_b"]}, (2, 2): {"invalid": ["fake_b"]}},
    )
    assert evaluate(base, cand, max_invalid_study_increase=1).ok
    v = evaluate(base, cand, max_invalid_study_increase=0)
    assert not v.ok
    assert "fake_b" in render_markdown(v)


def test_per_question_regressions_listed_worst_first_with_rationale():
    base = _run("b", ALL_PASS)
    cand = _run(
        "c",
        ALL_PASS | {1: [False, False], 3: [True, False]},
        per_turn={
            (1, 1): {"rationale": "States 499, not 500."},
            (3, 2): {"rationale": "Invented a p-value."},
        },
    )
    v = evaluate(base, cand, max_pass_drop=100)
    assert [(r["id"], r["baseline"], r["candidate"]) for r in v.regressions] == [
        (1, "2/2", "0/2"),
        (3, "2/2", "1/2"),
    ]
    assert v.regressions[0]["why"] == "States 499, not 500."
    md = render_markdown(v)
    assert "Per-question regressions (2)" in md
    assert "States 499, not 500." in md
    assert "| navigation |" in md  # per-track table


def test_incomparable_runs_fail_with_a_problem():
    cand = _run("c", ALL_PASS)
    cand["judge_model"] = "us.anthropic.claude-sonnet-4-6"
    v = evaluate(_run("b", ALL_PASS), cand)
    assert not v.ok
    assert any("judge_model" in p for p in v.problems)
    assert evaluate(_run("b", ALL_PASS), _run("c", {1: [True, True]})).problems


def test_run_with_nothing_graded_fails():
    v = evaluate(_run("b", ALL_PASS), _run("c", {q: ["err", "err"] for q in ALL_PASS}))
    assert not v.ok


def test_markdown_escapes_pipes_and_newlines():
    cand = _run("c", ALL_PASS | {1: [False, True]}, per_turn={(1, 1): {"rationale": "a | b\nc"}})
    md = render_markdown(evaluate(_run("b", ALL_PASS), cand, max_pass_drop=100))
    assert "a \\| b c" in md


def test_verdict_json_round_trips():
    out = verdict_json(evaluate(_run("b", ALL_PASS), _run("c", ALL_PASS)))
    json.dumps(out)
    assert out["ok"] and out["candidate"]["by_track"]["data"]["rate"] == 100.0


def _write(tmp_path, name, data):
    d = tmp_path / name
    d.mkdir()
    (d / "run.json").write_text(json.dumps(data))
    return str(d)


def test_cli_gate_exit_codes_and_outputs(tmp_path):
    base = _write(tmp_path, "base", _run("base", ALL_PASS))
    good = _write(tmp_path, "good", _run("good", ALL_PASS))
    bad = _write(tmp_path, "bad", _run("bad", ALL_PASS | {1: [False, False]}))
    summary, verdict = tmp_path / "summary.md", tmp_path / "verdict.json"
    runner = CliRunner()

    ok = runner.invoke(cli, ["chat-eval-gate", base, good, "--summary", str(summary), "--json", str(verdict)])
    assert ok.exit_code == 0, ok.output
    assert "✅ pass" in summary.read_text()
    assert json.loads(verdict.read_text())["ok"] is True

    fail = runner.invoke(
        cli, ["chat-eval-gate", base, bad, "--max-pass-drop", "10", "--summary", str(summary)]
    )
    assert fail.exit_code == 1
    assert "chat eval regression: Pass rate" in fail.output
    # Appended, not overwritten: GITHUB_STEP_SUMMARY collects every step's output.
    text = summary.read_text()
    assert "✅ pass" in text and "❌ regression" in text
