"""Answer questions with headless Claude Code standing in for the deployed agent.

The deployed agent's own instructions are the system prompt, the only tools are the same two MCP servers
(no Claude Code built-ins), and extended thinking is off to match the deployment. It runs on the Claude
subscription of the configured Claude home (CLAUDE_CONFIG_DIR) instead of per-token Bedrock billing, so it
is the cheap loop for iterating on prompts and guides; the Agents API runner remains the release check.
Credentials that would bill per token are kept out unless allowed, and so are the Claude home's user settings.
"""

import asyncio
import hashlib
import json
import os
import plistlib
import re
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .agent import AgentReply
from .agent_prompt import prompt_fingerprint
from .config import MODELS
from .persist import write_private_json, write_text
from .redact import describe_error, redact
from .traces import ToolCall, TraceStats, excerpt
from .versions import server_instructions

# Deliberately unlike the database connector's "claude_ai_cBioPortal_MCP": with two cBioPortal-looking tool
# prefixes the model mixes them up and calls navigator tools under the connector's name.
NAVIGATOR_SERVER = "navigator"
PROBE_ATTEMPTS = 4
CONNECTOR_ATTEMPTS = 4
HEADERS = {"x-user-id": "cbioportal-mcp-qa", "x-user-email": "cbioportal-mcp-qa@localhost"}

# What `claude -p` bills before the subscription login (https://code.claude.com/docs/en/authentication): a
# cloud provider (CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY/...), ANTHROPIC_AUTH_TOKEN, ANTHROPIC_API_KEY ("in
# non-interactive mode (-p), the key is always used when present"), an apiKeyHelper from the settings, and a
# named Anthropic profile or federation credentials (ANTHROPIC_PROFILE, ANTHROPIC_FEDERATION_RULE_ID).
# ANTHROPIC_BASE_URL goes too: a gateway would receive the subscription login. CLAUDE_CODE_OAUTH_TOKEN stays,
# it is a subscription token.
API_BILLING_ENV = re.compile(
    r"^(?:ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_BASE_URL|ANTHROPIC_PROFILE|ANTHROPIC_FEDERATION_\w+"
    r"|ANTHROPIC_IDENTITY_TOKEN\w*|CLAUDE_CODE_USE_\w+)$"
)
# Settings a session still reads with --setting-sources "" (user, project and local skipped): the managed ones
# (https://code.claude.com/docs/en/managed-settings): the system files and their drop-in directory, the macOS
# `com.anthropic.claudecode` managed-preferences profile (MDM), and the server-managed settings cached at
# <config dir>/remote-settings.json. A server-managed payload fetched fresh by a `-p` session isn't cached, so it
# can't be read here; neither can a policyHelper's output, so a policyHelper is refused.
MANAGED_SETTINGS_DIRS = (Path("/Library/Application Support/ClaudeCode"), Path("/etc/claude-code"))
MANAGED_PREFERENCES_DIR = Path("/Library/Managed Preferences")
MDM_PLIST = "com.anthropic.claudecode.plist"
# Plans whose logins can't receive server-managed settings, which only Claude for Teams and Enterprise have
# (https://code.claude.com/docs/en/server-managed-settings). A `-p` session fetches and applies such a policy
# without caching it, so a credential in its `env` can't be seen beforehand (and a bearer token there reports
# apiKeySource "none"): any other plan needs --claude-code-trust-org-policy.
NO_ORG_POLICY_PLANS = {"pro", "max"}
# A session's apiKeySource on the subscription login (also with a bearer token: that one is caught before).
NO_API_KEY_SOURCE = "none"


def session_env(base: Mapping[str, str], allow_api_billing: bool = False) -> tuple[dict, list[str]]:
    """The environment for `claude`, and the names of the billing variables taken out of it. Thinking is off to
    match the deployed agent (thinking=false); CLAUDE_CONFIG_DIR passes through."""
    env = {**base, "MAX_THINKING_TOKENS": "0"}
    stripped = [] if allow_api_billing else sorted(k for k in env if API_BILLING_ENV.match(k))
    for name in stripped:
        del env[name]
    return env, stripped


def config_dir(env: Mapping[str, str]) -> Path:
    return Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else Path.home() / ".claude"


