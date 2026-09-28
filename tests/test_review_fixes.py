"""Fixes from the review of the router benchmark (#70): secrets in recorded errors, comparability checks,
failed and missing turns, routing attribution, and question/category metrics."""

import base64
import json
import subprocess
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner
from test_router_compare import DATA, HAIKU, ROUTED_OBSERVATIONS, ROUTER, _batch, _gen

from cbioportal_mcp_qa import agent_prompt, versions
from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa import run as run_mod
from cbioportal_mcp_qa.agent import AgentClient
from cbioportal_mcp_qa.compare import compare, to_markdown, write_compare
from cbioportal_mcp_qa.config import TARGETS
from cbioportal_mcp_qa.redact import CommandFailed, describe_error, redact
from cbioportal_mcp_qa.report import quantile, summarize, write_report
from cbioportal_mcp_qa.run import Run, record_key
from cbioportal_mcp_qa.traces import UNKNOWN, trace_stats

SECRET = "hunter2-Zq9xT4"
JUDGE = "us.anthropic.claude-sonnet-4-6"


# --- 1. Secrets never reach saved results ----------------------------------------------------------------------


def _fake_kubectl(monkeypatch):
    """kubectl that finds the pod and secret, then fails the mongosh exec the way a real failure does."""

    def run(cmd, **kwargs):
        if "pods" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="pod/cbioagent-mongodb-0\n")
        if "secret" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=base64.b64encode(SECRET.encode()).decode())
        raise subprocess.CalledProcessError(
            1,
            cmd,
            stderr=f"MongoServerError: Authentication failed. uri=mongodb://cbioagent:{SECRET}@localhost",
        )

    monkeypatch.setattr(subprocess, "run", run)


def test_failed_mongosh_exec_does_not_leak_the_password(results_dir, monkeypatch):
    _fake_kubectl(monkeypatch)
    # The command carries the password (in its URI); the error raised where it fails carries no command.
    with pytest.raises(CommandFailed) as raised:
        agent_prompt.fetch_agent_prompt(ROUTER)
    assert SECRET not in str(raised.value) and str(raised.value).startswith("kubectl exited with status 1: ")

    agents = agent_prompt.describe_agents(ROUTER)
    assert "CommandFailed" in agents[ROUTER]["error"] and "***@localhost" in agents[ROUTER]["error"]
    probe = versions._probe(lambda: agent_prompt.fetch_agent_prompt(ROUTER))
    bench = Run.create(
        "beta-router",
        ["router"],
        1,
        JUDGE,
        "input/questions.yaml",
        extra={
            "agents": agents,
            "versions": {"librechat": probe},
            "agent_prompt": {"agent_id": ROUTER, "error": describe_error(raised.value)},
        },
    )
    write_report(bench)
    persisted = [p for p in results_dir.rglob("*") if p.is_file()]
    assert persisted and all(SECRET not in p.read_text() for p in persisted)


def test_request_errors_are_redacted_before_they_are_recorded():
    import asyncio

    client = AgentClient(TARGETS["beta-router"], "key")

    async def boom(*args, **kwargs):
        raise httpx.ConnectError(f"proxy http://user:{SECRET}@proxy:3128 refused")

    client.http.post = boom
    reply = asyncio.run(client._post({}, 0.0))
    asyncio.run(client.aclose())
    assert reply.error.startswith("ConnectError") and SECRET not in reply.error


@pytest.mark.parametrize(
    "text",
    [
        f"mongosh mongodb://cbioagent:{SECRET}@localhost:27017/cBioAgent --quiet",
        f"['mongosh', '--password', '{SECRET}', '--quiet']",
        f"mongosh --password={SECRET}",
        f"Authorization: Bearer {SECRET}abcdefgh",
        f'{{"api_key": "{SECRET}"}}',
        f"LANGFUSE_SECRET_KEY={SECRET}",
        f"https://x/api?token={SECRET}&page=1",
        "key sk-ant-api03-" + SECRET + "abcdef and sk-lf-" + SECRET + "1234",
        "AKIAABCDEFGHIJKLMNOP " + SECRET.replace("hunter2", "AKIA"),
    ],
)
def test_redact_removes_credentials(text):
    out = redact(text)
    assert SECRET not in out and "AKIAABCDEFGHIJKLMNOP" not in out
    assert "***" in out


