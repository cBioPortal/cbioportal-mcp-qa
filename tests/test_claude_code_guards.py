"""The claude-code runner's billing guard, settings isolation, beta MCP awareness and prompt record."""

import asyncio
import json
import tempfile
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from cbioportal_mcp_qa import claude_code, cli, versions
from cbioportal_mcp_qa.claude_code import (
    ClaudeCodeClient,
    ToolSetup,
    api_billing_settings,
    api_key_source,
    auth_status,
    bills_per_token,
    claude_args,
    probe_mcp_servers,
    prompt_parity,
    session_env,
    settings_files,
)
from cbioportal_mcp_qa.mcp_http import MCPSession

BILLING_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-api03-guardtestguardtest",
    "ANTHROPIC_AUTH_TOKEN": "gateway-bearer-guardtest",
    "ANTHROPIC_BASE_URL": "https://gateway.example",
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLAUDE_CODE_USE_FOUNDRY": "1",
    "CLAUDE_CODE_USE_SOMETHING_NEW": "1",
}


def _init(source: str | None, tools=()) -> str:
    return json.dumps({"type": "system", "subtype": "init", "tools": list(tools), "apiKeySource": source})


# --- 1. Billing guard -------------------------------------------------------------------------------------


def test_session_env_strips_per_token_billing_and_keeps_the_subscription():
    base = {
        **BILLING_ENV,
        "CLAUDE_CONFIG_DIR": "/home/x/.claude",
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription-token",
        "PATH": "/bin",
    }
    env, stripped = session_env(base)

    assert stripped == sorted(BILLING_ENV)
    assert not set(BILLING_ENV) & set(env)
    assert env["CLAUDE_CONFIG_DIR"] == "/home/x/.claude"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "subscription-token"
    assert env["MAX_THINKING_TOKENS"] == "0"
    assert base["ANTHROPIC_API_KEY"]  # the caller's environment is untouched

    kept, none = session_env(base, allow_api_billing=True)
    assert none == [] and kept["ANTHROPIC_API_KEY"] == BILLING_ENV["ANTHROPIC_API_KEY"]
    assert kept["MAX_THINKING_TOKENS"] == "0"


def test_billing_settings_are_found_in_the_files_sessions_load(monkeypatch, tmp_path):
    managed = tmp_path / "managed"
    (managed / "managed-settings.d").mkdir(parents=True)
    (managed / "managed-settings.json").write_text(json.dumps({"env": {"CLAUDE_CODE_USE_BEDROCK": "1"}}))
    (managed / "managed-settings.d" / "10-helper.json").write_text(json.dumps({"apiKeyHelper": "vault get"}))
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"apiKeyHelper": "echo key", "effortLevel": "high"}))
    env = {"CLAUDE_CONFIG_DIR": str(home)}

    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (managed,))
    isolated = settings_files(env, isolate_settings=True)
    assert isolated == [managed / "managed-settings.json", managed / "managed-settings.d" / "10-helper.json"]
    assert settings_files(env, isolate_settings=False) == [*isolated, home / "settings.json"]

    found = api_billing_settings(settings_files(env, isolate_settings=False))
    assert found == [
        f"{managed / 'managed-settings.json'}: env.CLAUDE_CODE_USE_BEDROCK",
        f"{managed / 'managed-settings.d' / '10-helper.json'}: apiKeyHelper",
        f"{home / 'settings.json'}: apiKeyHelper",
    ]
    # Values never appear, only where the setting is.
    assert "vault get" not in " ".join(found) and "echo key" not in " ".join(found)


