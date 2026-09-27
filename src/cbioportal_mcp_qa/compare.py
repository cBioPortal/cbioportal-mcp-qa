"""Compare two runs (A = baseline, B = candidate), per question and in aggregate, pooling repeats.

Only questions both runs asked are compared. Works with any run.json, including runs recorded before per-call
traces (their tool rounds and routing show as "–").
"""

import json
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .config import MODELS
from .dataset import CATEGORIES, TRACKS
from .report import (
    FAST_S,
    OUTCOME_ICONS,
    TRACK_LABELS,
    ModelStats,
    _env,
    _graded,
    category_of,
    mean,
    median,
    outcome_of,
    pct,
)
from .run import RESULTS_DIR, Run


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    fmt: str  # pct | secs | num | usd
    better: str  # higher | lower


METRICS = [
    Metric("pass_rate", "Pass rate", "pct", "higher"),
    Metric("precision", "Precision (pass when it answers)", "pct", "higher"),
    Metric("coverage", "Coverage (answers, not declines)", "pct", "higher"),
    Metric("median_latency", "Median latency", "secs", "lower"),
    Metric("p90_latency", "p90 latency", "secs", "lower"),
    Metric("fast_share", f"Answers under {FAST_S}s", "pct", "higher"),
    Metric("mean_llm_calls", "LLM calls / answer (mean)", "num", "lower"),
    Metric("median_llm_calls", "LLM calls / answer (median)", "num", "lower"),
    Metric("mean_tool_rounds", "Tool rounds / answer (mean)", "num", "lower"),
    Metric("mean_handoffs", "Handoffs / answer", "num", "lower"),
    Metric("tool_error_rate", "Tool error rate", "pct", "lower"),
    Metric("cost_per_answer", "Cost / answer", "usd", "lower"),
]


def pick_model(run: Run, model: str | None) -> str:
    models = run.data["models"]
    if model is None:
        if len(models) != 1:
            raise ValueError(f"run {run.data['run_id']} has models {models}; choose one")
        return models[0]
    if model not in models:
        raise ValueError(f"run {run.data['run_id']} has no model {model!r}; it has {models}")
    return model


def _by_question(run: Run, model: str) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for rec in run.records.values():
        if rec["model"] == model:
            out.setdefault(rec["question"]["id"], []).append(rec)
    for recs in out.values():
        recs.sort(key=lambda r: r["repeat"])
    return out


def _stats(records: list[dict], key: str, label: str) -> ModelStats:
    stats = ModelStats(key, label)
    for rec in records:
        stats.add(rec)
    return stats


def _cell(recs: list[dict]) -> dict:
    """One side of a question: its repeats pooled."""
    outcomes = [outcome_of(r) for r in recs]
    passes, graded = outcomes.count("pass"), _graded(Counter(outcomes))
    latencies = [r["reply"]["latency_s"] for r in recs if r["reply"].get("status") == 200]
    llm_calls = [r["trace"]["llm_calls"] for r in recs if r.get("trace")]
    rate = pct(passes, graded)
    return {
        "n": len(recs),
        "passes": passes,
        "graded": graded,
        "pass_rate": rate,
        # Bernoulli variance of pass/fail across repeats: 0 when every repeat agrees, 0.25 at 50/50.
        "pass_variance": (rate / 100) * (1 - rate / 100) if rate is not None and graded > 1 else None,
        "flaky": 0 < passes < graded,
        "icons": "".join(OUTCOME_ICONS[o] for o in outcomes),
        "median_latency": median(latencies),
        "latency_stdev": statistics.stdev(latencies) if len(latencies) > 1 else None,
        "mean_llm_calls": mean(llm_calls),
        "routed_to": sorted(
            {r["trace"]["routed_to"] for r in recs if (r.get("trace") or {}).get("routed_to")}
        ),
    }


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def _verdict(delta: float | None, better: str, tolerance: float = 0.0) -> str:
    """better | worse | same, from B's point of view."""
    if delta is None or abs(delta) <= tolerance:
        return "same"
    return "better" if (delta > 0) == (better == "higher") else "worse"


def _breakdown(sides: dict[str, ModelStats], keys: list[str], attr: str, labels: dict) -> list[dict]:
    rows = []
    for key in keys:
        counters = {s: getattr(stats, attr)[key] for s, stats in sides.items()}
        if not any(sum(c.values()) for c in counters.values()):
            continue
        rates = {s: pct(c["pass"], _graded(c)) for s, c in counters.items()}
        rows.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "n": {s: _graded(c) for s, c in counters.items()},
                "a": rates["a"],
                "b": rates["b"],
                "delta": _delta(rates["a"], rates["b"]),
            }
        )
    return rows


