"""Langfuse v2 observations API: cursor paging, JSON-string input/output, AgentGraph roots, tool-dispatch calls."""

import json

from cbioportal_mcp_qa.traces import Langfuse, _looks_failed, trace_stats


def _client(pages_by_name):
    """A Langfuse whose `_get` serves observation pages; records the params of every call."""
    lf = Langfuse("https://lf.example", "pk", "sk")
    calls = []

    def fake_get(path, retries=6, **params):
        calls.append((path, params))
        pages = pages_by_name[params.get("name") or params.get("traceId")]
        return pages[int(params.get("cursor") or 0)]

    lf._get = fake_get
    return lf, calls


def test_trace_ids_follow_cursors_and_match_both_root_names():
    def run(mid, tid):
        return {"traceId": tid, "metadata": {"messageId": mid}, "input": None, "output": None}

    lf, calls = _client(
        {
            "AgentRun": [
                {"data": [run("m1", "t1")], "meta": {"cursor": "1"}},
                {"data": [run("m2", "t2")], "meta": {}},
            ],
            "AgentGraph": [{"data": [run("m3", "t3"), run("m1", "other")], "meta": {}}],
        }
    )
    assert lf.trace_ids_by_message(1_700_000_000, 1_700_000_100) == {"m1": "t1", "m2": "t2", "m3": "t3"}
    assert {p["name"] for _, p in calls} == {"AgentRun", "AgentGraph"}
    assert all(path == "/v2/observations" and p["fromStartTime"].endswith("Z") for path, p in calls)


def test_observations_decode_json_string_input_and_output():
    obs = {"type": "CHAIN", "input": json.dumps([{"name": "x"}]), "output": "not json"}
    lf, _ = _client({"t": [{"data": [obs], "meta": {}}]})
    got = list(lf._observations(traceId="t"))
    assert got[0]["input"] == [{"name": "x"}] and got[0]["output"] == "not json"


def _dispatch(requests, results, start="2026-11-20T10:00:00Z"):
    return {
        "type": "CHAIN",
        "name": "tool-dispatch",
        "startTime": start,
        "input": requests,
        "output": {"messages": results},
    }


def test_tool_dispatch_pairs_requests_with_results_in_order():
    stats = trace_stats(
        "t",
        "u",
        [
            _dispatch(
                [
                    {
                        "name": "clickhouse_run_select_query_mcp_cbioportal-database",
                        "args": {"query": "SELECT 1"},
                    },
                    {"name": "list_studies_mcp_cbioportal-database", "args": {}},
                ],
                [
                    {"content": '{"rows": [[1]]}', "status": "success"},
                    {"content": "Error: boom", "status": "success"},
                ],
            )
        ],
    )
    assert [c.name for c in stats.tool_calls] == ["clickhouse_run_select_query", "list_studies"]
    assert [c.ok for c in stats.tool_calls] == [True, False]
    assert "SELECT 1" in stats.tool_calls[0].input
    assert stats.tool_rounds == 1 and len(stats.tool_errors) == 1


def test_error_status_marks_a_dispatch_result_failed():
    stats = trace_stats(
        "t", "u", [_dispatch([{"name": "t", "args": {}}], [{"content": "fine", "status": "error"}])]
    )
    assert not stats.tool_calls[0].ok


def test_looks_failed_heuristic():
    assert _looks_failed("Error: nope") and _looks_failed("  MCP error -32000")
    assert _looks_failed('{"error": "bad"}') and _looks_failed('{"isError": true}')
    assert not _looks_failed('{"rows": []}') and not _looks_failed("42 studies, no errors here")
