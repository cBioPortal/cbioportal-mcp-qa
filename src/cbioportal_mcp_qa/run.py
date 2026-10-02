"""A benchmark run: answers, trace stats and grades for (question, model, repeat), stored as run.json."""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from tqdm import tqdm

from .agent import AgentClient
from .claude_code import ClaudeCodeClient
from .dataset import DEFINITION_FIELDS, Question, asked_question
from .grade import BaseJudge, JudgeOutputError, StudyValidator, cbio_links, tool_log
from .persist import write_json
from .render import render_links
from .traces import Langfuse

RESULTS_DIR = Path("results")


def record_key(question_id: int, model: str, repeat: int) -> str:
    return f"{question_id}:{model}:{repeat}"


class Run:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data
        # Put back the text and history a legacy refresh moved to `asked`, so grading and snapshots use them.
        for rec in data.get("records", {}).values():
            if "asked" in rec:
                rec["question"] = asked_question(rec)
                del rec["asked"]

    @classmethod
    def create(
        cls,
        target: str,
        models: list[str],
        repeats: int,
        judge_model: str,
        questions_file: str,
        runner: str = "agents-api",
        extra: dict | None = None,
    ) -> "Run":
        run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M")
        path = RESULTS_DIR / run_id / "run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "run_id": run_id,
            "target": target,
            "runner": runner,
            "models": models,
            "repeats": repeats,
            "judge_model": judge_model,
            "questions_file": questions_file,
            "created_at": datetime.now(UTC).isoformat(),
            **(extra or {}),
            "records": {},
        }
        run = cls(path, data)
        run.save()
        return run

    @classmethod
    def load(cls, run_id_or_path: str) -> "Run":
        path = Path(run_id_or_path)
        if path.is_dir():
            path = path / "run.json"
        elif not path.exists():
            path = RESULTS_DIR / run_id_or_path / "run.json"
        return cls(path, json.loads(path.read_text()))

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def records(self) -> dict[str, dict]:
        return self.data["records"]

    def save(self) -> None:
        write_json(self.path, self.data, indent=1)


async def collect_answers(
    run: Run,
    questions: list[Question],
    client: "AgentClient | ClaudeCodeClient",
    concurrency: int,
) -> int:
    """Ask the questions without an answer yet (status 200). Returns how many were left unasked by a stop.

    A stop (the claude-code client's `stop_reason`: the subscription's usage limit, per-token billing, a plugin,
    an expired connector login) ends the batch: answers in flight finish and are saved, no queued answer starts a
    session, and neither those nor the reply that is the stop get a record, so `--resume` asks exactly them."""
    todo = [
        (q, model, r)
        for q in questions
        for r in range(1, run.data["repeats"] + 1)
        for model in run.data["models"]
        if (run.records.get(record_key(q.id, model, r)) or {}).get("reply", {}).get("status") != 200
    ]
    sem = asyncio.Semaphore(concurrency)
    bar = tqdm(total=len(todo), desc="answers", unit="ans")
    stop_reason = getattr(client, "stop_reason", lambda: None)  # only the claude-code client stops
    unasked = 0

    async def one(q: Question, model: str, repeat: int) -> None:
        nonlocal unasked
        async with sem:
            if stop_reason():
                unasked += 1
                return
            reply = await client.ask(q.question, model, q.history)
        if stop_reason() and client.is_stop(reply):
            unasked += 1
            return
        rec = {"question": asdict(q), "model": model, "repeat": repeat, "reply": asdict(reply)}
        if trace := rec["reply"].pop("trace"):
            rec["trace"] = trace
        run.records[record_key(q.id, model, repeat)] = rec
        run.save()
        bar.update(1)
        if reply.error:
            bar.write(f"[{model}] Q{q.id} failed: {reply.status} {reply.error[:200]}")

    await asyncio.gather(*(one(*item) for item in todo))
    if unasked:
        bar.write(f"Stopped: {stop_reason()[:200]}. {unasked} answers left unasked (not recorded).")
    bar.close()
    return unasked


