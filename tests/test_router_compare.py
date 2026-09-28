"""The handoff-router target, per-call traces, and `compare` against a run in the 2026-09-23 format."""

import asyncio
import json
import shutil
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa import compare as compare_mod
from cbioportal_mcp_qa import report as report_mod
from cbioportal_mcp_qa import run as run_mod
from cbioportal_mcp_qa.agent import AgentClient, AgentReply
from cbioportal_mcp_qa.agent_prompt import describe_agents
from cbioportal_mcp_qa.compare import compare, pick_model, write_compare
from cbioportal_mcp_qa.config import MODELS, TARGETS, price_for
from cbioportal_mcp_qa.report import record_cost, summarize, write_report
from cbioportal_mcp_qa.run import Run, record_key
from cbioportal_mcp_qa.traces import trace_stats, usage_split

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE = "20260923-1919"  # 4 questions (1, 2, 40, 60) × haiku, sonnet, trimmed from results/20260923-1919
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
SONNET = "us.anthropic.claude-sonnet-5"
ROUTER, DATA, NAV = "agent_cbiobeta_router", "agent_cbiobeta_data", "agent_cbiobeta_navigation"


def sent_body(target: str, model: str) -> dict:
    client = AgentClient(TARGETS[target], "key")
    sent = {}

    async def fake_post(body, started):
        sent.update(body)
        return AgentReply("ok", "r1", 200, None, 1.0, started)

    client._post = fake_post
    asyncio.run(client.ask("q", model))
    asyncio.run(client.aclose())
    return sent


def test_router_target_sends_no_spec_and_beta_keeps_its_spec():
    assert sent_body("beta-router", "router") == {
        "model": ROUTER,
        "messages": [{"role": "user", "content": "q"}],
        "stream": False,
    }
    assert sent_body("beta", "sonnet")["spec"] == "cBioPortalChatBetaSonnet"
    assert "spec" not in sent_body("beta-unified", "unified")
    assert TARGETS["beta-router"].librechat_deployment == "cbioagent-librechat-beta"


def test_models_are_checked_against_the_target():
    assert cli_mod._models(None, "beta-router") == ["router"]
    assert cli_mod._models(None, "beta") == ["haiku", "sonnet"]
    assert cli_mod._models("router", "beta-router") == ["router"]
    with pytest.raises(click.BadParameter, match="has no model"):
        cli_mod._models("router", "beta")
    with pytest.raises(click.BadParameter, match="has no model"):
        cli_mod._models("haiku", "beta-router")
    with pytest.raises(click.BadParameter, match="claude-code"):
        cli_mod._models("router", "beta-router", "claude-code")


def test_price_for_matches_bedrock_ids_with_or_without_region():
    assert price_for(HAIKU) is MODELS["haiku"].price
    assert price_for("anthropic.claude-haiku-4-5-20251001-v1:0") is MODELS["haiku"].price
    assert price_for("global.anthropic.claude-sonnet-5") is MODELS["sonnet"].price
    assert price_for("gpt-4o") is None and price_for(None) is None


def test_usage_split_handles_both_cache_conventions():
    # Langfuse's convention: cache tokens are separate from `input`.
    langfuse = {"usageDetails": {"input": 100, "output": 20, "input_cache_read": 900, "total": 1020}}
    assert usage_split(langfuse) == (100, 20, 900, None)
    # LangChain usage_metadata: `input` includes the cache, and total = input + output.
    langchain = {"usageDetails": {"input": 1000, "output": 20, "input_cache_read": 900, "total": 1020}}
    assert usage_split(langchain) == (100, 20, 900, None)
    assert usage_split({}) == (None, None, None, None)


def _gen(agent, model, start, end, usage, tool_calls=()):
    return {
        "type": "GENERATION",
        "name": "ChatBedrockConverse",
        "model": model,
        "startTime": start,
        "endTime": end,
        "metadata": {"langgraph_node": f"agent={agent}"},
        "usageDetails": usage,
        "output": {"tool_calls": [{"name": n, "id": f"c-{n}", "args": {}} for n in tool_calls]},
    }


