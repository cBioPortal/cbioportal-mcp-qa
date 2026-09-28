"""Fourth review of #70: failed commands are never recorded, and free text is redacted fail-closed."""

import json
import subprocess
import time

import pytest
from test_review_fixes import JUDGE
from test_review_round3 import QUOTED_COMMANDS

from cbioportal_mcp_qa import agent_prompt, versions
from cbioportal_mcp_qa.redact import CommandFailed, describe_error, redact, run_command
from cbioportal_mcp_qa.report import write_report
from cbioportal_mcp_qa.run import Run

H, T = "R4HEAD_8f91", "R4TAIL_7c62"

# codex's round-4 probes, as text an exception or stderr may carry.
PROBES = {
    "prior_space": f'mongosh -p "{H} {T}"',
    "prior_semicolon": f"mongosh -p '{H};{T}'",
    "prior_bracket": f'mongosh --eval "x[0]" -p {H}',
    "nested": f'''sh -c "mongosh -p '{H} {T}'"''',
    "escaped": f'mongosh -p "{H}\\" {T}"',
    "ansi_plain": f"mongosh -p $'{H} {T}'",
    "ansi_escaped": f"mongosh -p $'{H}\\' {T}'",
    "tabs": f'mongosh\t-p\t"{H}\t{T}"',
    "newline": f'mongosh -p "{H}\n{T}"',
    "continued_line": f"mongosh \\\n-p {H}",
    "continued_twice": f"mongosh --quiet \\\n  -p {H} \\\n  {T}",
    "json": json.dumps({"error": f'mongosh -p "{H} {T}"'}),
    "truncated_quote": f'mongosh -p {H}"{T}',
    "repr_quotes": repr(["mongosh", "-p", f"""{H}'" {T}"""]),
    "invalid_literal": "['mongosh', '-p', '" + H + "\\xZZ" + T + "']",
    "redis_cli": f"redis-cli -h redis -p 6379 -a '{H} {T}' ping",
    "mysql_attached": f'mysql -u root -p"{H} {T}" -h db',
    "long_flag": f"kubectl exec pod -- tool --password $'{H}\\' {T}'",
    "user_pass": f"curl -u 'admin:{H} {T}' https://example.org",
}


def _save(bench_agents, results_dir) -> list:
    bench = Run.create(
        "beta-router", ["router"], 1, JUDGE, "input/questions.yaml", extra={"agents": bench_agents}
    )
    write_report(bench)
    files = [p for p in results_dir.rglob("*") if p.is_file()]
    assert {p.name for p in files} >= {"run.json", "summary.json", "report.html"}
    return files


def _leaks(files) -> dict:
    return {
        p.name: [m for m in (H, T) if m in p.read_text()]
        for p in files
        if H in p.read_text() or T in p.read_text()
    }


@pytest.mark.parametrize("text", PROBES.values(), ids=PROBES.keys())
@pytest.mark.parametrize("how", ["message", "stderr"])
def test_probe_text_does_not_reach_saved_results(results_dir, text, how):
    def fetch(agent_id, context):
        if how == "message":
            raise RuntimeError(text)
        # A failed command whose stderr echoes it; the command itself carries the markers too.
        raise subprocess.CalledProcessError(1, ["sh", "-c", text], stderr=f"error running: {text}")

    agents = agent_prompt.describe_agents("agent_cbiobeta_router", None, fetch)
    assert agents["agent_cbiobeta_router"]["error"]
    assert _leaks(_save(agents, results_dir)) == {}


@pytest.mark.parametrize("cmd", [c for c in QUOTED_COMMANDS.values() if isinstance(c, list)], ids=str)
def test_round3_commands_as_free_text_are_redacted(cmd):
    # The round-3 variants, as they read when a command is echoed as text rather than recorded.
    for text in (" ".join(cmd), repr(cmd), str(subprocess.CalledProcessError(1, cmd))):
        out = redact(text)
        assert "SYNTH_HEAD_q4" not in out and "SYNTH_TAIL_k8" not in out, text


# --- Recorded failures carry no arguments -----------------------------------------------------------------------

ARGS = ["exec", "cbioagent-mongodb-0", "--", "mongosh", "ARG_MARKER_one", "--eval", "ARG_MARKER_two"]


def test_recorded_command_errors_contain_no_argv(results_dir):
    failed = subprocess.CalledProcessError(
        2, ["/usr/local/bin/kubectl", *ARGS], stderr="line 1\nerror: boom\n"
    )
    timed_out = subprocess.TimeoutExpired(["kubectl", *ARGS], 60, output=b"partial output")
    shell = subprocess.CalledProcessError(1, "PGPASSWORD=ARG_MARKER_three psql -c 'select 1'")
    assert describe_error(failed) == "CalledProcessError: kubectl exited with status 2: line 1\nerror: boom"
    assert describe_error(timed_out) == "TimeoutExpired: kubectl timed out after 60s: partial output"
    assert describe_error(shell) == "CalledProcessError: command exited with status 1"

    def fetch(agent_id, context):
        raise failed

    agents = agent_prompt.describe_agents("agent_cbiobeta_router", None, fetch)
    probe = versions._probe(lambda: (_ for _ in ()).throw(timed_out))
    agents["probe"] = probe
    files = _save(agents, results_dir)
    for path in files:
        text = path.read_text()
        assert "ARG_MARKER" not in text and "cbioagent-mongodb-0" not in text, path.name
    recorded = json.loads(next(p for p in files if p.name == "run.json").read_text())["agents"]
    assert recorded["agent_cbiobeta_router"]["error"].startswith(
        "CalledProcessError: kubectl exited with status 2"
    )
    assert recorded["probe"]["error"].startswith("TimeoutExpired: kubectl timed out after 60s")


def test_run_command_raises_without_the_command(monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr=f"auth failed for mongosh -p {H}")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(CommandFailed) as raised:
        run_command(["kubectl", *ARGS], timeout=5)
    assert str(raised.value) == "kubectl exited with status 1: auth failed for mongosh -p ***"
    # Nothing chained: the CalledProcessError (and its argv) isn't even kept as the context.
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_output_tail_is_redacted_before_it_is_cut():
    # The flag falls outside the kept tail but T inside it: cutting first would keep T with no flag to find.
    stderr = f"mongosh -p {H} {'y' * 400} {T}"
    assert T in stderr[-300:] and "-p" not in stderr[-300:]
    assert T not in describe_error(subprocess.CalledProcessError(1, ["kubectl"], stderr=stderr), 1000)


@pytest.mark.parametrize(
    "text",
    [
        "kubectl -n ns get pods",
        "ssh -p 2222 host",
        "psql -p 5432",
        "redis-cli -p 6379",
        "mysql -P 3306 -p -h db",
        "mongosh --eval 'print(\"-p 1\")' --quiet",
    ],
)
def test_harmless_flags_stay_readable(text):
    assert redact(text) == text


def test_hostile_text_is_redacted_quickly():
    for text in ["[" * 10000 + "'x'" + "]" * 10000, "['x'] " * 5000, repr(["mongosh", "-p"] * 20000)]:
        start = time.monotonic()
        redact(text)
        assert time.monotonic() - start < 1
