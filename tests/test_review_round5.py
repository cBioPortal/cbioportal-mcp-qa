"""Fifth review of #70: one redaction boundary for everything written, and known secret values masked first."""

import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
from test_review_fixes import JUDGE, _rec, _run

from cbioportal_mcp_qa import agent_prompt, config
from cbioportal_mcp_qa.claude_code import format_transcript, parse_stream
from cbioportal_mcp_qa.compare import compare, write_compare
from cbioportal_mcp_qa.persist import scrub, write_text
from cbioportal_mcp_qa.redact import CommandFailed, add_secret, redact
from cbioportal_mcp_qa.report import write_index, write_report
from cbioportal_mcp_qa.run import Run, record_key
from cbioportal_mcp_qa.traces import _tool_calls

H, T = "R5HEAD_93ce", "R5TAIL_42ab"
SRC = Path(__file__).parent.parent / "src" / "cbioportal_mcp_qa"


def _all_results(results_dir) -> dict[str, str]:
    return {str(p.relative_to(results_dir)): p.read_text() for p in results_dir.rglob("*") if p.is_file()}


def _leaks(results_dir, *markers) -> dict:
    return {
        name: [m for m in markers if m in text]
        for name, text in _all_results(results_dir).items()
        if any(m in text for m in markers)
    }


# --- 1. codex's round-5 free-text probes ---------------------------------------------------------------------

PROBES = {
    "escaped_quote_newline": f'mongosh -p "{H}\\"\n{T}"',
    "ansi_quote_newline": f"mongosh -p $'{H}\\'\n{T}'",
    "env_multiline": f'MONGO_PASSWORD="{H}\n{T}"',
    "token_multiline": f"export GITHUB_TOKEN='{H}\n{T}'",
    "json_tabs": json.dumps({"error": f"mongosh\t-p\t{H}"}),
    "json_newline_value": json.dumps({"error": f'mongosh -p "{H}\n{T}"'}),
    "quoted_newline_before_flag": f'mongosh --eval "a\nb" -p {H}',
}


@pytest.mark.parametrize("text", PROBES.values(), ids=PROBES.keys())
@pytest.mark.parametrize("how", ["message", "stderr", "stdout"])
def test_probe_text_does_not_reach_saved_results(results_dir, text, how):
    def fetch(agent_id, context):
        if how == "message":
            raise RuntimeError(text)
        stream = {"stderr": text} if how == "stderr" else {"output": text}
        raise subprocess.CalledProcessError(1, ["kubectl", "exec", "pod", "--", "mongosh", "-p", H], **stream)

    agents = agent_prompt.describe_agents("agent_cbiobeta_router", None, fetch)
    bench = Run.create("beta-router", ["router"], 1, JUDGE, "input/questions.yaml", extra={"agents": agents})
    write_report(bench)
    assert _leaks(results_dir, H, T) == {}


def test_db_client_detection_is_scoped_to_its_line():
    text = "mongosh --quiet\nssh -p 2222 host\npsql -p 5432\nredis-cli -p 6379\nkubectl -n ns get pods"
    assert redact(text) == text
    assert redact(f"mongosh --quiet\nmysql -u root -p{H}\nssh -p 2222 host") == (
        "mongosh --quiet\nmysql -u root -p***\nssh -p 2222 host"
    )
    # A backslash-continued line is still the client's command.
    assert (
        redact(f"mongosh --quiet \\\n  -p {H}\nssh -p 2222 host")
        == "mongosh --quiet \\\n  -p ***\nssh -p 2222 host"
    )


# --- 2. Known values -----------------------------------------------------------------------------------------

KNOWN = 'kn0wn-S3cret/Value+q=1&"x"\\y'


def test_known_values_are_masked_in_every_encoded_form(results_dir, monkeypatch):
    monkeypatch.setenv("MONGO_PASSWORD", KNOWN)
    forms = [KNOWN, quote(KNOWN, safe=""), json.dumps(KNOWN)[1:-1], html.escape(KNOWN)]
    # No pattern would catch these: the value appears as plain prose.
    bench = _run("K", "haiku", 1, [_rec(1, "haiku", 1)])
    rec = bench.records[record_key(1, "haiku", 1)]
    rec["reply"]["answer"] = " / ".join(f"the value is {f} here" for f in forms)
    bench.save()
    write_report(bench)
    for name, text in _all_results(results_dir).items():
        assert not any(f in text for f in forms), name
    assert (
        "the value is *** here"
        in json.loads((bench.dir / "run.json").read_text())["records"][record_key(1, "haiku", 1)]["reply"][
            "answer"
        ]
    )


def test_settings_and_the_k8s_mongo_password_are_known(monkeypatch):
    monkeypatch.setenv("LIBRECHAT_API_KEY", "librechat-key-6f1d")
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    config.load_settings()
    assert redact("sent librechat-key-6f1d along") == "sent *** along"

    def run(cmd, **kwargs):
        if "pods" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="pod/cbioagent-mongodb-0\n")
        if "secret" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="bW9uZ28tcHctN2E5Yw==")  # mongo-pw-7a9c
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(CommandFailed):
        agent_prompt.fetch_agent_prompt("agent_x")
    assert redact("the agent said mongo-pw-7a9c in prose") == "the agent said *** in prose"
    assert redact("raw bW9uZ28tcHctN2E5Yw== value") == "raw *** value"


