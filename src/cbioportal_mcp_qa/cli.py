import asyncio
from dataclasses import asdict
from pathlib import Path

import click

from .agent import AgentClient
from .agent_prompt import describe_agents, fetch_agent_prompt, prompt_fingerprint
from .claude_code import ClaudeCodeClient, find_connector, prompt_parity
from .claude_judge import ClaudeCodeJudge
from .compare import compare as compare_runs
from .compare import write_compare
from .config import MODELS, TARGETS, load_settings
from .dataset import (
    ASKED_FIELDS,
    DEFAULT_QUESTIONS,
    REFERENCE_FIELDS,
    definition_fields,
    load_questions,
    parse_selection,
)
from .grade import BaseJudge, Judge, JudgeStopped
from .persist import write_text
from .redact import describe_error, redact
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
from .versions import database_mcp_env

MODEL_CHOICES = [k for k in MODELS if any(k in t.specs for t in TARGETS.values())]


def _models(value: str | None, target: str, runner: str = "agents-api") -> list[str]:
    """The models to ask, checked against what the target offers (default: all of them).

    The claude-code runner doesn't go through the target's LibreChat specs, so any model with a Claude Code id works."""
    offered = list(TARGETS[target].specs)
    if runner == "claude-code":
        offered += [k for k, m in MODELS.items() if m.claude_code_id and k not in offered]
    models = [m.strip() for m in value.split(",") if m.strip()] if value else offered
    unknown = [m for m in models if m not in offered]
    if unknown:
        raise click.BadParameter(f"target {target} has no model(s) {unknown}; choose from {offered}")
    if runner == "claude-code" and (no_cc := [m for m in models if not MODELS[m].claude_code_id]):
        raise click.BadParameter(f"the claude-code runner can't run {no_cc}: they aren't a single model")
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


def claude_code_options(f):
    """Options of the claude-code runner (ignored by the Agents API runner)."""
    f = click.option(
        "--require-beta-mcp",
        is_flag=True,
        help="claude-code runner on a beta target: fail unless the database MCP is beta's (DATABASE_MCP_URL at "
        "beta's service, or DATABASE_MCP_ENV=beta for a port-forward or local image) instead of warning.",
    )(f)
    return claude_code_session_options(f)


def claude_code_session_options(f):
    """How `claude` sessions bill and which settings they load: the claude-code runner's and judge's."""
    f = click.option(
        "--claude-code-user-settings",
        is_flag=True,
        help="Load the Claude home's user settings (and project/local ones) in claude-code sessions. By default "
        "only managed settings apply, so effortLevel, hooks and plugins from ~/.claude stay out.",
    )(f)
    f = click.option(
        "--claude-code-trust-org-policy",
        is_flag=True,
        envvar="CLAUDE_CODE_TRUST_ORG_POLICY",
        help="Run claude-code sessions on a Team or Enterprise login (or any plan but Pro/Max). Their "
        "organization can push server-managed settings that a session applies without caching, so the billing "
        "guard can't check them beforehand; this trusts that policy not to bill per token.",
    )(f)
    f = click.option(
        "--claude-code-allow-api-billing",
        is_flag=True,
        envvar="CLAUDE_CODE_ALLOW_API_BILLING",
        help="Let claude-code sessions use ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL, a "
        "cloud provider (CLAUDE_CODE_USE_*) or an apiKeyHelper, billed per token. By default those are "
        "removed or refused so answers bill the subscription login.",
    )(f)
    return f


JUDGE_RUNNERS = ["bedrock", "claude-code"]