def test_redact_keeps_ordinary_text_and_links():
    text = "See https://www.cbioportal.org/study/summary?id=msk_chord_2024 (tokens: 1200 input)"
    assert redact(text) == text
    assert redact(None) is None


def test_describe_error_redacts_before_truncating():
    def failing(pad: int) -> subprocess.CalledProcessError:
        return subprocess.CalledProcessError(1, ["mongosh", "x" * pad + f"mongodb://u:{SECRET}@h"])

    # Pad so the password straddles the 200-character cut: truncating first would keep its first half.
    pad = next(n for n in range(200) if 190 < f"CalledProcessError: {failing(n)}".find(SECRET) < 196)
    raw = f"CalledProcessError: {failing(pad)}"[:200]
    assert SECRET[:4] in raw and SECRET not in raw
    assert SECRET[:4] not in describe_error(failing(pad), 200)


# --- 2. Only comparable runs are compared -----------------------------------------------------------------------


def _question(qid: int, **overrides) -> dict:
    return {
        "id": qid,
        "category": "Study discovery" if qid < 3 else "Alteration frequency",
        "study": "all",
        "question": f"Question {qid}?",
        "track": "data",
        "expected_answer": str(qid),
        "expected_links": [],
        "notes": "",
        "history": [],
    } | overrides


def _rec(
    qid, model, repeat, passed=True, *, declined=False, status=200, latency=5.0, graded=True, trace=None, **q
):
    rec = {
        "question": _question(qid, **q),
        "model": model,
        "repeat": repeat,
        "reply": {
            "answer": "x" if status == 200 else "",
            "response_id": f"r{qid}{repeat}",
            "status": status,
            "error": None if status == 200 else "504 Gateway Timeout",
            "latency_s": latency,
            "started_at": 0.0,
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
    }
    if trace:
        rec["trace"] = trace
    if status == 200 and graded:
        rec["grade"] = {"passed": passed, "declined": declined, "rationale": "", "links": []}
    return rec


def _run(run_id, model, repeats, records, judge=JUDGE, questions_file="input/questions.yaml"):
    created = Run.create("beta", [model], repeats, judge, questions_file)
    created.path.unlink()
    # Run.create names the directory by the minute; give each test run its own.
    bench = Run(run_mod.RESULTS_DIR / run_id / "run.json", created.data | {"run_id": run_id})
    bench.path.parent.mkdir(parents=True, exist_ok=True)
    for rec in records:
        bench.records[record_key(rec["question"]["id"], model, rec["repeat"])] = rec
    bench.save()
    return bench


def _pair(**b_overrides):
    a = _run("A", "haiku", 1, [_rec(q, "haiku", 1) for q in (1, 2, 3)])
    b_records = [_rec(q, "router", r, **(b_overrides if q == 2 else {})) for q in (1, 2, 3) for r in (1, 2)]
    return a, b_records


def test_compare_refuses_a_different_judge(results_dir):
    a, recs = _pair()
    b = _run("B", "router", 2, recs, judge="us.anthropic.claude-haiku-4-5")
    with pytest.raises(ValueError, match="judge model differs"):
        compare(a, b, "haiku")


def test_compare_refuses_a_different_questions_file(results_dir):
    a, recs = _pair()
    b = _run("B", "router", 2, recs, questions_file="input/questions-multiturn.yaml")
    with pytest.raises(ValueError, match="questions file differs"):
        compare(a, b, "haiku")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"question": "A reworded question?"}, "question"),
        ({"expected_answer": "999"}, "expected_answer"),
        ({"notes": "A correct answer must: cite the study"}, "notes"),
        (
            {"history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]},
            "history",
        ),
        ({"expected_links": ["https://www.cbioportal.org/datasets"]}, "expected_links"),
    ],
)
def test_compare_refuses_changed_question_definitions(results_dir, overrides, field):
    a, recs = _pair(**overrides)
    b = _run("B", "router", 2, recs)
    with pytest.raises(ValueError, match=rf"1 questions changed.*Q2 \({field}\)"):
        compare(a, b, "haiku")
    result = compare(a, b, "haiku", allow_mismatch=True)
    assert result["mismatched_questions"] == [2]
    assert {q["id"]: q["mismatch"] for q in result["questions"]} == {1: [], 2: [field], 3: []}
    assert any("different definitions" in w for w in result["warnings"])
    assert "⚠ changed: " + field in to_markdown(result)


