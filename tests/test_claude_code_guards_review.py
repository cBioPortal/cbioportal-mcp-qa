"""Review fixes to the claude-code billing guard (fail closed before any model call) and to database_mcp_env."""

import asyncio
import json
import plistlib
from types import SimpleNamespace

import pytest

from cbioportal_mcp_qa import claude_code, cli, versions
from cbioportal_mcp_qa.claude_code import ClaudeCodeClient
from cbioportal_mcp_qa.claude_code import auth_status as real_auth_status

CONNECTOR = "claude.ai cBioPortal MCP"


class ModelCalls:
    """Records every `claude` invocation that could reach a model: the connector probe (`subprocess.run` of
    `claude -p`) and answers (`asyncio.create_subprocess_exec`). `claude auth status` gets `auth` as its output."""

    def __init__(self, monkeypatch, auth: dict | None = None):
        self.calls: list[list[str]] = []
        self.auth = auth

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["claude", "auth", "status"]:
                return SimpleNamespace(stdout=json.dumps(self.auth), stderr="", returncode=0)
            self.calls.append(cmd)
            init = {"type": "system", "subtype": "init", "apiKeySource": "none"}
            init["tools"] = ["mcp__claude_ai_cBioPortal_MCP__read_guide"]
            return SimpleNamespace(stdout=json.dumps(init), stderr="", returncode=0)

        async def fake_exec(*args, **kwargs):
            self.calls.append(list(args))
            raise AssertionError("no answer should be asked")

        monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        if auth is not None:
            monkeypatch.setattr(claude_code, "auth_status", real_auth_status)


def _connector_client(**kwargs) -> ClaudeCodeClient:
    """A client that probes the connector (a model call) as soon as the guard lets it."""
    return ClaudeCodeClient("PROMPT", "unused", "https://nav/mcp", database_connector=CONNECTOR, **kwargs)


def _managed(monkeypatch, tmp_path, settings: dict):
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "managed-settings.json").write_text(json.dumps(settings))
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (managed,))


SUBSCRIPTION = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "subscriptionType": "max",
}


# --- Blocking 1: every settings source isolated sessions still read -----------------------------------------


@pytest.mark.parametrize(
    "settings",
    [
        {"env": {"ANTHROPIC_AUTH_TOKEN": "bearer-from-policy"}},
        {"env": {"ANTHROPIC_API_KEY": "sk-ant-api03-from-policy"}},
        {"env": {"ANTHROPIC_BASE_URL": "https://gateway.example"}},
        {"env": {"CLAUDE_CODE_USE_BEDROCK": "1"}},
        {"env": {"ANTHROPIC_PROFILE": "console"}},
        {"apiKeyHelper": "vault read -field=key secret/anthropic"},
        {"policyHelper": "/usr/local/bin/policy"},
    ],
)
def test_managed_settings_that_bill_per_token_refuse_before_any_model_call(monkeypatch, tmp_path, settings):
    _managed(monkeypatch, tmp_path, settings)
    model = ModelCalls(monkeypatch, SUBSCRIPTION)
    with pytest.raises(RuntimeError, match="--claude-code-allow-api-billing"):
        _connector_client()
    assert model.calls == []


def test_mdm_profile_injecting_a_bearer_token_refuses(monkeypatch, tmp_path):
    prefs = tmp_path / "Managed Preferences"
    (prefs / "someone").mkdir(parents=True)
    (prefs / "someone" / "com.anthropic.claudecode.plist").write_bytes(
        plistlib.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "bearer-from-mdm"}})
    )
    monkeypatch.setattr(claude_code, "MANAGED_PREFERENCES_DIR", prefs)
    model = ModelCalls(monkeypatch, SUBSCRIPTION)
    with pytest.raises(RuntimeError, match="com.anthropic.claudecode.plist: env.ANTHROPIC_AUTH_TOKEN"):
        _connector_client()
    assert model.calls == []


def test_cached_server_managed_settings_injecting_an_api_key_refuse(monkeypatch, tmp_path):
    home = tmp_path / "claude-home-with-cache"
    home.mkdir()
    cache = {"uuid": "x", "settings": {"env": {"ANTHROPIC_API_KEY": "sk-ant-api03-from-console"}}}
    (home / "remote-settings.json").write_text(json.dumps(cache))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    model = ModelCalls(monkeypatch, SUBSCRIPTION)
    with pytest.raises(RuntimeError, match="remote-settings.json: env.ANTHROPIC_API_KEY"):
        _connector_client()
    assert model.calls == []


def test_an_unreadable_managed_settings_file_refuses(monkeypatch, tmp_path):
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "managed-settings.json").write_text("{not json")
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (managed,))
    ModelCalls(monkeypatch, SUBSCRIPTION)
    with pytest.raises(RuntimeError, match="unreadable"):
        _connector_client()


def test_profile_and_federation_credentials_are_stripped(monkeypatch):
    for name in ("ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_IDENTITY_TOKEN_FILE"):
        monkeypatch.setenv(name, "x")
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    try:
        assert {"ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_IDENTITY_TOKEN_FILE"} <= set(
            client.stripped_env
        )
        assert "ANTHROPIC_PROFILE" not in client.env
    finally:
        asyncio.run(client.aclose())


# --- Blocking 1: oauth_token is the subscription only when confirmed -----------------------------------------


def test_oauth_token_without_a_subscription_type_is_refused(monkeypatch):
    # A bearer token (e.g. from a policy's env block) and a subscription token both report as oauth_token.
    token = {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}
    model = ModelCalls(monkeypatch, token)
    with pytest.raises(RuntimeError, match="confirmed subscription"):
        _connector_client()
    assert model.calls == []


