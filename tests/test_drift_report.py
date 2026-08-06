import json

from cbioportal_mcp_qa.drift_report import (
    build_drift_summary,
    main,
    render_markdown,
)


def _write_eval_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Average correctness_score: 2.50,,,,",
        "question,correctness_score,completeness_score",
    ]
    for question, correctness, completeness in rows:
        lines.append(f"{question},{correctness},{completeness}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_build_drift_summary_detects_per_question_regression(temp_dir):
    current_dir = temp_dir / "results" / "agent" / "20260617" / "eval"
    baseline_dir = temp_dir / "results" / "agent" / "latest" / "eval"

    _write_eval_csv(
        baseline_dir / "evaluation_20260616.csv",
        [
            ("Question A", 3, 3),
            ("Question B", 3, 3),
        ],
    )
    _write_eval_csv(
        current_dir / "evaluation_20260617.csv",
        [
            ("Question A", 1, 3),
            ("Question B", 3, 2),
        ],
    )

    summary = build_drift_summary(
        agent_type="agent",
        current_eval_dir=current_dir,
        baseline_eval_dir=baseline_dir,
        drop_threshold=1.0,
    )

    assert summary.has_regressions
    assert summary.current_averages["correctness_score"] == 2.0
    assert summary.baseline_averages["correctness_score"] == 3.0
    assert summary.average_deltas["correctness_score"] == -1.0
    assert summary.regressions == [
        {
            "question": "Question A",
            "metric": "correctness_score",
            "baseline": 3.0,
            "current": 1.0,
            "delta": -2.0,
        },
        {
            "question": "Question B",
            "metric": "completeness_score",
            "baseline": 3.0,
            "current": 2.0,
            "delta": -1.0,
        },
    ]


def test_render_markdown_includes_scores_and_regressions(temp_dir):
    current_dir = temp_dir / "current"
    baseline_dir = temp_dir / "baseline"
    _write_eval_csv(baseline_dir / "evaluation_20260616.csv", [("Question A", 3, 3)])
    _write_eval_csv(current_dir / "evaluation_20260617.csv", [("Question A", 2, 3)])

    summary = build_drift_summary(
        agent_type="agent",
        current_eval_dir=current_dir,
        baseline_eval_dir=baseline_dir,
        drop_threshold=1.0,
    )
    markdown = render_markdown(summary)

    assert "# Drift Report: `agent`" in markdown
    assert "| correctness_score | 2.00 | 3.00 | -1.00 |" in markdown
    assert "| Question A | correctness_score | 3.00 | 2.00 | -1.00 |" in markdown


def test_main_writes_markdown_and_json(temp_dir):
    current_dir = temp_dir / "current"
    baseline_dir = temp_dir / "baseline"
    output_markdown = temp_dir / "drift.md"
    output_json = temp_dir / "drift.json"
    _write_eval_csv(baseline_dir / "evaluation_20260616.csv", [("Question A", 3, 3)])
    _write_eval_csv(current_dir / "evaluation_20260617.csv", [("Question A", 3, 3)])

    exit_code = main(
        [
            "--agent-type",
            "agent",
            "--current-eval-dir",
            str(current_dir),
            "--baseline-eval-dir",
            str(baseline_dir),
            "--output-markdown",
            str(output_markdown),
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert output_markdown.exists()
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["agent_type"] == "agent"
    assert report["has_regressions"] is False


def test_build_drift_summary_ignores_blank_question_rows(temp_dir):
    current_dir = temp_dir / "current"
    baseline_dir = temp_dir / "baseline"
    _write_eval_csv(
        baseline_dir / "evaluation_20260616.csv",
        [
            ("Question A", 3, 3),
            ("", 1, 1),
        ],
    )
    _write_eval_csv(
        current_dir / "evaluation_20260617.csv",
        [
            ("Question A", 3, 3),
            ("", 1, 1),
        ],
    )

    summary = build_drift_summary(
        agent_type="agent",
        current_eval_dir=current_dir,
        baseline_eval_dir=baseline_dir,
        drop_threshold=1.0,
    )

    assert summary.regressions == []
