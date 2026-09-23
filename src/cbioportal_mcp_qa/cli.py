import asyncio
from dataclasses import asdict
from pathlib import Path

import click

from .agent import AgentClient
from .config import MODELS, TARGETS, load_settings
from .dataset import DEFAULT_QUESTIONS, load_questions, parse_selection
from .grade import Judge
from .report import write_index, write_report
from .run import Run, attach_traces, collect_answers, grade_answers, wait_for_ingestion
from .traces import Langfuse

MODEL_CHOICES = [k for k in MODELS if k in TARGETS["beta"].specs]


def _models(value: str) -> list[str]:
    models = [m.strip() for m in value.split(",") if m.strip()]
    unknown = [m for m in models if m not in MODEL_CHOICES]
    if unknown:
        raise click.BadParameter(f"unknown model(s) {unknown}; choose from {MODEL_CHOICES}")
    return models


def _langfuse(settings) -> Langfuse:
    langfuse = Langfuse(settings.langfuse_host, settings.langfuse_public_key, settings.langfuse_secret_key)
    if not langfuse.enabled:
        click.echo("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set: skipping tool-call stats", err=True)
    return langfuse


def _judge(settings) -> Judge:
    return Judge(settings.judge_model, settings.aws_region, settings.aws_profile)


@click.group()
def cli() -> None:
    """Benchmark cBioPortalChat by asking the deployed agent the questions in input/questions.yaml."""


@cli.command()
@click.argument("question")
@click.option("--target", type=click.Choice(list(TARGETS)), default="beta", show_default=True)
@click.option("--model", type=click.Choice(MODEL_CHOICES), default="haiku", show_default=True)
def ask(question: str, target: str, model: str) -> None:
    """Ask the deployed agent a single question."""
    settings = load_settings()

    async def go():
        client = AgentClient(TARGETS[target], settings.api_key)
        try:
            return await client.ask(question, model)
        finally:
            await client.aclose()

    reply = asyncio.run(go())
    if reply.error:
        raise click.ClickException(f"{reply.status}: {reply.error}")
    click.echo(reply.answer)
    click.echo(
        f"\n--- {reply.latency_s:.0f}s · prompt {reply.prompt_tokens} (cache read {reply.cache_read_tokens}, "
        f"write {reply.cache_write_tokens}) · completion {reply.completion_tokens} · id {reply.response_id}",
        err=True,
    )


@cli.command()
@click.option("--target", type=click.Choice(list(TARGETS)), default="beta", show_default=True)
@click.option("--models", "models_arg", default="haiku,sonnet", show_default=True, help="Comma-separated.")
@click.option("--questions", "selection", default=None, help='Question ids, e.g. "1-10,15". Default: all.')
@click.option(
    "--questions-file",
    type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_QUESTIONS,
    show_default=True,
)
@click.option(
    "--repeats", type=int, default=1, show_default=True, help="Times to ask each question per model."
)
@click.option("--concurrency", type=int, default=2, show_default=True, help="Parallel requests to the agent.")
@click.option("--resume", default=None, help="Run id to continue (re-asks only missing/failed answers).")
@click.option("--no-grade", is_flag=True, help="Only collect answers and traces.")
def run(target, models_arg, selection, questions_file, repeats, concurrency, resume, no_grade) -> None:
    """Ask every selected question with each model, attach traces, grade, and write the report."""
    settings = load_settings()
    questions = parse_selection(selection, load_questions(questions_file))
    if not questions:
        raise click.UsageError("no questions selected")
    if resume:
        bench = Run.load(resume)
        target = bench.data["target"]
    else:
        bench = Run.create(target, _models(models_arg), repeats, settings.judge_model, str(questions_file))
    click.echo(
        f"Run {bench.data['run_id']}: {len(questions)} questions × {bench.data['models']} × "
        f"{bench.data['repeats']} on {TARGETS[target].url}"
    )

    async def go():
        client = AgentClient(TARGETS[target], settings.api_key)
        try:
            await collect_answers(bench, questions, client, concurrency)
        finally:
            await client.aclose()

    asyncio.run(go())
    wait_for_ingestion()
    click.echo(f"Attached {attach_traces(bench, _langfuse(settings))} traces")
    if not no_grade:
        grade_answers(bench, _judge(settings))
    click.echo(f"Report: {write_report(bench)}")


@cli.command()
@click.argument("run_id")
def traces(run_id: str) -> None:
    """Attach Langfuse stats to answers that don't have them yet (e.g. after ingestion lag)."""
    bench = Run.load(run_id)
    click.echo(f"Attached {attach_traces(bench, _langfuse(load_settings()))} traces")
    click.echo(f"Report: {write_report(bench)}")


@cli.command()
@click.argument("run_id")
@click.option("--regrade", is_flag=True, help="Discard existing grades first.")
@click.option(
    "--refresh-questions",
    is_flag=True,
    help="Replace the run's copy of each question with the current questions file (implies --regrade).",
)
def grade(run_id: str, regrade: bool, refresh_questions: bool) -> None:
    """Grade answers that don't have a grade yet."""
    bench = Run.load(run_id)
    if refresh_questions:
        current = {q.id: asdict(q) for q in load_questions(Path(bench.data["questions_file"]))}
        for rec in bench.records.values():
            rec["question"] = current.get(rec["question"]["id"], rec["question"])
    if regrade or refresh_questions:
        for rec in bench.records.values():
            rec.pop("grade", None)
    grade_answers(bench, _judge(load_settings()))
    click.echo(f"Report: {write_report(bench)}")


@cli.command()
@click.argument("run_id", required=False)
def report(run_id: str | None) -> None:
    """Re-render a run's report (or just the results index when no run id is given)."""
    click.echo(write_report(Run.load(run_id)) if run_id else write_index())
