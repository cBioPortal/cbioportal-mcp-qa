"""Logins whose organization can push server-managed settings (Team, Enterprise, unrecognised plans) are refused
before any model call unless the org's policy is trusted: a `-p` session applies such a policy uncached."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from cbioportal_mcp_qa import claude_code, cli
from cbioportal_mcp_qa.claude_code import ClaudeCodeClient
from cbioportal_mcp_qa.claude_code import auth_status as real_auth_status

CONNECTOR = "claude.ai cBioPortal MCP"


class ModelCalls:
    """`claude auth status` answers with `status`; every other `claude` run (the connector probe, answers) is
    recorded as a model-capable call."""

    def __init__(self, monkeypatch, status: dict):
        self.calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["claude", "auth", "status"]:
                return SimpleNamespace(stdout=json.dumps(status), stderr="", returncode=0)
            self.calls.append(cmd)
            init = {"type": "system", "subtype": "init", "apiKeySource": "none", "plugins": []}
            init["tools"] = ["mcp__claude_ai_cBioPortal_MCP__read_guide"]
            return SimpleNamespace(stdout=json.dumps(init), stderr="", returncode=0)

        async def fake_exec(*args, **kwargs):
            self.calls.append(list(args))
            raise AssertionError("no answer should be asked")

        monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(claude_code, "auth_status", real_auth_status)


def _login(plan: str | None, method: str = "claude.ai") -> dict:
    status = {"loggedIn": True, "authMethod": method, "apiProvider": "firstParty"}
    status |= {"email": "someone@example.org", "orgId": "org-123", "orgName": "Some Org"}
    return status | ({"subscriptionType": plan} if plan is not None else {})


def _connector_client(**kwargs) -> ClaudeCodeClient:
    """A client that probes the connector (a model call) as soon as the guard lets it."""
    return ClaudeCodeClient("PROMPT", "unused", "https://nav/mcp", database_connector=CONNECTOR, **kwargs)


@pytest.mark.parametrize("plan", ["pro", "max", "Max"])
def test_plans_without_server_managed_settings_are_allowed(monkeypatch, plan):
    model = ModelCalls(monkeypatch, _login(plan))
    client = _connector_client()
    try:
        described = client.describe()
        assert described["auth_mode"] == "subscription" and described["account_type"] == plan
        assert described["trust_org_policy"] is False
        assert len(model.calls) == 1 and model.calls[0][:2] == ["claude", "-p"]  # the probe, after the guard
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize(
    ("plan", "method"),
    [
        ("team", "claude.ai"),
        ("enterprise", "claude.ai"),
        ("Enterprise", "claude.ai"),
        ("team", "oauth_token"),  # a `claude setup-token` token of a Team login
        ("free", "claude.ai"),  # unrecognised
        ("", "claude.ai"),  # missing
        (None, "claude.ai"),
    ],
)
def test_plans_that_can_receive_org_policy_refuse_before_any_model_call(monkeypatch, plan, method):
    model = ModelCalls(monkeypatch, _login(plan, method))
    with pytest.raises(RuntimeError) as err:
        _connector_client()
    assert model.calls == []
    message = str(err.value)
    assert "--claude-code-trust-org-policy" in message or "confirmed subscription" in message
    if plan in ("team", "enterprise", "Enterprise"):
        assert "server-managed settings" in message and "--claude-code-trust-org-policy" in message


@pytest.mark.parametrize("plan", ["team", "enterprise", "free"])
def test_trusting_the_org_policy_allows_them(monkeypatch, plan):
    model = ModelCalls(monkeypatch, _login(plan))
    client = _connector_client(trust_org_policy=True)
    try:
        described = client.describe()
        assert described["account_type"] == plan and described["trust_org_policy"] is True
        assert described["allow_api_billing"] is False
        assert described["auth_status"]["organization"] is True
        assert "org-123" not in json.dumps(described) and "Some Org" not in json.dumps(described)
        assert "someone@example.org" not in json.dumps(described)
        assert len(model.calls) == 1
    finally:
        asyncio.run(client.aclose())


def test_trusting_the_org_policy_is_not_allowing_api_billing(monkeypatch, tmp_path):
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "managed-settings.json").write_text(json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "bearer"}}))
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (managed,))
    model = ModelCalls(monkeypatch, _login("team"))
    with pytest.raises(RuntimeError, match="--claude-code-allow-api-billing"):
        _connector_client(trust_org_policy=True)
    assert model.calls == []


def test_cli_passes_the_opt_in_from_the_flag_and_the_environment(monkeypatch):
    monkeypatch.setattr("cbioportal_mcp_qa.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_MCP_URL", "http://localhost:18080/db/mcp")
    seen = []

    def fake_client(*args, **kwargs):
        seen.append(kwargs.get("trust_org_policy"))
        raise cli.click.ClickException("stop here")

    monkeypatch.setattr(cli, "_client", fake_client)
    base = ["ask", "q?", "--runner", "claude-code", "--target", "prod"]
    CliRunner().invoke(cli.cli, base)
    CliRunner().invoke(cli.cli, [*base, "--claude-code-trust-org-policy"])
    CliRunner().invoke(cli.cli, base, env={"CLAUDE_CODE_TRUST_ORG_POLICY": "1"})
    assert seen == [False, True, True]


def test_run_json_records_the_account_type_and_opt_ins(monkeypatch, results_dir):
    monkeypatch.setattr("cbioportal_mcp_qa.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_MCP_URL", "http://localhost:18081/db/mcp")
    monkeypatch.setenv("DATABASE_MCP_ENV", "beta")
    monkeypatch.setenv("CLAUDE_CODE_TRUST_ORG_POLICY", "1")
    ModelCalls(monkeypatch, _login("team"))
    monkeypatch.setattr(
        cli, "fetch_agent_prompt", lambda agent_id, ctx=None: {"instructions": "AGENT", "updated_at": "t"}
    )
    monkeypatch.setattr(cli, "describe_agents", lambda *a: {})
    monkeypatch.setattr(cli, "collect_versions", lambda *a: {})
    monkeypatch.setattr(claude_code, "server_instructions", lambda url: "SERVER")
    monkeypatch.setattr(cli, "write_report", lambda bench: bench.dir / "report.html")

    async def no_answers(bench, questions, client, concurrency):
        _record_failures(bench, questions)

    monkeypatch.setattr(cli, "collect_answers", no_answers)
    result = CliRunner().invoke(
        cli.cli,
        ["run", "--runner", "claude-code", "--target", "beta", "--models", "haiku"]
        + ["--questions", "1", "--no-grade", "--no-render"],
    )
    assert result.exit_code == 0, result.output
    (run_json,) = results_dir.glob("*/run.json")
    recorded = json.loads(run_json.read_text())["claude_code"]
    assert recorded["account_type"] == "team"
    assert recorded["trust_org_policy"] is True and recorded["allow_api_billing"] is False
    assert "org-123" not in run_json.read_text() and "someone@example.org" not in run_json.read_text()


def _record_failures(bench, questions):
    """What collect_answers leaves when every answer fails: a failure record per planned turn."""
    from dataclasses import asdict

    from cbioportal_mcp_qa.run import record_key

    for q in questions:
        for model in bench.data["models"]:
            reply = {"answer": "", "status": None, "error": "stub", "latency_s": 0.0, "started_at": 0.0}
            bench.records[record_key(q.id, model, 1)] = {
                "question": asdict(q),
                "model": model,
                "repeat": 1,
                "reply": reply,
            }
