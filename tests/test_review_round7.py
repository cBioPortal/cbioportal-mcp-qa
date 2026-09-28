"""Seventh review of #70: secret context reaches nested values and numeric credentials."""

import json
from collections import Counter

import pytest

from cbioportal_mcp_qa.persist import scrub, write_json
from cbioportal_mcp_qa.report import _headline, summarize
from cbioportal_mcp_qa.run import Run

SECRET = "ContainerSecret_R7_49af"


@pytest.mark.parametrize(
    ("obj", "expected"),
    [
        # codex's four cases
        ({"password": [SECRET]}, {"password": ["***"]}),
        ({"headers": {"Authorization": [SECRET]}}, {"headers": {"Authorization": ["***"]}}),
        ({"credentials": {"value": SECRET}}, {"credentials": {"value": "***"}}),
        ({"password": 987654321}, {"password": "***"}),
        # structure is kept, every leaf masked
        ({"token": {"a": [SECRET, (SECRET,)], "b": {"c": SECRET}}}, {"token": {"a": ["***", ("***",)], "b": {"c": "***"}}}),
        ({"credentials": {"user": "admin", "pin": 1234, "enabled": True, "note": None}},
         {"credentials": {"user": "***", "pin": "***", "enabled": True, "note": None}}),
        ({"db_password": 3.14159}, {"db_password": "***"}),
        ({"api_key": [123456, SECRET]}, {"api_key": ["***", "***"]}),
        ({"Cookie": {"session": SECRET}}, {"Cookie": {"session": "***"}}),  # keys are structure, values masked
    ],
)  # fmt: skip
def test_secret_keys_mask_every_nested_leaf(obj, expected, results_dir):
    assert scrub(obj) == expected
    write_json(results_dir / "out.json", obj)
    assert SECRET not in (results_dir / "out.json").read_text()
    assert "987654321" not in (results_dir / "out.json").read_text()


@pytest.mark.parametrize(
    "obj",
    [
        {"pass": 3, "fail": 1, "passed": True, "declined": 0},
        {"prompt_tokens": 12345, "completion_tokens": 5432, "total_tokens": 17777, "tokens": 777},
        {"max_tokens": 4096, "token_count": 9, "cache_read_tokens": 0, "cache_write_tokens": 3},
        {"password_count": 2, "secret_total": 4, "auth_count": 1},
        {"token": 42},  # a number under `token` is more likely a count than a credential
        {"password": None, "secret": True, "auth": False},
        {"outcomes": Counter({"pass": 3, "fail": 1})},
    ],
)
def test_counters_stay_intact(obj):
    assert scrub(obj) == obj


def test_counter_types_survive():
    out = scrub({"outcomes": Counter({"pass": 3})})
    assert isinstance(out["outcomes"], Counter) and out["outcomes"]["pass"] == 3


def test_the_09_23_run_and_its_summary_scrub_unchanged():
    base = Run.load("results/20260923-1919")
    cleaned = scrub(base.data)
    assert cleaned == base.data
    assert _headline(summarize(Run(base.path, cleaned))) == _headline(summarize(base))
    summary = json.loads((base.dir / "summary.json").read_text())
    assert scrub(summary) == summary