def attach_traces(run: Run, langfuse: Langfuse) -> int:
    """Attach Langfuse stats to answered records that don't have them yet. Returns the number attached."""
    pending = [
        rec for rec in run.records.values() if rec["reply"].get("response_id") and not rec.get("trace")
    ]
    if not pending or not langfuse.enabled:
        return 0
    start = min(r["reply"]["started_at"] for r in pending)
    end = max(r["reply"]["started_at"] + r["reply"]["latency_s"] for r in pending)
    by_message = langfuse.trace_ids_by_message(start, end)
    attached = 0
    for rec in tqdm(pending, desc="traces", unit="trace"):
        trace_id = by_message.get(rec["reply"]["response_id"])
        if trace_id:
            rec["trace"] = langfuse.stats(trace_id).to_dict()
            attached += 1
            if attached % 10 == 0:
                run.save()
    run.save()
    return attached


def grade_answers(run: Run, judge: BaseJudge, concurrency: int = 1) -> None:
    """Grade answers without a grade. Each grade records its judge model and a snapshot of the question it was
    graded against (`graded`), so `compare` checks what was actually graded.

    A verdict the judge got wrong twice (invalid JSON, not the schema) leaves the answer ungraded, with
    `judge_error` saying why; the next `grade` tries it again. A JudgeStopped (e.g. the subscription's usage
    limit) stops grading: the grades so far are saved and it is raised once the answers in flight finish."""
    # Grades from before per-turn judges were all made by the run's judge.
    for rec in run.records.values():
        if rec.get("grade") and "judge_model" not in rec["grade"]:
            rec["grade"]["judge_model"] = run.data.get("judge_model")
    studies = StudyValidator()
    pending = [
        rec for rec in run.records.values() if rec["reply"].get("status") == 200 and not rec.get("grade")
    ]
    lock = threading.Lock()
    # The first JudgeStopped or unexpected error (e.g. Bedrock credentials) stops the answers not started yet.
    stopped: list[Exception] = []
    bar = tqdm(total=len(pending), desc="grading", unit="ans")

    def one(rec: dict) -> None:
        if stopped:
            return
        q = Question.from_dict(rec["question"])
        try:
            grade = judge.grade(
                q, rec["reply"]["answer"], studies, run.data.get("renders", {}), tool_log(rec, run.dir)
            ).to_dict()
        except JudgeOutputError as exc:
            with lock:
                rec["judge_error"] = {"judge_model": judge.model, "error": str(exc)}
                run.save()
                bar.update(1)
                bar.write(f"[{rec['model']}] Q{q.id} left ungraded: {str(exc)[:200]}")
            return
        except Exception as exc:  # noqa: BLE001 - re-raised after the answers in flight
            stopped.append(exc)
            return
        with lock:
            rec.pop("judge_error", None)
            rec["grade"] = grade | {
                "judge_model": judge.model,
                "graded": {f: rec["question"].get(f) for f in DEFINITION_FIELDS},
            }
            record_judges(run)
            run.save()
            bar.update(1)

    try:
        with ThreadPoolExecutor(max(1, concurrency)) as pool:
            list(pool.map(one, pending))
    finally:
        bar.close()
        record_judges(run)
        run.save()
    if stopped:
        raise stopped[0]


def record_judges(run: Run) -> None:
    """`judge_models`: every judge model the run's grades used. `judge_model` becomes that judge when there is
    exactly one (e.g. after regrading everything with another judge); with several it stays as it was, and
    `judge_models` shows the mix."""
    used = sorted(
        {g["judge_model"] for r in run.records.values() if (g := r.get("grade")) and g.get("judge_model")}
    )
    if used:
        run.data["judge_models"] = used
        if len(used) == 1:
            run.data["judge_model"] = used[0]


def render_navigation_links(
    run: Run, executable: str | None, concurrency: int = 3, screenshots: bool = True
) -> int:
    """Open the cBioPortal links in navigation answers, and group comparison links in any answer (their session ids
    can't be decoded), and record what each page shows. Returns the number rendered."""
    renders = run.data.setdefault("renders", {})
    urls = sorted(
        {
            url
            for rec in run.records.values()
            if rec["reply"].get("status") == 200
            for url in cbio_links(rec["reply"]["answer"])
            if rec["question"].get("track") == "navigation" or "/comparison" in url
        }
        - renders.keys()
    )
    if not urls:
        return 0
    results = asyncio.run(
        render_links(urls, run.dir / "shots", "shots", executable, concurrency, screenshots)
    )
    renders.update({url: r.to_dict() for url, r in results.items()})
    run.save()
    return len(results)


def wait_for_ingestion(seconds: int = 60) -> None:
    """Langfuse ingests asynchronously; give the last traces time to land."""
    time.sleep(seconds)
