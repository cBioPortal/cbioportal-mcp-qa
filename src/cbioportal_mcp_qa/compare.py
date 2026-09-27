"""Compare two runs (A = baseline, B = candidate), per question and in aggregate, pooling repeats.

Only questions both runs asked are compared, and only when both were graded the same way: the same judge model,
questions file and, per question, the same text, history, track and references. Otherwise `compare` refuses
unless `allow_mismatch` is set, which marks the affected questions and adds a warning.

Every expected turn (question × repeat) is accounted for:

- completed: the agent answered (HTTP 200). failed: it returned an error or timed out. missing: never recorded
  (an interrupted run). ungraded: completed, the question has a reference, but no grade yet. no reference: the
  question can't be graded at all.
- eligible turns = the gradeable question's expected turns minus ungraded ones. A failed or missing turn is
  eligible and counts as not passing.
- recall = passes / eligible turns. precision = passes / attempted answers (pass + fail). attempt rate =
  attempted / eligible turns (declines, failures and missing turns are not attempts), so recall = precision ×
  attempt rate. `pass_rate` keeps the report's definition, passes / graded answers, which leaves failed turns
  out; it is shown for continuity with the per-run reports.
- latency is reported over completed turns, and again over completed + failed turns with each failure at its
  elapsed time (missing turns have none). The share under 10s counts failures as not fast.

Works with any run.json, including runs recorded before per-call traces (their tool rounds and routing show "–").
"""

import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import MODELS
from .dataset import CATEGORIES, TRACKS
from .report import (
    FAST_S,
    OUTCOME_ICONS,
    TRACK_LABELS,
    _env,
    _has_reference,
    category_of,
    mean,
    median,
    outcome_of,
    pct,
    quantile,
    record_cost,
)
from .run import RESULTS_DIR, Run

MISSING_ICON = "?"
# What makes two runs' answers to a question comparable: it was asked and graded against the same thing.
DEFINITION_FIELDS = ("question", "history", "expected_answer", "expected_links", "notes", "track")


class IncompatibleRuns(ValueError):
    pass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    fmt: str  # pct | secs | num | usd | int
    better: str  # higher | lower


METRICS = [
    Metric("recall", "Recall: passes / eligible turns (failed or missing = not passed)", "pct", "higher"),
    Metric("precision", "Precision: passes / attempted answers", "pct", "higher"),
    Metric("attempt_rate", "Attempt rate: attempted / eligible turns", "pct", "higher"),
    Metric(
        "pass_rate", "Pass rate over graded answers (report definition; failures left out)", "pct", "higher"
    ),
    Metric("median_latency", "Median latency, completed turns", "secs", "lower"),
    Metric("p90_latency", "p90 latency, completed turns", "secs", "lower"),
    Metric("median_latency_all", "Median latency, completed + failed turns", "secs", "lower"),
    Metric("p90_latency_all", "p90 latency, completed + failed turns", "secs", "lower"),
    Metric("fast_share", f"Under {FAST_S}s, of completed turns", "pct", "higher"),
    Metric("fast_share_all", f"Under {FAST_S}s, of completed + failed turns", "pct", "higher"),
    Metric("mean_llm_calls", "LLM calls / answer (mean)", "num", "lower"),
    Metric("median_llm_calls", "LLM calls / answer (median)", "num", "lower"),
    Metric("mean_tool_rounds", "Tool rounds / answer (mean)", "num", "lower"),
    Metric("mean_handoffs", "Successful handoffs / answer", "num", "lower"),
    Metric("failed_handoffs", "Failed handoffs (total)", "int", "lower"),
    Metric("tool_error_rate", "Tool error rate", "pct", "lower"),
    Metric("cost_per_answer", "Cost / answer", "usd", "lower"),
]
COUNT_KEYS = ("expected", "completed", "failed", "missing", "ungraded", "no_reference")


