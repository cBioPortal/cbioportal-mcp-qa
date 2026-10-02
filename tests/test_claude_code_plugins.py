"""Plugins in `claude -p` sessions: turned off, checked by a preflight before the first model call, refused
unless allowed, and recorded per answer, per grade and in run.json. Against a fake `claude` binary on PATH that
loads plugins the way Claude Code 2.1.287 does: every plugin it offers unless --settings turns it off with
`enabledPlugins`, except the ones only managed policy can turn off (cc-plugin-sec-default)."""

import asyncio
import json
import os
import stat
import sys

import pytest
from test_review_fixes import JUDGE, _rec, _run

from cbioportal_mcp_qa import claude_code
from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa.claude_code import (
    BUILTIN_PLUGINS,
    PREFLIGHT_MODEL,
    ClaudeCodeClient,
    ToolSetup,
    claude_args,
    plugin_guard,
    session_plugins,
)
from cbioportal_mcp_qa.claude_judge import ClaudeCodeJudge
from cbioportal_mcp_qa.grade import JudgeStopped
from cbioportal_mcp_qa.run import Run, grade_answers

REAL_PREFLIGHT = claude_code.preflight_plugins
SEC_DEFAULT = "cc-plugin-sec-default@builtin"
VERDICT = {"rationale": "States the reference count.", "passed": True, "declined": False}