def judge_options(f):
    f = click.option(
        "--judge-model",
        default=None,
        help="Judge model: a model key (sonnet-4.6), Bedrock id or Claude Code id. Default: JUDGE_MODEL "
        "(Sonnet 4.6 on Bedrock), or the same model through Claude Code.",
    )(f)
    f = click.option(
        "--judge-runner",
        type=click.Choice(JUDGE_RUNNERS),
        default="bedrock",
        show_default=True,
        help="bedrock: the Bedrock judge at temperature 0 (bills AWS). claude-code: the same prompt through "
        "`claude -p` on the Claude subscription, no tools; grades are recorded as claude-code:<model>, can't be "
        "at temperature 0, and aren't comparable with Bedrock grades. Takes the --claude-code-* billing options.",
    )(f)
    return f


screenshots_option = click.option(
    "--screenshots/--no-screenshots",
    default=True,
    show_default=True,
    help="Save a screenshot of each rendered page. Screenshots are pixels, so they aren't redacted; they only "
    "show the public cBioPortal pages answers linked to.",
)


def _agent_prompt(settings, target: str) -> dict:
    try:
        return fetch_agent_prompt(TARGETS[target].agent_id, settings.kube_context)
    except Exception as exc:
        raise click.ClickException(
            f"could not read the {target} agent's prompt via kubectl: {describe_error(exc, 2000)}"
        ) from exc


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


def _check_database_mcp(settings, target: str, runner: str, require_beta: bool) -> str | None:
    """Which database MCP (beta, prod, local, unknown, conflict) the claude-code runner reaches. Warns when a
    beta target would be answered from another one or it can't be told, and on any target when
    DATABASE_MCP_ENV contradicts the URL; with `require_beta`, a beta target fails instead."""
    if runner != "claude-code":
        return None
    env = database_mcp_env(settings)
    beta = target.startswith("beta")
    if env != "conflict" and (not beta or env == "beta"):
        return env
    where = settings.database_mcp_url or f"the claude.ai connector for {settings.database_connector_url}"
    if env == "conflict":
        problem = (
            f"DATABASE_MCP_ENV={settings.database_mcp_env} contradicts the database MCP's URL ({where}); unset "
            "it or fix DATABASE_MCP_URL."
        )
    elif env == "prod":
        problem = (
            f"--target {target} but the database MCP is PROD ({where}), not beta's "
            f"({TARGETS[target].mcp_deployment}): answers use prod's server, guides and ClickHouse buffers."
        )
    else:
        problem = (
            f"--target {target} but the database MCP ({where}) is {env}, not beta's; set DATABASE_MCP_ENV=beta "
            "if it is (e.g. a port-forward of the beta service)."
        )
    if require_beta and beta:
        raise click.ClickException(f"{problem} See README: point DATABASE_MCP_URL at the beta MCP.")
    bar = "!" * 100
    hint = "Point DATABASE_MCP_URL at the beta MCP (README) or pass --require-beta-mcp to make this an error."
    click.echo(f"{bar}\nWARNING: {problem}\n{hint if beta else ''}\n{bar}", err=True)
    return env


def _client(
    settings,
    target: str,
    runner: str,
    prompt: str | None = None,
    transcript_dir: Path | None = None,
    allow_api_billing: bool = False,
    user_settings: bool = False,
    trust_org_policy: bool = False,
):
    if runner == "claude-code":
        try:
            return ClaudeCodeClient(
                prompt or _agent_prompt(settings, target)["instructions"],
                settings.database_mcp_url,
                settings.navigator_mcp_url,
                database_connector=_database_connector(settings),
                transcript_dir=transcript_dir,
                allow_api_billing=allow_api_billing,
                isolate_settings=not user_settings,
                trust_org_policy=trust_org_policy,
            )
        except RuntimeError as exc:
            raise click.ClickException(redact(str(exc))) from exc
    return AgentClient(TARGETS[target], settings.api_key)


def _judge(settings) -> Judge:
    return Judge(settings.judge_model, settings.aws_region, settings.aws_profile)


