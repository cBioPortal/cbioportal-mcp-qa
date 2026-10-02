"""The judge on the local Claude Code subscription (`claude -p`) instead of Bedrock.

Same prompt, rubric and grade fields as the Bedrock judge, with the claude-code runner's safeguards: billing
variables removed, the billing guard run before the first call (and the session's apiKeySource checked after
each), user settings always left out, an empty working directory, and no tools at all (no built-ins, no MCP
servers, no claude.ai connectors). Its own hooks, auto memory and Claude Code's built-in plugins are off, but
managed (policy) hooks, managed CLAUDE.md and managed plugins or MCP servers can't be turned off from a session:
the judge refuses to start while the managed settings it can read carry any of them, or while a preflight
session (no model call) still loads a plugin, and stops if a session shows hooks, plugins or MCP servers
anyway. Each grade records the plugins its session loaded. Claude Code can't set the temperature, so its
grades vary more than Bedrock's temperature-0 ones; each grade records the judge as `claude-code:<model>` so
`compare` keeps them apart.
"""

import json
import os
import subprocess
import tempfile
import threading

from . import claude_code
from .claude_code import (
    USAGE_LIMIT,
    api_billing_error,
    api_key_source,
    bills_per_token,
    check_billing,
    plugin_guard,
    plugins_error,
    session_env,
    session_plugins,
    setting_sources_args,
    settings_files,
)
from .config import MODELS, _model_family
from .grade import JUDGE_SCHEMA, BaseJudge, JudgeOutputError, JudgeStopped, parse_verdict
from .persist import write_private_json
from .redact import redact

JUDGE_ID_PREFIX = "claude-code:"
# Claude Code's own system prompt (tools, coding style) would be part of the grading context otherwise.
JUDGE_SYSTEM_PROMPT = "You are a grader. Reply with the verdict the JSON schema describes, nothing else."
ATTEMPTS = 2  # an invalid verdict is retried once, then the answer stays ungraded


def claude_code_model(model: str) -> str:
    """A Claude Code model id from a model key (`sonnet-4.6`), a Bedrock id (`us.anthropic.claude-sonnet-4-6`)
    or a Claude Code id (`claude-sonnet-4-6`): by default the same model as the Bedrock judge."""
    if model in MODELS:
        known = MODELS[model]
        if known.claude_code_id:
            return known.claude_code_id
        if not known.bedrock_id:
            raise ValueError(f"{model} isn't a single model")
        model = known.bedrock_id
    return _model_family(model)


# Turns off the hooks of every settings source a session can override (managed hooks stay: see
# managed_customizations) and auto memory.
JUDGE_SETTINGS = {"disableAllHooks": True, "autoMemoryEnabled": False}


def judge_args(model: str, mcp_config_path: str, settings: dict | None = None) -> list[str]:
    """`claude -p` with the prompt on stdin, no tools, MCP servers, skills, hooks or user settings, and the verdict
    as structured output."""
    return [
        "claude",
        "-p",
        "--model",
        model,
        "--system-prompt",
        JUDGE_SYSTEM_PROMPT,
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        mcp_config_path,
        "--json-schema",
        json.dumps(JUDGE_SCHEMA),
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--settings",
        json.dumps(settings or JUDGE_SETTINGS),
        *setting_sources_args(True),
    ]


def judge_env(base, allow_api_billing: bool) -> tuple[dict, list[str]]:
    """The runner's session environment, with the claude.ai connectors and auto memory off too."""
    env, stripped = session_env(base, allow_api_billing)
    return env | {"ENABLE_CLAUDEAI_MCP_SERVERS": "false", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}, stripped


# Managed files besides the settings (https://code.claude.com/docs/en/memory, /managed-mcp): the managed
# CLAUDE.md, managed MCP servers, and a managed .claude directory (rules, skills, agents), in each managed dir.
MANAGED_FILES = ("CLAUDE.md", "managed-mcp.json", ".claude")


def _present(value) -> bool:
    """Whether a setting configures anything: `{"SessionStart": []}` or `{"plugin@market": false}` doesn't."""
    if isinstance(value, dict):
        return any(_present(v) for v in value.values())
    if isinstance(value, list):
        return any(_present(v) for v in value)
    return bool(value)