def _batch(start, *messages):
    return {
        "type": "TOOL",
        "name": "tool_batch",
        "startTime": start,
        "input": {"messages": []},
        "output": {
            "messages": [
                {"id": ["langchain_core", "messages", "ToolMessage"], "kwargs": {"name": n, "content": c}}
                for n, c in messages
            ]
        },
    }


ROUTED_OBSERVATIONS = [
    # Out of order on purpose: Langfuse pages aren't sorted by time.
    _gen(DATA, HAIKU, "2026-09-27T10:00:03Z", "2026-09-27T10:00:05Z", {"input": 50, "output": 100}),
    _gen(
        ROUTER,
        HAIKU,
        "2026-09-27T10:00:00Z",
        "2026-09-27T10:00:01Z",
        {"input": 1000, "output": 30},
        ["lc_transfer_to_" + DATA],
    ),
    _batch("2026-09-27T10:00:01Z", ("lc_transfer_to_" + DATA, "Successfully transferred")),
    _gen(
        DATA,
        HAIKU,
        "2026-09-27T10:00:01Z",
        "2026-09-27T10:00:02Z",
        {
            "input": 200,
            "output": 40,
            "input_cache_read": 30_000,
            "input_cache_creation": 1000,
            "total": 31_240,
        },
        ["clickhouse_run_select_query"],
    ),
    _batch("2026-09-27T10:00:02Z", ("clickhouse_run_select_query_mcp_cbioportal-database", '{"n": 548}')),
    {"type": "SPAN", "name": "other", "startTime": "2026-09-27T10:00:00Z"},
]


def test_trace_stats_records_each_call_and_the_route():
    stats = trace_stats("t1", "https://lf/t1", ROUTED_OBSERVATIONS)
    assert stats.llm_calls == 3
    assert [g.agent for g in stats.generations] == [ROUTER, DATA, DATA]
    assert stats.generations[0].start == "2026-09-27T10:00:00Z"
    assert stats.generations[0].end == "2026-09-27T10:00:01Z"
    assert stats.models == [HAIKU]
    assert stats.handoffs == 1 and stats.routed_to == DATA
    # The handoff is not a data tool call and its batch is not a tool round.
    assert [c.name for c in stats.tool_calls] == ["clickhouse_run_select_query"]
    assert stats.tool_rounds == 1
    router = stats.generations[0]
    assert router.cost == pytest.approx((1000 * 1.0 + 30 * 5.0) / 1e6)
    data = stats.generations[1]
    assert (data.input_tokens, data.cache_read_tokens, data.cache_write_tokens) == (200, 30_000, 1000)
    assert data.cost == pytest.approx((200 * 1.0 + 40 * 5.0 + 1000 * 1.25 + 30_000 * 0.10) / 1e6)
    assert json.loads(json.dumps(stats.to_dict()))["routed_to"] == DATA


def test_handoff_seen_only_in_the_router_output_still_counts():
    observations = [o for o in ROUTED_OBSERVATIONS if o is not ROUTED_OBSERVATIONS[2]]
    stats = trace_stats("t", "u", observations)
    assert stats.handoffs == 1 and stats.routed_to == DATA and stats.tool_rounds == 1


def test_single_agent_trace_routes_to_its_own_node():
    stats = trace_stats(
        "t", "u", [_gen("agent_OHVSJI9Gd6gwsDnFSL-Xl", HAIKU, "a", "b", {"input": 1, "output": 1})]
    )
    assert stats.handoffs == 0 and stats.routed_to == "agent_OHVSJI9Gd6gwsDnFSL-Xl"


def test_describe_agents_follows_handoff_edges():
    agents = {
        ROUTER: {"instructions": "route", "model": HAIKU, "edges": [DATA, NAV], "updated_at": "2026-09-26"},
        DATA: {"instructions": "data", "model": HAIKU, "edges": []},
    }

    def fetch(agent_id, context):
        if agent_id not in agents:
            raise RuntimeError("not found")
        return agents[agent_id]

    out = describe_agents(ROUTER, None, fetch)
    assert list(out) == [ROUTER, DATA, NAV]
    assert out[ROUTER]["edges"] == [DATA, NAV] and out[ROUTER]["model"] == HAIKU and out[ROUTER]["chars"] == 5
    assert "not found" in out[NAV]["error"]


