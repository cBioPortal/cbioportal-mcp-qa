import pytest

from cbioportal_mcp_qa import compare as compare_mod
from cbioportal_mcp_qa import report as report_mod
from cbioportal_mcp_qa import run as run_mod


@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    """A temporary results/ directory for everything that reads or writes runs."""
    for mod in (run_mod, report_mod, compare_mod):
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    return tmp_path


SUBSCRIPTION = {
    "mode": "subscription",
    "auth_method": "claude.ai",
    "api_provider": "firstParty",
    "subscription_type": "max",
}


@pytest.fixture(autouse=True)
def subscription_login(monkeypatch, tmp_path):
    """Claude Code clients see a subscription login, no plugins, and none of this machine's settings (managed
    files, MDM profile, the Claude home's server-managed cache): tests never run `claude`."""
    from cbioportal_mcp_qa import claude_code

    monkeypatch.setattr(claude_code, "auth_status", lambda env: dict(SUBSCRIPTION))
    # The plugin preflight finds none (tests/test_claude_code_plugins.py runs the real one on a fake binary).
    monkeypatch.setattr(claude_code, "preflight_plugins", lambda env, workdir, settings, isolate: [])
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS_DIRS", (tmp_path / "no-managed-settings",))
    monkeypatch.setattr(claude_code, "MANAGED_PREFERENCES_DIR", tmp_path / "no-managed-preferences")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
