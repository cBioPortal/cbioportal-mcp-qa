"""Differential regression tests for the cBioPortal MCP servers.

Each test makes the same fixed tool calls against the server under test (--url, e.g. a PR build) and a
baseline (--baseline-url, e.g. the released image) connected to the same data. A difference in results
is a behavior change: it fails the test unless --allow-changes is given (CI passes that when the PR has
the `mcp-behavior-change` label). A call that errors on the server under test but not on the baseline
always fails.
"""

import difflib
import os
from pathlib import Path

import pytest
import yaml

from .client import McpClient

CALLS_DIR = Path(__file__).parent / "calls"
_changes: list[dict] = []


def pytest_addoption(parser):
    group = parser.getgroup("mcp regression")
    group.addoption(
        "--server", choices=["mcp", "navigator"], required=True, help="Which MCP server is under test."
    )
    group.addoption("--url", required=True, help="MCP endpoint of the server under test.")
    group.addoption("--baseline-url", default=None, help="MCP endpoint of the baseline server.")
    group.addoption("--allow-changes", action="store_true", help="Report behavior changes without failing.")


@pytest.fixture(scope="session")
def server(request) -> str:
    return request.config.getoption("--server")


@pytest.fixture(scope="session")
def candidate(request) -> McpClient:
    return McpClient(request.config.getoption("--url"))


@pytest.fixture(scope="session")
def baseline(request) -> McpClient | None:
    url = request.config.getoption("--baseline-url")
    return McpClient(url) if url else None


@pytest.fixture(scope="session")
def allow_changes(request) -> bool:
    return request.config.getoption("--allow-changes")


def load_calls(server: str) -> list[dict]:
    return yaml.safe_load((CALLS_DIR / f"{server}.yaml").read_text())


def pytest_generate_tests(metafunc):
    if "call" in metafunc.fixturenames:
        calls = load_calls(metafunc.config.getoption("--server"))
        metafunc.parametrize("call", calls, ids=[c["id"] for c in calls])


def record_change(title: str, before: str, after: str, *, blocking: bool) -> None:
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), "baseline", "candidate", lineterm="", n=2
        )
    )
    _changes.append({"title": title, "diff": diff, "blocking": blocking})


def pytest_terminal_summary(terminalreporter):
    if not _changes:
        return
    lines = ["## MCP behavior changes", ""]
    for change in _changes:
        kind = "change" if change["blocking"] else "info"
        diff = change["diff"]
        if len(diff) > 6000:
            diff = diff[:6000] + "\n… (truncated)"
        lines += [
            f"<details><summary>{kind}: {change['title']}</summary>",
            "",
            "```diff",
            diff,
            "```",
            "</details>",
            "",
        ]
    text = "\n".join(lines)
    terminalreporter.write_sep("=", "MCP behavior changes")
    terminalreporter.write_line(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text + "\n")
