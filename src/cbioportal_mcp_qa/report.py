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
    reply = rec["reply"]
    prompt, completion = reply.get("prompt_tokens"), reply.get("completion_tokens")
    if prompt is None or completion is None:
        return None, False
    price = MODELS[rec["model"]].price
    read, write = reply.get("cache_read_tokens"), reply.get("cache_write_tokens")
    if read is None or write is None:
        return price.cost(prompt, completion, 0, 0), False
    return price.cost(max(prompt - read - write, 0), completion, write, read), True


def pct(n: int, d: int) -> float | None:
    return 100 * n / d if d else None


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def _graded(c: Counter) -> int:
    return c["pass"] + c["fail"] + c["declined"]


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
        return statistics.median(self.latencies) if self.latencies else None

    @property
    def p90_latency(self) -> float | None:
        return quantile(self.latencies, 0.9)

    @property
    def mean_llm_calls(self) -> float | None:
        return statistics.mean(self.llm_calls) if self.llm_calls else None

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

    for rec in run.records.values():
        s = stats[rec["model"]]
        q = rec["question"]
        track = q.get("track") or "data"
        category = category_of(q)
        outcome = outcome_of(rec)
        s.outcomes[outcome] += 1
        s.by_track[track][outcome] += 1
        s.by_category[category][outcome] += 1
        reply = rec["reply"]
        cost, complete = record_cost(rec)
        if reply.get("status") == 200:
            s.answers += 1
            s.latencies.append(reply["latency_s"])
            s.prompt_tokens += reply.get("prompt_tokens") or 0
            s.completion_tokens += reply.get("completion_tokens") or 0
            s.cache_read_tokens += reply.get("cache_read_tokens") or 0
            s.cache_write_tokens += reply.get("cache_write_tokens") or 0
            s.cost += cost or 0.0
            s.cost_complete &= complete
        trace = rec.get("trace")
        if trace:
            s.traced += 1
            s.llm_calls.append(trace["llm_calls"])
            for call in trace["tool_calls"]:
                s.tool_calls[call["name"]] += 1
                if not call["ok"]:
                    s.tool_errors[call["name"]] += 1
                    s.schema_errors += SCHEMA_ERROR in (call.get("error") or "")
        grade = rec.get("grade") or {}
        disagreement = False
        if grade:
            judge_tokens["input"] += grade.get("judge_input_tokens", 0)
            judge_tokens["output"] += grade.get("judge_output_tokens", 0)
            if grade.get("number_match") is not None and grade.get("passed") is not None:
                s.number_checks += 1
                disagreement = grade["number_match"] != grade["passed"]
                s.number_disagreements += disagreement
            s.link_answers += bool(grade.get("links"))
            s.invalid_study_links += bool(grade.get("invalid_studies"))

        leaks = (
            internal_leaks(reply.get("answer") or "")
            if reply.get("status") == 200 and not q.get("technical")
            else []
        )
        s.internal_leak_answers += bool(leaks)

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
    out.write_text(_env().get_template("report.html.j2").render(**summary))
    (run.dir / "summary.json").write_text(json.dumps(_headline(summary), indent=1))
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
                "tool_error_rate": s.tool_error_rate,
                "by_track": {row["track"]: row["values"][s.key] for row in summary["by_track"]},
                "by_category": {row["category"]: row["values"][s.key] for row in summary["by_category"]},
            }
            for s in summary["models"]
        },
    }


RUN_SETUP_KEYS = ("agent_prompt", "versions", "database_mcp", "questions_file")

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
    # A setup value is flagged when it differs from the next older run of the same set that recorded it.
    for set_runs in sets.values():
        for i, run in enumerate(set_runs):
            run["changed"] = set()
            for key, value in run["setup"].items():
                older = next(
                    (r["setup"][key] for r in set_runs[i + 1 :] if r["setup"][key] is not None), None
                )
                if value is not None and older is not None and value != older:
                    run["changed"].add(key)
    order = list(QUESTION_SETS)
    question_sets = [
        question_set_info(f) | {"runs": sets.get(f, [])}
        for f in sorted(
            set(QUESTION_SETS) | set(sets), key=lambda f: (order.index(f) if f in order else len(order), f)
        )
    ]
    env = _env()
    (RESULTS_DIR / "test-sets.html").write_text(
        env.get_template("test_sets.html.j2").render(question_sets=question_sets, track_labels=TRACK_LABELS)
    )
    out = RESULTS_DIR / "index.html"
    out.write_text(
        env.get_template("index.html.j2").render(question_sets=question_sets, track_labels=TRACK_LABELS)
    )
    return out