def _make_judge(
    settings,
    judge_runner: str,
    judge_model: str | None,
    allow_api_billing: bool = False,
    user_settings: bool = False,
    trust_org_policy: bool = False,
) -> BaseJudge:
    if judge_runner == "claude-code":
        try:
            return ClaudeCodeJudge(
                judge_model or settings.judge_model,
                allow_api_billing=allow_api_billing,
                isolate_settings=not user_settings,
                trust_org_policy=trust_org_policy,
            )
        except (RuntimeError, ValueError) as exc:
            raise click.ClickException(f"claude-code judge: {redact(str(exc))}") from exc
    if not judge_model:
        return _judge(settings)
    return Judge(_bedrock_judge_model(settings, judge_model), settings.aws_region, settings.aws_profile)


def _bedrock_judge_model(settings, judge_model: str | None) -> str:
    if not judge_model:
        return settings.judge_model
    model = MODELS[judge_model].bedrock_id if judge_model in MODELS else judge_model
    if not model:
        raise click.BadParameter(f"{judge_model} has no Bedrock id", param_hint="--judge-model")
    return model


def _grade(bench: Run, judge: BaseJudge, concurrency: int, command: str) -> None:
    """Grade, and on a stop (the subscription's usage limit, per-token billing) write the report and say how to
    resume."""
    try:
        grade_answers(bench, judge, concurrency)
    except JudgeStopped as exc:
        click.echo(f"Report: {write_report(bench)}")
        raise click.ClickException(
            f"grading stopped: {exc}. The grades so far are saved; once it is resolved (a usage limit resets), "
            f"continue with `{command}`."
        ) from exc
    finally:
        if close := getattr(judge, "close", None):
            close()


def _grade_command(bench: Run, judge_runner: str, judge_model: str | None, trust_org_policy: bool) -> str:
    """The `grade` command that continues grading this run with the same judge."""
    cmd = f"cbioportal-mcp-qa grade {bench.data['run_id']}"
    if judge_runner != "bedrock":
        cmd += f" --judge-runner {judge_runner}"
    if judge_model:
        cmd += f" --judge-model {judge_model}"
    if judge_runner == "claude-code" and trust_org_policy:
        cmd += " --claude-code-trust-org-policy"
    return cmd


@click.group()
def cli() -> None:
    """Benchmark cBioPortalChat by asking the deployed agent the questions in input/questions.yaml."""