def test_equivalent_empty_fields_are_not_a_mismatch(results_dir):
    # Old runs stored missing history as [] or left it out; neither is a change.
    a = _run("A", "haiku", 1, [_rec(1, "haiku", 1, history=None, notes=None)])
    b = _run("B", "router", 1, [_rec(1, "router", 1)])
    assert compare(a, b, "haiku")["mismatched_questions"] == []


def test_compare_command_refuses_then_allows_with_a_warning(results_dir):
    a, recs = _pair(notes="changed")
    b = _run("B", "router", 2, recs)
    refused = CliRunner().invoke(cli_mod.cli, ["compare", str(a.dir), str(b.dir), "--model-a", "haiku"])
    assert refused.exit_code == 2 and "--allow-mismatch" in refused.output and "Q2 (notes)" in refused.output
    allowed = CliRunner().invoke(
        cli_mod.cli, ["compare", str(a.dir), str(b.dir), "--model-a", "haiku", "--allow-mismatch"]
    )
    assert allowed.exit_code == 0, allowed.output
    assert "Warning: 1 questions have different definitions" in allowed.output


# --- 3. Failed, missing and ungraded turns are counted ----------------------------------------------------------


@pytest.fixture
def incomplete(results_dir):
    a = _run("A", "haiku", 1, [_rec(q, "haiku", 1, latency=4.0) for q in (1, 2, 3)])
    b = _run(
        "B",
        "router",
        3,
        [
            _rec(1, "router", 1, latency=4.0),
            _rec(1, "router", 2, latency=6.0),  # repeat 3 missing
            _rec(2, "router", 1, latency=8.0),
            _rec(2, "router", 2, status=504, latency=120.0),
            _rec(2, "router", 3, latency=9.0),
            _rec(3, "router", 1, latency=30.0),
            _rec(3, "router", 2, graded=False, latency=31.0),  # not graded yet
            _rec(3, "router", 3, passed=False, latency=32.0),
        ],
    )
    return a, b


def test_failed_and_missing_turns_count_against_recall_and_are_reported(incomplete):
    a, b = incomplete
    r = compare(a, b, "haiku")
    assert r["b"]["counts"] == {
        "expected": 9,
        "completed": 7,
        "failed": 1,
        "missing": 1,
        "ungraded": 1,
        "no_reference": 0,
        "eligible": 8,  # 6 graded + 1 failed + 1 missing
        "unexpected": 0,
    }
    m = {x["key"]: x for x in r["metrics"]}
    assert m["recall"]["b"] == pytest.approx(100 * 5 / 8)
    assert m["pass_rate"]["b"] == pytest.approx(100 * 5 / 6)  # report definition leaves failures out
    assert m["precision"]["b"] == pytest.approx(100 * 5 / 6)
    assert m["attempt_rate"]["b"] == pytest.approx(100 * 6 / 8)
    # Latency over completed turns, and with the failed turn at its elapsed 120s.
    assert m["median_latency"]["b"] == 9.0 and m["p90_latency"]["b"] == 32.0
    assert m["median_latency_all"]["b"] == pytest.approx(19.5) and m["p90_latency_all"]["b"] == 120.0
    assert m["fast_share"]["b"] == pytest.approx(100 * 4 / 7)
    assert m["fast_share_all"]["b"] == pytest.approx(100 * 4 / 8)
    assert any(
        "B (B) is incomplete: 7 of 9" in w and "1 failed, 1 missing, 1 ungraded" in w for w in r["warnings"]
    )
    assert not any(w.startswith("A ") for w in r["warnings"])

    q = {x["id"]: x["b"] for x in r["questions"]}
    assert q[1]["icons"] == "✓✓?" and (q[1]["missing"], q[1]["eligible"], q[1]["recall"]) == (
        1,
        3,
        pytest.approx(200 / 3),
    )
    assert q[2]["icons"] == "✓!✓" and q[2]["failed"] == 1 and q[2]["recall"] == pytest.approx(200 / 3)
    assert q[3]["ungraded"] == 1 and q[3]["eligible"] == 2 and q[3]["recall"] == 50.0
    cats = {c["key"]: c["b"] for c in r["by_category"]}
    assert (cats["Study discovery"]["failed"], cats["Study discovery"]["missing"]) == (1, 1)
    assert cats["Alteration frequency"]["ungraded"] == 1

    md = to_markdown(r)
    assert "| B | 9 | 7 | 1 | 1 | 1 | 0 | 8 |" in md
    assert "4/6 (1, 1, 0)" in md  # Study discovery for B: completed/expected (failed, missing, ungraded)
    html = write_compare(r).read_text()
    assert "is incomplete" in html and "✓!✓" in html