# Managed settings that put instructions, tools or servers in a session.
MANAGED_CONTEXT_KEYS = ("claudeMd", "enabledPlugins", "mcpServers", "agent", "outputStyle")


def _settings_dicts(obj):
    """The settings objects in a settings document (the server-managed cache wraps them), not descending into
    `hooks`, whose matcher objects have a `hooks` key of their own."""
    if isinstance(obj, dict):
        yield obj
        for key, value in obj.items():
            if key != "hooks":
                yield from _settings_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _settings_dicts(value)


def managed_customizations(env) -> list[str]:
    """`file: what` for each managed customization a judge session would inherit and can't switch off: managed
    hooks (unless the managed settings disable all hooks), managed CLAUDE.md (file or `claudeMd`), plugins,
    MCP servers, an agent or output style. Read from every managed source the runner's billing guard reads (the
    managed settings files and drop-ins, the MDM profile, the cached server-managed settings) plus the managed
    CLAUDE.md, MCP and .claude paths. `allowManagedHooksOnly` is listed with them. An unreadable file counts."""
    found, docs = [], []
    for path in settings_files(env, isolate_settings=True):
        try:
            raw = path.read_bytes()
            doc = claude_code.plistlib.loads(raw) if path.suffix == ".plist" else json.loads(raw)
        except (OSError, ValueError, claude_code.plistlib.InvalidFileException):
            found.append(f"{path}: unreadable")
            continue
        docs += [(path, settings) for settings in _settings_dicts(doc)]
    # Only a managed `disableAllHooks: true` turns managed hooks off; any managed `false` could override it.
    flags = [settings["disableAllHooks"] for _, settings in docs if "disableAllHooks" in settings]
    hooks_off = bool(flags) and all(flag is True for flag in flags)
    for path, settings in docs:
        if not hooks_off:
            found += [f"{path}: {k}" for k in ("hooks", "allowManagedHooksOnly") if _present(settings.get(k))]
        found += [f"{path}: {k}" for k in MANAGED_CONTEXT_KEYS if _present(settings.get(k))]
    for directory in claude_code.MANAGED_SETTINGS_DIRS:
        found += [f"{directory / name}" for name in MANAGED_FILES if (directory / name).exists()]
    return list(dict.fromkeys(found))


# What --json-schema adds to the session to return the verdict; it does nothing else.
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"


HOOK_EVENTS = {"hook_started", "hook_progress", "hook_response"}


def session_customizations(events: list[dict]) -> list[str]:
    """What the session had besides the structured-output tool, from its stream: other tools (built-in or MCP),
    MCP servers, plugin errors, and hooks that ran (SessionStart and Setup hooks always stream)."""
    found = []
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    if tools := sorted(t for t in init.get("tools") or [] if t != STRUCTURED_OUTPUT_TOOL):
        found.append(f"tools {tools}")
    for key in ("mcp_servers", "plugin_errors"):  # plugins: see plugin_guard
        if init.get(key):
            names = [x.get("name") or x.get("plugin") if isinstance(x, dict) else x for x in init[key]]
            found.append(f"{key} {names}")
    hooks = sorted(
        {
            str(e.get("hook_event") or e.get("hook_name") or e.get("subtype"))
            for e in events
            if e.get("type") == "system" and e.get("subtype") in HOOK_EVENTS
        }
    )
    if hooks:
        found.append(f"hooks {hooks}")
    return found


