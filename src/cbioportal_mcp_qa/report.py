"""Aggregate a run into stats and render the static HTML report + results index."""

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .checks import internal_leaks
from .config import MODELS, PRICES_BY_BEDROCK_ID, TARGETS
from .dataset import CATEGORIES, TRACKS, load_questions
from .persist import write_json, write_rendered
from .run import RESULTS_DIR, Run
from .traces import SCHEMA_ERROR

OUTCOMES = ["pass", "fail", "declined", "ungraded", "error"]
OUTCOME_LABELS = {
    "pass": "Pass",
    "fail": "Fail",
    "declined": "Declined",
    "ungraded": "No reference",
    "error": "Request failed",
}
OUTCOME_ICONS = {"pass": "✓", "fail": "✗", "declined": "–", "ungraded": "·", "error": "!"}
TRACK_LABELS = {
    "data": "Data",
    "navigation": "Navigation",
    "analysis": "Analysis",
    "out_of_scope": "Out of scope",
}


def outcome_of(rec: dict) -> str:
    if rec["reply"].get("status") != 200:
        return "error"
    grade = rec.get("grade") or {}
    if grade.get("passed") is None:
        return "ungraded"
    if grade["passed"]:
        return "pass"
    return "declined" if grade.get("declined") else "fail"


def category_of(q: dict) -> str:
    return q.get("category") or q.get("type") or "Other"


def record_cost(rec: dict) -> tuple[float | None, bool]:
    """Estimated USD for one answer and whether the cache split was known."""
    price = MODELS[rec["model"]].price
    if price is None:
        return _per_call_cost(rec)
    reply = rec["reply"]
    prompt, completion = reply.get("prompt_tokens"), reply.get("completion_tokens")
    if prompt is None or completion is None:
        return None, False
    read, write = reply.get("cache_read_tokens"), reply.get("cache_write_tokens")
    if read is None or write is None:
        return price.cost(prompt, completion, 0, 0), False
    return price.cost(max(prompt - read - write, 0), completion, write, read), True


def _per_call_cost(rec: dict) -> tuple[float | None, bool]:
    """For a model label that stands for several models (the handoff router): the sum over its traced LLM calls."""
    generations = (rec.get("trace") or {}).get("generations") or []
    costs = [g.get("cost") for g in generations]
    if not costs or all(c is None for c in costs):
        return None, False
    # Complete when every call was priced (a call's usage records its own cache split, if any).
    return sum(c or 0.0 for c in costs), all(c is not None for c in costs)


def pct(n: int, d: int) -> float | None:
    return 100 * n / d if d else None


def quantile(values: list[float], q: float) -> float | None:
    """Upper nearest-rank quantile: the sorted value at index floor(q·n), clamped to the last one.

    For p90 that is the maximum when n <= 10 (n=10 -> 10th value; n=11 -> 10th; n=20 -> 19th), so with few
    answers it errs high rather than interpolating. None for no values."""
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


FAST_S = 10  # "fast answer" threshold for the share of answers under it


def _graded(c: Counter) -> int:
    return c["pass"] + c["fail"] + c["declined"]


def number_disagreement(grade: dict) -> bool:
    """The objective number check and the judge disagree."""
    return (
        grade.get("number_match") is not None
        and grade.get("passed") is not None
        and grade["number_match"] != grade["passed"]
    )


def record_leaks(rec: dict) -> list[str]:
    reply = rec["reply"]
    if reply.get("status") != 200 or rec["question"].get("technical"):
        return []
    return internal_leaks(reply.get("answer") or "")