@dataclass
class Pool:
    """Turns pooled over repeats (and over questions, for a category, track or the whole run)."""

    expected: int = 0
    completed: int = 0
    failed: int = 0
    missing: int = 0
    ungraded: int = 0
    no_reference: int = 0
    unexpected: int = 0  # records with a repeat number above the run's repeats (left out)
    # Failed and missing turns of questions with a reference: eligible, counted as not passed.
    failed_gradeable: int = 0
    missing_gradeable: int = 0
    outcomes: Counter = field(default_factory=Counter)  # pass / fail / declined
    latencies: list[float] = field(default_factory=list)  # completed turns
    failed_latencies: list[float] = field(default_factory=list)
    llm_calls: list[int] = field(default_factory=list)
    tool_rounds: list[int] = field(default_factory=list)
    handoffs: list[int] = field(default_factory=list)
    failed_handoff_count: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    cost: float = 0.0
    routed_to: Counter = field(default_factory=Counter)

    def add(self, recs: list[dict], expected: int, question: dict) -> None:
        in_range = [r for r in recs if 1 <= r["repeat"] <= expected]
        self.unexpected += len(recs) - len(in_range)
        gradeable = _has_reference(question)
        self.expected += expected
        missing = expected - len({r["repeat"] for r in in_range})
        self.missing += missing
        self.missing_gradeable += missing * gradeable
        for rec in in_range:
            reply = rec["reply"]
            if reply.get("status") != 200:
                self.failed += 1
                self.failed_gradeable += gradeable
                if reply.get("latency_s") is not None:
                    self.failed_latencies.append(reply["latency_s"])
                continue
            self.completed += 1
            self.latencies.append(reply["latency_s"])
            self.cost += record_cost(rec)[0] or 0.0
            outcome = outcome_of(rec)
            if not gradeable:
                self.no_reference += 1
            elif outcome == "ungraded":
                self.ungraded += 1
            else:
                self.outcomes[outcome] += 1
            if trace := rec.get("trace"):
                self.llm_calls.append(trace["llm_calls"])
                if "tool_rounds" in trace:
                    self.tool_rounds.append(trace["tool_rounds"])
                    self.handoffs.append(trace.get("handoffs") or 0)
                    self.failed_handoff_count += trace.get("failed_handoffs") or 0
                if trace.get("routed_to"):
                    self.routed_to[trace["routed_to"]] += 1
                self.tool_calls += len(trace["tool_calls"])
                self.tool_errors += sum(not c["ok"] for c in trace["tool_calls"])
        if not gradeable:
            # Failed or missing turns of a question without a reference are no-reference turns too.
            self.no_reference += expected - sum(r["reply"].get("status") == 200 for r in in_range)

    @property
    def passes(self) -> int:
        return self.outcomes["pass"]

    @property
    def attempted(self) -> int:
        return self.outcomes["pass"] + self.outcomes["fail"]

    @property
    def eligible(self) -> int:
        """Turns of gradeable questions that count toward recall: graded, failed or missing."""
        return sum(self.outcomes.values()) + self.failed_gradeable + self.missing_gradeable

    @property
    def recall(self) -> float | None:
        return pct(self.passes, self.eligible)

    @property
    def precision(self) -> float | None:
        return pct(self.passes, self.attempted)

    @property
    def attempt_rate(self) -> float | None:
        return pct(self.attempted, self.eligible)

    @property
    def pass_rate(self) -> float | None:
        return pct(self.passes, sum(self.outcomes.values()))

    @property
    def median_latency(self) -> float | None:
        return median(self.latencies)

    @property
    def p90_latency(self) -> float | None:
        return quantile(self.latencies, 0.9)

    @property
    def median_latency_all(self) -> float | None:
        return median(self.latencies + self.failed_latencies)

    @property
    def p90_latency_all(self) -> float | None:
        return quantile(self.latencies + self.failed_latencies, 0.9)

    @property
    def fast_share(self) -> float | None:
        return pct(sum(t < FAST_S for t in self.latencies), len(self.latencies))

    @property
    def fast_share_all(self) -> float | None:
        return pct(sum(t < FAST_S for t in self.latencies), self.completed + self.failed)

    @property
    def latency_stdev(self) -> float | None:
        return statistics.stdev(self.latencies) if len(self.latencies) > 1 else None

    @property
    def mean_llm_calls(self) -> float | None:
        return mean(self.llm_calls)

    @property
    def median_llm_calls(self) -> float | None:
        return median(self.llm_calls)

    @property
    def mean_tool_rounds(self) -> float | None:
        return mean(self.tool_rounds)

    @property
    def mean_handoffs(self) -> float | None:
        return mean(self.handoffs)

    @property
    def failed_handoffs(self) -> int | None:
        """None when no trace recorded handoffs (traces attached before per-call traces)."""
        return self.failed_handoff_count if self.handoffs else None

    @property
    def tool_error_rate(self) -> float | None:
        return pct(self.tool_errors, self.tool_calls)

    @property
    def cost_per_answer(self) -> float | None:
        return self.cost / self.completed if self.completed else None

    @property
    def pass_variance(self) -> float | None:
        """Bernoulli variance of passing across eligible turns: 0 when all agree, 0.25 at 50/50."""
        if self.eligible < 2:
            return None
        p = self.passes / self.eligible
        return p * (1 - p)

    @property
    def flaky(self) -> bool:
        return 0 < self.passes < self.eligible

    @property
    def incomplete(self) -> bool:
        return bool(self.failed or self.missing or self.ungraded or self.unexpected)

    def counts(self) -> dict:
        return {k: getattr(self, k) for k in COUNT_KEYS}

    def to_dict(self) -> dict:
        return self.counts() | {
            "passes": self.passes,
            "attempted": self.attempted,
            "eligible": self.eligible,
            "unexpected": self.unexpected,
            **{m.key: getattr(self, m.key) for m in METRICS},
            "latency_stdev": self.latency_stdev,
            "pass_variance": self.pass_variance,
            "flaky": self.flaky,
            "routed_to": dict(self.routed_to.most_common()),
        }


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


