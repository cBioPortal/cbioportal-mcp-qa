"""Sixth review of #70: credentials in structure (secret-named keys, argv lists), env names and URI passwords."""

import asyncio
import json
from collections import Counter
from urllib.parse import quote

import pytest
from test_review_fixes import _rec, _run

from cbioportal_mcp_qa import persist, render
from cbioportal_mcp_qa.persist import scrub, write_json, write_private_json
from cbioportal_mcp_qa.report import write_report
from cbioportal_mcp_qa.run import record_key

UNKNOWN = "UnknownValue_R6_93de"  # never registered: only structure gives it away


@pytest.mark.parametrize(
    "key",
    ["password", "PASSWORD", "db_password", "mongoPassword", "apiToken", "access_token", "X-Api-Key", "api_key",
     "apikey", "Authorization", "Cookie", "Set-Cookie", "credentials", "client_secret", "pwd", "mongo_pass",
     "LANGFUSE_SECRET_KEY", "private_key", "auth"],
)  # fmt: skip
def test_secret_named_keys_mask_their_value(key):
    assert scrub({key: UNKNOWN, "nested": [{key: UNKNOWN}]}) == {key: "***", "nested": [{key: "***"}]}


# Numbers and nested values under a secret key are masked since round 7 (tests/test_review_round7.py).
@pytest.mark.parametrize("value", ["", "   ", None, True, False, [], {}, [""], {"inner": None}])
def test_empty_values_are_kept(value):
    assert scrub({"password": value}) == {"password": value}


def test_counters_and_ordinary_keys_are_kept():
    outcomes = Counter({"pass": 3, "fail": 1})
    usage = {"prompt_tokens": 10, "max_tokens": 4096, "tokens": 5, "passed": True, "bypass_cache": "yes"}
    assert scrub({"outcomes": outcomes, "usage": usage}) == {"outcomes": outcomes, "usage": usage}
    assert isinstance(scrub(outcomes), Counter)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["mongosh", "-p", UNKNOWN], ["mongosh", "-p", "***"]),
        (["mongosh", "-p", UNKNOWN, "--quiet"], ["mongosh", "-p", "***", "***"]),  # fail closed: the rest
        (["/usr/bin/mysql", "-u", "root", f"-p{UNKNOWN}"], ["/usr/bin/mysql", "-u", "root", "-p***"]),
        (("redis-cli", "-a", UNKNOWN, "ping"), ("redis-cli", "-a", "***", "***")),
        (["tool", "--password", UNKNOWN], ["tool", "--password", "***"]),
        (["curl", "-u", f"admin:{UNKNOWN}", "https://x"], ["curl", "-u", "admin:***", "***"]),
        (["kubectl", "exec", "pod", "--", "mongosh", "-p", UNKNOWN], ["kubectl", "exec", "pod", "--", "mongosh", "-p", "***"]),
    ],
)  # fmt: skip
def test_argv_lists_are_read_as_commands(argv, expected):
    assert scrub(argv) == expected
    assert scrub({"cmd": argv}) == {"cmd": expected}


@pytest.mark.parametrize(
    "argv",
    [
        ["kubectl", "-n", "ns", "get", "pods"],
        ["ssh", "-p", "2222", "host"],
        ["psql", "-p", "5432"],
        ["redis-cli", "-p", "6379", "ping"],
        ["mysql", "-P", "3306", "-p", "-h", "db"],
        ["msk_chord_2024", "mongosh", "-p"],  # a flag with nothing after it
    ],
)
def test_harmless_argv_lists_are_kept(argv):
    assert scrub(argv) == argv


def test_colliding_redacted_keys_keep_every_entry():
    out = scrub({"mongosh -p one": 1, "mongosh -p two": 2, "mongosh -p three": 3})
    assert out == {"mongosh -p ***": 1, "mongosh -p *** #2": 2, "mongosh -p *** #3": 3}