@cli.command()
@click.argument("question")
@click.option("--target", type=click.Choice(list(TARGETS)), default="beta", show_default=True)
@click.option("--model", type=click.Choice(MODEL_CHOICES), default=None, help="Default: the target's first.")
@runner_option
@claude_code_options
def ask(
    question: str,
    target: str,
    model: str | None,
    runner: str,
    claude_code_allow_api_billing: bool,
    claude_code_trust_org_policy: bool,
    claude_code_user_settings: bool,
    require_beta_mcp: bool,
) -> None:
    """Ask the deployed agent a single question."""
    settings = load_settings()
    model = _models(model, target, runner)[0]
    _check_database_mcp(settings, target, runner, require_beta_mcp)

    async def go():
        client = _client(
            settings,
            target,
            runner,
            allow_api_billing=claude_code_allow_api_billing,
            user_settings=claude_code_user_settings,
            trust_org_policy=claude_code_trust_org_policy,
        )
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
@click.option(
    "--models",
    "models_arg",
    default=None,
    help="Comma-separated. Default: every model the target offers (beta: haiku,sonnet; beta-router: router).",
)
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
@judge_options
@click.option(
    "--judge-concurrency", type=int, default=1, show_default=True, help="Answers graded in parallel."
)
@click.option(
    "--render/--no-render",
    default=True,
    show_default=True,
    help="Open navigation answers' links in Chromium.",
)
@screenshots_option
@runner_option
@claude_code_options
def run(
    target,
    models_arg,
    selection,
    questions_file,
    repeats,
    concurrency,
    resume,
    no_grade,
    judge_runner,
    judge_model,
    judge_concurrency,
    render,
    screenshots,
    runner,
    claude_code_allow_api_billing,
    claude_code_trust_org_policy,
    claude_code_user_settings,
    require_beta_mcp,
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
    else:
        models = _models(models_arg, target, runner)
    agent = None
    if runner == "claude-code" or not resume:
        try:
            agent = fetch_agent_prompt(TARGETS[target].agent_id, settings.kube_context)
        except Exception as exc:  # noqa: BLE001 - only the claude-code runner needs the prompt itself
            if runner == "claude-code":
                raise click.ClickException(
                    f"could not read the {target} agent's prompt via kubectl: {describe_error(exc, 2000)}"
                ) from exc
            agent_error = describe_error(exc)
    prompt = agent["instructions"] if agent and runner == "claude-code" else None
    mcp_env = _check_database_mcp(settings, target, runner, require_beta_mcp)
    # Before the run exists: the claude-code judge, like the runner, refuses to start on per-token billing.
    judge = None
    if not no_grade and judge_runner == "claude-code":
        judge = _make_judge(
            settings,
            judge_runner,
            judge_model,
            claude_code_allow_api_billing,
            claude_code_user_settings,
            claude_code_trust_org_policy,
        )
    client = _client(
        settings,
        target,
        runner,
        prompt,
        allow_api_billing=claude_code_allow_api_billing,
        user_settings=claude_code_user_settings,
        trust_org_policy=claude_code_trust_org_policy,
    )
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
        root = TARGETS[target].agent_id
        extra = {
            "agent_prompt": prompt_info,
            "target_config": {"url": TARGETS[target].url, "agent_id": root, "specs": TARGETS[target].specs},
            # The target agent and every agent it hands off to (the router's specialists).
            "agents": describe_agents(
                root,
                settings.kube_context,
                lambda agent_id, ctx: (
                    agent if agent and agent_id == root else fetch_agent_prompt(agent_id, ctx)
                ),
            ),
            "versions": collect_versions(settings, runner, target),
        }
        if runner == "claude-code":
            extra["database_mcp"] = client.setup.connector or settings.database_mcp_url
            extra["database_mcp_env"] = mcp_env
            extra["navigator_mcp"] = settings.navigator_mcp_url
            extra["claude_code"] = client.describe() | {
                "prompt": prompt_parity(prompt, settings.database_mcp_url)
            }
        judge_id = judge.model if judge else _bedrock_judge_model(settings, judge_model)
        bench = Run.create(target, models, repeats, judge_id, str(questions_file), runner, extra)
        if agent:
            # A record of the prompt this run tested (the benchmark itself always reads the live agent).
            write_text(bench.dir / "agent-prompt.md", agent["instructions"])
    click.echo(
        f"Run {bench.data['run_id']} ({runner}): {len(questions)} questions × {bench.data['models']} × "
        f"{bench.data['repeats']} against {TARGETS[target].agent_id} ({target})"
    )

    if runner == "claude-code":
        client.transcript_dir = bench.dir / "transcripts"

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
    if getattr(client, "api_billing", None):
        raise click.ClickException(f"{client.api_billing}. Stopped before grading.")
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
        rendered = render_navigation_links(bench, settings.chromium_path, screenshots=screenshots)
        click.echo(f"Rendered {rendered} navigation links")
    if not no_grade:
        judge = judge or _make_judge(settings, judge_runner, judge_model)
        _grade(
            bench,
            judge,
            judge_concurrency,
            _grade_command(bench, judge_runner, judge_model, claude_code_trust_org_policy),
        )
    click.echo(f"Report: {write_report(bench)}")


@cli.command("render")
@click.argument("run_id")
@click.option("--concurrency", type=int, default=3, show_default=True)
@screenshots_option
def render_cmd(run_id: str, concurrency: int, screenshots: bool) -> None:
    """Open the cBioPortal links in navigation answers and record what each page shows (then regrade them)."""
    bench = Run.load(run_id)
    rendered = render_navigation_links(bench, load_settings().chromium_path, concurrency, screenshots)
    click.echo(f"Rendered {rendered} links")
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
    help="Update each question's references (expected answer, links, notes, track) from the current questions "
    "file, then regrade (implies --regrade). The question text and history stay as they were asked.",
)
@judge_options
@click.option("--concurrency", type=int, default=1, show_default=True, help="Answers graded in parallel.")
@claude_code_session_options
def grade(
    run_id: str,
    regrade: bool,
    refresh_questions: bool,
    judge_runner: str,
    judge_model: str | None,
    concurrency: int,
    claude_code_allow_api_billing: bool,
    claude_code_trust_org_policy: bool,
    claude_code_user_settings: bool,
) -> None:
    """Grade answers that don't have a grade yet (and answers the judge left ungraded)."""
    bench = Run.load(run_id)
    # Before any grade is discarded: the claude-code judge refuses to start on per-token billing.
    judge = _make_judge(
        load_settings(),
        judge_runner,
        judge_model,
        claude_code_allow_api_billing,
        claude_code_user_settings,
        claude_code_trust_org_policy,
    )
    if refresh_questions:
        current = {q.id: asdict(q) for q in load_questions(Path(bench.data["questions_file"]))}
        reworded = set()
        for rec in bench.records.values():
            new = current.get(rec["question"]["id"])
            if new is None:
                continue
            asked, now = definition_fields(rec["question"]), definition_fields(new)
            if any(asked[f] != now[f] for f in ASKED_FIELDS):
                reworded.add(rec["question"]["id"])
            # The answer was to the text and history that were asked, so only the references change.
            rec["question"] = rec["question"] | {f: new[f] for f in REFERENCE_FIELDS}
        if reworded:
            click.echo(
                f"Warning: {len(reworded)} questions were reworded since this run asked them "
                f"({', '.join(map(str, sorted(reworded)))}). They keep the text that was asked and are graded "
                "against the current references; `compare` flags them against runs that asked the new text.",
                err=True,
            )
    if regrade or refresh_questions:
        for rec in bench.records.values():
            rec.pop("grade", None)
        bench.save()
    _grade(
        bench,
        judge,
        concurrency,
        _grade_command(bench, judge_runner, judge_model, claude_code_trust_org_policy),
    )
    click.echo(f"Report: {write_report(bench)}")


