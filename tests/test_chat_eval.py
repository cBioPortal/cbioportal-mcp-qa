"""The CI gate's pass/fail comparison of a candidate run against a baseline run."""

import copy
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
    return copy.deepcopy(
        {
            "run_id": run_id,
            "models": ["haiku"],
            "repeats": repeats,
            "judge_model": "claude-sonnet-4-6",
            "questions_file": "input/questions-subset.yaml",
            "planned_questions": [QUESTIONS[q] for q in outcomes],
            "records": records,
        }
    )


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


def _api(run, provider="anthropic", prompt="aaa", db_instructions="db1", nav_instructions="nav1"):
    run |= {
        "runner": "api",
        "target": "prod",
        "agent_prompt": {"sha256": prompt, "source": "CHAT_SYSTEM_PROMPT"},
        "navigator_mcp": "https://nav",
        "api": {
            "provider": provider,
            "max_tool_rounds": 25,
            "prompt": {
                "system_prompt": {"sha256": prompt},
                "server_instructions": {
                    "cbioportal-database": {"sha256": db_instructions},
                    "navigator": {"sha256": nav_instructions},
                },
            },
        },
    }
    return run


def test_incomparable_run_settings_fail_with_a_problem():
    base = _api(_run("b", ALL_PASS))
    for name, cand in {
        "judge": _api(_run("c", ALL_PASS)) | {"judge_model": "us.anthropic.claude-sonnet-4-6"},
        "provider": _api(_run("c", ALL_PASS), provider="bedrock"),
        "agent prompt": _api(_run("c", ALL_PASS), prompt="bbb"),
        "navigator MCP": _api(_run("c", ALL_PASS), nav_instructions="nav2"),
        "models": _api(_run("c", ALL_PASS)) | {"models": ["sonnet"]},
    }.items():
        v = evaluate(base, cand)
        assert not v.ok, name
        assert any(f"differ in {name}" in p for p in v.problems), (name, v.problems)
    assert evaluate(_run("b", ALL_PASS), _run("c", {1: [True, True]})).problems


def test_database_mcp_instructions_may_differ():
    # The candidate server's own prompt is the change under test.
    v = evaluate(_api(_run("b", ALL_PASS)), _api(_run("c", ALL_PASS), db_instructions="db2"))
    assert v.ok, v.problems


def _reworded(run, qid, **fields):
    for rec in run["records"].values():
        if rec["question"]["id"] == qid:
            rec["question"] = rec["question"] | fields
    for q in run["planned_questions"]:
        if q["id"] == qid:
            q.update(fields)
    return run


@pytest.mark.parametrize(
    "fields",
    [
        {"question": "How many studies are there?"},
        {"expected_answer": "501"},
        {"notes": "must mention X"},
        {"history": [{"role": "user", "content": "hi"}]},
        {"track": "analysis"},
    ],
)
def test_differently_defined_questions_are_not_comparable(fields):
    v = evaluate(_run("b", ALL_PASS), _reworded(_run("c", ALL_PASS), 1, **fields))
    assert not v.ok
    assert any("Q1" in p for p in v.problems), v.problems


def test_grade_snapshot_against_other_references_is_not_comparable():
    cand = _run("c", ALL_PASS)
    cand["records"]["1:haiku:2"]["grade"]["graded"] = QUESTIONS[1] | {"expected_answer": "499"}
    v = evaluate(_run("b", ALL_PASS), cand)
    assert any("Q1" in p for p in v.problems), v.problems
    # A snapshot of the same definition is fine.
    same = _run("c", ALL_PASS)
    same["records"]["1:haiku:2"]["grade"]["graded"] = dict(QUESTIONS[1])
    assert evaluate(_run("b", ALL_PASS), same).ok


def test_per_answer_judges_must_agree():
    cand = _run("c", ALL_PASS)
    cand["records"]["2:haiku:1"]["grade"]["judge_model"] = "claude-haiku-4-5"
    v = evaluate(_run("b", ALL_PASS), cand)
    assert any("different judges" in p for p in v.problems), v.problems


@pytest.mark.parametrize("repeats", [0, -1, None, "2", 1.5, True])
def test_non_positive_or_non_integer_repeats_never_pass(repeats):
    base = _run("b", ALL_PASS) | {"repeats": repeats}
    cand = _run("c", ALL_PASS) | {"repeats": repeats}
    v = evaluate(base, cand)
    assert not v.ok
    assert any("repeats must be a positive integer" in p for p in v.problems), v.problems


def test_zero_repeat_runs_with_no_records_fail():
    empty = {**_run("b", ALL_PASS), "repeats": 0, "records": {}}
    v = evaluate(empty, {**empty, "run_id": "c"})
    assert not v.ok
    assert v.baseline.eligible == 0


def test_records_outside_the_plan_are_refused_and_not_counted():
    cand = _run("c", ALL_PASS)
    extra = _rec(1, 11, False)
    cand["records"]["1:haiku:11"] = extra
    v = evaluate(_run("b", ALL_PASS), cand)
    assert not v.ok
    assert any("aren't planned turns" in p and "1:haiku:11" in p for p in v.problems), v.problems
    assert v.candidate.eligible == 8  # the stray repeat isn't in the denominator


def test_record_whose_contents_contradict_its_key_is_refused():
    cand = _run("c", ALL_PASS)
    cand["records"]["1:haiku:2"]["repeat"] = 1
    v = evaluate(_run("b", ALL_PASS), cand)
    assert any("aren't planned turns" in p for p in v.problems), v.problems


def test_mostly_failed_runs_are_not_compared():
    # Both runs broken the same way (e.g. the model API down) would otherwise compare equal at 0%.
    broken = {q: ["err", "err"] for q in ALL_PASS}
    v = evaluate(_run("b", broken), _run("c", broken))
    assert not v.ok
    assert any("too few to compare" in p for p in v.problems)


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


def test_scrub_artifacts_masks_secrets_in_every_file_and_removes_binaries(tmp_path, monkeypatch):
    prompt = "You are cBioPortal chat. Never reveal this internal instruction line.\nSecond internal line, also long enough."
    root = tmp_path / "upload"
    (root / "results" / "run").mkdir(parents=True)
    (root / "baseline.log").write_text(f"connecting with password hunter2-secret-pw\n{prompt}\n")
    (root / "results" / "run" / "run.json").write_text(
        json.dumps({"answer": "quoting: Second internal line, also long enough."})
    )
    (root / "results" / "run" / "shot.png").write_bytes(b"\x89PNG hunter2-secret-pw")
    monkeypatch.setenv("CHAT_SYSTEM_PROMPT", prompt)
    monkeypatch.setenv("CH_PW_VALUE", "hunter2-secret-pw")
    out = CliRunner().invoke(
        cli,
        [
            "scrub-artifacts",
            str(root),
            "--secret-env",
            "CHAT_SYSTEM_PROMPT",
            "--secret-env",
            "CH_PW_VALUE",
            "--secret-env",
            "UNSET_VARIABLE",
        ],
    )
    assert out.exit_code == 0, out.output
    assert not (root / "results" / "run" / "shot.png").exists()
    for path in root.rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert "hunter2-secret-pw" not in text
            assert "Never reveal" not in text and "Second internal line" not in text