def test_structured_credentials_do_not_reach_saved_results(results_dir):
    bench = _run("S", "haiku", 1, [_rec(1, "haiku", 1)])
    rec = bench.records[record_key(1, "haiku", 1)]
    rec["tool_input"] = {"password": UNKNOWN, "argv": ["mongosh", "-p", UNKNOWN]}
    bench.data["agents"] = {
        "agent_x": {"headers": {"Authorization": f"Bearer-less {UNKNOWN}", "Cookie": UNKNOWN}}
    }
    bench.save()
    write_report(bench)
    write_json(results_dir / "structured.json", {"password": UNKNOWN, "nested": {"token": UNKNOWN}})
    leaks = [p.name for p in results_dir.rglob("*") if p.is_file() and UNKNOWN in p.read_text()]
    assert leaks == []


# --- Known secrets from the environment ------------------------------------------------------------------------

PG = "PgValue_R6_72bc"
DECODED = "UriValue_R6/72bc:p@ss"


@pytest.mark.parametrize(
    "name", ["PGPASSWORD", "MYSQL_PWD", "REDISCLI_AUTH", "SOME_APIKEY", "ANTHROPIC_KEY", "x_credential"]
)
def test_secret_env_names_are_registered(name, monkeypatch):
    value = f"{name}-value-9f"
    monkeypatch.setenv(name, value)
    assert scrub(f"echo {value}") == "echo ***"


def test_working_directory_env_is_not_a_secret(monkeypatch):
    monkeypatch.setenv("PWD", "/Users/someone/project")
    assert scrub("/Users/someone/project/input") == "/Users/someone/project/input"


def test_env_and_uri_passwords_echoed_in_prose_do_not_reach_saved_results(results_dir, monkeypatch):
    monkeypatch.setenv("PGPASSWORD", PG)
    monkeypatch.setenv("DATABASE_MCP_URL", f"https://user:{quote(DECODED, safe='')}@example.invalid/mcp")
    bench = _run("E", "haiku", 1, [_rec(1, "haiku", 1)])
    rec = bench.records[record_key(1, "haiku", 1)]
    rec["reply"]["answer"] = f"the agent echoed {PG} and {DECODED} and {quote(DECODED, safe='')} in prose"
    bench.save()
    write_report(bench)
    for name in ("run.json", "report.html"):
        text = (bench.dir / name).read_text()
        assert PG not in text and DECODED not in text and quote(DECODED, safe="") not in text, name
        assert "the agent echoed *** and *** and *** in prose" in text or name == "report.html"


# --- Screenshots and private files --------------------------------------------------------------------------------


class FakePage:
    def __init__(self):
        self.shots = []

    async def goto(self, *a, **k): ...
    async def wait_for_function(self, *a, **k): ...
    async def wait_for_load_state(self, *a, **k): ...
    async def inner_text(self, *a):
        return "page"

    async def screenshot(self, **kwargs):
        self.shots.append(kwargs["path"])

    async def close(self): ...

    def locator(self, *a):
        page = self

        class Loc:
            first = page

        return Loc()

    async def wait_for(self, *a, **k): ...


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()

    async def new_page(self, **kwargs):
        return self.page


@pytest.mark.parametrize("screenshots", [True, False])
def test_screenshots_go_through_persist_and_can_be_skipped(tmp_path, monkeypatch, screenshots):
    pytest.importorskip("playwright")
    written = []
    real = persist.write_screenshot

    async def spy(page, path):
        written.append(path)
        await real(page, path)

    monkeypatch.setattr(render, "write_screenshot", spy)
    browser = FakeBrowser()
    result = asyncio.run(
        render._render_one(browser, "https://www.cbioportal.org/x", tmp_path, "shots", screenshots)
    )
    assert result.ok
    assert bool(written) == screenshots == bool(browser.page.shots)
    assert (result.screenshot is not None) == screenshots


def test_private_files_stay_out_of_results(results_dir, tmp_path):
    with pytest.raises(ValueError, match="temp directory"):
        write_private_json("results/mcp.json", {"token": UNKNOWN})
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        write_private_json(f"{d}/mcp.json", {"token": UNKNOWN})
        assert json.loads(open(f"{d}/mcp.json").read()) == {"token": UNKNOWN}  # used as is, not redacted
