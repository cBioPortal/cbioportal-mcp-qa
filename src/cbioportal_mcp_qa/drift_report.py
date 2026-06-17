"""Generate drift reports by comparing benchmark runs to a baseline."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DriftSummary:
    agent_type: str
    current_eval: Path
    baseline_eval: Path | None
    current_averages: dict[str, float]
    baseline_averages: dict[str, float]
    average_deltas: dict[str, float]
    regressions: list[dict[str, Any]]

    @property
    def has_regressions(self) -> bool:
        return bool(self.regressions)


def _latest_csv(eval_dir: Path, pattern: str = "evaluation_*.csv") -> Path | None:
    candidates = sorted(eval_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _read_eval_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, comment="#")


def _score_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if col.endswith("_score")]


def _score_averages(df: pd.DataFrame) -> dict[str, float]:
    return {
        col: float(value)
        for col, value in df[_score_columns(df)].astype(float).mean().to_dict().items()
    }


def _row_regressions(
    current_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    drop_threshold: float,
) -> list[dict[str, Any]]:
    if "question" not in current_df.columns or "question" not in baseline_df.columns:
        return []

    shared_score_cols = sorted(set(_score_columns(current_df)) & set(_score_columns(baseline_df)))
    if not shared_score_cols:
        return []

    current_clean = current_df.dropna(subset=["question"]).copy()
    baseline_clean = baseline_df.dropna(subset=["question"]).copy()
    current_clean["question"] = current_clean["question"].astype(str)
    baseline_clean["question"] = baseline_clean["question"].astype(str)

    current_by_question = current_clean.set_index("question")
    baseline_by_question = baseline_clean.set_index("question")
    shared_questions = sorted(set(current_by_question.index) & set(baseline_by_question.index))

    regressions: list[dict[str, Any]] = []
    for question in shared_questions:
        for score_col in shared_score_cols:
            current_value = float(current_by_question.loc[question, score_col])
            baseline_value = float(baseline_by_question.loc[question, score_col])
            delta = current_value - baseline_value
            if delta <= -drop_threshold:
                regressions.append(
                    {
                        "question": question,
                        "metric": score_col,
                        "baseline": baseline_value,
                        "current": current_value,
                        "delta": delta,
                    }
                )

    regressions.sort(key=lambda row: (row["delta"], row["question"], row["metric"]))
    return regressions


def build_drift_summary(
    agent_type: str,
    current_eval_dir: Path,
    baseline_eval_dir: Path,
    drop_threshold: float,
) -> DriftSummary:
    current_eval = _latest_csv(current_eval_dir)
    if current_eval is None:
        raise FileNotFoundError(f"No evaluation CSV found in {current_eval_dir}")

    current_df = _read_eval_csv(current_eval)
    current_averages = _score_averages(current_df)

    baseline_eval = _latest_csv(baseline_eval_dir)
    if baseline_eval is None:
        return DriftSummary(
            agent_type=agent_type,
            current_eval=current_eval,
            baseline_eval=None,
            current_averages=current_averages,
            baseline_averages={},
            average_deltas={},
            regressions=[],
        )

    baseline_df = _read_eval_csv(baseline_eval)
    baseline_averages = _score_averages(baseline_df)
    average_deltas = {
        metric: current_averages[metric] - baseline_averages[metric]
        for metric in sorted(set(current_averages) & set(baseline_averages))
    }
    regressions = _row_regressions(current_df, baseline_df, drop_threshold)

    return DriftSummary(
        agent_type=agent_type,
        current_eval=current_eval,
        baseline_eval=baseline_eval,
        current_averages=current_averages,
        baseline_averages=baseline_averages,
        average_deltas=average_deltas,
        regressions=regressions,
    )


def summary_to_dict(summary: DriftSummary) -> dict[str, Any]:
    return {
        "agent_type": summary.agent_type,
        "current_eval": str(summary.current_eval),
        "baseline_eval": str(summary.baseline_eval) if summary.baseline_eval else None,
        "current_averages": summary.current_averages,
        "baseline_averages": summary.baseline_averages,
        "average_deltas": summary.average_deltas,
        "regressions": summary.regressions,
        "has_regressions": summary.has_regressions,
    }


def render_markdown(summary: DriftSummary) -> str:
    lines = [
        f"# Drift Report: `{summary.agent_type}`",
        "",
        f"- Current evaluation: `{summary.current_eval}`",
        f"- Baseline evaluation: `{summary.baseline_eval or 'not found'}`",
        "",
        "## Average Scores",
        "",
        "| Metric | Current | Baseline | Delta |",
        "|---|---:|---:|---:|",
    ]

    metrics = sorted(set(summary.current_averages) | set(summary.baseline_averages))
    for metric in metrics:
        current = summary.current_averages.get(metric)
        baseline = summary.baseline_averages.get(metric)
        delta = summary.average_deltas.get(metric)
        lines.append(
            "| {metric} | {current} | {baseline} | {delta} |".format(
                metric=metric,
                current=f"{current:.2f}" if current is not None else "n/a",
                baseline=f"{baseline:.2f}" if baseline is not None else "n/a",
                delta=f"{delta:+.2f}" if delta is not None else "n/a",
            )
        )

    lines.extend(["", "## Regressions", ""])
    if not summary.regressions:
        lines.append("No per-question regressions exceeded the configured threshold.")
    else:
        lines.extend(
            [
                "| Question | Metric | Baseline | Current | Delta |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for regression in summary.regressions:
            question = str(regression["question"]).replace("|", "\\|")
            lines.append(
                "| {question} | {metric} | {baseline:.2f} | {current:.2f} | {delta:+.2f} |".format(
                    question=question,
                    metric=regression["metric"],
                    baseline=regression["baseline"],
                    current=regression["current"],
                    delta=regression["delta"],
                )
            )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-type", required=True)
    parser.add_argument("--current-eval-dir", type=Path, required=True)
    parser.add_argument("--baseline-eval-dir", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--drop-threshold", type=float, default=1.0)
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args(argv)

    summary = build_drift_summary(
        agent_type=args.agent_type,
        current_eval_dir=args.current_eval_dir,
        baseline_eval_dir=args.baseline_eval_dir,
        drop_threshold=args.drop_threshold,
    )

    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.write_text(render_markdown(summary), encoding="utf-8")
    args.output_json.write_text(json.dumps(summary_to_dict(summary), indent=2), encoding="utf-8")

    print(render_markdown(summary))
    if args.fail_on_regression and summary.has_regressions:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