@dataclass
class ModelStats:
    key: str
    label: str
    answers: int = 0
    outcomes: Counter = field(default_factory=Counter)
    by_track: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    by_category: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    latencies: list[float] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0
    cost_complete: bool = True
    llm_calls: list[int] = field(default_factory=list)
    tool_rounds: list[int] = field(default_factory=list)
    handoffs: list[int] = field(default_factory=list)
    failed_handoffs: int = 0
    routed_to: Counter = field(default_factory=Counter)
    tool_calls: Counter = field(default_factory=Counter)
    tool_errors: Counter = field(default_factory=Counter)
    schema_errors: int = 0
    traced: int = 0
    number_checks: int = 0
    number_disagreements: int = 0
    link_answers: int = 0
    invalid_study_links: int = 0
    internal_leak_answers: int = 0

    @property
    def graded(self) -> int:
        return _graded(self.outcomes)

    @property
    def pass_rate(self) -> float | None:
        return pct(self.outcomes["pass"], self.graded)

    @property
    def precision(self) -> float | None:
        """Pass rate among questions it attempted rather than declined."""
        return pct(self.outcomes["pass"], self.outcomes["pass"] + self.outcomes["fail"])

    @property
    def coverage(self) -> float | None:
        return pct(self.outcomes["pass"] + self.outcomes["fail"], self.graded)

    @property
    def cost_per_answer(self) -> float | None:
        return self.cost / self.answers if self.answers else None

    @property
    def cost_per_pass(self) -> float | None:
        return self.cost / self.outcomes["pass"] if self.outcomes["pass"] else None

    @property
    def median_latency(self) -> float | None:
        return median(self.latencies)

    @property
    def p90_latency(self) -> float | None:
        return quantile(self.latencies, 0.9)

    @property
    def fast_share(self) -> float | None:
        """% of answers returned in under FAST_S seconds."""
        return pct(sum(t < FAST_S for t in self.latencies), len(self.latencies))

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
    def median_tool_rounds(self) -> float | None:
        return median(self.tool_rounds)

    @property
    def mean_handoffs(self) -> float | None:
        return mean(self.handoffs)

    @property
    def mean_tool_calls(self) -> float | None:
        return sum(self.tool_calls.values()) / self.traced if self.traced else None

    @property
    def tool_error_rate(self) -> float | None:
        return pct(sum(self.tool_errors.values()), sum(self.tool_calls.values()))

    def track_pass_rate(self, track: str) -> float | None:
        return pct(self.by_track[track]["pass"], _graded(self.by_track[track]))

    def category_pass_rate(self, category: str) -> float | None:
        return pct(self.by_category[category]["pass"], _graded(self.by_category[category]))

    def add(self, rec: dict) -> float | None:
        """Count one record; returns its estimated cost."""
        q = rec["question"]
        outcome = outcome_of(rec)
        self.outcomes[outcome] += 1
        self.by_track[q.get("track") or "data"][outcome] += 1
        self.by_category[category_of(q)][outcome] += 1
        reply = rec["reply"]
        cost, complete = record_cost(rec)
        if reply.get("status") == 200:
            self.answers += 1
            self.latencies.append(reply["latency_s"])
            self.prompt_tokens += reply.get("prompt_tokens") or 0
            self.completion_tokens += reply.get("completion_tokens") or 0
            self.cache_read_tokens += reply.get("cache_read_tokens") or 0
            self.cache_write_tokens += reply.get("cache_write_tokens") or 0
            self.cost += cost or 0.0
            self.cost_complete &= complete
        if trace := rec.get("trace"):
            self.traced += 1
            self.llm_calls.append(trace["llm_calls"])
            # Traces attached before tool rounds and routing were recorded have neither.
            if "tool_rounds" in trace:
                self.tool_rounds.append(trace["tool_rounds"])
                self.handoffs.append(trace.get("handoffs") or 0)
                self.failed_handoffs += trace.get("failed_handoffs") or 0
            if trace.get("routed_to"):
                self.routed_to[trace["routed_to"]] += 1
            for call in trace["tool_calls"]:
                self.tool_calls[call["name"]] += 1
                if not call["ok"]:
                    self.tool_errors[call["name"]] += 1
                    self.schema_errors += SCHEMA_ERROR in (call.get("error") or "")
        grade = rec.get("grade") or {}
        if grade:
            if grade.get("number_match") is not None and grade.get("passed") is not None:
                self.number_checks += 1
                self.number_disagreements += number_disagreement(grade)
            self.link_answers += bool(grade.get("links"))
            self.invalid_study_links += bool(grade.get("invalid_studies"))
        self.internal_leak_answers += bool(record_leaks(rec))
        return cost

    def outcome_segments(self) -> list[dict]:
        total = sum(self.outcomes.values())
        return [
            {
                "key": o,
                "label": OUTCOME_LABELS[o],
                "icon": OUTCOME_ICONS[o],
                "count": self.outcomes[o],
                "pct": pct(self.outcomes[o], total),
            }
            for o in OUTCOMES
            if self.outcomes[o]
        ]