# (passed, declined, latency_s) per repeat
ROUTER_OUTCOMES = {
    1: [(True, False, 4.0), (True, False, 5.0), (True, False, 6.0)],
    2: [(True, False, 8.0), (False, False, 9.0), (True, False, 12.0)],
    40: [(True, False, 40.0)] * 3,
    60: [(False, False, 20.0), (False, False, 20.0), (False, True, 20.0)],
}


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(report_mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(compare_mod, "RESULTS_DIR", tmp_path)
    shutil.copytree(FIXTURES / BASELINE, tmp_path / BASELINE)
    baseline = Run.load(str(tmp_path / BASELINE))
    questions = {r["question"]["id"]: r["question"] for r in baseline.records.values()}
    questions[99] = questions[1] | {"id": 99, "question": "Only asked in the new run?"}
    ROUTER_OUTCOMES[99] = [(True, False, 3.0)] * 3
    router = Run.create(
        "beta-router", ["router"], 3, "us.anthropic.claude-sonnet-4-6", "input/questions.yaml"
    )
    router.data["run_id"] = "20260927-1200"
    for qid, repeats in ROUTER_OUTCOMES.items():
        for i, (passed, declined, latency) in enumerate(repeats, 1):
            observations = (
                ROUTED_OBSERVATIONS
                if qid != 40
                else [
                    _gen(ROUTER, HAIKU, "0", "1", {"input": 1000, "output": 30}, ["lc_transfer_to_" + NAV]),
                    _gen(NAV, SONNET, "1", "2", {"input": 500, "output": 200}),
                ]
            )
            trace = trace_stats(f"t{qid}{i}", "u", observations).to_dict()
            router.records[record_key(qid, "router", i)] = {
                "question": questions[qid],
                "model": "router",
                "repeat": i,
                "reply": {
                    "answer": "548",
                    "response_id": f"r{qid}{i}",
                    "status": 200,
                    "error": None,
                    "latency_s": latency,
                    "started_at": 0.0,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "trace": trace,
                "grade": {"passed": passed, "declined": declined, "rationale": "", "links": []},
            }
    router.save()
    yield baseline, router
    ROUTER_OUTCOMES.pop(99)


def test_router_answers_are_priced_per_call(results):
    _, router = results
    cost, complete = record_cost(router.records[record_key(40, "router", 1)])
    assert cost == pytest.approx((1000 * 1.0 + 30 * 5.0) / 1e6 + (500 * 2.0 + 200 * 10.0) / 1e6)
    assert complete is True
    # A call on an unpriced model leaves the cost incomplete.
    rec = router.records[record_key(40, "router", 2)]
    rec["trace"]["generations"][1]["cost"] = None
    cost, complete = record_cost(rec)
    assert complete is False and cost == pytest.approx((1000 * 1.0 + 30 * 5.0) / 1e6)


def test_summary_json_has_latency_calls_and_routing(results):
    _, router = results
    write_report(router)
    headline = json.loads((router.dir / "summary.json").read_text())["models"]["router"]
    assert headline["label"] == "Handoff router"
    assert headline["routed_to"] == {DATA: 12, NAV: 3}
    assert headline["median_llm_calls"] == 3 and headline["mean_tool_rounds"] == pytest.approx(0.8)
    assert headline["mean_handoffs"] == 1
    assert headline["p90_latency"] == 40.0
    assert headline["fast_share"] == pytest.approx(100 * 8 / 15)
    assert summarize(router)["models"][0].cost_per_answer > 0


def test_old_runs_summarize_without_the_new_trace_fields(results):
    baseline, _ = results
    haiku = summarize(baseline)["models"][0]
    assert haiku.mean_llm_calls == pytest.approx((2 + 2 + 17 + 9) / 4)
    assert haiku.mean_tool_rounds is None and not haiku.routed_to


def test_pick_model_needs_a_choice_for_multi_model_runs(results):
    baseline, router = results
    assert pick_model(router, None) == "router"
    with pytest.raises(ValueError, match="choose one"):
        pick_model(baseline, None)
    with pytest.raises(ValueError, match="no model 'router'"):
        pick_model(baseline, "router")


def test_compare_pools_repeats_against_the_old_baseline(results):
    baseline, router = results
    r = compare(baseline, router, "haiku")
    assert r["a"]["repeats"] == 1 and r["b"]["repeats"] == 3
    assert r["n_questions"] == 4 and r["only_b"] == [99] and r["only_a"] == []
    m = {x["key"]: x for x in r["metrics"]}
    assert m["pass_rate"]["a"] == 75.0
    assert m["pass_rate"]["b"] == pytest.approx(100 * 8 / 12)
    assert m["pass_rate"]["verdict"] == "worse"
    assert m["recall"]["b"] == pytest.approx(100 * 8 / 12)  # complete run: recall = graded pass rate
    assert m["attempt_rate"]["b"] == pytest.approx(100 * 11 / 12)
    assert m["fast_share"]["a"] == 50.0 and m["fast_share"]["b"] == pytest.approx(100 * 5 / 12)
    assert m["median_latency"]["verdict"] == "better"  # ~17.7s → 16s
    assert m["mean_tool_rounds"]["a"] is None and m["mean_tool_rounds"]["b"] is not None
    q = {x["id"]: x for x in r["questions"]}
    assert q[2]["b"]["flaky"] and q[2]["b"]["icons"] == "✓✗✓" and q[2]["verdict"] == "worse"
    assert q[2]["b"]["pass_variance"] == pytest.approx(2 / 3 * 1 / 3)
    assert q[1]["a"]["pass_variance"] is None  # one repeat: no variance
    assert q[40]["b"]["routed_to"] == [NAV]
    assert r["questions"][0]["id"] == 2  # regressions first
    assert r["question_verdicts"] == {"better": 0, "worse": 1, "same": 3}
    assert r["b"]["consistency"]["flaky"] == 1 and r["a"]["consistency"]["flaky"] == 0
    cats = {c["key"]: c for c in r["by_category"]}
    assert cats["Study discovery"]["a"]["recall"] == 100.0
    assert cats["Study discovery"]["b"]["recall"] == pytest.approx(100 * 5 / 6)
    assert cats["Study discovery"]["b"]["fast_share"] == pytest.approx(100 * 5 / 6)
    assert cats["Expression & multi-omics"]["a"]["eligible"] == 1
    assert cats["Expression & multi-omics"]["b"]["eligible"] == 3
    assert {t["key"] for t in r["by_track"]} == {"data", "analysis"}


def test_compare_writes_html_markdown_and_json(results, tmp_path):
    baseline, router = results
    out = write_compare(compare(baseline, router, "sonnet"))
    assert out == tmp_path / "compare" / f"{BASELINE}-sonnet_vs_20260927-1200-router" / "compare.html"
    html = out.read_text()
    assert "Handoff router" in html and "Sonnet 5" in html and "Under 10s, of completed turns" in html
    assert "✓✗✓" in html and "Expression &amp; multi-omics" in html
    md = (out.parent / "compare.md").read_text()
    assert (
        "| Recall: passes / eligible turns (failed or missing = not passed) | 75.0% | 66.7% | -8.3 pp ▼ |"
        in md
    )
    assert (
        "Routed to (B): `agent_cbiobeta_data` 9, `agent_cbiobeta_navigation` 3" in md
    )  # shared questions only
    assert json.loads((out.parent / "compare.json").read_text())["b"]["model"] == "router"


def test_compare_command(results, tmp_path):
    baseline, router = results
    args = [str(baseline.dir), str(router.dir), "--model-a", "haiku", "--out", str(tmp_path / "cmp")]
    result = CliRunner().invoke(cli_mod.cli, ["compare", *args])
    assert result.exit_code == 0, result.output
    assert "# Benchmark comparison" in result.output and (tmp_path / "cmp" / "compare.html").exists()
    result = CliRunner().invoke(cli_mod.cli, ["compare", str(baseline.dir), str(router.dir)])
    assert result.exit_code == 2 and "choose one" in result.output
