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

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .dataset import Question, asked_question, definition_fields
from .run import Run, record_key

TRACK_ORDER = ("data", "navigation", "analysis", "out_of_scope")


def load_run_data(run_id_or_path: str) -> dict:
    return Run.load(run_id_or_path).data


def _repeats(data: dict) -> int | None:
    r = data.get("repeats")
    return r if isinstance(r, int) and not isinstance(r, bool) and r >= 1 else None


def _expected_keys(data: dict) -> dict[str, tuple[dict, str, int]]:
    """The run's planned turns (question × model × repeat), by record key."""
    repeats = _repeats(data) or 0
    models = [m for m in data.get("models") or [] if isinstance(m, str)]
    return {
        record_key(q["id"], model, r): (q, model, r)
        for q in data.get("planned_questions") or []
        for model in models
        for r in range(1, repeats + 1)
    }


def validate_run(data: dict) -> list[str]:
    """Why a run can't be gated on: no positive integer repeats, no models or planned questions, or records
    that aren't one of its planned turns (an out-of-range repeat, another model, an unplanned question)."""
    rid = data.get("run_id", "?")
    problems = []
    if _repeats(data) is None:
        problems.append(f"run {rid}: repeats must be a positive integer, got {data.get('repeats')!r}")
    models = data.get("models")
    if not isinstance(models, list) or not models or not all(isinstance(m, str) and m for m in models):
        problems.append(f"run {rid}: no models recorded")
    if not data.get("planned_questions"):
        problems.append(f"run {rid}: no planned questions")
    expected = _expected_keys(data)
    unexpected = []
    for key, rec in (data.get("records") or {}).items():
        if key not in expected:
            unexpected.append(key)
            continue
        q, model, r = expected[key]
        if (
            rec.get("model") != model
            or rec.get("repeat") != r
            or (rec.get("question") or {}).get("id") != q["id"]
        ):
            unexpected.append(key)
    if unexpected:
        shown = ", ".join(sorted(unexpected)[:5]) + (" …" if len(unexpected) > 5 else "")
        problems.append(f"run {rid}: {len(unexpected)} records aren't planned turns ({shown})")
    return problems


def _turns(data: dict) -> list[dict]:
    """Every planned turn of the run: its record, or a placeholder (failed) when it has none. Records that aren't
    planned turns are left out (and `validate_run` refuses the run)."""
    records = data.get("records") or {}
    turns = []
    for key, (q, model, r) in _expected_keys(data).items():
        rec = records.get(key)
        if rec is not None and rec.get("model") == model and rec.get("repeat") == r:
            turns.append(rec)
        else:
            turns.append({"question": q, "model": model, "repeat": r, "missing": True, "reply": {}})
    return turns


def _fingerprint(value) -> str | None:
    if isinstance(value, dict):
        return value.get("sha256")
    return value


# What must be the same for both runs to be comparable: everything but the database MCP under test (its own
# instructions, tools and version may differ: that is the change being tested).
INVARIANTS = {
    "runner": lambda d: d.get("runner"),
    "target": lambda d: d.get("target"),
    "models": lambda d: d.get("models"),
    "repeats": lambda d: d.get("repeats"),
    "questions file": lambda d: d.get("questions_file"),
    "judge": lambda d: d.get("judge_model"),
    "provider": lambda d: (d.get("api") or {}).get("provider"),
    "max tool rounds": lambda d: (d.get("api") or {}).get("max_tool_rounds"),
    "reasoning effort": lambda d: d.get("reasoning_efforts"),
    "agent prompt": lambda d: (
        (d.get("agent_prompt") or {}).get("sha256"),
        (d.get("agent_prompt") or {}).get("source"),
        _fingerprint((((d.get("api") or {}).get("prompt")) or {}).get("system_prompt")),
    ),
    "navigator MCP": lambda d: (
        d.get("navigator_mcp"),
        _fingerprint(
            ((((d.get("api") or {}).get("prompt")) or {}).get("server_instructions") or {}).get("navigator")
        ),
    ),
}


def _definitions(data: dict, model: str | None) -> dict[int, set[str]]:
    """Per question: every definition it was asked and graded with in this run (planned, each record as asked,
    each grade's snapshot), normalized."""
    out: dict[int, set[str]] = defaultdict(set)

    def add(qid, q):
        out[qid].add(json.dumps(definition_fields(q), sort_keys=True, ensure_ascii=False))

    for q in data.get("planned_questions") or []:
        add(q["id"], q)
    for rec in _turns(data):
        if model and rec.get("model") != model:
            continue
        q = rec["question"]
        add(q["id"], asked_question(rec))
        if graded := (rec.get("grade") or {}).get("graded"):
            add(q["id"], graded)
    return out


def _judges(data: dict, model: str | None) -> set[str]:
    found = {
        (rec.get("grade") or {}).get("judge_model") or data.get("judge_model")
        for rec in _turns(data)
        if rec.get("grade") and (not model or rec.get("model") == model)
    }
    return found or {data.get("judge_model")}


def comparability(baseline: dict, candidate: dict, model: str | None = None) -> list[str]:
    """Why the two runs don't measure the same thing (empty when they do)."""
    problems = []
    for name, get in INVARIANTS.items():
        b, c = get(baseline), get(candidate)
        if b != c:
            problems.append(f"the runs differ in {name} ({b!r} vs {c!r}): not comparable")
    judges = _judges(baseline, model) | _judges(candidate, model)
    if len(judges) != 1:
        problems.append(f"answers were graded by different judges ({', '.join(sorted(map(str, judges)))})")
    bdef, cdef = _definitions(baseline, model), _definitions(candidate, model)
    if set(bdef) != set(cdef):
        problems.append("the runs planned different questions")
    differing = sorted(q for q in set(bdef) & set(cdef) if len(bdef[q] | cdef[q]) != 1)
    if differing:
        problems.append(
            "questions were asked or graded with different text, history or references: "
            + ", ".join(f"Q{q}" for q in differing[:10])
            + (" …" if len(differing) > 10 else "")
        )
    return problems


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
    problems = validate_run(baseline) + validate_run(candidate) + comparability(baseline, candidate, model)
    base, cand = run_metrics(baseline, model), run_metrics(candidate, model)
    for side, m in (("baseline", base), ("candidate", cand)):
        graded = m.eligible - m.failed_requests - m.ungraded
        if not m.eligible:
            problems.append(f"the {side} run has no turns of a question with a reference")
        elif graded * 2 < m.eligible:
            # Most turns failed or went ungraded: the infrastructure (model API, judge, server) broke, and two
            # broken runs would compare equal.
            problems.append(
                f"the {side} run graded only {graded} of {m.eligible} turns: too few to compare (failed requests "
                f"{m.failed_requests}, ungraded {m.ungraded})"
            )
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