def test_repeats_above_the_run_setting_are_flagged(results_dir):
    a = _run("A", "haiku", 1, [_rec(1, "haiku", 1), _rec(1, "haiku", 2)])
    b = _run("B", "router", 1, [_rec(1, "router", 1)])
    r = compare(a, b, "haiku")
    assert r["a"]["counts"]["unexpected"] == 1 and r["a"]["counts"]["expected"] == 1
    assert any("repeat number above the run's 1" in w for w in r["warnings"])


def test_no_reference_questions_stay_out_of_recall(results_dir):
    no_ref = {"expected_answer": None, "notes": ""}
    a = _run("A", "haiku", 1, [_rec(1, "haiku", 1), _rec(2, "haiku", 1, passed=None, **no_ref)])
    b = _run("B", "router", 1, [_rec(1, "router", 1), _rec(2, "router", 1, status=500, **no_ref)])
    r = compare(a, b, "haiku")
    assert r["b"]["counts"]["no_reference"] == 1 and r["b"]["counts"]["eligible"] == 1
    assert {x["key"]: x for x in r["metrics"]}["recall"]["b"] == 100.0


def test_the_2026_09_23_headline_is_unchanged():
    baseline = Run.load("results/20260923-1919")
    haiku, sonnet = summarize(baseline)["models"]
    assert round(haiku.pass_rate, 1) == 54.5 and round(sonnet.pass_rate, 1) == 63.9
    assert round(haiku.median_latency, 1) == 29.6 and round(sonnet.median_latency, 1) == 71.7
    r = compare(baseline, baseline, "haiku", "sonnet")
    m = {x["key"]: x for x in r["metrics"]}
    assert round(m["pass_rate"]["a"], 1) == 54.5 and round(m["pass_rate"]["b"], 1) == 63.9
    assert round(m["median_latency"]["a"], 1) == 29.6 and round(m["median_latency"]["b"], 1) == 71.7
    assert r["b"]["counts"]["failed"] == 1 and round(m["recall"]["b"], 1) == 63.4


# --- 4. Routing is attributed to the agent that answered ---------------------------------------------------------


def test_routed_to_is_unknown_when_the_answering_call_has_no_agent():
    observations = [dict(o) for o in ROUTED_OBSERVATIONS]
    final = next(o for o in observations if o["startTime"] == "2026-09-27T10:00:03Z")
    final["metadata"] = {}
    stats = trace_stats("t", "u", observations)
    # Not the transfer's destination, and not the last agent that happened to be recorded.
    assert stats.routed_to == UNKNOWN
    assert stats.handoffs == 1


def _failed_transfer_observations() -> list[dict]:
    batch = _batch("1", ("lc_transfer_to_" + DATA, "Error: agent not found"))
    batch["output"]["messages"][0]["kwargs"]["status"] = "error"
    return [
        _gen(ROUTER, HAIKU, "0", "1", {"input": 10, "output": 5}, ["lc_transfer_to_" + DATA]),
        batch,
        _gen(ROUTER, HAIKU, "2", "3", {"input": 10, "output": 50}),
    ]