def test_oauth_token_with_a_bearer_token_in_user_settings_is_refused(monkeypatch, tmp_path):
    # Isolated sessions skip the user settings, but `claude auth status` reads them: its oauth_token may be that.
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "bearer-in-user-settings"}})
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    token = {
        "loggedIn": True,
        "authMethod": "oauth_token",
        "apiProvider": "firstParty",
        "subscriptionType": "max",
    }
    model = ModelCalls(monkeypatch, token)
    with pytest.raises(RuntimeError, match="settings.json: env.ANTHROPIC_AUTH_TOKEN"):
        _connector_client()
    assert model.calls == []


def test_a_confirmed_subscription_token_is_allowed(monkeypatch):
    token = {
        "loggedIn": True,
        "authMethod": "oauth_token",
        "apiProvider": "firstParty",
        "subscriptionType": "max",
    }
    model = ModelCalls(monkeypatch, token)
    client = _connector_client()
    try:
        assert client.describe()["auth_mode"] == "subscription"
        assert len(model.calls) == 1 and model.calls[0][:2] == ["claude", "-p"]  # the probe, after the guard
    finally:
        asyncio.run(client.aclose())


def test_a_claude_ai_login_without_a_subscription_type_is_refused(monkeypatch):
    model = ModelCalls(
        monkeypatch, {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}
    )
    with pytest.raises(RuntimeError, match="confirmed subscription"):
        _connector_client()
    assert model.calls == []


# --- Blocking 2: fail closed before the first billable call ------------------------------------------------


def test_unconfirmed_auth_refuses_before_the_connector_probe(monkeypatch):
    model = ModelCalls(monkeypatch)
    monkeypatch.setattr(
        claude_code, "auth_status", lambda env: {"mode": "unconfirmed", "auth_method": "api_key_helper"}
    )
    with pytest.raises(RuntimeError, match="--claude-code-allow-api-billing"):
        _connector_client()
    assert model.calls == []


def test_the_opt_in_allows_unconfirmed_auth_and_billing_settings(monkeypatch, tmp_path):
    _managed(monkeypatch, tmp_path, {"env": {"ANTHROPIC_AUTH_TOKEN": "bearer-from-policy"}})
    model = ModelCalls(monkeypatch)
    monkeypatch.setattr(
        claude_code, "auth_status", lambda env: {"mode": "unconfirmed", "auth_method": "oauth_token"}
    )
    client = _connector_client(allow_api_billing=True)
    try:
        assert client.describe()["auth_mode"] == "unconfirmed" and client.describe()["allow_api_billing"]
        assert len(model.calls) == 1  # the probe ran
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize(
    "source", ["ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "bearer", "apiKeyHelper"]
)
def test_a_session_with_a_token_or_helper_api_key_source_stops_the_run(monkeypatch, source):
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    lines = [
        json.dumps({"type": "system", "subtype": "init", "apiKeySource": source}),
        json.dumps({"type": "result", "subtype": "success", "result": "x"}),
    ]
    calls = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return ("\n".join(lines).encode(), b"")

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    try:
        first = asyncio.run(client.ask("q?", "haiku"))
        second = asyncio.run(client.ask("q2?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    assert source in first.error and second.error == first.error and len(calls) == 1
    assert not claude_code.bills_per_token("none")


# --- Non-blocking: database_mcp_env conflicts ---------------------------------------------------------------


def _settings(url=None, env=None, connector_url="https://mcp.cbioportal.org/db/mcp"):
    return SimpleNamespace(database_mcp_url=url, database_mcp_env=env, database_connector_url=connector_url)


@pytest.mark.parametrize(
    ("url", "declared", "expected"),
    [
        # Other spellings of prod's hosts
        ("https://MCP.cbioportal.org./db/mcp", None, "prod"),
        ("http://cbioagent-clickhouse-mcp.default.svc.cluster.local:80/db/mcp", None, "prod"),
        # A stale beta declaration on a prod host, and the reverse
        ("https://mcp.cbioportal.org/db/mcp", "beta", "conflict"),
        ("http://cbioagent-clickhouse-mcp:80/db/mcp", "beta", "conflict"),
        ("http://cbioagent-clickhouse-mcp-beta:80/db/mcp", "prod", "conflict"),
        (None, "beta", "conflict"),  # the connector's public (prod) endpoint
        # A declaration that agrees with the host
        ("http://cbioagent-clickhouse-mcp-beta:80/db/mcp", "beta", "beta"),
        # A port-forward only says what it is by declaration
        ("http://localhost:18081/db/mcp", "beta", "beta"),
        ("http://127.0.0.1:18081/db/mcp", "prod", "prod"),
        ("http://localhost:18081/db/mcp", None, "unknown"),
    ],
)
def test_database_mcp_env_conflicts(url, declared, expected):
    assert versions.database_mcp_env(_settings(url, declared)) == expected


def test_a_conflict_warns_on_any_target_and_fails_require_beta(capsys):
    stale = _settings("https://mcp.cbioportal.org/db/mcp", "beta")
    assert cli._check_database_mcp(stale, "prod", "claude-code", True) == "conflict"
    assert "WARNING" in capsys.readouterr().err
    assert cli._check_database_mcp(stale, "beta", "claude-code", False) == "conflict"
    assert "contradicts" in capsys.readouterr().err
    with pytest.raises(cli.click.ClickException, match="contradicts"):
        cli._check_database_mcp(stale, "beta", "claude-code", True)


def test_an_unknown_port_forward_warns_on_a_beta_target(capsys):
    unknown = _settings("http://localhost:18081/db/mcp")
    assert cli._check_database_mcp(unknown, "beta", "claude-code", False) == "unknown"
    assert "DATABASE_MCP_ENV=beta" in capsys.readouterr().err