class ClaudeCodeJudge(BaseJudge):
    def __init__(
        self,
        model: str,
        allow_api_billing: bool = False,
        trust_org_policy: bool = False,
        allow_managed_customizations: bool = False,
        allow_plugins: bool = False,
        timeout_s: float = 300.0,
    ):
        self.claude_model = claude_code_model(model)
        self.model = JUDGE_ID_PREFIX + self.claude_model
        self.allow_api_billing = allow_api_billing
        self.trust_org_policy = trust_org_policy
        self.allow_managed_customizations = allow_managed_customizations
        self.timeout_s = timeout_s
        self.env, self.stripped_env = judge_env(os.environ, allow_api_billing)
        # Before any grading call: per-token billing (and unchecked org policies) are refused, user settings are
        # never loaded, and so is a managed customization that could put context or tools in front of the judge.
        self.auth = check_billing(self.env, True, allow_api_billing, trust_org_policy)
        self.managed_customizations = managed_customizations(self.env)
        if self.managed_customizations and not allow_managed_customizations:
            raise RuntimeError(
                "managed settings would give the judge sessions hooks, instructions, plugins or MCP servers that "
                f"a session can't turn off: {', '.join(self.managed_customizations)}. Grade with the Bedrock "
                "judge, or pass --judge-allow-managed-customizations to grade with them anyway (recorded in "
                "run.json)"
            )
        self._workdir = tempfile.TemporaryDirectory(prefix="mcp-qa-judge-")
        self.allow_plugins = allow_plugins
        try:
            self.settings, self.plugins = plugin_guard(
                self.env, self._workdir.name, True, allow_plugins, JUDGE_SETTINGS
            )
        except BaseException:
            self._workdir.cleanup()
            raise
        self.mcp_config_path = os.path.join(self._workdir.name, "no-mcp.json")
        write_private_json(self.mcp_config_path, {"mcpServers": {}})
        self.stopped: str | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        self._workdir.cleanup()

    def describe(self) -> dict:
        """How the judge sessions run, for run.json (names only, no values)."""
        return {
            "judge_model": self.model,
            "auth_mode": self.auth["mode"],
            "account_type": self.auth.get("subscription_type"),
            "allow_api_billing": self.allow_api_billing,
            "trust_org_policy": self.trust_org_policy,
            "allow_managed_customizations": self.allow_managed_customizations,
            "managed_customizations": self.managed_customizations,
            "allow_plugins": self.allow_plugins,
            "plugins": self.plugins,
            "disabled_plugins": sorted(self.settings["enabledPlugins"]),
            "stripped_env": self.stripped_env,
            "setting_sources": "managed only",
        }

    def _stop(self, reason: str) -> JudgeStopped:
        with self._lock:
            self.stopped = self.stopped or reason
        return JudgeStopped(self.stopped)

    def verdict(self, prompt: str) -> tuple[dict, int, int]:
        problem = ""
        for _ in range(ATTEMPTS):
            if self.stopped:
                raise JudgeStopped(self.stopped)
            try:
                return self._call(prompt)
            except JudgeOutputError as exc:
                problem = str(exc)
        raise JudgeOutputError(f"{problem} (after {ATTEMPTS} attempts)")

    def _call(self, prompt: str) -> tuple[dict, int, int]:
        try:
            out = subprocess.run(
                judge_args(self.claude_model, self.mcp_config_path, self.settings),
                input=prompt,
                cwd=self._workdir.name,  # empty: no project CLAUDE.md
                env=self.env,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise JudgeOutputError(f"timed out after {self.timeout_s:.0f}s") from exc
        lines = out.stdout.splitlines()
        if not self.allow_api_billing and bills_per_token(source := api_key_source(lines)):
            raise self._stop(api_billing_error(source))
        events = []
        for line in lines:
            if line.strip().startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        if (found := session_customizations(events)) and not self.allow_managed_customizations:
            raise self._stop(f"the judge session had {'; '.join(found)}; it must have none")
        plugins = session_plugins(lines)
        if plugins and not self.allow_plugins:
            raise self._stop(plugins_error(plugins))
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        verdict = (result or {}).get("structured_output")
        if result is None or result.get("is_error") or verdict is None:
            # Checked before any retry: a limit stops on the call that hit it.
            error = redact(str((result or {}).get("result") or (result or {}).get("subtype") or "no result"))
            stderr = redact(out.stderr or "")
            if USAGE_LIMIT.search(error) or USAGE_LIMIT.search(stderr):
                raise self._stop(
                    f"Claude subscription limit: {(error if USAGE_LIMIT.search(error) else stderr)[:300]}"
                )
        if result is None or result.get("is_error"):
            raise JudgeOutputError(f"claude failed: {error[:300]} (exit {out.returncode}: {stderr[-300:]})")
        verdict = parse_verdict(verdict if verdict is not None else (result.get("result") or ""))
        usage = result.get("usage") or {}
        input_tokens = sum(
            usage.get(k) or 0
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        # Recorded on the grade (BaseJudge.grade): which plugins this verdict's session loaded.
        return verdict | {"plugins": plugins}, input_tokens, usage.get("output_tokens") or 0