def test_failed_transfer_is_not_a_handoff_and_does_not_route():
    stats = trace_stats("t", "u", _failed_transfer_observations())
    assert stats.handoffs == 0 and stats.failed_handoffs == 1
    assert stats.handoff_evidence == [{"to": DATA, "status": "error", "error": "Error: agent not found"}]
    assert stats.routed_to == ROUTER


def test_transfer_without_result_or_destination_call_is_unconfirmed():
    observations = [
        _gen(ROUTER, HAIKU, "0", "1", {"input": 10, "output": 5}, ["lc_transfer_to_" + DATA]),
        _gen(ROUTER, HAIKU, "2", "3", {"input": 10, "output": 50}),
    ]
    stats = trace_stats("t", "u", observations)
    assert stats.handoffs == 0 and stats.failed_handoffs == 0
    assert stats.handoff_evidence == [{"to": DATA, "status": "unconfirmed", "error": None}]
    assert stats.routed_to == ROUTER


def test_trace_without_generations_is_unknown():
    assert trace_stats("t", "u", []).routed_to == UNKNOWN


def test_failed_handoffs_reach_summary_json(results_dir):
    trace = trace_stats("t", "u", _failed_transfer_observations()).to_dict()
    bench = _run("R", "router", 1, [_rec(1, "router", 1, trace=trace)])
    write_report(bench)
    headline = json.loads((bench.dir / "summary.json").read_text())["models"]["router"]
    assert headline["failed_handoffs"] == 1 and headline["mean_handoffs"] == 0
    assert headline["routed_to"] == {ROUTER: 1}


# --- 5. Question- and category-level precision, recall, p90, share under 10s, calls ------------------------------


def test_question_and_category_metrics(results_dir):
    trace = {"llm_calls": 4, "tool_calls": [], "tool_rounds": 1, "handoffs": 1, "routed_to": DATA}
    a = _run("A", "haiku", 1, [_rec(q, "haiku", 1) for q in (1, 2)])
    b = _run(
        "B",
        "router",
        3,
        [
            _rec(1, "router", 1, latency=3.0, trace=trace),
            _rec(1, "router", 2, passed=False, latency=12.0, trace=trace | {"llm_calls": 6}),
            _rec(1, "router", 3, passed=False, declined=True, latency=20.0, trace=trace | {"llm_calls": 2}),
            *[_rec(2, "router", r, latency=40.0) for r in (1, 2, 3)],
        ],
    )
    r = compare(a, b, "haiku")
    q1 = next(q for q in r["questions"] if q["id"] == 1)["b"]
    assert q1["precision"] == 50.0 and q1["recall"] == pytest.approx(100 / 3)
    assert q1["attempt_rate"] == pytest.approx(200 / 3)
    assert q1["p90_latency"] == 20.0 and q1["fast_share"] == pytest.approx(100 / 3)
    assert q1["mean_llm_calls"] == 4.0
    cat = next(c for c in r["by_category"] if c["key"] == "Study discovery")["b"]
    assert cat["precision"] == pytest.approx(100 * 4 / 5) and cat["recall"] == pytest.approx(100 * 4 / 6)
    assert cat["p90_latency"] == 40.0 and cat["mean_llm_calls"] == 4.0
    html = write_compare(r).read_text()
    assert "Precision A" in html and "p90 A" in html and "LLM calls A" in html


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, None), (1, 1), (9, 9), (10, 10), (11, 10), (19, 18), (20, 19), (100, 91)],
)
def test_p90_is_the_upper_nearest_rank(n, expected):
    assert quantile([float(i) for i in range(n, 0, -1)], 0.9) == expected


def test_readme_defines_recall_and_the_p90_estimator():
    readme = Path("README.md").read_text()
    assert "**Recall**" in readme and "**Attempt rate**" in readme and "p90" in readme and "⌊0.9·n⌋" in readme