def summarize(run: Run) -> dict:
    models = run.data["models"]
    stats = {m: ModelStats(m, MODELS[m].label) for m in models}
    questions: dict[int, dict] = {}
    judge_tokens = Counter()
    renders = run.data.get("renders", {})

    # Planned turns a stop left unasked count as failed requests, as their failure records did.
    for rec in [*run.records.values(), *run.missing_records()]:
        s = stats[rec["model"]]
        q = rec["question"]
        outcome = outcome_of(rec)
        reply = rec["reply"]
        cost = s.add(rec)
        trace = rec.get("trace")
        grade = rec.get("grade") or {}
        disagreement = number_disagreement(grade)
        if grade:
            judge_tokens["input"] += grade.get("judge_input_tokens", 0)
            judge_tokens["output"] += grade.get("judge_output_tokens", 0)
        leaks = record_leaks(rec)

        row = questions.setdefault(q["id"], {"question": q, "cells": defaultdict(list)})
        row["cells"][rec["model"]].append(
            {
                "repeat": rec["repeat"],
                "outcome": outcome,
                "outcome_label": OUTCOME_LABELS[outcome],
                "outcome_icon": OUTCOME_ICONS[outcome],
                "answer": reply.get("answer") or "",
                "error": reply.get("error"),
                "latency": reply.get("latency_s"),
                "cost": cost,
                "tokens": (reply.get("prompt_tokens") or 0) + (reply.get("completion_tokens") or 0),
                "grade": grade,
                "number_disagreement": disagreement,
                "internal_leaks": leaks,
                "renders": [renders[u] for u in (grade.get("links") or []) if u in renders],
                "trace": trace,
                "tool_errors": [c for c in (trace or {}).get("tool_calls", []) if not c["ok"]],
            }
        )

    tracks = [t for t in TRACKS if any(sum(s.by_track[t].values()) for s in stats.values())]
    by_track = [
        {
            "track": t,
            "label": TRACK_LABELS[t],
            "n": max(_graded(stats[m].by_track[t]) for m in models),
            "values": {m: stats[m].track_pass_rate(t) for m in models},
        }
        for t in tracks
    ]
    seen = {c for s in stats.values() for c in s.by_category}
    by_category = [
        {
            "category": c,
            "n": max(_graded(stats[m].by_category[c]) for m in models),
            "values": {m: stats[m].category_pass_rate(c) for m in models},
        }
        for c in [c for c in CATEGORIES if c in seen] + sorted(seen - set(CATEGORIES))
    ]
    judge_price = PRICES_BY_BEDROCK_ID.get(run.data["judge_model"])
    judge_cost = (
        judge_price.cost(judge_tokens["input"], judge_tokens["output"], 0, 0) if judge_price else None
    )

    return {
        "run": run.data,
        "target": TARGETS.get(run.data["target"]),
        "models": [stats[m] for m in models],
        "by_track": by_track,
        "by_category": by_category,
        "track_labels": TRACK_LABELS,
        "questions": [questions[k] for k in sorted(questions)],
        "judge_cost": judge_cost,
        "n_questions": len(questions),
        "n_gradeable": sum(1 for row in questions.values() if _has_reference(row["question"])),
        "all_tools": sorted({t for s in stats.values() for t in s.tool_calls}),
    }


def _has_reference(q: dict) -> bool:
    return bool(
        q.get("expected_answer") or q.get("expected_links") or "must" in (q.get("notes") or "").lower()
    )


def _env() -> Environment:
    env = Environment(loader=PackageLoader("cbioportal_mcp_qa"), autoescape=select_autoescape())
    env.filters["num"] = lambda v, d=0: "–" if v is None else f"{v:,.{d}f}"
    env.filters["usd"] = lambda v: "–" if v is None else (f"${v:,.2f}" if v >= 1 else f"${v:.3f}")
    env.filters["pct"] = lambda v: "–" if v is None else f"{v:.0f}%"
    env.filters["secs"] = lambda v: "–" if v is None else f"{v:.0f}s"
    return env


