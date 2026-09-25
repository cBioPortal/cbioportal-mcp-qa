import asyncio
from dataclasses import asdict
from pathlib import Path

import click

from .agent import AgentClient
from .agent_prompt import fetch_agent_prompt, prompt_fingerprint
from .claude_code import ClaudeCodeClient, find_connector
from .config import MODELS, TARGETS, load_settings
from .dataset import DEFAULT_QUESTIONS, load_questions, parse_selection
from .grade import Judge
from .report import write_index, write_report
from .run import (
    Run,
    attach_traces,
    collect_answers,
    grade_answers,
    render_navigation_links,
    wait_for_ingestion,
)
from .traces import Langfuse
from .versions import collect as collect_versions

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


RUNNERS = ["agents-api", "claude-code"]
runner_option = click.option(
    "--runner",
    type=click.Choice(RUNNERS),
    default="agents-api",
    show_default=True,
    help="agents-api: the deployed agent through LibreChat. claude-code: headless Claude Code with the "
    "deployed agent's prompt and the same MCP servers (runs on the Claude subscription).",
)


def _agent_prompt(settings, target: str) -> dict:
    try:
        return fetch_agent_prompt(TARGETS[target].agent_id, settings.kube_context)
    except Exception as exc:
        raise click.ClickException(f"could not read the {target} agent's prompt via kubectl: {exc}") from exc


def _database_connector(settings) -> str | None:
    """How the claude-code runner reaches the database MCP: an explicitly named claude.ai connector, else a
    DATABASE_MCP_URL (e.g. a port-forward), else the claude.ai connector pointing at DATABASE_CONNECTOR_URL."""
    if settings.database_connector or settings.database_mcp_url:
        return settings.database_connector
    connector = find_connector(settings.database_connector_url)
    if connector is None:
        raise click.ClickException(
            f"no claude.ai connector points at {settings.database_connector_url}; add it in claude.ai, set "
            "CLAUDE_AI_DATABASE_CONNECTOR to its name, or set DATABASE_MCP_URL (e.g. a port-forward)"
        )
    return connector


def _client(
    settings, target: str, runner: str, prompt: str | None = None, transcript_dir: Path | None = None
):
    if runner == "claude-code":
        try:
            return ClaudeCodeClient(
                prompt or _agent_prompt(settings, target)["instructions"],
                settings.database_mcp_url,
                settings.navigator_mcp_url,
                database_connector=_database_connector(settings),
                transcript_dir=transcript_dir,
            )
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
    return AgentClient(TARGETS[target], settings.api_key)


def _judge(settings) -> Judge:
    return Judge(settings.judge_model, settings.aws_region, settings.aws_profile)


@click.group()
def cli() -> None:
    """Benchmark cBioPortalChat by asking the deployed agent the questions in input/questions.yaml."""


@cli.command()
@click.argument("question")
@click.option("--target", type=click.Choice(list(TARGETS)), default="beta", show_default=True)
@click.option("--model", type=click.Choice(MODEL_CHOICES), default="haiku", show_default=True)
@runner_option
def ask(question: str, target: str, model: str, runner: str) -> None:
    """Ask the deployed agent a single question."""
    settings = load_settings()

    async def go():
        client = _client(settings, target, runner)
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
@click.option(
    "--render/--no-render",
    default=True,
    show_default=True,
    help="Open navigation answers' links in Chromium.",
)
@runner_option
def run(
    target, models_arg, selection, questions_file, repeats, concurrency, resume, no_grade, render, runner
) -> None:
    """Ask every selected question with each model, attach traces, grade, and write the report."""
    settings = load_settings()
    questions = parse_selection(selection, load_questions(questions_file))
    if not questions:
        raise click.UsageError("no questions selected")
    if resume:
        bench = Run.load(resume)
        target = bench.data["target"]
        runner = bench.data.get("runner", "agents-api")
    agent = None
    if runner == "claude-code" or not resume:
        try:
            agent = fetch_agent_prompt(TARGETS[target].agent_id, settings.kube_context)
        except Exception as exc:  # noqa: BLE001 - only the claude-code runner needs the prompt itself
            if runner == "claude-code":
                raise click.ClickException(
                    f"could not read the {target} agent's prompt via kubectl: {exc}"
                ) from exc
            agent_error = f"{type(exc).__name__}: {exc}"[:200]
    prompt = agent["instructions"] if agent and runner == "claude-code" else None
    if resume:
        recorded = (bench.data.get("agent_prompt") or {}).get("sha256")
        if prompt and recorded and prompt_fingerprint(prompt)["sha256"] != recorded:
            click.echo("Warning: the agent's prompt changed since this run started", err=True)
    else:
        prompt_info = {"agent_id": TARGETS[target].agent_id, "target": target}
        if agent:
            prompt_info |= prompt_fingerprint(agent["instructions"]) | {
                "agent_updated_at": agent.get("updated_at")
            }
        else:
            prompt_info["error"] = agent_error
        extra = {"agent_prompt": prompt_info, "versions": collect_versions(settings, runner, target)}
        if runner == "claude-code":
            extra["database_mcp"] = _database_connector(settings) or settings.database_mcp_url
            extra["navigator_mcp"] = settings.navigator_mcp_url
        bench = Run.create(
            target, _models(models_arg), repeats, settings.judge_model, str(questions_file), runner, extra
        )
        if agent:
            # A record of the prompt this run tested (the benchmark itself always reads the live agent).
            (bench.dir / "agent-prompt.md").write_text(agent["instructions"])
    click.echo(
        f"Run {bench.data['run_id']} ({runner}): {len(questions)} questions × {bench.data['models']} × "
        f"{bench.data['repeats']} against {TARGETS[target].agent_id} ({target})"
    )

    client = _client(settings, target, runner, prompt, bench.dir / "transcripts")

    async def go():
        try:
            await collect_answers(bench, questions, client, concurrency)
        finally:
            await client.aclose()

    asyncio.run(go())
    if getattr(client, "signin_expired", False):
        raise click.ClickException(
            f"{client.signin_message()}: authenticate it (claude.ai → Settings → Connectors, or `/mcp` in "
            f"`claude` with the same CLAUDE_CONFIG_DIR), then continue with "
            f"`cbioportal-mcp-qa run --resume {bench.data['run_id']}`. Stopped before grading."
        )
    if getattr(client, "usage_limit", None):
        raise click.ClickException(
            f"Claude subscription limit: {client.usage_limit}. Once it resets, continue with "
            f"`cbioportal-mcp-qa run --resume {bench.data['run_id']}` (same CLAUDE_CONFIG_DIR). "
            f"Stopped before grading."
        )
    if runner == "agents-api":
        wait_for_ingestion()
        click.echo(f"Attached {attach_traces(bench, _langfuse(settings))} traces")
    if render:
        click.echo(f"Rendered {render_navigation_links(bench, settings.chromium_path)} navigation links")
    if not no_grade:
        grade_answers(bench, _judge(settings))
    click.echo(f"Report: {write_report(bench)}")


@cli.command("render")
@click.argument("run_id")
@click.option("--concurrency", type=int, default=3, show_default=True)
def render_cmd(run_id: str, concurrency: int) -> None:
    """Open the cBioPortal links in navigation answers and record what each page shows (then regrade them)."""
    bench = Run.load(run_id)
    click.echo(f"Rendered {render_navigation_links(bench, load_settings().chromium_path, concurrency)} links")
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