def compare(run_a: Run, run_b: Run, model_a: str | None = None, model_b: str | None = None) -> dict:
    model_a, model_b = pick_model(run_a, model_a), pick_model(run_b, model_b)
    qa, qb = _by_question(run_a, model_a), _by_question(run_b, model_b)
    common = sorted(qa.keys() & qb.keys())
    sides = {
        "a": _stats([r for q in common for r in qa[q]], model_a, MODELS[model_a].label),
        "b": _stats([r for q in common for r in qb[q]], model_b, MODELS[model_b].label),
    }
    metrics = []
    for m in METRICS:
        a, b = getattr(sides["a"], m.key), getattr(sides["b"], m.key)
        d = _delta(a, b)
        metrics.append(m.__dict__ | {"a": a, "b": b, "delta": d, "verdict": _verdict(d, m.better)})

    seen_categories = {c for s in sides.values() for c in s.by_category}
    categories = [c for c in CATEGORIES if c in seen_categories] + sorted(seen_categories - set(CATEGORIES))
    by_category = _breakdown(sides, categories, "by_category", {})
    for row in by_category:
        for s, recs in (("a", qa), ("b", qb)):
            lat = [
                r["reply"]["latency_s"]
                for q in common
                for r in recs[q]
                if category_of(r["question"]) == row["key"] and r["reply"].get("status") == 200
            ]
            row[f"median_latency_{s}"] = median(lat)
            row[f"fast_share_{s}"] = pct(sum(t < FAST_S for t in lat), len(lat))
    by_track = _breakdown(sides, list(TRACKS), "by_track", TRACK_LABELS)

    questions = []
    for qid in common:
        question = qb[qid][0]["question"]
        a, b = _cell(qa[qid]), _cell(qb[qid])
        delta = _delta(a["pass_rate"], b["pass_rate"])
        questions.append(
            {
                "id": qid,
                "question": question["question"],
                "category": category_of(question),
                "track": question.get("track") or "data",
                "a": a,
                "b": b,
                "delta": delta,
                "latency_delta": _delta(a["median_latency"], b["median_latency"]),
                "verdict": _verdict(delta, "higher"),
            }
        )
    # Regressions first, then improvements, each by size; unchanged last, in question order.
    questions.sort(key=lambda q: ({"worse": 0, "better": 1, "same": 2}[q["verdict"]], -abs(q["delta"] or 0)))
    verdicts = Counter(q["verdict"] for q in questions)

    def consistency(side: str) -> dict:
        cells = [q[side] for q in questions if q[side]["graded"]]
        variances = [c["pass_variance"] for c in cells if c["pass_variance"] is not None]
        stdevs = [c["latency_stdev"] for c in cells if c["latency_stdev"] is not None]
        return {
            "flaky": sum(c["flaky"] for c in cells),
            "with_repeats": len(variances),
            "mean_pass_variance": mean(variances),
            "median_latency_stdev": median(stdevs),
        }

    def describe(side: str, run: Run, model: str) -> dict:
        stats = sides[side]
        return {
            "run_id": run.data["run_id"],
            "target": run.data["target"],
            "runner": run.data.get("runner", "agents-api"),
            "model": model,
            "label": stats.label,
            "repeats": run.data.get("repeats", 1),
            "created_at": run.data.get("created_at"),
            "agent_id": (run.data.get("agent_prompt") or {}).get("agent_id"),
            "librechat": (run.data.get("versions") or {}).get("librechat"),
            "answers": stats.answers,
            "records": sum(stats.outcomes.values()),
            "routed_to": dict(stats.routed_to.most_common()),
            "consistency": consistency(side),
        }

    return {
        "a": describe("a", run_a, model_a),
        "b": describe("b", run_b, model_b),
        "n_questions": len(common),
        "only_a": sorted(qa.keys() - qb.keys()),
        "only_b": sorted(qb.keys() - qa.keys()),
        "metrics": metrics,
        "by_category": by_category,
        "by_track": by_track,
        "questions": questions,
        "question_verdicts": {k: verdicts[k] for k in ("better", "worse", "same")},
    }


def _fmt(value, fmt: str, signed: bool = False) -> str:
    if value is None:
        return "–"
    sign = "+" if signed and value > 0 else ""
    if fmt == "pct":
        return f"{sign}{value:.1f}{' pp' if signed else '%'}"
    if fmt == "secs":
        return f"{sign}{value:.1f}s"
    if fmt == "usd":
        return f"{sign}${value:.3f}"
    return f"{sign}{value:.2f}"


def _side_name(side: dict) -> str:
    return f"{side['run_id']} {side['label']} ({side['target']}, ×{side['repeats']})"