def write_report(run: Run) -> Path:
    summary = summarize(run)
    out = run.dir / "report.html"
    write_rendered(out, _env().get_template("report.html.j2").render, **summary)
    write_json(run.dir / "summary.json", _headline(summary), indent=1)
    write_index()
    return out


def _headline(summary: dict) -> dict:
    return {
        "run_id": summary["run"]["run_id"],
        "target": summary["run"]["target"],
        "runner": summary["run"].get("runner", "agents-api"),
        **{k: summary["run"].get(k) for k in RUN_SETUP_KEYS},
        "created_at": summary["run"]["created_at"],
        "n_questions": summary["n_questions"],
        "n_gradeable": summary["n_gradeable"],
        "models": {
            s.key: {
                "label": s.label,
                "pass_rate": s.pass_rate,
                "precision": s.precision,
                "coverage": s.coverage,
                "graded": s.graded,
                "answers": s.answers,
                "errors": s.outcomes["error"],
                "cost_per_answer": s.cost_per_answer,
                "cost_per_pass": s.cost_per_pass,
                "median_latency": s.median_latency,
                "p90_latency": s.p90_latency,
                "fast_share": s.fast_share,
                "mean_llm_calls": s.mean_llm_calls,
                "median_llm_calls": s.median_llm_calls,
                "mean_tool_rounds": s.mean_tool_rounds,
                "median_tool_rounds": s.median_tool_rounds,
                "mean_handoffs": s.mean_handoffs,
                "failed_handoffs": s.failed_handoffs if s.handoffs else None,
                "routed_to": dict(s.routed_to.most_common()),
                "tool_error_rate": s.tool_error_rate,
                "by_track": {row["track"]: row["values"][s.key] for row in summary["by_track"]},
                "by_category": {row["category"]: row["values"][s.key] for row in summary["by_category"]},
            }
            for s in summary["models"]
        },
    }


RUN_SETUP_KEYS = ("agent_prompt", "agents", "versions", "database_mcp", "questions_file", "judge_models")

# Each questions file is its own test set: its runs get a separate table on the index, in this order.
QUESTION_SETS = {
    "input/questions.yaml": {
        "title": "Main benchmark",
        "short": "Single questions covering data lookups, analysis, navigation links and out-of-scope requests.",
        "purpose": "The headline score. Each question stands alone: a count, frequency or list from the "
        "data, an analysis (comparison, survival, co-occurrence), a request for a cBioPortal link, or "
        "something the agent should decline or redirect. Use it to compare prompts, models and runners.",
    },
    "input/questions-multiturn.yaml": {
        "title": "Multi-turn follow-ups",
        "short": "Follow-up messages in a scripted conversation, modeled on real traffic. Smaller set; scores "
        "are not comparable with the main benchmark.",
        "purpose": "About 40% of real messages are follow-ups that need the earlier conversation. Each "
        "question is the user's next message after scripted turns: swapping a gene, study or cohort, "
        "breaking results down, accepting an offered option, answering a clarifying question, pushing back "
        "on a correct number, asking for significance or citations, and follow-ups in other languages.",
    },
    "input/questions-subset.yaml": {
        "title": "Subset questions",
        "short": "Statistics over a subset of samples or patients that per-study precomputed tables don't cover. "
        "Scores are not comparable with the main benchmark.",
        "purpose": "The main set leans on per-study statistics (top genes in a study, a gene's frequency in a "
        "study), which precomputed tables and per-study tools answer directly. Here the cohort is a clinical "
        "subset of a study (sample type, sex, smoking, stage, MSI, receptor status, OncoTree code) or a pooled "
        "set of studies, so the agent must write the SQL and must not answer with the whole-study number. "
        "Covers subset frequencies, pooled studies, subset comparisons, co-occurrence, top genes, patient vs "
        "sample level, clinical counts in mutation-defined groups and multi-turn narrowing.",
    },
}
SOURCE_URL = "https://github.com/cBioPortal/cbioportal-mcp-qa/blob/main/"


