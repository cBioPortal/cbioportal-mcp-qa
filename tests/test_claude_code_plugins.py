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
settings = json.loads(argv[argv.index("--settings") + 1]) if "--settings" in argv else {{}}
off = {{k for k, v in (settings.get("enabledPlugins") or {{}}).items() if v is False}}
plugins = [p for p in spec["plugins"] if p not in off or p in spec.get("policy_only", [])]
plugins += spec.get("session_extra", []) if "{preflight}" not in argv else []
init = {{"type": "system", "subtype": "init", "tools": ["StructuredOutput"], "apiKeySource": "none",
        "plugins": [{{"name": p.split("@")[0], "path": "builtin", "source": p}} for p in plugins]}}
if spec.get("no_init"):
    sys.stderr.write("claude: boom\\n"); sys.exit(1)
lines = [json.dumps(init)]
if "{preflight}" in argv:
    lines.append(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                              "result": "There's an issue with the selected model", "total_cost_usd": 0}}))
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
    assert session_plugins([json.dumps({"type": "system", "subtype": "init"})]) == []
    assert session_plugins(['{"type": "result"}']) is None


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
