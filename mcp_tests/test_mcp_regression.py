import json
import re

import pytest

from .client import ToolInfo
from .conftest import record_change

GUIDE_URI_RE = re.compile(r"cbioportal://[a-z0-9-]+(?:/[a-z0-9_]+)?")


def _schema_text(tool: ToolInfo) -> str:
    return json.dumps(
        {"description": tool.description, "input_schema": tool.input_schema}, indent=1, sort_keys=True
    )


def test_tools_are_listed(candidate):
    assert candidate.list_tools(), "server lists no tools"


def test_tool_contract_matches_baseline(candidate, baseline, allow_changes):
    if baseline is None:
        pytest.skip("no --baseline-url")
    new, old = candidate.list_tools(), baseline.list_tools()
    changed = []
    for name in sorted(old.keys() | new.keys()):
        before = _schema_text(old[name]) if name in old else ""
        after = _schema_text(new[name]) if name in new else ""
        if before != after:
            record_change(f"tool `{name}` definition", before, after, blocking=name in old)
            if name in old:
                changed.append(name)
    if changed and not allow_changes:
        pytest.fail(
            f"tool definitions changed or removed: {changed} (add the mcp-behavior-change label if intended)"
        )


def test_call(call, candidate, baseline, allow_changes):
    result = candidate.call(call["tool"], call.get("args") or {})
    if baseline is None:
        assert not result.is_error or call.get("expect_error"), result.normalized()[:2000]
        return
    expected = baseline.call(call["tool"], call.get("args") or {})
    if result.is_error and not expected.is_error:
        pytest.fail(f"call now errors (baseline succeeds):\n{result.normalized()[:2000]}")
    if result.normalized() != expected.normalized():
        record_change(
            f"`{call['id']}` ({call['tool']})", expected.normalized(), result.normalized(), blocking=True
        )
        if not allow_changes:
            pytest.fail("result differs from baseline (add the mcp-behavior-change label if intended)")


def test_guides_readable(server, candidate, baseline):
    """Every listed guide loads. Guide text changes are reported but don't fail: they're reviewed in the PR diff."""
    if server != "mcp":
        pytest.skip("guides are an mcp-server feature")
    listed = candidate.call("list_guides", {})
    assert not listed.is_error, listed.normalized()[:2000]
    uris = sorted({u for u in GUIDE_URI_RE.findall(listed.normalized()) if "{" not in u})
    assert uris, "list_guides returned no guide URIs"
    broken = []
    for uri in uris:
        guide = candidate.call("read_guide", {"uri": uri})
        if guide.is_error or not guide.normalized().strip():
            broken.append(uri)
            continue
        if baseline is not None:
            before = baseline.call("read_guide", {"uri": uri})
            if not before.is_error and before.normalized() != guide.normalized():
                record_change(f"guide `{uri}`", before.normalized(), guide.normalized(), blocking=False)
    assert not broken, f"guides failed to load: {broken}"