def question_set_info(questions_file: str) -> dict:
    """Title, purpose and question/track counts for a questions file (counts are None if it can't be read)."""
    info = {"file": questions_file, "title": questions_file, "short": "", "purpose": ""} | QUESTION_SETS.get(
        questions_file, {}
    )
    try:
        questions = load_questions(RESULTS_DIR.parent / questions_file)
    except (OSError, ValueError):
        questions = None
    info["n_questions"] = len(questions) if questions is not None else None
    tracks = Counter(q.track for q in questions or ())
    info["tracks"] = [(TRACK_LABELS[t], tracks[t]) for t in TRACKS if tracks[t]]
    categories = Counter(q.category for q in questions or ())
    info["categories"] = [(c, categories[c]) for c in CATEGORIES if categories[c]]
    info["questions"] = [asdict(q) | {"has_reference": q.has_reference} for q in questions or ()]
    info["url"] = SOURCE_URL + questions_file
    info["anchor"] = Path(questions_file).stem
    return info


def run_setup(run: dict) -> dict:
    """What a run ran on, as short labels: runner, prompt and server versions (None when not recorded)."""
    v = run.get("versions") or {}
    api = v.get("cbioportal_api") or {}
    digests = v.get("image_digests") or {}
    digests = {} if digests.get("error") else digests
    nav = v.get("cbioportal_navigator") or {}
    mcp = v.get("cbioportal_mcp") or {}
    prompt = run.get("agent_prompt") or {}
    if run.get("runner") == "claude-code":
        cc = v.get("claude_code")
        runner = "Claude Code " + cc.split()[0] if isinstance(cc, str) else "Claude Code"
    else:
        lc = v.get("librechat")
        runner = "LibreChat " + lc.split(":")[-1] if isinstance(lc, str) else "LibreChat"

    def server(version: str | None, digest: str | None) -> str | None:
        parts = [x for x in (version, digest and digest.removeprefix("sha256:")[:7]) if x]
        return " ".join(parts) or None

    return {
        "runner": runner,
        "prompt": prompt.get("sha256"),
        "cbioportal_mcp": server(mcp.get("version"), digests.get("cbioportal_mcp")),
        "navigator": server(nav.get("version"), digests.get("cbioportal_navigator")),
        "cbioportal": " / ".join(
            x
            for x in (
                api.get("portal_version"),
                api.get("db_schema_version") and f"DB {api['db_schema_version']}",
                api.get("gene_table_version"),
            )
            if x
        )
        or None,
    }


def write_index() -> Path:
    runs = []
    for path in sorted(RESULTS_DIR.glob("*/summary.json"), reverse=True):
        summary = json.loads(path.read_text())
        if not all(k in summary for k in RUN_SETUP_KEYS) and (path.parent / "run.json").exists():
            recorded = json.loads((path.parent / "run.json").read_text())
            summary |= {k: recorded.get(k) for k in RUN_SETUP_KEYS}
        summary["setup"] = run_setup(summary)
        runs.append(summary)
    sets: dict[str, list[dict]] = {}
    for run in runs:
        sets.setdefault(run.get("questions_file") or "input/questions.yaml", []).append(run)
    # A setup value is flagged, with its previous value, when it differs from the next older run of the same set
    # that recorded it.
    for set_runs in sets.values():
        for i, run in enumerate(set_runs):
            run["changed"] = {}
            for key, value in run["setup"].items():
                older = next(
                    (r["setup"][key] for r in set_runs[i + 1 :] if r["setup"][key] is not None), None
                )
                if value is not None and older is not None and value != older:
                    run["changed"][key] = older
    order = list(QUESTION_SETS)
    question_sets = [
        question_set_info(f) | {"runs": sets.get(f, [])}
        for f in sorted(
            set(QUESTION_SETS) | set(sets), key=lambda f: (order.index(f) if f in order else len(order), f)
        )
    ]
    # Other published checks (e.g. a database latency check) aren't benchmark runs: each folder has a check.json
    # with its title, date and summary, and the index lists them in their own table.
    checks = [
        json.loads(path.read_text()) | {"dir": path.parent.name} for path in RESULTS_DIR.glob("*/check.json")
    ]
    checks.sort(key=lambda c: (c.get("date") or "", c["dir"]), reverse=True)
    env = _env()
    for name in ("test_sets", "index"):
        write_rendered(
            RESULTS_DIR / f"{name.replace('_', '-')}.html",
            env.get_template(f"{name}.html.j2").render,
            question_sets=question_sets,
            track_labels=TRACK_LABELS,
            checks=checks,
        )
    out = RESULTS_DIR / "index.html"
    return out
