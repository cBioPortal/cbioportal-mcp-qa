# MCP regression gate

Run the live harness with:

```sh
uv run --frozen --group mcp-tests pytest mcp_tests --server mcp \
  --url http://localhost:8001/db/mcp --baseline-url http://localhost:8002/db/mcp \
  --librechat-headers
```

The reusable workflow defaults to `http_path: /mcp`, `librechat_headers: false`,
and `fail_on_missing_secrets: false` for existing callers. MCP's caller opts into
the production path, synthetic LibreChat identity headers, and mandatory secrets
on main. Fork PRs cannot receive secrets: a maintainer must push the reviewed
branch to upstream and run the PR checks, or select that upstream branch in
the caller's workflow_dispatch. Beta can continue to skip with a notice.

There are two independent classes of checks:

* Baseline diffs compare schemas and responses. The behavior-change label
  (`--allow-changes`) makes only these differences report-only.
* Hard checks require every tool named in the call file (plus read_guide),
  reject candidate MCP errors, nested error_message/error/exception or
  success=false responses, and enforce goldens. Exceptions also fail tests.
  Only the exact intentional DROP call may error, and it must be rejected.
  A shared bug in candidate and baseline therefore still fails.

Ten GOLDEN calls in calls/mcp.yaml assert absolute properties without consulting
the baseline. They check stable TCGA study identity, TP53 symbol resolution,
OncoTree BRCA identity, SQL scalar/empty-result behavior, and all four domain
tools. Domain results must be non-empty, respect requested limits, have valid
sample/patient/WES relationships, and have frequencies in [0, 100] consistent
with counts within 0.051 percentage points (one-decimal rounding tolerance).
Both compact column/row tables and legacy record lists are supported.

These assertions tolerate daily clone drift: no frozen sample counts or
ranked gene identities are used. The tests require the public portal's TCGA
cohort and curated metadata. They are smoke/invariant checks, not an independent
oracle for every scientific denominator; MCP's synthetic live-ClickHouse
equivalence suite supplies the deeper SQL/oracle coverage.

Offline harness and workflow-policy tests are in tests/test_mcp_harness.py:

```sh
uv run --frozen --group dev --group mcp-tests pytest tests
```