def settings_files(env: Mapping[str, str], isolate_settings: bool) -> list[Path]:
    """The settings sources a benchmark session loads that exist on this machine (its working directory is empty,
    so no project files)."""
    files = [
        f
        for d in MANAGED_SETTINGS_DIRS
        for f in [d / "managed-settings.json", *sorted(d.glob("managed-settings.d/*.json"))]
    ]
    files += [MANAGED_PREFERENCES_DIR / MDM_PLIST, *sorted(MANAGED_PREFERENCES_DIR.glob(f"*/{MDM_PLIST}"))]
    files.append(config_dir(env) / "remote-settings.json")
    if not isolate_settings:
        files.append(config_dir(env) / "settings.json")
    return [p for p in files if p.is_file()]


def _dicts(obj):
    """Every dict in a settings document, however nested (the server-managed cache wraps the settings)."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _dicts(value)


def api_billing_settings(files: list[Path]) -> list[str]:
    """`file: key` for each setting that would (or might) bill per token: an apiKeyHelper, a policyHelper (its
    output can't be checked), or a billing variable in an `env` block. An unreadable file counts too."""
    found = []
    for path in files:
        try:
            raw = path.read_bytes()
            doc = plistlib.loads(raw) if path.suffix == ".plist" else json.loads(raw)
        except (OSError, ValueError, plistlib.InvalidFileException):
            found.append(f"{path}: unreadable")
            continue
        for settings in _dicts(doc):
            found += [f"{path}: {k}" for k in ("apiKeyHelper", "policyHelper") if settings.get(k)]
            env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
            found += [f"{path}: env.{k}" for k in sorted(env) if API_BILLING_ENV.match(k) and env[k]]
    return list(dict.fromkeys(found))


def auth_status(env: Mapping[str, str]) -> dict:
    """How `claude` authenticates with this environment, from `claude auth status` (no model call): `mode` is
    subscription, api-key, cloud-provider, none or unconfirmed. Identity (email, org) is left out.

    `claude auth status` reports a bearer token (ANTHROPIC_AUTH_TOKEN) and a subscription token
    (CLAUDE_CODE_OAUTH_TOKEN) alike as `oauth_token`, so only a login that also names its subscription type
    counts as the subscription."""
    out = subprocess.run(
        ["claude", "auth", "status", "--json"],
        env=dict(env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        status = json.loads(out.stdout)
    except ValueError:
        return {"mode": "unconfirmed", "error": redact(out.stderr or out.stdout)[-300:]}
    method, provider = status.get("authMethod"), status.get("apiProvider")
    subscription = status.get("subscriptionType")
    if provider and provider != "firstParty":
        mode = "cloud-provider"
    elif method in ("api_key", "api_key_helper") or (
        method == "oauth_token" and env.get("ANTHROPIC_AUTH_TOKEN")
    ):
        mode = "api-key"
    elif method in ("claude.ai", "oauth_token") and subscription:
        mode = "subscription"  # the /login OAuth, or CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`)
    elif method == "none" or status.get("loggedIn") is False:
        mode = "none"
    else:
        mode = "unconfirmed"
    info = {"mode": mode, "auth_method": method, "api_provider": provider}
    if subscription:
        info["subscription_type"] = subscription
    # Whether the login belongs to an organization (not which: ids and names stay out of run.json).
    info["organization"] = bool(status.get("orgId") or status.get("orgName"))
    return info


def api_key_source(lines: list[str]) -> str | None:
    """The session's `apiKeySource` from its stream-json init event."""
    for line in lines:
        if line.startswith("{") and '"init"' in line:
            event = json.loads(line)
            if event.get("subtype") == "init":
                return event.get("apiKeySource")
    return None


def bills_per_token(source: str | None) -> bool:
    """Whether a session's apiKeySource names a per-token credential (ANTHROPIC_API_KEY, apiKeyHelper, a Console
    /login key, a token or bearer source). A bearer token reports "none" like the subscription, so this is only
    the backstop for what `check_billing` can't see."""
    if not source or source == NO_API_KEY_SOURCE:
        return False
    return any(word in source.lower() for word in ("key", "token", "helper", "bearer"))


def check_billing(
    env: Mapping[str, str], isolate_settings: bool, allow_api_billing: bool, trust_org_policy: bool = False
) -> dict:
    """The auth status sessions will run with. Unless API billing is allowed, anything but a confirmed
    subscription login is refused here, before the first model call (the connector probe included), and so is
    a plan that can receive server-managed settings (Team, Enterprise, or one this doesn't recognise) unless
    its organization's policy is trusted."""
    found = api_billing_settings(settings_files(env, isolate_settings))
    status = auth_status(env)
    if allow_api_billing:
        return status
    if found:
        raise RuntimeError(
            "these settings would (or might) bill claude per token instead of the subscription login: "
            f"{', '.join(found)}; remove them or pass --claude-code-allow-api-billing"
        )
    # `claude auth status` also reads the user settings the sessions skip: a bearer token set there reports as
    # `oauth_token` too, so the login below it can't be confirmed.
    bearer = [f for f in api_billing_settings(settings_files(env, False)) if "ANTHROPIC_AUTH_TOKEN" in f]
    if status["mode"] == "subscription" and status.get("auth_method") == "oauth_token" and bearer:
        status = status | {"mode": "unconfirmed"}
    if status["mode"] != "subscription":
        raise RuntimeError(
            f"claude isn't on a confirmed subscription login (claude auth status: {status.get('auth_method')!r}, "
            f"provider {status.get('api_provider')!r}, subscription {status.get('subscription_type')!r}"
            f"{'; ' + ', '.join(bearer) if bearer else ''}); log in with `claude` (/login) for this "
            "CLAUDE_CONFIG_DIR, remove an apiKeyHelper or billing variable from its settings, or pass "
            "--claude-code-allow-api-billing"
        )
    plan = str(status.get("subscription_type") or "").lower()
    if plan not in NO_ORG_POLICY_PLANS and not trust_org_policy:
        raise RuntimeError(
            f"this Claude login's plan ({status.get('subscription_type')!r}) can receive server-managed settings "
            "from its organization, which a `claude -p` session fetches and applies without caching, so a "
            "credential they set (e.g. ANTHROPIC_AUTH_TOKEN) can't be checked before answers are billed to it. "
            "If you trust your organization's Claude Code policy not to route sessions to per-token billing, pass "
            "--claude-code-trust-org-policy (or CLAUDE_CODE_TRUST_ORG_POLICY=1); only Pro and Max logins run "
            "without it"
        )
    return status


@dataclass
class ToolSetup:
    """The MCP servers Claude Code gets. `servers` are plain URLs written to an --mcp-config file: the navigator
    always (its public endpoint needs no login), and the database too when it's reached by URL (port-forward).
    `connector` is a claude.ai connector used for the database instead: its public endpoint needs the OAuth
    login that only the connector holds. The other claude.ai connectors go in `disallowed`."""

    servers: dict[str, str]
    connector: str | None = None
    disallowed: list[str] = field(default_factory=list)

    def mcp_config(self) -> dict:
        return {
            "mcpServers": {n: {"type": "http", "url": u, "headers": HEADERS} for n, u in self.servers.items()}
        }

    @property
    def allowed(self) -> list[str]:
        prefixes = [f"mcp__{name}" for name in self.servers]
        return prefixes + ([f"mcp__{connector_tool_prefix(self.connector)}"] if self.connector else [])


def find_connector(url: str, env: dict | None = None) -> str | None:
    """The claude.ai connector (by whatever name it has in this Claude home) that points at `url`."""
    out = subprocess.run(
        ["claude", "mcp", "list"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    for line in out.splitlines():
        name, sep, rest = line.partition(": ")
        if (
            sep
            and name.startswith("claude.ai ")
            and rest.split(" - ")[0].strip().rstrip("/") == url.rstrip("/")
        ):
            return name
    return None


def connector_tool_prefix(connector: str) -> str:
    """'claude.ai cBioPortal MCP' → 'claude_ai_cBioPortal_MCP', the server segment of its tool names."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", connector)


def tool_setup(
    database_url: str,
    navigator_url: str,
    connector: str | None,
    workdir: str,
    env: dict,
    isolate_settings: bool = True,
    allow_api_billing: bool = False,
    settings: dict | None = None,
    allow_plugins: bool = False,
) -> ToolSetup:
    if not connector:
        return ToolSetup({"cbioportal-database": database_url, NAVIGATOR_SERVER: navigator_url})
    setup = ToolSetup({NAVIGATOR_SERVER: navigator_url}, connector)
    wanted = connector_tool_prefix(connector)
    loaded = probe_mcp_servers(
        setup, workdir, env, isolate_settings, allow_api_billing, settings, allow_plugins
    )
    if wanted not in loaded:
        raise RuntimeError(
            f"claude.ai connector {connector!r} did not load for this Claude home — it may need you to sign in "
            f"again (claude.ai → Settings → Connectors, or /mcp in claude); loaded: {sorted(loaded)}"
        )
    # Every other claude.ai connector would otherwise be visible to the model.
    setup.disallowed = [f"mcp__{s}" for s in sorted(loaded) if s.startswith("claude_ai_") and s != wanted]
    return setup


def loaded_servers(lines: list[str]) -> set[str] | None:
    """MCP servers whose tools the session actually had, from the stream-json init event (None if absent)."""
    for line in lines:
        if line.startswith("{") and '"init"' in line:
            event = json.loads(line)
            if event.get("subtype") == "init":
                return {t.split("__")[1] for t in event.get("tools", []) if t.startswith("mcp__")}
    return None


# Plugins built into the claude binary (2.1.287): they load in every session, even with no settings sources, and
# report as `<name>@builtin` in the init event. agents-md loads AGENTS.md as project instructions, telemetry lets
# plugins log analytics events, plugin-authoring is a skill, the rest are interactive UI (tips, diff, mermaid,
# ...). All but cc-plugin-sec-default turn off with `enabledPlugins: {"<id>": false}` in --settings; sec-default
# (seated for Team and Enterprise logins and on machines with managed settings) only turns off by managed
# policy. The preflight finds any other plugin a session would load.
BUILTIN_PLUGINS = (
    "cc-plugin-sec-default",
    "cc-plugin-agents-md",
    "cc-plugin-telemetry",
    "cc-plugin-plugin-authoring",
    "cc-plugin-mods-guide",
    "cc-plugin-tips",
    "cc-plugin-mermaid",
    "cc-plugin-responsive-mode",
    "cc-plugin-diff",
    "cc-plugin-you-should-know",
    "cc-plugin-claude-test",
)
# A model no account has: the preflight session emits its init event (plugins, apiKeySource) and then fails with
# model_not_found before anything is generated or billed.
PREFLIGHT_MODEL = "claude-mcp-qa-preflight-no-such-model"


def no_plugins_settings(extra: list[str] = ()) -> dict:
    """--settings that turn off the built-in plugins and `extra` (plugin ids a preflight found)."""
    ids = [f"{name}@builtin" for name in BUILTIN_PLUGINS] + list(extra)
    return {"enabledPlugins": dict.fromkeys(ids, False)}


def stream_events(lines: list[str]) -> list[dict]:
    """The stream-json events in `lines`, skipping anything that isn't a JSON object."""
    events = []
    for line in lines:
        if line.strip().startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def init_event(lines: list[str]) -> dict | None:
    return next((e for e in stream_events(lines) if e.get("subtype") == "init"), None)


def session_plugins(lines: list[str]) -> list[str] | None:
    """The plugins a session loaded (`name@marketplace`), from its stream-json init event. None when there is no
    init event or it has no plugin list: the session's plugins are unknown, and callers refuse it."""
    plugins = (init_event(lines) or {}).get("plugins")
    if not isinstance(plugins, list):
        return None
    return [str(p.get("source") or p.get("name")) if isinstance(p, dict) else str(p) for p in plugins]


def preflight_problem(lines: list[str]) -> str | None:
    """Why the preflight session might have reached a model, or None if it provably ended before generation:
    a model_not_found error for PREFLIGHT_MODEL, no tokens in or out, and nothing billed."""
    events = stream_events(lines)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None:
        return "no result"
    model_not_found = any(e.get("error") == "model_not_found" for e in events if e.get("type") == "assistant")
    if not (result.get("is_error") and PREFLIGHT_MODEL in str(result.get("result")) and model_not_found):
        return f"it didn't fail on the missing model: {redact(str(result.get('result')))[:300]!r}"
    usage = result.get("usage") or {}
    if tokens := {k: v for k, v in usage.items() if k.endswith("_tokens") and v}:
        return f"it used tokens {tokens}"
    if result.get("modelUsage"):
        return f"it used models {sorted(result['modelUsage'])}"
    if result.get("total_cost_usd", 0) != 0:
        return f"it cost ${result['total_cost_usd']}"
    return None


def plugins_problem(
    plugins: list[str] | None, allow_plugins: bool, what: str = "claude session"
) -> str | None:
    """Why a session's plugins stop the run, or None. A session that didn't report its plugins always stops:
    what it loaded is unknown, and an accepted answer or grade must record it."""
    if plugins is None:
        return (
            f"the {what} didn't report its plugins (no init event with a plugin list), so what it loaded is "
            "unknown; it is refused even with --claude-code-allow-plugins"
        )
    if plugins and not allow_plugins:
        return plugins_error(plugins, what)
    return None


def preflight_plugins(
    env: Mapping[str, str], workdir: str, settings: dict, isolate_settings: bool
) -> list[str]:
    """The plugins a session with these settings loads, from a session on PREFLIGHT_MODEL: no model call."""
    config = os.path.join(workdir, "preflight-mcp.json")
    write_private_json(config, {"mcpServers": {}})
    cmd = ["claude", "-p", "Reply OK.", "--model", PREFLIGHT_MODEL, "--tools", "", "--strict-mcp-config"]
    cmd += ["--mcp-config", config, "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    cmd += ["--settings", json.dumps(settings), *setting_sources_args(isolate_settings)]
    try:
        out = subprocess.run(
            cmd,
            cwd=workdir,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not start claude to check its plugins: {exc}") from exc
    lines = out.stdout.splitlines()
    plugins = session_plugins(lines)
    if plugins is None:
        raise RuntimeError(f"could not start claude to check its plugins: {redact(out.stderr)[-500:]}")
    if problem := preflight_problem(lines):
        raise RuntimeError(
            f"the plugin preflight did not end before generation: {problem}. It must fail on the missing model "
            f"{PREFLIGHT_MODEL!r} with no tokens and no cost; refusing to start"
        )
    return plugins


def plugin_guard(
    env: Mapping[str, str],
    workdir: str,
    isolate_settings: bool,
    allow_plugins: bool,
    base: dict | None = None,
) -> tuple[dict, list[str]]:
    """The --settings for every session (`base` plus every plugin turned off that can be) and the plugins the
    sessions still load. A plugin the first preflight finds is turned off and checked again; whatever stays
    can't be turned off from a session and is refused unless plugins are allowed."""
    settings = (base or {}) | no_plugins_settings()
    found = preflight_plugins(env, workdir, settings, isolate_settings)
    if new := [p for p in found if p not in settings["enabledPlugins"]]:
        settings = (base or {}) | no_plugins_settings(new)
        found = preflight_plugins(env, workdir, settings, isolate_settings)
    if found and not allow_plugins:
        raise RuntimeError(
            f"claude sessions would load plugins that can't be turned off from a session: {', '.join(found)} "
            "(cc-plugin-sec-default is seated for Team and Enterprise logins and on machines with managed "
            "settings). Use a Pro or Max login, or pass --claude-code-allow-plugins to run with them (recorded "
            "in run.json)"
        )
    return settings, found


def plugins_error(plugins: list[str], what: str = "claude session") -> str:
    return (
        f"the {what} loaded plugins {plugins} that the preflight didn't find; pass "
        "--claude-code-allow-plugins to allow them"
    )


def setting_sources_args(isolate_settings: bool) -> list[str]:
    """No user, project or local settings: ~/.claude's effortLevel, hooks, plugins and apiKeyHelper stay out of
    benchmark sessions (managed settings still apply). The login and claude.ai connectors aren't settings."""
    return ["--setting-sources", ""] if isolate_settings else []


def api_billing_error(source: str | None) -> str:
    return (
        f"claude billed this session per token (apiKeySource {source!r}), not the subscription login; pass "
        "--claude-code-allow-api-billing to allow that"
    )


def probe_mcp_servers(
    setup: ToolSetup,
    workdir: str,
    env: dict,
    isolate_settings: bool = True,
    allow_api_billing: bool = False,
    settings: dict | None = None,
    allow_plugins: bool = False,
) -> set[str]:
    """The MCP servers a Claude Code session loads, read from the stream-json init event of a trivial call."""
    config = os.path.join(workdir, "probe-mcp.json")
    write_private_json(config, setup.mcp_config())
    cmd = [
        "claude",
        "-p",
        "Reply OK.",
        "--tools",
        "",
        "--mcp-config",
        config,
        "--output-format",
        "stream-json",
    ]
    cmd += ["--verbose", "--no-session-persistence", "--model", MODELS["haiku"].claude_code_id]
    cmd += [
        "--settings",
        json.dumps(settings or no_plugins_settings()),
        *setting_sources_args(isolate_settings),
    ]
    # claude.ai connectors load only some of the time in headless mode, so retry until one shows up.
    seen: set[str] = set()
    for _ in range(PROBE_ATTEMPTS):
        out = subprocess.run(
            cmd, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180
        )
        lines = out.stdout.splitlines()
        servers = loaded_servers(lines)
        if servers is None:
            raise RuntimeError(f"could not start claude to probe MCP servers: {redact(out.stderr)[-500:]}")
        if not allow_api_billing and bills_per_token(source := api_key_source(lines)):
            raise RuntimeError(api_billing_error(source))
        if problem := plugins_problem(session_plugins(lines), allow_plugins, "connector probe session"):
            raise RuntimeError(problem)
        seen |= servers
        if any(name.startswith("claude_ai_") for name in servers):
            break
    return seen


def claude_args(
    question: str,
    model: str,
    system_prompt: str,
    setup: ToolSetup,
    mcp_config_path: str,
    isolate_settings: bool = True,
    settings: dict | None = None,
) -> list[str]:
    args = [
        "claude",
        "-p",
        question,
        "--model",
        MODELS[model].claude_code_id,
        "--system-prompt",
        system_prompt,
        "--tools",
        "",
        "--mcp-config",
        mcp_config_path,
        "--allowedTools",
        *setup.allowed,
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--settings",
        json.dumps(settings or no_plugins_settings()),
        *setting_sources_args(isolate_settings),
    ]
    if setup.connector is None:
        args.insert(args.index("--mcp-config"), "--strict-mcp-config")
    if setup.disallowed:
        args += ["--disallowedTools", *setup.disallowed]
    return args


def short_tool_name(name: str) -> str:
    return name.split("__", 2)[-1] if name.startswith("mcp__") else name


RESULT_CHARS = 3000


def conversation_prompt(question: str, history: tuple[dict, ...]) -> str:
    """`claude -p` takes one message, so earlier turns are quoted ahead of the user's new message."""
    if not history:
        return question
    turns = "\n\n".join(f"<{t['role']}>\n{t['content']}\n</{t['role']}>" for t in history)
    return (
        f"<conversation_so_far>\n{turns}\n</conversation_so_far>\n\n"
        f"Continue this conversation: reply to the user's new message.\n\n<user>\n{question}\n</user>"
    )


def connector_needs_signin(lines: list[str], connector: str) -> bool:
    """Whether the claude.ai connector's login has expired: its init status or a tool error says so."""
    for line in lines:
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event.get("subtype") == "init":
            for server in event.get("mcp_servers") or []:
                if server.get("name") == connector and server.get("status") == "needs-auth":
                    return True
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                if "sign in" in json.dumps(block.get("content")):
                    return True
    return False


# The Claude subscription's usage limit, as `claude -p` reports it (shared by the runner and the judge):
# "You've hit your limit · resets 5pm" (2.1.287), "hit your session / weekly / 5-hour / Opus limit",
# "usage limit reached", and a rate limit that names its reset. A plain transient 429 has no reset time.
USAGE_LIMIT = re.compile(
    r"hit your (?:[\w-]+ ){0,3}limit"
    r"|usage limit"
    r"|\b(?:session|weekly|daily|5-hour|five-hour) limit\b.{0,40}\b(?:reached|exceeded|resets?)\b"
    r"|rate limit\b.{0,80}\bresets?\b|\bresets?\b.{0,80}\brate limit",
    re.IGNORECASE,
)


def tool_result_text(content) -> str:
    """A tool_result block's text, unwrapping the MCP `{"result": "..."}` envelope."""
    if isinstance(content, list):
        text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    else:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    try:
        wrapped = json.loads(text)
        if isinstance(wrapped, dict) and isinstance(wrapped.get("result"), str):
            return wrapped["result"]
    except ValueError:
        pass
    return text


def format_transcript(lines: list[str]) -> str:
    """A readable transcript: every tool call with its arguments and (truncated) result, then the answer."""
    out: list[str] = []
    for line in lines:
        if not line.strip().startswith("{"):
            continue
        event = json.loads(line)
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                args = json.dumps(block.get("input"), indent=1, ensure_ascii=False)
                out.append(f"▶ {short_tool_name(block['name'])}\n{args.replace(chr(92) + 'n', chr(10))}\n")
            elif block.get("type") == "tool_result":
                text = tool_result_text(block.get("content"))
                label = "✗ error" if block.get("is_error") else "◀ result"
                more = f" … ({len(text) - RESULT_CHARS} more chars)" if len(text) > RESULT_CHARS else ""
                out.append(f"{label}\n{text[:RESULT_CHARS]}{more}\n")
        if event.get("type") == "result":
            out.append(f"═ answer ({event.get('subtype')})\n{event.get('result') or ''}\n")
    return redact("\n".join(out))


def parse_stream(lines: list[str], started: float, latency_s: float) -> AgentReply:
    """Turn `claude -p --output-format stream-json` events into a reply with its tool-call trace."""
    events = [json.loads(line) for line in lines if line.strip().startswith("{")]
    calls: dict[str, ToolCall] = {}
    message_ids: set[str] = set()
    models: set[str] = set()
    for event in events:
        message = event.get("message") or {}
        if event.get("type") == "assistant":
            message_ids.add(message.get("id") or str(len(message_ids)))
            if message.get("model"):
                models.add(message["model"])
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    calls[block["id"]] = ToolCall(
                        short_tool_name(block["name"]),
                        True,
                        input=excerpt(redact(json.dumps(block.get("input"), ensure_ascii=False))),
                    )
        elif event.get("type") == "user":
            for block in message.get("content") or []:
                if block.get("type") != "tool_result" or block.get("tool_use_id") not in calls:
                    continue
                call = calls[block["tool_use_id"]]
                call.result = excerpt(redact(tool_result_text(block.get("content"))))
                if block.get("is_error"):
                    content = block.get("content")
                    call.ok = False
                    call.error = redact(content if isinstance(content, str) else json.dumps(content))[:500]
    result = next((e for e in events if e.get("type") == "result"), None)
    trace = TraceStats("", "", len(message_ids), list(calls.values()), sorted(models))
    if result is None or result.get("is_error"):
        error = (result or {}).get("result") or (result or {}).get("subtype") or "no result event"
        return AgentReply(
            "", None, None, redact(str(error))[:2000], latency_s, started, trace=trace.to_dict()
        )
    usage = result.get("usage") or {}
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    return AgentReply(
        answer=result.get("result") or "",
        response_id=None,
        status=200,
        error=None,
        latency_s=latency_s,
        started_at=started,
        prompt_tokens=(usage.get("input_tokens") or 0) + cache_read + cache_write,
        completion_tokens=usage.get("output_tokens"),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        trace=trace.to_dict(),
    )


# Claude Code sends the MCP servers' `instructions` itself, with --system-prompt too: a "# MCP Server
# Instructions" system-reminder in the first user turn, after the system prompt (seen in the request Claude
# Code 2.1.283 sends). That is LibreChat's order with `serverInstructions: true` (agent instructions, then the
# server's), so the runner doesn't append them again; it records which ones the sessions got.
SERVER_INSTRUCTIONS_DELIVERY = "claude-code (system-reminder after the system prompt)"


def prompt_parity(system_prompt: str, database_url: str | None, fetch=None) -> dict:
    """Hashes of the agent instructions, the database MCP's server instructions, and both in LibreChat's order
    (agent instructions, a blank line, server instructions) as `combined`."""
    out = {
        "system_prompt": prompt_fingerprint(system_prompt),
        "server_instructions_delivery": SERVER_INSTRUCTIONS_DELIVERY,
    }
    if not database_url:
        out["server_instructions"] = {
            "error": "not read: the claude.ai connector's endpoint needs its OAuth login"
        }
        return out
    try:
        instructions = (fetch or server_instructions)(database_url)
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal
        out["server_instructions"] = {"error": describe_error(exc)}
        return out
    if not instructions:
        out["server_instructions"] = None
        return out
    out["server_instructions"] = prompt_fingerprint(instructions)
    out["combined"] = prompt_fingerprint(f"{system_prompt}\n\n{instructions}")
    return out


class ClaudeCodeClient:
    """Same interface as AgentClient: `await ask(question, model)` returns an AgentReply (with its trace)."""

    def __init__(
        self,
        system_prompt: str,
        database_url: str,
        navigator_url: str,
        database_connector: str | None = None,
        timeout_s: float = 900.0,
        retries: int = 1,
        transcript_dir: Path | None = None,
        allow_api_billing: bool = False,
        isolate_settings: bool = True,
        trust_org_policy: bool = False,
        allow_plugins: bool = False,
    ):
        self.system_prompt = system_prompt
        self.transcript_dir = transcript_dir
        self.signin_expired = False
        self.usage_limit: str | None = None
        self.api_billing: str | None = None
        self.plugins_error: str | None = None
        self.timeout_s = timeout_s
        self.retries = retries
        self.allow_api_billing = allow_api_billing
        self.isolate_settings = isolate_settings
        self.env, self.stripped_env = session_env(os.environ, allow_api_billing)
        self.trust_org_policy = trust_org_policy
        self.auth = check_billing(self.env, isolate_settings, allow_api_billing, trust_org_policy)
        self._workdir = tempfile.TemporaryDirectory(prefix="mcp-qa-claude-")
        self.allow_plugins = allow_plugins
        # Before the first model call (the connector probe included): plugins are turned off, and one that can't
        # be is refused unless allowed.
        try:
            self.settings, self.plugins = plugin_guard(
                self.env, self._workdir.name, isolate_settings, allow_plugins
            )
        except BaseException:
            self._workdir.cleanup()
            raise
        self.setup = tool_setup(
            database_url,
            navigator_url,
            database_connector,
            self._workdir.name,
            self.env,
            isolate_settings,
            allow_api_billing,
            self.settings,
            allow_plugins,
        )
        self.mcp_config_path = os.path.join(self._workdir.name, "mcp.json")
        write_private_json(self.mcp_config_path, self.setup.mcp_config())

    async def aclose(self) -> None:
        self._workdir.cleanup()

    def describe(self) -> dict:
        """How sessions authenticate and which settings they load, for run.json (names only, no values)."""
        return {
            "auth_mode": self.auth["mode"],
            "auth_status": self.auth,
            "account_type": self.auth.get("subscription_type"),
            "allow_api_billing": self.allow_api_billing,
            "trust_org_policy": self.trust_org_policy,
            "stripped_env": self.stripped_env,
            "setting_sources": "managed only" if self.isolate_settings else "user, project, local",
            "allow_plugins": self.allow_plugins,
            "plugins": self.plugins,
            "disabled_plugins": sorted(self.settings["enabledPlugins"]),
        }

    def signin_message(self) -> str:
        return f"claude.ai connector {self.setup.connector!r} needs you to sign in again"

    async def ask(self, question: str, model: str, history: tuple[dict, ...] = ()) -> AgentReply:
        question = conversation_prompt(question, history)
        started = time.time()
        retries = connector_misses = 0
        while True:
            if self.signin_expired:
                return AgentReply("", None, None, self.signin_message(), 0.0, started)
            if stop := self.usage_limit or self.api_billing or self.plugins_error:
                return AgentReply("", None, None, stop, 0.0, started)
            reply = await self._run(question, model, started)
            if reply.error is None:
                return reply
            if self.signin_expired or self.usage_limit or self.api_billing or self.plugins_error:
                return reply
            if "did not load in this session" in reply.error:
                # The attempt never had the database tools; retry it without using up a regular retry.
                connector_misses += 1
                if connector_misses < CONNECTOR_ATTEMPTS:
                    continue
            elif retries < self.retries:
                retries += 1
                await asyncio.sleep(10)
                continue
            return reply

    async def _run(self, question: str, model: str, started: float) -> AgentReply:
        t0 = time.monotonic()
        # An empty working directory keeps project CLAUDE.md files out of the context.
        proc = await asyncio.create_subprocess_exec(
            *claude_args(
                question,
                model,
                self.system_prompt,
                self.setup,
                self.mcp_config_path,
                self.isolate_settings,
                self.settings,
            ),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workdir.name,
            env=self.env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return AgentReply(
                "", None, None, f"timed out after {self.timeout_s:.0f}s", time.monotonic() - t0, started
            )
        lines = stdout.decode().splitlines()
        reply = parse_stream(lines, started, time.monotonic() - t0)
        if not self.allow_api_billing and bills_per_token(source := api_key_source(lines)):
            # Stop asking: every later session would bill the same way.
            self.api_billing = api_billing_error(source)
            reply.status = None
            reply.error = self.api_billing
            return reply
        plugins = session_plugins(lines)
        if reply.trace is not None:
            reply.trace["plugins"] = plugins
        # A session that failed before its init event is an ordinary failure; an answer is only accepted with its
        # plugins known.
        if (plugins is not None or reply.error is None) and (
            problem := plugins_problem(plugins, self.allow_plugins)
        ):
            # Stop asking: the preflight said there would be none, so every later session would have them too.
            self.plugins_error = problem
            reply.status = None
            reply.error = problem
            return reply
        if reply.error and USAGE_LIMIT.search(reply.error):
            self.usage_limit = reply.error
            return reply
        if self.setup.connector and connector_needs_signin(lines, self.setup.connector):
            self.signin_expired = True
            reply.status = None
            reply.error = self.signin_message()
            return reply
        if self.setup.connector and connector_tool_prefix(self.setup.connector) not in (
            loaded_servers(lines) or set()
        ):
            reply.status = None
            reply.error = f"claude.ai connector {self.setup.connector!r} did not load in this session"
            return reply
        if self.transcript_dir is not None and reply.trace is not None:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha1(f"{model}:{question}:{started}".encode()).hexdigest()[:12] + ".txt"
            write_text(self.transcript_dir / name, f"Q ({model}): {question}\n\n{format_transcript(lines)}")
            reply.trace["url"] = f"{self.transcript_dir.name}/{name}"
        if reply.error and proc.returncode:
            reply.error = f"{reply.error} (exit {proc.returncode}: {redact(stderr.decode())[-500:]})"
        return reply
