"""Offline regression-harness tests: no MCP endpoint or database required."""

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from mcp_tests import client, conftest
from mcp_tests import test_mcp_regression as harness
from mcp_tests.client import ToolResult, _reports_failure
from mcp_tests.golden import assert_golden

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "payload",
    [
        {"error_message": "bad SQL"},
        [{"rows": [{"exception": "boom"}]}],
        {"nested": {"success": False}},
        [{"error": "study lookup failed"}],
    ],
)
def test_nested_errors(payload):
    assert _reports_failure(payload)


def test_valid_data():
    assert not _reports_failure({"rows": [[1, "TP53"]], "columns": ["n", "gene"]})


@pytest.mark.parametrize("waived", [False, True])
def test_shared_error_is_never_waived(waived):
    result = ToolResult(True, [{"error_message": "same bug in both servers"}])
    baseline = SimpleNamespace(call=lambda *args: result)
    call = {"id": "query", "tool": "clickhouse_run_select_query"}
    harness.test_call_baseline_diff(call, result, baseline, waived)
    with pytest.raises(AssertionError):
        harness.test_call_hard_checks(call, result)


def test_only_actual_drop_can_expect_error():
    with pytest.raises(AssertionError):
        harness.test_call_hard_checks(
            {"id": "query", "tool": "other", "expect_error": True}, ToolResult(True, [])
        )
    drop = next(c for c in conftest.load_calls("mcp") if c["id"] == "sql_invalid_rejected")
    harness.test_call_hard_checks(drop, ToolResult(True, []))
    with pytest.raises(AssertionError):
        harness.test_call_hard_checks(drop, ToolResult(False, []))


def test_missing_domain_tool_fails_even_with_other_tools():
    candidate = SimpleNamespace(list_tools=lambda: {"list_guides": object()})
    with pytest.raises(AssertionError, match="get_profiled_counts"):
        harness.test_tools_are_listed(candidate, "mcp")


def test_baseline_diff_waiver_only():
    call = {"id": "query", "tool": "query"}
    baseline = SimpleNamespace(call=lambda *args: ToolResult(False, [1]))
    harness.test_call_baseline_diff(call, ToolResult(False, [2]), baseline, True)
    with pytest.raises(pytest.fail.Exception):
        harness.test_call_baseline_diff(call, ToolResult(False, [2]), baseline, False)


@pytest.mark.parametrize("compact", [False, True])
def test_golden_accepts_result_formats(compact):
    row = {"altered_samples": 1, "profiled_samples": 3, "frequency_pct": 33.33}
    data = {"columns": list(row), "rows": [list(row.values())]} if compact else {"rows": [row]}
    assert_golden([data], {"kind": "frequency", "min_rows": 1, "max_rows": 1})


@pytest.mark.parametrize(
    "data,spec",
    [
        ([], {"min_rows": 1}),
        ([{"gene": "WRONG"}], {"contains": {"gene": "TP53"}}),
        (
            [{"rows": [{"altered_samples": 10, "profiled_samples": 2, "frequency_pct": 500}]}],
            {"kind": "frequency"},
        ),
        (
            [{"rows": [{"altered_samples": 1, "profiled_samples": 2, "frequency_pct": 40}]}],
            {"kind": "frequency"},
        ),
        ([{"rows": [{"samples": 5, "patients": 6, "wes_samples": 0}]}], {"kind": "profiled_counts"}),
        ([], {"min_row": 1}),
    ],
)
def test_bad_goldens_fail(data, spec):
    with pytest.raises(AssertionError):
        assert_golden(data, spec)


def test_ten_goldens_and_all_domain_tools():
    calls = conftest.load_calls("mcp")
    assert len({c["id"] for c in calls}) == len(calls)
    assert sum("golden" in c for c in calls) == 10
    assert {
        "get_alteration_frequency",
        "get_top_altered_genes",
        "get_gene_frequency_by_cancer_type",
        "get_profiled_counts",
    } <= {c["tool"] for c in calls}


@pytest.mark.parametrize(
    "gate,missing",
    [
        (gate, missing)
        for gate in (True, False)
        for missing in (
            "CLICKHOUSE_HOST",
            "CLICKHOUSE_USER",
            "CLICKHOUSE_PASSWORD",
            "CLICKHOUSE_DATABASE",
            None,
        )
    ],
)
def test_workflow_secret_policy(tmp_path, gate, missing):
    workflow = yaml.safe_load((ROOT / ".github/workflows/mcp-regression.yml").read_text())
    configure = next(s for s in workflow["jobs"]["regression"]["steps"] if s.get("id") == "cfg")
    env = dict(
        os.environ,
        SERVER="mcp",
        HTTP_PATH="/db/mcp",
        BASELINE_IMAGE="",
        FAIL_ON_MISSING_SECRETS=str(gate).lower(),
        HAS_LABEL="false",
        RUNNER_TEMP=str(tmp_path),
        GITHUB_OUTPUT=str(tmp_path / "output"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
    )
    for key in ("CLICKHOUSE_HOST", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD", "CLICKHOUSE_DATABASE"):
        env[key] = "" if key == missing else "test"
    env["CLICKHOUSE_PORT"] = ""
    result = subprocess.run(["bash", "-c", configure["run"]], env=env, text=True, capture_output=True)
    assert (result.returncode != 0) == (gate and missing is not None), result.stderr
    if gate and missing:
        assert "::error::" in result.stdout and "Fork PRs" in result.stdout
        assert "workflow_dispatch" in result.stdout
    elif missing:
        assert "::notice::" in result.stdout
        assert "skip=true" in (tmp_path / "output").read_text()
    else:
        assert "skip=false" in (tmp_path / "output").read_text()
        assert "CLICKHOUSE_MCP_HTTP_PATH=/db/mcp" in (tmp_path / "server.env").read_text()


def test_headers_reach_http_transport(monkeypatch):
    seen = {}

    class Http:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def transport(url, http_client):
        seen["url"] = url
        yield ("read", "write")

    class Client:
        def __init__(self, transport, **kwargs):
            self.transport = transport

        async def __aenter__(self):
            await self.transport.__aenter__()
            return self

        async def __aexit__(self, *args):
            await self.transport.__aexit__(*args)

    monkeypatch.setattr(client.httpx2, "AsyncClient", Http)
    monkeypatch.setattr(client, "streamable_http_client", transport)
    monkeypatch.setattr(client, "Client", Client)
    headers = conftest.headers.__wrapped__(SimpleNamespace(config=SimpleNamespace(getoption=lambda _: True)))
    client.McpClient("http://localhost/db/mcp", headers=headers)._run(AsyncMock(return_value=None))
    assert seen["url"].endswith("/db/mcp")
    assert seen["headers"] == {
        "x-user-id": "mcp-regression-ci",
        "x-user-email": "mcp-regression-ci@cbioportal.org",
        "x-user-email-verified": "true",
    }
