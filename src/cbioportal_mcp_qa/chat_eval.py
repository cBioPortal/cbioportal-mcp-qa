"""The CI gate: did a candidate MCP server make the chat agent's answers worse than the baseline server did?

Both runs answer the same questions with the same model, prompt, judge and database, against two MCP servers
(the PR's image and the released one). A turn is one question × repeat. Pass rate = passed turns / eligible
turns, where eligible turns are every turn of a question with a reference, and a failed request, a missing turn or
an answer the judge left ungraded counts as not passed (fail closed). Questions without a reference are ignored.

The gate fails when
- the candidate's pass rate is more than `max_pass_drop` percentage points below the baseline's;
- the candidate's tool errors (MCP tool calls that returned an error) exceed the baseline's by more than
  `max_tool_error_increase`;
- the candidate's answers link to more distinct nonexistent study ids (a hallucination signal) than the
  baseline's, by more than `max_invalid_study_increase`.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .dataset import Question
from .run import Run, record_key

TRACK_ORDER = ("data", "navigation", "analysis", "out_of_scope")


def load_run_data(run_id_or_path: str) -> dict:
    return Run.load(run_id_or_path).data


def _turns(data: dict) -> list[dict]:
    """Every planned turn of the run: its record, or a placeholder (failed) when it has none."""
    records = data.get("records") or {}
    planned = {q["id"]: q for q in data.get("planned_questions") or []}
    turns = list(records.values())
    for qid, q in planned.items():
        for model in data.get("models") or []:
            for r in range(1, (data.get("repeats") or 1) + 1):
                if record_key(qid, model, r) not in records:
                    turns.append({"question": q, "model": model, "repeat": r, "missing": True, "reply": {}})
    return turns


def _has_reference(q: dict) -> bool:
    try:
        return Question.from_dict(q).has_reference
    except (KeyError, TypeError, ValueError):
        return bool(q.get("expected_answer") or q.get("expected_links") or q.get("notes"))


@dataclass
class RunMetrics:
    run_id: str
    eligible: int = 0
    passes: int = 0
    failed_requests: int = 0
    ungraded: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    invalid_study_ids: set[str] = field(default_factory=set)
    invalid_study_answers: int = 0
    by_track: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    by_repeat: dict[int, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    # question id -> [passes, eligible turns]
    by_question: dict[int, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    questions: dict[int, dict] = field(default_factory=dict)
    rationales: dict[int, list[str]] = field(default_factory=lambda: defaultdict(list))
    tool_errors_by_tool: Counter = field(default_factory=Counter)

    @property
    def pass_rate(self) -> float | None:
        return 100.0 * self.passes / self.eligible if self.eligible else None

    def track_rate(self, track: str) -> float | None:
        p, n = self.by_track.get(track, (0, 0))
        return 100.0 * p / n if n else None


def run_metrics(data: dict, model: str | None = None) -> RunMetrics:
    """Pass rate (overall, per track, per repeat, per question), tool errors and invalid study ids of one run."""
    m = RunMetrics(data.get("run_id", "?"))
    for rec in _turns(data):
        if model and rec.get("model") != model:
            continue
        q = rec["question"]
        reply = rec.get("reply") or {}
        answered = reply.get("status") == 200
        for call in (rec.get("trace") or {}).get("tool_calls") or []:
            m.tool_calls += 1
            if not call.get("ok", True):
                m.tool_errors += 1
                m.tool_errors_by_tool[call.get("name") or "?"] += 1
        grade = rec.get("grade") or {}
        if bad := grade.get("invalid_studies"):
            m.invalid_study_ids.update(bad)
            m.invalid_study_answers += 1
        if not _has_reference(q):
            continue
        passed = bool(answered and grade.get("passed") is True)
        if not answered:
            m.failed_requests += 1
        elif grade.get("passed") is None:
            m.ungraded += 1
        m.eligible += 1
        m.passes += passed
        track = q.get("track") or "data"
        for bucket in (m.by_track[track], m.by_repeat[rec.get("repeat", 1)], m.by_question[q["id"]]):
            bucket[0] += passed
            bucket[1] += 1
        m.questions.setdefault(q["id"], q)
        if not passed:
            why = (
                grade.get("rationale")
                or reply.get("error")
                or (
                    "not asked"
                    if rec.get("missing")
                    else "ungraded"
                    if answered and grade.get("passed") is None
                    else "failed"
                )
            )
            m.rationales[q["id"]].append(str(why))
    return m


@dataclass
class Check:
    name: str
    baseline: float | None
    candidate: float | None
    limit: str
    ok: bool


@dataclass
class Verdict:
    baseline: RunMetrics
    candidate: RunMetrics
    checks: list[Check]
    regressions: list[dict]
    improvements: list[dict]
    problems: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems and all(c.ok for c in self.checks)


def _question_deltas(base: RunMetrics, cand: RunMetrics) -> tuple[list[dict], list[dict]]:
    """Questions both runs graded whose pass share went down (regressions) or up, largest change first."""
    down, up = [], []
    for qid in sorted(set(base.by_question) & set(cand.by_question)):
        bp, bn = base.by_question[qid]
        cp, cn = cand.by_question[qid]
        delta = cp / cn - bp / bn
        if delta == 0:
            continue
        q = cand.questions.get(qid) or base.questions.get(qid) or {}
        row = {
            "id": qid,
            "track": q.get("track") or "data",
            "question": q.get("question", ""),
            "baseline": f"{bp}/{bn}",
            "candidate": f"{cp}/{cn}",
            "delta": delta,
            "why": (cand.rationales.get(qid) or [""])[0],
        }
        (down if delta < 0 else up).append(row)
    down.sort(key=lambda r: (r["delta"], r["id"]))
    up.sort(key=lambda r: (-r["delta"], r["id"]))
    return down, up


def evaluate(
    baseline: dict,
    candidate: dict,
    max_pass_drop: float = 10.0,
    max_tool_error_increase: int = 8,
    max_invalid_study_increase: int = 1,
    model: str | None = None,
) -> Verdict:
    """Compare a candidate run against the baseline run and decide whether the candidate regressed."""
    problems = []
    for key in ("judge_model", "questions_file", "repeats", "models"):
        if baseline.get(key) != candidate.get(key):
            problems.append(
                f"the runs differ in {key} ({baseline.get(key)!r} vs {candidate.get(key)!r}): not comparable"
            )
    base, cand = run_metrics(baseline, model), run_metrics(candidate, model)
    if not base.eligible or not cand.eligible:
        problems.append("a run has no graded turns with a reference")
    if set(base.by_question) != set(cand.by_question):
        problems.append("the runs asked different questions")
    checks = []
    if base.pass_rate is not None and cand.pass_rate is not None:
        drop = base.pass_rate - cand.pass_rate
        checks.append(
            Check(
                "Pass rate (%)",
                base.pass_rate,
                cand.pass_rate,
                f"drop ≤ {max_pass_drop:g} pts",
                drop <= max_pass_drop,
            )
        )
    checks.append(
        Check(
            "Tool errors",
            base.tool_errors,
            cand.tool_errors,
            f"increase ≤ {max_tool_error_increase}",
            cand.tool_errors - base.tool_errors <= max_tool_error_increase,
        )
    )
    checks.append(
        Check(
            "Nonexistent study ids linked",
            len(base.invalid_study_ids),
            len(cand.invalid_study_ids),
            f"increase ≤ {max_invalid_study_increase}",
            len(cand.invalid_study_ids) - len(base.invalid_study_ids) <= max_invalid_study_increase,
        )
    )
    down, up = _question_deltas(base, cand)
    return Verdict(base, cand, checks, down, up, problems)


def _fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "–"
    if pct:
        return f"{value:.1f}%"
    return f"{value:g}"


def _cell(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(v: Verdict, title: str = "Chat behavioral eval") -> str:
    b, c = v.baseline, v.candidate
    lines = [f"## {title}: {'✅ pass' if v.ok else '❌ regression'}", ""]
    lines += [f"Baseline run `{b.run_id}` vs candidate run `{c.run_id}`.", ""]
    for p in v.problems:
        lines.append(f"> ⚠️ {p}")
    if v.problems:
        lines.append("")
    lines += ["| Check | Baseline | Candidate | Limit | |", "|---|---|---|---|---|"]
    for ch in v.checks:
        pct = ch.name.startswith("Pass rate")
        lines.append(
            f"| {ch.name} | {_fmt(ch.baseline, pct)} | {_fmt(ch.candidate, pct)} | {ch.limit} | {'✅' if ch.ok else '❌'} |"
        )
    lines += [
        "",
        f"Turns graded: baseline {b.passes}/{b.eligible} passed ({b.failed_requests} failed requests, {b.ungraded} "
        f"ungraded); candidate {c.passes}/{c.eligible} passed ({c.failed_requests} failed requests, {c.ungraded} "
        "ungraded). Failed and ungraded turns count as not passed.",
        "",
        "### Pass rate by track",
        "",
        "| Track | Baseline | Candidate | Δ pts |",
        "|---|---|---|---|",
    ]
    tracks = [t for t in TRACK_ORDER if t in b.by_track or t in c.by_track]
    tracks += sorted((set(b.by_track) | set(c.by_track)) - set(tracks))
    for t in tracks:
        br, cr = b.track_rate(t), c.track_rate(t)
        delta = f"{cr - br:+.1f}" if br is not None and cr is not None else "–"
        bn, cn = b.by_track.get(t, (0, 0)), c.by_track.get(t, (0, 0))
        lines.append(
            f"| {t} | {_fmt(br, True)} ({bn[0]}/{bn[1]}) | {_fmt(cr, True)} ({cn[0]}/{cn[1]}) | {delta} |"
        )
    repeats = sorted(set(b.by_repeat) | set(c.by_repeat))
    if len(repeats) > 1:
        lines += ["", "### Pass rate by repeat", "", "| Repeat | Baseline | Candidate |", "|---|---|---|"]
        for r in repeats:
            bp, bn = b.by_repeat.get(r, (0, 0))
            cp, cn = c.by_repeat.get(r, (0, 0))
            lines.append(
                f"| {r} | {_fmt(100 * bp / bn if bn else None, True)} | {_fmt(100 * cp / cn if cn else None, True)} |"
            )
    lines += ["", f"### Per-question regressions ({len(v.regressions)})", ""]
    if v.regressions:
        lines += [
            "| Q | Track | Baseline | Candidate | Question | Why the candidate failed |",
            "|---|---|---|---|---|---|",
        ]
        for r in v.regressions:
            lines.append(
                f"| {r['id']} | {r['track']} | {r['baseline']} | {r['candidate']} | {_cell(r['question'], 90)} | "
                f"{_cell(r['why'])} |"
            )
    else:
        lines.append("None.")
    if v.improvements:
        lines += ["", f"<details><summary>Per-question improvements ({len(v.improvements)})</summary>", ""]
        lines += ["| Q | Track | Baseline | Candidate | Question |", "|---|---|---|---|---|"]
        for r in v.improvements:
            lines.append(
                f"| {r['id']} | {r['track']} | {r['baseline']} | {r['candidate']} | {_cell(r['question'], 90)} |"
            )
        lines += ["", "</details>"]
    new_ids = sorted(c.invalid_study_ids - b.invalid_study_ids)
    if new_ids:
        lines += [
            "",
            f"Nonexistent study ids only the candidate linked: {', '.join(f'`{i}`' for i in new_ids)}",
        ]
    if c.tool_errors_by_tool or b.tool_errors_by_tool:
        tools = sorted(set(c.tool_errors_by_tool) | set(b.tool_errors_by_tool))
        lines += [
            "",
            "<details><summary>Tool errors by tool</summary>",
            "",
            "| Tool | Baseline | Candidate |",
            "|---|---|---|",
        ]
        for t in tools:
            lines.append(f"| `{t}` | {b.tool_errors_by_tool[t]} | {c.tool_errors_by_tool[t]} |")
        lines += ["", "</details>"]
    lines += [
        "",
        "LLM answers vary between runs: a small difference is noise. Each question was asked "
        f"{max(repeats) if repeats else 1}× per server; the thresholds are inputs of the workflow.",
        "",
    ]
    return "\n".join(lines)


def verdict_json(v: Verdict) -> dict:
    def side(m: RunMetrics) -> dict:
        return {
            "run_id": m.run_id,
            "pass_rate": m.pass_rate,
            "passes": m.passes,
            "eligible": m.eligible,
            "failed_requests": m.failed_requests,
            "ungraded": m.ungraded,
            "tool_calls": m.tool_calls,
            "tool_errors": m.tool_errors,
            "invalid_study_ids": sorted(m.invalid_study_ids),
            "by_track": {
                t: {"passes": p, "eligible": n, "rate": m.track_rate(t)} for t, (p, n) in m.by_track.items()
            },
        }

    return {
        "ok": v.ok,
        "problems": v.problems,
        "checks": [c.__dict__ for c in v.checks],
        "baseline": side(v.baseline),
        "candidate": side(v.candidate),
        "regressions": v.regressions,
        "improvements": v.improvements,
    }