def test_short_values_are_not_known():
    add_secret("abc12")
    assert redact("abc12 stays") == "abc12 stays"


# --- 3. Everything written goes through the boundary -------------------------------------------------------------

PATTERN_SECRET = f"mongosh -p {H}"  # caught by the patterns
RAW = "raw-known-9c2e71"  # caught as a known value


def _stream_lines(secret: str) -> list[str]:
    return [
        json.dumps(e)
        for e in [
            {
                "type": "assistant",
                "message": {
                    "id": "m",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t",
                            "name": "mcp__db__query",
                            "input": {"cmd": secret, secret: [secret]},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t", "is_error": True, "content": secret}
                    ]
                },
            },
            {"type": "result", "is_error": True, "result": secret},
        ]
    ]


def test_every_file_written_under_results_is_scrubbed(results_dir, monkeypatch):
    monkeypatch.setenv("BENCH_API_TOKEN", RAW)
    a = _run("A", "haiku", 1, [_rec(1, "haiku", 1), _rec(2, "haiku", 1)])
    b = _run("B", "router", 1, [_rec(1, "router", 1), _rec(2, "router", 1)])
    for run, model in ((a, "haiku"), (b, "router")):
        for qid, secret in ((1, PATTERN_SECRET), (2, RAW)):
            rec = run.records[record_key(qid, model, 1)]
            # Captured the real way: Claude's stream and a Langfuse observation...
            reply = parse_stream(_stream_lines(secret), 0, 1)
            langfuse = _tool_calls(
                {
                    "output": {
                        "messages": [
                            {
                                "id": ["ToolMessage"],
                                "kwargs": {"name": "t", "status": "error", "content": secret},
                            }
                        ]
                    }
                }
            )
            # ...and put in raw, as if a capture point were missed, in every field type.
            rec["reply"]["error"] = secret
            rec["reply"]["answer"] = f"answer with {secret}"
            rec["trace"] = reply.trace | {
                "tool_calls": reply.trace["tool_calls"]
                + [c.__dict__ for c in langfuse]
                + [
                    {
                        "name": "q",
                        "ok": False,
                        "error": secret,
                        "input": secret,
                        "result": [secret, {secret: secret}],
                    }
                ],
                "url": "transcript.txt",
            }
            rec["question"]["notes"] = secret
            rec["grade"]["rationale"] = secret
            rec[secret] = {"nested": [[secret]]}
        run.data["agents"] = {"agent_x": {"error": RAW}, RAW: {"error": PATTERN_SECRET}}
        run.save()
        write_text(
            run.dir / "transcript.txt", format_transcript(_stream_lines(PATTERN_SECRET)) + f"\nraw: {RAW}"
        )
        write_report(run)
    write_compare(compare(a, b, "haiku", allow_mismatch=True))
    write_index()
    files = _all_results(results_dir)
    assert {
        "A/run.json",
        "A/summary.json",
        "A/report.html",
        "A/transcript.txt",
        "index.html",
        "test-sets.html",
    } <= set(files)
    assert any(n.endswith("compare.json") for n in files) and any(n.endswith("compare.md") for n in files)
    assert _leaks(results_dir, H, RAW) == {}
    # The run is still readable after scrubbing.
    reloaded = Run.load("A")
    assert reloaded.records[record_key(1, "haiku", 1)]["reply"]["answer"] == "answer with mongosh -p ***"


def test_scrub_keeps_types_and_walks_keys():
    from collections import Counter, defaultdict

    counts = Counter({f"mongosh -p {H}": 2})
    by = defaultdict(list, {"k": [f"mongosh -p {H}"]})
    out = scrub({"counts": counts, "by": by, ("t", 1): (f"mongosh -p {H}",)})
    assert isinstance(out["counts"], Counter) and out["counts"] == Counter({"mongosh -p ***": 2})
    assert (
        isinstance(out["by"], defaultdict)
        and out["by"]["missing"] == []
        and out["by"]["k"] == ["mongosh -p ***"]
    )
    assert out[("t", 1)] == ("mongosh -p ***",)


def test_only_persist_writes_files():
    # Every write under results/ must go through persist; the only other writes are Claude's temp MCP configs.
    writes = re.compile(r"\.write_text\(|\.write_bytes\(|json\.dump\(|open\([^)]*[\"'][wa]")
    found = {
        f"{p.name}:{i}"
        for p in SRC.glob("*.py")
        if p.name != "persist.py"
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if writes.search(line)
    }
    temp_configs = {n for n in found if n.startswith("claude_code.py:")}
    assert found == temp_configs and len(temp_configs) == 4, found
    for n in temp_configs:
        line = (SRC / "claude_code.py").read_text().splitlines()[int(n.split(":")[1]) - 1]
        assert "config" in line or "json.dump(" in line, line


def test_real_results_are_not_over_masked():
    # The 09-23 baseline holds no secrets; scrubbing it must not change a thing (one answer has sample code
    # with `password=""`, which used to be masked to the end of the answer).
    baseline = Run.load("results/20260923-1919")
    assert scrub(baseline.data) == baseline.data
    assert (
        redact('password="",\n    database="x"\nprint("\\n")')
        == 'password="",\n    database="x"\nprint("\\n")'
    )