def _norm(value):
    if value in (None, "", [], ()):
        return None
    return list(value) if isinstance(value, tuple) else value


def definition(question: dict) -> str:
    """The fields that decide how a question is asked and graded, as a comparable string."""
    fields = {f: _norm(question.get(f)) for f in DEFINITION_FIELDS}
    fields["track"] = fields["track"] or "data"
    return json.dumps(fields, sort_keys=True, ensure_ascii=False)


def definition_mismatch(recs_a: list[dict], recs_b: list[dict]) -> list[str]:
    """Which definition fields differ for one question, between runs or between one run's repeats."""
    defs = {side: {definition(r["question"]) for r in recs} for side, recs in (("A", recs_a), ("B", recs_b))}
    out = [f"differs between {side}'s repeats" for side, d in defs.items() if len(d) > 1]
    a, b = (json.loads(sorted(defs[s])[0]) for s in ("A", "B"))
    out += [f for f in DEFINITION_FIELDS if a[f] != b[f]]
    return out


def _run_setup_mismatch(run_a: Run, run_b: Run) -> list[str]:
    problems = []
    for key, what in (("judge_model", "judge model"), ("questions_file", "questions file")):
        a, b = run_a.data.get(key), run_b.data.get(key)
        if a != b:
            problems.append(f"{what} differs: A {a!r}, B {b!r}")
    return problems


def _cell(recs: list[dict], expected: int, question: dict) -> dict:
    pool = Pool()
    pool.add(recs, expected, question)
    by_repeat = {r["repeat"]: r for r in recs}
    icons = "".join(
        OUTCOME_ICONS[outcome_of(by_repeat[i])] if i in by_repeat else MISSING_ICON
        for i in range(1, expected + 1)
    )
    return pool.to_dict() | {"icons": icons, "routed_to": sorted(pool.routed_to)}


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def _verdict(delta: float | None, better: str, tolerance: float = 0.0) -> str:
    """better | worse | same, from B's point of view."""
    if delta is None or abs(delta) <= tolerance:
        return "same"
    return "better" if (delta > 0) == (better == "higher") else "worse"


def _group_rows(groups: dict[str, dict[str, Pool]], order: list[str], labels: dict) -> list[dict]:
    rows = []
    for key in order:
        if key not in groups:
            continue
        a, b = groups[key]["a"], groups[key]["b"]
        rows.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "a": a.to_dict(),
                "b": b.to_dict(),
                "delta": _delta(a.recall, b.recall),
            }
        )
    return rows