@cli.command()
@click.argument("run_id", required=False)
def report(run_id: str | None) -> None:
    """Re-render a run's report (or just the results index when no run id is given)."""
    click.echo(write_report(Run.load(run_id)) if run_id else write_index())


@cli.command()
@click.argument("run_a")
@click.argument("run_b")
@click.option("--model-a", default=None, help="Model of RUN_A to compare (needed when it ran several).")
@click.option("--model-b", default=None, help="Model of RUN_B to compare (needed when it ran several).")
@click.option(
    "--allow-mismatch",
    is_flag=True,
    help="Compare even if the judge, questions file or a question's text, history or references differ "
    "(those questions are marked).",
)
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory. Default: results/compare/<A>-<model>_vs_<B>-<model>/.",
)
def compare(
    run_a: str, run_b: str, model_a: str | None, model_b: str | None, allow_mismatch: bool, out: Path | None
) -> None:
    """Compare RUN_B against the baseline RUN_A per question and in aggregate (repeats pooled).

    Refuses runs graded differently unless --allow-mismatch. Writes compare.html, compare.md and compare.json,
    and prints the markdown."""
    try:
        result = compare_runs(Run.load(run_a), Run.load(run_b), model_a, model_b, allow_mismatch)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    html = write_compare(result, out)
    click.echo((html.parent / "compare.md").read_text())
    for warning in result["warnings"]:
        click.echo(f"Warning: {warning}", err=True)
    click.echo(f"Report: {html}")