@pytest.mark.parametrize(
    ("status", "env", "mode"),
    [
        ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}, {}, "subscription"),
        ({"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}, {}, "subscription"),
        (
            {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"},
            {"ANTHROPIC_AUTH_TOKEN": "x"},
            "api-key",
        ),
        ({"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}, {}, "api-key"),
        ({"loggedIn": True, "authMethod": "api_key_helper", "apiProvider": "firstParty"}, {}, "api-key"),
        ({"loggedIn": True, "authMethod": "third_party", "apiProvider": "bedrock"}, {}, "cloud-provider"),
        ({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}, {}, "none"),
        ({"loggedIn": True, "authMethod": "something_new", "apiProvider": "firstParty"}, {}, "unconfirmed"),
    ],
)
def test_auth_status_names_the_billing_mode(monkeypatch, status, env, mode):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["env"] = cmd, kwargs["env"]
        payload = status | {"email": "someone@example.org", "orgId": "org-1", "subscriptionType": "team"}
        return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    info = auth_status(env)

    assert seen["cmd"] == ["claude", "auth", "status", "--json"] and seen["env"] == env
    assert info["mode"] == mode and info["auth_method"] == status["authMethod"]
    assert "email" not in json.dumps(info) and "org-1" not in json.dumps(info)


def test_client_refuses_anything_but_the_subscription(monkeypatch):
    monkeypatch.setattr(claude_code, "auth_status", lambda env: {"mode": "api-key", "auth_method": "api_key"})
    with pytest.raises(RuntimeError, match="--claude-code-allow-api-billing"):
        ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")

    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp", allow_api_billing=True)
    try:
        assert client.describe()["auth_mode"] == "api-key"
        assert client.describe()["allow_api_billing"] is True
    finally:
        asyncio.run(client.aclose())


def test_client_refuses_an_api_key_helper_in_loaded_settings(monkeypatch, tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"apiKeyHelper": "echo sk-helper"}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="apiKeyHelper"):
        ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp", isolate_settings=False)
    # Isolated sessions skip the user settings, but `claude auth status` doesn't, so it reports the helper and
    # the login below it can't be confirmed: refused as well (fail closed).
    monkeypatch.setattr(
        claude_code, "auth_status", lambda env: {"mode": "api-key", "auth_method": "api_key_helper"}
    )
    with pytest.raises(RuntimeError, match="confirmed subscription"):
        ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")


PRO = {"mode": "subscription", "auth_method": "claude.ai", "subscription_type": "pro", "organization": False}


def test_client_strips_billing_env_and_records_the_auth_mode(monkeypatch):
    for name, value in BILLING_ENV.items():
        monkeypatch.setenv(name, value)
    seen = {}
    monkeypatch.setattr(
        claude_code,
        "auth_status",
        lambda env: seen.setdefault("env", dict(env)) and dict(PRO),
    )
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    try:
        # `claude auth status` sees the same stripped environment as the sessions.
        assert not set(BILLING_ENV) & set(seen["env"]) and not set(BILLING_ENV) & set(client.env)
        assert client.describe() == {
            "auth_mode": "subscription",
            "auth_status": PRO,
            "account_type": "pro",
            "allow_api_billing": False,
            "trust_org_policy": False,
            "stripped_env": sorted(BILLING_ENV),
            "setting_sources": "managed only",
        }
    finally:
        asyncio.run(client.aclose())


def test_api_key_source_and_what_bills_per_token():
    assert api_key_source([_init("none")]) == "none"
    assert api_key_source(['{"type": "result"}']) is None
    for source in ("ANTHROPIC_API_KEY", "apiKeyHelper", "/login managed key"):
        assert bills_per_token(source)
    for source in ("none", None, ""):
        assert not bills_per_token(source)


def _fake_exec(monkeypatch, outputs):
    calls = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return ("\n".join(next(outputs)).encode(), b"")

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


def test_a_session_billed_per_token_stops_the_run(monkeypatch):
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    answered = [
        _init("ANTHROPIC_API_KEY"),
        json.dumps({"type": "result", "subtype": "success", "result": "x"}),
    ]
    calls = _fake_exec(monkeypatch, iter([answered, answered]))
    try:
        first = asyncio.run(client.ask("q?", "haiku"))
        second = asyncio.run(client.ask("q2?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    assert first.status is None and "ANTHROPIC_API_KEY" in first.error
    assert second.error == first.error and len(calls) == 1  # never asked again


def test_a_per_token_session_is_allowed_with_the_opt_in(monkeypatch):
    monkeypatch.setattr(claude_code, "auth_status", lambda env: {"mode": "api-key"})
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp", allow_api_billing=True)
    answered = [
        _init("ANTHROPIC_API_KEY"),
        json.dumps({"type": "result", "subtype": "success", "result": "x"}),
    ]
    _fake_exec(monkeypatch, iter([answered]))
    try:
        reply = asyncio.run(client.ask("q?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    assert reply.error is None and reply.answer == "x"


def test_the_connector_probe_refuses_per_token_billing(monkeypatch):
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout=_init("apiKeyHelper", ["mcp__claude_ai_X__t"]), stderr="", returncode=0)

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    setup = ToolSetup({"navigator": "http://nav/mcp"}, "claude.ai X")
    with tempfile.TemporaryDirectory() as workdir:
        with pytest.raises(RuntimeError, match="apiKeyHelper"):
            probe_mcp_servers(setup, workdir, {})
        assert commands[0][commands[0].index("--setting-sources") + 1] == ""

        assert probe_mcp_servers(setup, workdir, {}, True, True) == {"claude_ai_X"}


# --- 2. Settings isolation --------------------------------------------------------------------------------


def test_sessions_load_no_user_project_or_local_settings():
    setup = ToolSetup({"cbioportal-database": "http://db/mcp", "navigator": "http://nav/mcp"})
    args = claude_args("q?", "haiku", "PROMPT", setup, "/tmp/mcp.json")
    assert args[args.index("--setting-sources") + 1] == ""
    # The rest of the command is unchanged: the system prompt, no built-in tools, only the MCP servers.
    assert args[args.index("--system-prompt") + 1] == "PROMPT" and args[args.index("--tools") + 1] == ""

    with_user = claude_args("q?", "haiku", "PROMPT", setup, "/tmp/mcp.json", isolate_settings=False)
    assert "--setting-sources" not in with_user


def test_client_passes_isolation_to_every_session(monkeypatch):
    client = ClaudeCodeClient("PROMPT", "http://db/mcp", "http://nav/mcp")
    calls = _fake_exec(monkeypatch, iter([[_init("none"), json.dumps({"type": "result", "result": "ok"})]]))
    try:
        asyncio.run(client.ask("q?", "haiku"))
    finally:
        asyncio.run(client.aclose())
    args = list(calls[0])
    assert args[args.index("--setting-sources") + 1] == ""
    assert client.env["MAX_THINKING_TOKENS"] == "0"


# --- 3. Beta awareness ------------------------------------------------------------------------------------


def _settings(url=None, env=None, connector_url="https://mcp.cbioportal.org/db/mcp"):
    return SimpleNamespace(database_mcp_url=url, database_mcp_env=env, database_connector_url=connector_url)


@pytest.mark.parametrize(
    ("url", "declared", "expected"),
    [
        (None, None, "prod"),  # the claude.ai connector for the public (prod) endpoint
        (None, "beta", "conflict"),  # a declaration can't make the public endpoint beta
        ("https://mcp.cbioportal.org/db/mcp", "beta", "conflict"),
        ("http://cbioagent-clickhouse-mcp:80/db/mcp", None, "prod"),
        ("http://cbioagent-clickhouse-mcp-beta:80/db/mcp", None, "beta"),
        ("http://cbioagent-clickhouse-mcp-beta.default.svc.cluster.local/db/mcp", None, "beta"),
        ("http://localhost:18080/db/mcp", None, "unknown"),
        ("http://localhost:18080/db/mcp", "beta", "beta"),
        ("http://localhost:18080/mcp", "local", "local"),
        ("http://localhost:18080/mcp", "staging", "unknown"),
    ],
)
def test_database_mcp_env(url, declared, expected):
    assert versions.database_mcp_env(_settings(url, declared)) == expected


def test_versions_follow_the_targets_mcp_deployment(monkeypatch):
    def pod(name, image):
        status = {"ready": True, "image": image, "imageID": f"docker.io/x@sha256:{name[-4:]}" + "0" * 20}
        return {"metadata": {"name": name}, "status": {"containerStatuses": [status]}}

    pods = {
        "items": [
            pod("cbioagent-clickhouse-mcp-7d9f-aaaa", "cbioportal/mcp:latest"),
            pod("cbioagent-clickhouse-mcp-beta-5c4b-bbbb", "cbioportal/mcp:beta"),
            pod("cbioportal-navigator-6f7c-cccc", "cbioportal/navigator:latest"),
        ]
    }
    monkeypatch.setattr(versions, "run_command", lambda cmd, timeout: json.dumps(pods))

    assert versions.deployments("beta-router") == {
        "cbioportal_mcp": "cbioagent-clickhouse-mcp-beta",
        "cbioportal_navigator": "cbioportal-navigator",
    }
    for target in ("beta", "beta-router", "beta-unified"):
        assert versions.image_tags(None, target)["cbioportal_mcp"] == "cbioportal/mcp:beta"
    assert versions.image_tags(None, "prod") == {
        "cbioportal_mcp": "cbioportal/mcp:latest",
        "cbioportal_navigator": "cbioportal/navigator:latest",
    }


def test_collect_records_the_deployments_it_looked_at(monkeypatch):
    for name in ("cbioportal_api", "claude_code", "mcp_server", "image_digests", "image_tags"):
        monkeypatch.setattr(versions, name, lambda *a, **k: {})
    settings = SimpleNamespace(kube_context=None, navigator_mcp_url="http://nav", database_mcp_url=None)
    recorded = versions.collect(settings, "claude-code", "beta")
    assert recorded["deployments"]["cbioportal_mcp"] == "cbioagent-clickhouse-mcp-beta"


def test_beta_target_on_the_prod_mcp_warns_or_fails(capsys):
    assert cli._check_database_mcp(_settings(), "beta-router", "claude-code", False) == "prod"
    err = capsys.readouterr().err
    assert "WARNING" in err and "PROD" in err and "cbioagent-clickhouse-mcp-beta" in err

    with pytest.raises(cli.click.ClickException, match="not beta's"):
        cli._check_database_mcp(_settings(), "beta", "claude-code", True)
    with pytest.raises(cli.click.ClickException, match="DATABASE_MCP_ENV=beta"):
        cli._check_database_mcp(_settings("http://localhost:18080/db/mcp"), "beta", "claude-code", True)

    beta = _settings("http://localhost:18080/db/mcp", "beta")
    assert cli._check_database_mcp(beta, "beta", "claude-code", True) == "beta"
    assert cli._check_database_mcp(_settings(), "prod", "claude-code", True) == "prod"
    assert cli._check_database_mcp(_settings(), "beta", "agents-api", True) is None
    assert capsys.readouterr().err == ""


def test_ask_with_require_beta_mcp_fails_before_starting_claude(monkeypatch):
    monkeypatch.delenv("DATABASE_MCP_URL", raising=False)
    monkeypatch.delenv("DATABASE_CONNECTOR_URL", raising=False)
    monkeypatch.setattr("cbioportal_mcp_qa.config.load_dotenv", lambda: None)
    started = []
    monkeypatch.setattr(cli, "_client", lambda *a, **k: started.append(1))
    result = CliRunner().invoke(
        cli.cli, ["ask", "q?", "--runner", "claude-code", "--target", "beta", "--require-beta-mcp"]
    )
    assert result.exit_code != 0 and "not beta's" in result.output and not started


# --- 4. Server instructions -------------------------------------------------------------------------------


def test_initialize_keeps_the_server_instructions(monkeypatch):
    replies = iter(
        [
            {"result": {"serverInfo": {"name": "db", "version": "2"}, "instructions": "Read the guide."}},
            {},
        ]
    )
    monkeypatch.setattr(MCPSession, "_post", lambda self, *a, **k: next(replies))
    with MCPSession("http://db/mcp") as mcp:
        assert mcp.initialize() == {"name": "db", "version": "2"}
    assert mcp.instructions == "Read the guide."


def test_mcp_server_version_records_an_instructions_hash(monkeypatch):
    def fake_initialize(self):
        self.instructions = "Read the guide."
        return {"name": "db", "version": "2"}

    monkeypatch.setattr(MCPSession, "initialize", fake_initialize)
    info = versions.mcp_server("http://db/mcp")
    assert info["version"] == "2" and info["instructions"]["chars"] == len("Read the guide.")
    assert versions.server_instructions("http://db/mcp") == "Read the guide."


def test_prompt_parity_hashes_in_librechats_order():
    from cbioportal_mcp_qa.agent_prompt import prompt_fingerprint

    parity = prompt_parity("AGENT", "http://db/mcp", fetch=lambda url: "SERVER")
    assert parity["system_prompt"] == prompt_fingerprint("AGENT")
    assert parity["server_instructions"] == prompt_fingerprint("SERVER")
    assert parity["combined"] == prompt_fingerprint("AGENT\n\nSERVER")
    assert parity["server_instructions_delivery"].startswith("claude-code")

    assert "OAuth" in prompt_parity("AGENT", None)["server_instructions"]["error"]
    assert "combined" not in prompt_parity("AGENT", None)

    def boom(url):
        raise ConnectionError("refused")

    assert prompt_parity("AGENT", "http://db/mcp", fetch=boom)["server_instructions"] == {
        "error": "ConnectionError: refused"
    }
    assert prompt_parity("AGENT", "http://db/mcp", fetch=lambda url: None)["server_instructions"] is None


# --- run.json -----------------------------------------------------------------------------------------------


def test_run_records_the_new_fields_through_the_persist_path(monkeypatch, results_dir):
    for name, value in BILLING_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATABASE_MCP_URL", "http://localhost:18080/db/mcp")
    monkeypatch.setenv("DATABASE_MCP_ENV", "beta")
    monkeypatch.setattr("cbioportal_mcp_qa.config.load_dotenv", lambda: None)
    monkeypatch.setattr(
        cli, "fetch_agent_prompt", lambda agent_id, ctx=None: {"instructions": "AGENT", "updated_at": "t"}
    )
    monkeypatch.setattr(cli, "describe_agents", lambda *a: {})
    monkeypatch.setattr(cli, "collect_versions", lambda *a: {})
    monkeypatch.setattr(claude_code, "server_instructions", lambda url: "SERVER")
    monkeypatch.setattr(cli, "write_report", lambda bench: bench.dir / "report.html")
    kwargs = {}

    async def no_answers(bench, questions, client, concurrency):
        kwargs["transcripts"] = client.transcript_dir

    monkeypatch.setattr(cli, "collect_answers", no_answers)
    result = CliRunner().invoke(
        cli.cli,
        [
            "run",
            "--runner",
            "claude-code",
            "--target",
            "beta-router",
            "--models",
            "router",
            "--questions",
            "1",
            "--no-grade",
            "--no-render",
            "--require-beta-mcp",
        ],
    )
    assert result.exit_code != 0 and "router" in result.output  # router isn't a single model

    result = CliRunner().invoke(
        cli.cli,
        ["run", "--runner", "claude-code", "--target", "beta", "--models", "haiku"]
        + ["--questions", "1", "--no-grade", "--no-render", "--require-beta-mcp"],
    )
    assert result.exit_code == 0, result.output
    (run_json,) = results_dir.glob("*/run.json")
    text = run_json.read_text()
    data = json.loads(text)
    assert data["database_mcp_env"] == "beta"
    assert data["claude_code"]["auth_mode"] == "subscription"
    assert data["claude_code"]["stripped_env"] == sorted(BILLING_ENV)
    assert data["claude_code"]["setting_sources"] == "managed only"
    assert data["claude_code"]["prompt"]["combined"]["chars"] == len("AGENT\n\nSERVER")
    assert kwargs["transcripts"] == run_json.parent / "transcripts"
    for value in BILLING_ENV.values():
        if len(value) > 6:
            assert value not in text