FAKE_CLAUDE = """#!{python}
import json, os, sys
argv = sys.argv[1:]
spec = json.load(open(os.environ["FAKE_CLAUDE_SPEC"]))
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps({{"argv": argv, "stdin": sys.stdin.read()}}) + "\\n")
preflight = "{preflight}" in argv
settings = json.loads(argv[argv.index("--settings") + 1]) if "--settings" in argv else {{}}
off = {{k for k, v in (settings.get("enabledPlugins") or {{}}).items() if v is False}}
plugins = [p for p in spec["plugins"] if p not in off or p in spec.get("policy_only", [])]
plugins += spec.get("session_extra", []) if not preflight else []
init = {{"type": "system", "subtype": "init", "apiKeySource": "none",
        "tools": ["StructuredOutput", *spec.get("mcp_tools", [])],
        "plugins": [{{"name": p.split("@")[0], "path": "builtin", "source": p}} for p in plugins]}}
if spec.get("no_init"):
    sys.stderr.write("claude: boom\\n"); sys.exit(1)
if spec.get("session_init_without_plugins") and not preflight:
    del init["plugins"]
lines = [] if spec.get("session_no_init") and not preflight else [json.dumps(init)]
zero = {{"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
if preflight:
    # What claude 2.1.287 prints for a model that doesn't exist: a synthetic message, nothing generated.
    message = "There's an issue with the selected model ({preflight}). It may not exist or you may not have access to it."
    lines.append(json.dumps({{"type": "assistant", "error": "model_not_found", "message": {{"model": "<synthetic>",
                              "usage": zero, "content": [{{"type": "text", "text": message}}]}}}}))
    result = {{"type": "result", "subtype": "success", "is_error": True, "api_error_status": 404,
              "result": message, "total_cost_usd": 0, "usage": zero, "modelUsage": {{}}}}
    result.update(spec.get("preflight_result", {{}}))
    result = {{k: v for k, v in result.items() if v is not None}}
    if not spec.get("preflight_no_result"):
        lines.append(json.dumps(result))
else:
    lines.append(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "42 patients",
                              "structured_output": {verdict}, "usage": {{"input_tokens": 10, "output_tokens": 5}}}}))
sys.stdout.write("\\n".join(lines) + "\\n")
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """A `claude` that offers `set(plugins=...)` and logs every call; the real preflight runs against it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "claude"
    exe.write_text(
        FAKE_CLAUDE.format(python=sys.executable, preflight=PREFLIGHT_MODEL, verdict=repr(VERDICT))
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log, spec = tmp_path / "calls.jsonl", tmp_path / "spec.json"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_SPEC", str(spec))
    monkeypatch.setattr(claude_code, "preflight_plugins", REAL_PREFLIGHT)

    class Fake:
        def set(self, **fields):
            spec.write_text(json.dumps({"plugins": [], **fields}))

        @property
        def calls(self) -> list[list[str]]:
            return [json.loads(line)["argv"] for line in log.read_text().splitlines()] if log.exists() else []

        @property
        def preflights(self) -> list[list[str]]:
            return [argv for argv in self.calls if PREFLIGHT_MODEL in argv]

    fake = Fake()
    # What Claude Code 2.1.287 loads on a Pro login with no settings sources.
    fake.set(plugins=[f"cc-plugin-{n}@builtin" for n in ("agents-md", "telemetry", "plugin-authoring")])
    return fake


def _settings(argv: list[str]) -> dict:
    return json.loads(argv[argv.index("--settings") + 1])


TEAM = [SEC_DEFAULT, "cc-plugin-agents-md@builtin", "cc-plugin-telemetry@builtin"]


# --- the preflight ----------------------------------------------------------------------------------------------


def test_the_preflight_makes_no_model_call_and_turns_every_builtin_plugin_off(fake_claude, tmp_path):
    settings, found = plugin_guard(dict(os.environ), str(tmp_path), True, False)
    assert found == []
    (argv,) = fake_claude.calls
    # A model no account has: the init event arrives, then model_not_found, before anything is generated.
    assert argv[argv.index("--model") + 1] == PREFLIGHT_MODEL
    assert argv[argv.index("--setting-sources") + 1] == "" and argv[argv.index("--tools") + 1] == ""
    assert _settings(argv) == settings == {"enabledPlugins": {f"{n}@builtin": False for n in BUILTIN_PLUGINS}}


def test_a_plugin_the_preflight_finds_is_turned_off_and_checked_again(fake_claude, tmp_path):
    fake_claude.set(plugins=["cc-plugin-agents-md@builtin", "new-builtin@builtin", "skills@user-market"])
    settings, found = plugin_guard(dict(os.environ), str(tmp_path), False, False, {"disableAllHooks": True})
    assert found == [] and len(fake_claude.preflights) == 2
    assert settings["disableAllHooks"] is True
    assert settings["enabledPlugins"]["new-builtin@builtin"] is False
    assert settings["enabledPlugins"]["skills@user-market"] is False
    assert "--setting-sources" not in fake_claude.calls[1]  # user settings, as the sessions load them


def test_a_plugin_only_policy_can_turn_off_is_refused_unless_allowed(fake_claude, tmp_path):
    fake_claude.set(plugins=TEAM, policy_only=[SEC_DEFAULT])
    with pytest.raises(RuntimeError, match="cc-plugin-sec-default@builtin.*--claude-code-allow-plugins"):
        plugin_guard(dict(os.environ), str(tmp_path), True, False)
    _, found = plugin_guard(dict(os.environ), str(tmp_path), True, True)
    assert found == [SEC_DEFAULT]


def test_a_preflight_without_an_init_event_fails(fake_claude, tmp_path):
    fake_claude.set(no_init=True)
    with pytest.raises(RuntimeError, match="could not start claude to check its plugins: claude: boom"):
        plugin_guard(dict(os.environ), str(tmp_path), True, False)


def test_a_preflight_that_times_out_fails_with_a_message(fake_claude, tmp_path, monkeypatch):
    def hang(*args, **kwargs):
        raise claude_code.subprocess.TimeoutExpired(args[0], 120)

    monkeypatch.setattr(claude_code.subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="could not start claude to check its plugins: .*timed out"):
        plugin_guard(dict(os.environ), str(tmp_path), True, False)


def test_session_plugins_reads_the_init_event():
    init = {
        "type": "system",
        "subtype": "init",
        "plugins": [{"name": "a", "source": "a@builtin"}, {"name": "b"}],
    }
    assert session_plugins([json.dumps(init)]) == ["a@builtin", "b"]
    assert session_plugins([json.dumps(init | {"plugins": []})]) == []
    # No plugin list, no init event, or an unparseable one: unknown, so callers refuse the session.
    assert session_plugins([json.dumps({"type": "system", "subtype": "init"})]) is None
    assert session_plugins(['{"type": "result"}']) is None
    assert session_plugins(['{"type": "system", "subtype": "init", "plugins": [']) is None


# --- the answer runner ------------------------------------------------------------------------------------------


def test_runner_sessions_turn_plugins_off_and_record_them(fake_claude):
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    try:
        reply = asyncio.run(client.ask("q?", "haiku"))
        described = client.describe()
    finally:
        asyncio.run(client.aclose())
    assert reply.error is None and reply.trace["plugins"] == []
    preflight, session = fake_claude.calls
    assert PREFLIGHT_MODEL in preflight and _settings(session) == _settings(preflight) == client.settings
    assert described["plugins"] == [] and described["allow_plugins"] is False
    assert described["disabled_plugins"] == sorted(f"{n}@builtin" for n in BUILTIN_PLUGINS)


def test_runner_refuses_before_any_session_when_a_plugin_stays(fake_claude):
    fake_claude.set(plugins=TEAM, policy_only=[SEC_DEFAULT])
    with pytest.raises(RuntimeError, match="--claude-code-allow-plugins"):
        ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    assert all(PREFLIGHT_MODEL in argv for argv in fake_claude.calls)


def test_runner_with_plugins_allowed_records_them_per_answer_and_in_run_json(fake_claude):
    fake_claude.set(plugins=TEAM, policy_only=[SEC_DEFAULT])
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp", allow_plugins=True)
    try:
        reply = asyncio.run(client.ask("q?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    assert reply.error is None and reply.trace["plugins"] == [SEC_DEFAULT]
    assert client.describe()["plugins"] == [SEC_DEFAULT] and client.describe()["allow_plugins"] is True


def test_runner_stops_when_a_session_loads_a_plugin_the_preflight_missed(fake_claude):
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    fake_claude.set(session_extra=["late@builtin"])
    try:
        first = asyncio.run(client.ask("q?", "haiku"))
        second = asyncio.run(client.ask("q2?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    assert "late@builtin" in first.error and first.trace["plugins"] == ["late@builtin"]
    assert second.error == first.error == client.plugins_error
    assert len(fake_claude.calls) == 2  # the preflight and one session: no retry, no second question


def test_claude_args_and_the_connector_probe_carry_the_settings():
    setup = ToolSetup({"navigator": "http://nav/mcp"})
    args = claude_args("q?", "haiku", "PROMPT", setup, "/tmp/mcp.json")
    assert _settings(args) == claude_code.no_plugins_settings()
    custom = {"enabledPlugins": {"x@y": False}}
    assert _settings(claude_args("q?", "haiku", "PROMPT", setup, "/tmp/mcp.json", settings=custom)) == custom


# --- the judge --------------------------------------------------------------------------------------------------


@pytest.fixture
def ungraded(results_dir):
    return _run("U", "haiku", 1, [_rec(q, "haiku", 1, graded=False) for q in (1, 2)])


def test_judge_turns_plugins_off_and_records_them_per_grade(fake_claude, ungraded):
    judge = ClaudeCodeJudge(JUDGE)
    grade_answers(ungraded, judge)
    judge.close()
    grades = [r["grade"] for r in Run.load(str(ungraded.dir)).records.values()]
    assert [g["judge_plugins"] for g in grades] == [[], []]
    settings = _settings(fake_claude.calls[-1])
    assert settings["disableAllHooks"] is True and settings["enabledPlugins"][SEC_DEFAULT] is False
    assert judge.describe()["plugins"] == [] and judge.describe()["allow_plugins"] is False


def test_judge_refuses_before_grading_when_a_plugin_stays(fake_claude, ungraded):
    fake_claude.set(plugins=TEAM, policy_only=[SEC_DEFAULT])
    with pytest.raises(RuntimeError, match="cc-plugin-sec-default"):
        ClaudeCodeJudge(JUDGE)
    assert all(PREFLIGHT_MODEL in argv for argv in fake_claude.calls)


def test_judge_with_plugins_allowed_records_them(fake_claude, ungraded):
    fake_claude.set(plugins=TEAM, policy_only=[SEC_DEFAULT])
    judge = ClaudeCodeJudge(JUDGE, allow_plugins=True)
    grade_answers(ungraded, judge)
    judge.close()
    grades = [r["grade"] for r in Run.load(str(ungraded.dir)).records.values()]
    assert [g["judge_plugins"] for g in grades] == [[SEC_DEFAULT]] * 2
    assert judge.describe()["plugins"] == [SEC_DEFAULT] and judge.describe()["allow_plugins"] is True


def test_judge_stops_when_a_session_loads_a_plugin_the_preflight_missed(fake_claude, ungraded):
    judge = ClaudeCodeJudge(JUDGE)
    fake_claude.set(session_extra=["late@builtin"])
    with pytest.raises(JudgeStopped, match="late@builtin"):
        grade_answers(ungraded, judge)
    assert not any("grade" in r for r in Run.load(str(ungraded.dir)).records.values())


def test_the_resume_command_keeps_allow_plugins():
    cmd = cli_mod._grade_command("R", "claude-code", None, 1, allow_plugins=True)
    assert cmd.endswith("--claude-code-allow-plugins")
    assert "--claude-code-allow-plugins" not in cli_mod._grade_command("R", "claude-code", None, 1)


# --- review fixes: fail closed ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        {"total_cost_usd": 0.0001},  # billed
        {"usage": {"input_tokens": 12, "output_tokens": 0}},  # sent to a model
        {"usage": {"input_tokens": 0, "output_tokens": 3}},  # generated
        {"usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 5}},
        {"modelUsage": {"claude-haiku-4-5": {"inputTokens": 1}}},
        {"is_error": False, "result": "OK", "api_error_status": None},  # the model answered
        {"result": "Credit balance is too low", "api_error_status": 400},  # some other error
    ],
)
def test_a_preflight_that_did_not_end_at_the_missing_model_refuses(fake_claude, tmp_path, result):
    fake_claude.set(preflight_result=result)
    with pytest.raises(RuntimeError, match="plugin preflight did not end before generation"):
        plugin_guard(dict(os.environ), str(tmp_path), True, False)


def test_a_preflight_without_a_result_refuses(fake_claude, tmp_path):
    fake_claude.set(preflight_no_result=True)
    with pytest.raises(RuntimeError, match="plugin preflight did not end before generation: no result"):
        plugin_guard(dict(os.environ), str(tmp_path), True, False)


def test_a_preflight_with_no_cost_field_and_zero_usage_passes(fake_claude, tmp_path):
    fake_claude.set(preflight_result={"total_cost_usd": None})
    assert plugin_guard(dict(os.environ), str(tmp_path), True, False)[1] == []


def _probe(allow_plugins: bool, tmp_path) -> set[str]:
    setup = ToolSetup({"navigator": "http://nav/mcp"}, "cBioPortal DB")
    return claude_code.probe_mcp_servers(
        setup, str(tmp_path), dict(os.environ), settings=claude_code.no_plugins_settings(),
        allow_plugins=allow_plugins,
    )  # fmt: skip


def test_the_connector_probe_stops_on_a_plugin(fake_claude, tmp_path):
    fake_claude.set(session_extra=["late@builtin"], mcp_tools=["mcp__claude_ai_cBioPortal_DB__q"])
    with pytest.raises(RuntimeError, match="late@builtin.*--claude-code-allow-plugins"):
        _probe(False, tmp_path)
    assert len(fake_claude.calls) == 1  # no further probe attempt
    assert _probe(True, tmp_path) == {"claude_ai_cBioPortal_DB"}


def test_the_connector_probe_stops_without_a_plugin_list(fake_claude, tmp_path):
    fake_claude.set(session_init_without_plugins=True, mcp_tools=["mcp__claude_ai_cBioPortal_DB__q"])
    with pytest.raises(RuntimeError, match="didn't report its plugins"):
        _probe(False, tmp_path)


@pytest.mark.parametrize("missing", ["session_no_init", "session_init_without_plugins"])
@pytest.mark.parametrize("allow", [False, True])
def test_runner_stops_on_a_successful_session_that_did_not_report_its_plugins(fake_claude, missing, allow):
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp", allow_plugins=allow)
    fake_claude.set(**{missing: True})
    try:
        reply = asyncio.run(client.ask("q?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    assert reply.status is None and "didn't report its plugins" in reply.error
    assert reply.error == client.plugins_error
    assert len(fake_claude.calls) == 2  # the preflight and one session: no retry


@pytest.mark.parametrize("missing", ["session_no_init", "session_init_without_plugins"])
@pytest.mark.parametrize("allow", [False, True])
def test_judge_stops_on_a_session_that_did_not_report_its_plugins(fake_claude, ungraded, missing, allow):
    judge = ClaudeCodeJudge(JUDGE, allow_plugins=allow)
    fake_claude.set(**{missing: True})
    with pytest.raises(JudgeStopped, match="didn't report its plugins"):
        grade_answers(ungraded, judge)
    assert not any("grade" in r for r in Run.load(str(ungraded.dir)).records.values())


def test_grades_without_a_judge_session_say_so(fake_claude, results_dir):
    from test_review_fixes import _question

    records = [_rec(1, "haiku", 1, graded=False), _rec(2, "haiku", 1, graded=False)]
    records[0]["reply"]["answer"] = ""
    records[1]["question"] = _question(2, expected_answer="", expected_links=[])
    bench = _run("N", "haiku", 1, records)
    judge = ClaudeCodeJudge(JUDGE)
    grade_answers(bench, judge)
    judge.close()
    grades = [r["grade"] for r in Run.load(str(bench.dir)).records.values()]
    assert [g["judge_plugins"] for g in grades] == [None, None]
    assert {g["judge_plugins_note"] for g in grades} == {"no judge session: graded without the judge"}
    assert len(fake_claude.calls) == 1  # the preflight only


def test_a_plugin_stop_prints_the_resume_command(fake_claude, results_dir, monkeypatch):
    from click.testing import CliRunner

    monkeypatch.setattr(cli_mod, "fetch_agent_prompt", lambda *a: {"instructions": "PROMPT", "id": "x"})
    monkeypatch.setattr(cli_mod, "_check_database_mcp", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "_database_connector", lambda settings: None)
    monkeypatch.setattr(cli_mod, "collect_versions", lambda *a, **k: {}, raising=False)
    fake_claude.set(session_extra=["late@builtin"])
    out = CliRunner().invoke(
        cli_mod.cli,
        ["run", "--runner", "claude-code", "--models", "haiku", "--questions", "1", "--no-grade",
         "--claude-code-trust-org-policy"],
    )  # fmt: skip
    assert out.exit_code != 0, out.output
    assert "late@builtin" in out.output and "Stopped before grading" in out.output
    assert "aren't recorded" in out.output
    assert "--resume" in out.output and "--claude-code-trust-org-policy" in out.output