def to_markdown(result: dict, per_question_limit: int = 40) -> str:
    a, b = result["a"], result["b"]
    lines = [
        f"# Benchmark comparison: {a['run_id']} vs {b['run_id']}",
        "",
        f"- **A (baseline):** {_side_name(a)}, {a['records']} answers",
        f"- **B:** {_side_name(b)}, {b['records']} answers",
        f"- {result['n_questions']} questions in both runs; repeats pooled."
        + (f" Only in A: {len(result['only_a'])}." if result["only_a"] else "")
        + (f" Only in B: {len(result['only_b'])}." if result["only_b"] else ""),
        "",
        "## Headline",
        "",
        "| Metric | A | B | Δ (B − A) |",
        "|---|---:|---:|---:|",
    ]
    marks = {"better": " ▲", "worse": " ▼", "same": ""}
    for m in result["metrics"]:
        lines.append(
            f"| {m['label']} | {_fmt(m['a'], m['fmt'])} | {_fmt(m['b'], m['fmt'])} | "
            f"{_fmt(m['delta'], m['fmt'], signed=True)}{marks[m['verdict']]} |"
        )
    v = result["question_verdicts"]
    lines += [
        "",
        f"Per question (pass rate across repeats): {v['better']} better, {v['worse']} worse, {v['same']} same.",
        "",
        "| Consistency | A | B |",
        "|---|---:|---:|",
        f"| Questions with mixed pass/fail across repeats | {a['consistency']['flaky']} | "
        f"{b['consistency']['flaky']} |",
        f"| Mean per-question pass variance (0–0.25) | "
        f"{_fmt(a['consistency']['mean_pass_variance'], 'num')} | "
        f"{_fmt(b['consistency']['mean_pass_variance'], 'num')} |",
        f"| Median per-question latency stdev | {_fmt(a['consistency']['median_latency_stdev'], 'secs')} | "
        f"{_fmt(b['consistency']['median_latency_stdev'], 'secs')} |",
    ]
    for key, side in (("A", a), ("B", b)):
        if side["routed_to"]:
            routes = ", ".join(f"`{k}` {n}" for k, n in side["routed_to"].items())
            lines += ["", f"Routed to ({key}): {routes}"]
    lines += [
        "",
        "## By category",
        "",
        "| Category | n (A/B) | Pass A | Pass B | Δ | Median latency A | B | <10s A | B |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in result["by_category"]:
        lines.append(
            f"| {r['label']} | {r['n']['a']}/{r['n']['b']} | {_fmt(r['a'], 'pct')} | {_fmt(r['b'], 'pct')} | "
            f"{_fmt(r['delta'], 'pct', signed=True)} | {_fmt(r['median_latency_a'], 'secs')} | "
            f"{_fmt(r['median_latency_b'], 'secs')} | {_fmt(r['fast_share_a'], 'pct')} | "
            f"{_fmt(r['fast_share_b'], 'pct')} |"
        )
    lines += ["", "## By track", "", "| Track | n (A/B) | Pass A | Pass B | Δ |", "|---|---:|---:|---:|---:|"]
    for r in result["by_track"]:
        lines.append(
            f"| {r['label']} | {r['n']['a']}/{r['n']['b']} | {_fmt(r['a'], 'pct')} | {_fmt(r['b'], 'pct')} | "
            f"{_fmt(r['delta'], 'pct', signed=True)} |"
        )
    changed = [q for q in result["questions"] if q["verdict"] != "same"]
    lines += [
        "",
        f"## Questions that changed ({len(changed)}; the HTML report lists all)",
        "",
        "| Q | Category | A | B | Δ pass | Median latency A → B | Question |",
        "|---:|---|---|---|---:|---|---|",
    ]
    for q in changed[:per_question_limit]:
        text = q["question"].replace("|", "\\|").replace("\n", " ")
        text = text if len(text) <= 90 else text[:89] + "…"
        lines.append(
            f"| {q['id']} | {q['category']} | {q['a']['icons']} {q['a']['passes']}/{q['a']['graded']} | "
            f"{q['b']['icons']} {q['b']['passes']}/{q['b']['graded']} | {_fmt(q['delta'], 'pct', signed=True)} | "
            f"{_fmt(q['a']['median_latency'], 'secs')} → {_fmt(q['b']['median_latency'], 'secs')} | {text} |"
        )
    if len(changed) > per_question_limit:
        lines.append(f"\n…and {len(changed) - per_question_limit} more.")
    return "\n".join(lines) + "\n"


def default_out_dir(result: dict) -> Path:
    a, b = result["a"], result["b"]
    return RESULTS_DIR / "compare" / f"{a['run_id']}-{a['model']}_vs_{b['run_id']}-{b['model']}"


def write_compare(result: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or default_out_dir(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compare.json").write_text(json.dumps(result, indent=1))
    (out_dir / "compare.md").write_text(to_markdown(result))
    env = _env()
    # select_autoescape() in _env() matches *.html, not *.html.j2; question text must be escaped here.
    env.autoescape = True
    env.filters["fmt"] = _fmt
    out = out_dir / "compare.html"
    out.write_text(env.get_template("compare.html.j2").render(r=result, side_name=_side_name))
    return out
