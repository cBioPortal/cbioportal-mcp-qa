"""A benchmark run: answers, trace stats and grades for (question, model, repeat), stored as run.json."""

import asyncio
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from tqdm import tqdm

from .agent import AgentClient
from .claude_code import ClaudeCodeClient
from .dataset import Question
from .grade import Judge, StudyValidator, cbio_links
from .render import render_links
from .traces import Langfuse

RESULTS_DIR = Path("results")


def record_key(question_id: int, model: str, repeat: int) -> str:
    return f"{question_id}:{model}:{repeat}"


class Run:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

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
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)


async def collect_answers(
    run: Run,
    questions: list[Question],
    client: "AgentClient | ClaudeCodeClient",
    concurrency: int,
) -> None:
    todo = [
        (q, model, r)
        for q in questions
        for r in range(1, run.data["repeats"] + 1)
        for model in run.data["models"]
        if (run.records.get(record_key(q.id, model, r)) or {}).get("reply", {}).get("status") != 200
    ]
    sem = asyncio.Semaphore(concurrency)
    bar = tqdm(total=len(todo), desc="answers", unit="ans")

    async def one(q: Question, model: str, repeat: int) -> None:
        async with sem:
            reply = await client.ask(q.question, model, q.history)
        rec = {"question": asdict(q), "model": model, "repeat": repeat, "reply": asdict(reply)}
        if trace := rec["reply"].pop("trace"):
            rec["trace"] = trace
        run.records[record_key(q.id, model, repeat)] = rec
        run.save()
        bar.update(1)
        if reply.error:
            bar.write(f"[{model}] Q{q.id} failed: {reply.status} {reply.error[:200]}")

    await asyncio.gather(*(one(*item) for item in todo))
    bar.close()


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


def grade_answers(run: Run, judge: Judge) -> None:
    studies = StudyValidator()
    pending = [
        rec for rec in run.records.values() if rec["reply"].get("status") == 200 and not rec.get("grade")
    ]
    for rec in tqdm(pending, desc="grading", unit="ans"):
        q = Question.from_dict(rec["question"])
        rec["grade"] = judge.grade(q, rec["reply"]["answer"], studies, run.data.get("renders", {})).to_dict()
        run.save()


def render_navigation_links(run: Run, executable: str | None, concurrency: int = 3) -> int:
    """Open the cBioPortal links in navigation answers and record what each page shows. Returns the number rendered."""
    renders = run.data.setdefault("renders", {})
    urls = sorted(
        {
            url
            for rec in run.records.values()
            if rec["question"].get("track") == "navigation" and rec["reply"].get("status") == 200
            for url in cbio_links(rec["reply"]["answer"])
        }
        - renders.keys()
    )
    if not urls:
        return 0
    results = asyncio.run(render_links(urls, run.dir / "shots", "shots", executable, concurrency))
    renders.update({url: r.to_dict() for url, r in results.items()})
    run.save()
    return len(results)


def wait_for_ingestion(seconds: int = 60) -> None:
    """Langfuse ingests asynchronously; give the last traces time to land."""
    time.sleep(seconds)