def _warn_incomplete(side: str, run: Run, pool: Pool) -> list[str]:
    if not pool.incomplete:
        return []
    parts = [
        f"{pool.failed} failed",
        f"{pool.missing} missing",
        f"{pool.ungraded} ungraded",
    ]
    if pool.unexpected:
        parts.append(f"{pool.unexpected} with a repeat number above the run's {run.data.get('repeats', 1)}")
    return [
        f"{side} ({run.data['run_id']}) is incomplete: {pool.completed} of {pool.expected} expected turns "
        f"completed; "
        + ", ".join(parts)
        + ". Failed and missing turns count as not passed; ungraded ones are "
        "left out of recall until graded."
    ]


def compare(
    run_a: Run,
    run_b: Run,
    model_a: str | None = None,
    model_b: str | None = None,
    allow_mismatch: bool = False,
) -> dict:
    model_a, model_b = pick_model(run_a, model_a), pick_model(run_b, model_b)
    qa, qb = _by_question(run_a, model_a), _by_question(run_b, model_b)
    rep_a, rep_b = run_a.data.get("repeats", 1), run_b.data.get("repeats", 1)
    common = sorted(qa.keys() & qb.keys())

    setup_problems = _run_setup_mismatch(run_a, run_b)
    mismatched = {qid: m for qid in common if (m := definition_mismatch(qa[qid], qb[qid]))}
    if (setup_problems or mismatched) and not allow_mismatch:
        lines = list(setup_problems)
        if mismatched:
            shown = ", ".join(f"Q{qid} ({', '.join(m)})" for qid, m in list(mismatched.items())[:10])
            more = f" and {len(mismatched) - 10} more" if len(mismatched) > 10 else ""
            lines.append(f"{len(mismatched)} questions changed between the runs: {shown}{more}")
        raise IncompatibleRuns(
            "runs were not asked or graded the same way, so their scores aren't comparable:\n  - "
            + "\n  - ".join(lines)
            + "\nRegrade the older run against the current questions (`cbioportal-mcp-qa grade <run> "
            "--refresh-questions`), or pass --allow-mismatch to compare anyway with those questions marked."
        )
    warnings = [f"Setup mismatch allowed: {p}" for p in setup_problems]
    if mismatched:
        warnings.append(
            f"{len(mismatched)} questions have different definitions in A and B (marked ⚠); their pass/fail "
            "compares answers graded against different questions or references."
        )

    totals = {"a": Pool(), "b": Pool()}
    by_category: dict[str, dict[str, Pool]] = {}
    by_track: dict[str, dict[str, Pool]] = {}
    questions = []
    for qid in common:
        question_a, question = qa[qid][0]["question"], qb[qid][0]["question"]
        for side, recs, expected, q in (("a", qa[qid], rep_a, question_a), ("b", qb[qid], rep_b, question)):
            for pools in (
                totals,
                by_category.setdefault(category_of(q), {"a": Pool(), "b": Pool()}),
                by_track.setdefault(q.get("track") or "data", {"a": Pool(), "b": Pool()}),
            ):
                pools[side].add(recs, expected, q)
        a, b = _cell(qa[qid], rep_a, question_a), _cell(qb[qid], rep_b, question)
        delta = _delta(a["recall"], b["recall"])
        questions.append(
            {
                "id": qid,
                "question": question["question"],
                "category": category_of(question),
                "track": question.get("track") or "data",
                "gradeable": _has_reference(question),
                "mismatch": mismatched.get(qid, []),
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
    warnings += _warn_incomplete("A", run_a, totals["a"]) + _warn_incomplete("B", run_b, totals["b"])

    metrics = []
    for m in METRICS:
        a, b = getattr(totals["a"], m.key), getattr(totals["b"], m.key)
        d = _delta(a, b)
        metrics.append(m.__dict__ | {"a": a, "b": b, "delta": d, "verdict": _verdict(d, m.better)})

    def consistency(side: str) -> dict:
        cells = [q[side] for q in questions if q[side]["eligible"]]
        variances = [c["pass_variance"] for c in cells if c["pass_variance"] is not None]
        stdevs = [c["latency_stdev"] for c in cells if c["latency_stdev"] is not None]
        return {
            "flaky": sum(c["flaky"] for c in cells),
            "with_repeats": len(variances),
            "mean_pass_variance": mean(variances),
            "median_latency_stdev": median(stdevs),
        }

    def describe(side: str, run: Run, model: str) -> dict:
        pool = totals[side]
        return {
            "run_id": run.data["run_id"],
            "target": run.data["target"],
            "runner": run.data.get("runner", "agents-api"),
            "model": model,
            "label": MODELS[model].label,
            "repeats": run.data.get("repeats", 1),
            "judge_model": run.data.get("judge_model"),
            "questions_file": run.data.get("questions_file"),
            "created_at": run.data.get("created_at"),
            "agent_id": (run.data.get("agent_prompt") or {}).get("agent_id"),
            "librechat": (run.data.get("versions") or {}).get("librechat"),
            "counts": pool.counts() | {"eligible": pool.eligible, "unexpected": pool.unexpected},
            "routed_to": dict(pool.routed_to.most_common()),
            "consistency": consistency(side),
        }

    seen = set(by_category)
    return {
        "a": describe("a", run_a, model_a),
        "b": describe("b", run_b, model_b),
        "n_questions": len(common),
        "only_a": sorted(qa.keys() - qb.keys()),
        "only_b": sorted(qb.keys() - qa.keys()),
        "warnings": warnings,
        "mismatched_questions": sorted(mismatched),
        "metrics": metrics,
        "by_category": _group_rows(
            by_category, [c for c in CATEGORIES if c in seen] + sorted(seen - set(CATEGORIES)), {}
        ),
        "by_track": _group_rows(by_track, list(TRACKS), TRACK_LABELS),
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
    if fmt == "int":
        return f"{sign}{value:,.0f}"
    return f"{sign}{value:.2f}"


def _side_name(side: dict) -> str:
    return f"{side['run_id']} {side['label']} ({side['target']}, ×{side['repeats']})"


def _counts_text(c: dict) -> str:
    return (
        f"{c['completed']}/{c['expected']} completed · {c['failed']} failed · {c['missing']} missing · "
        f"{c['ungraded']} ungraded · {c['no_reference']} no reference"
    )


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(result: dict, per_question_limit: int = 40) -> str:
    a, b = result["a"], result["b"]
    lines = [
        f"# Benchmark comparison: {a['run_id']} vs {b['run_id']}",
        "",
        f"- **A (baseline):** {_side_name(a)}, judge `{a['judge_model']}`",
        f"- **B:** {_side_name(b)}, judge `{b['judge_model']}`",
        f"- {result['n_questions']} questions in both runs; repeats pooled."
        + (f" Only in A: {len(result['only_a'])}." if result["only_a"] else "")
        + (f" Only in B: {len(result['only_b'])}." if result["only_b"] else ""),
    ]
    if result["warnings"]:
        lines += ["", *[f"> ⚠ {w}" for w in result["warnings"]]]
    lines += [
        "",
        "## Turns",
        "",
        "| | Expected | Completed | Failed | Missing | Ungraded | No reference | Eligible |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, side in (("A", a), ("B", b)):
        c = side["counts"]
        lines.append(
            f"| {key} | {c['expected']} | {c['completed']} | {c['failed']} | {c['missing']} | {c['ungraded']} | "
            f"{c['no_reference']} | {c['eligible']} |"
        )
    lines += ["", "## Headline", "", "| Metric | A | B | Δ (B − A) |", "|---|---:|---:|---:|"]
    marks = {"better": " ▲", "worse": " ▼", "same": ""}
    for m in result["metrics"]:
        lines.append(
            f"| {m['label']} | {_fmt(m['a'], m['fmt'])} | {_fmt(m['b'], m['fmt'])} | "
            f"{_fmt(m['delta'], m['fmt'], signed=True)}{marks[m['verdict']]} |"
        )
    v = result["question_verdicts"]
    lines += [
        "",
        f"Per question (recall across repeats): {v['better']} better, {v['worse']} worse, {v['same']} same.",
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
    for title, rows in (("By category", result["by_category"]), ("By track", result["by_track"])):
        lines += [
            "",
            f"## {title}",
            "",
            "| | Completed/expected (failed, missing, ungraded) A · B | Recall A | Recall B | Δ | Precision A | B "
            "| Median latency A | B | p90 A | B | <10s A | B | LLM calls A | B |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in rows:
            ra, rb = r["a"], r["b"]
            counts = " · ".join(
                f"{x['completed']}/{x['expected']} ({x['failed']}, {x['missing']}, {x['ungraded']})"
                for x in (ra, rb)
            )
            lines.append(
                f"| {r['label']} | {counts} | {_fmt(ra['recall'], 'pct')} | {_fmt(rb['recall'], 'pct')} | "
                f"{_fmt(r['delta'], 'pct', signed=True)} | {_fmt(ra['precision'], 'pct')} | "
                f"{_fmt(rb['precision'], 'pct')} | {_fmt(ra['median_latency'], 'secs')} | "
                f"{_fmt(rb['median_latency'], 'secs')} | {_fmt(ra['p90_latency'], 'secs')} | "
                f"{_fmt(rb['p90_latency'], 'secs')} | {_fmt(ra['fast_share'], 'pct')} | "
                f"{_fmt(rb['fast_share'], 'pct')} | {_fmt(ra['mean_llm_calls'], 'num')} | "
                f"{_fmt(rb['mean_llm_calls'], 'num')} |"
            )
    listed = [q for q in result["questions"] if q["verdict"] != "same" or q["mismatch"] or _q_incomplete(q)]
    lines += [
        "",
        f"## Questions that changed, differ or are incomplete ({len(listed)}; the HTML report lists all)",
        "",
        "| Q | Category | A | B | Δ recall | Precision A → B | Median · p90 A | Median · p90 B | <10s A → B "
        "| Failed/missing/ungraded A · B | Question |",
        "|---:|---|---|---|---:|---|---|---|---|---|---|",
    ]
    for q in listed[:per_question_limit]:
        text = _md(q["question"])
        text = text if len(text) <= 90 else text[:89] + "…"
        if q["mismatch"]:
            text = f"⚠ changed: {', '.join(q['mismatch'])} — {text}"
        qa_, qb_ = q["a"], q["b"]
        lines.append(
            f"| {q['id']} | {q['category']} | {qa_['icons']} {qa_['passes']}/{qa_['eligible']} | "
            f"{qb_['icons']} {qb_['passes']}/{qb_['eligible']} | {_fmt(q['delta'], 'pct', signed=True)} | "
            f"{_fmt(qa_['precision'], 'pct')} → {_fmt(qb_['precision'], 'pct')} | "
            f"{_fmt(qa_['median_latency'], 'secs')} · {_fmt(qa_['p90_latency'], 'secs')} | "
            f"{_fmt(qb_['median_latency'], 'secs')} · {_fmt(qb_['p90_latency'], 'secs')} | "
            f"{_fmt(qa_['fast_share'], 'pct')} → {_fmt(qb_['fast_share'], 'pct')} | "
            f"{qa_['failed']}/{qa_['missing']}/{qa_['ungraded']} · {qb_['failed']}/{qb_['missing']}/{qb_['ungraded']} "
            f"| {text} |"
        )
    if len(listed) > per_question_limit:
        lines.append(f"\n…and {len(listed) - per_question_limit} more.")
    lines += [
        "",
        f"Marks per repeat: ✓ pass · ✗ fail · – declined · · no reference or ungraded · ! request failed · "
        f"{MISSING_ICON} missing. Recall = passes / eligible turns; eligible = graded + failed + missing turns of "
        "questions with a reference.",
    ]
    return "\n".join(lines) + "\n"


def _q_incomplete(q: dict) -> bool:
    return any(q[s][k] for s in ("a", "b") for k in ("failed", "missing", "ungraded"))


def default_out_dir(result: dict) -> Path:
    a, b = result["a"], result["b"]
    return RESULTS_DIR / "compare" / f"{a['run_id']}-{a['model']}_vs_{b['run_id']}-{b['model']}"


def write_compare(result: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or default_out_dir(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compare.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    (out_dir / "compare.md").write_text(to_markdown(result))
    env = _env()
    # select_autoescape() in _env() matches *.html, not *.html.j2; question text must be escaped here.
    env.autoescape = True
    env.filters["fmt"] = _fmt
    out = out_dir / "compare.html"
    out.write_text(
        env.get_template("compare.html.j2").render(
            r=result, side_name=_side_name, counts_text=_counts_text, missing_icon=MISSING_ICON
        )
    )
    return out
