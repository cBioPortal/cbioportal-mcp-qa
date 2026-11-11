"""Explicit secrets are masked (or refused) in every form a CI artifact could carry them: regression tests for each
bypass found in review."""

import base64
import json
from urllib.parse import quote

import pytest
from click.testing import CliRunner

from cbioportal_mcp_qa.cli import cli
from cbioportal_mcp_qa.persist import scrub_tree
from cbioportal_mcp_qa.secret_scan import MASK, Matcher, base64_fragments, matchers

PW = "hunter2-Secret_pw"


def _scrub(tmp_path, text, secrets=(("CH_PASSWORD", PW),), name="out.log"):
    root = tmp_path / "upload"
    root.mkdir(exist_ok=True)
    (root / name).write_text(text)
    scrubbed, removed, problems = scrub_tree(root, list(secrets))
    return (root / name).read_text() if (root / name).exists() else None, problems


def _b64(raw: bytes, urlsafe=False, pad=True) -> str:
    out = (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(raw).decode()
    return out if pad else out.rstrip("=")


@pytest.mark.parametrize("urlsafe", [False, True])
@pytest.mark.parametrize("pad", [False, True])
def test_whole_base64(tmp_path, urlsafe, pad):
    text, problems = _scrub(tmp_path, f"token={_b64(PW.encode(), urlsafe, pad)}\n")
    assert problems == [] and _b64(PW.encode(), urlsafe, pad).rstrip("=") not in text


@pytest.mark.parametrize("prefix", [b"", b"u", b"us", b"user:", b"user:12"])  # every alignment
@pytest.mark.parametrize("urlsafe", [False, True])
def test_base64_inside_a_larger_blob(tmp_path, prefix, urlsafe):
    # e.g. an HTTP Basic header or a base64'd connection string.
    blob = _b64(prefix + PW.encode() + b"@clickhouse:8443", urlsafe)
    text, problems = _scrub(tmp_path, f"Authorization: Basic {blob}\n")
    assert problems == []
    assert not any(f in text for f in base64_fragments(PW) if len(f) >= 8)


def test_base64_wrapped_at_76_columns(tmp_path):
    blob = _b64(b"x" * 50 + PW.encode() + b"y" * 50)
    wrapped = "\n".join(blob[i : i + 76] for i in range(0, len(blob), 76))
    text, problems = _scrub(tmp_path, wrapped)
    assert problems == [] and MASK in text


@pytest.mark.parametrize(
    "split",
    [
        "hunter2-Sec\nret_pw",
        "hunter2-Sec\r\nret_pw",
        "hunter2-Sec\n    ret_pw",  # wrapped and indented
        "hunter2-Sec\\nret_pw",  # a JSON-escaped line break
        "hu\nnter2-Se\ncret_pw",  # several breaks
    ],
)
def test_split_across_lines(tmp_path, split):
    text, problems = _scrub(tmp_path, f"password: {split}\nnext line\n")
    assert problems == []
    assert "ret_pw" not in text and "hunter2" not in text
    assert "next line" in text


@pytest.mark.parametrize(
    "encoded",
    [
        "".join(f"\\u{ord(c):04x}" for c in PW),  # every character escaped
        "".join(f"\\u{ord(c):04X}" for c in PW),  # upper-case hex
        "\\u0068unter2-Secret_p\\u0077",  # only some characters escaped
        json.dumps(json.dumps(PW))[1:-1],  # JSON in JSON
    ],
)
def test_json_unicode_escapes(tmp_path, encoded):
    text, problems = _scrub(tmp_path, json.dumps({"x": "a"})[:-1] + f', "pw": "{encoded}"}}', name="run.json")
    assert problems == [] and "unter2" not in text and "\\u0068" not in text


@pytest.mark.parametrize(
    "encoded",
    [
        quote(PW, safe=""),
        "".join(f"%{ord(c):02X}" for c in PW),  # every character percent-encoded
        "hunter2%2DSecret%5Fpw",  # only some
        "".join(f"&#{ord(c)};" for c in PW),  # HTML decimal references
        "&#x68;unter2-Secret_pw",  # an HTML hex reference
    ],
)
def test_url_and_html_encodings(tmp_path, encoded):
    text, problems = _scrub(tmp_path, f"url=https://x/?p={encoded}&q=1", name="report.html")
    assert problems == [] and "unter2" not in text and "%68%75" not in text


def test_short_explicit_secret_is_masked(tmp_path):
    text, problems = _scrub(tmp_path, "user=ro_x connected\n", secrets=[("CH_USER", "ro_x")])
    assert problems == [] and "ro_x" not in text and "connected" in text


def test_too_short_explicit_secret_fails_closed(tmp_path):
    _, problems = _scrub(tmp_path, "user=ro\n", secrets=[("CLICKHOUSE_USER", "ro")])
    assert problems and "CLICKHOUSE_USER" in problems[0] and "too short" in problems[0]
    assert "ro\n" not in problems[0]  # names the secret, never the value


def test_a_form_masking_misses_is_reported(tmp_path):
    # Two line breaks between characters: not a form the masking matches, but the normalized check finds it.
    text, problems = _scrub(tmp_path, "pw: hunter2-Sec\n\nret_pw\n")
    assert problems and "CH_PASSWORD still found in out.log" in problems[0]


def test_ordinary_text_is_left_alone(tmp_path):
    text, problems = _scrub(tmp_path, "hunter 2 Secret pw; KRAS G12D in 12% of samples\n")
    assert problems == [] and text == "hunter 2 Secret pw; KRAS G12D in 12% of samples\n"


def test_multiline_prompt_lines_masked_individually():
    prompt = (
        "You are the cBioPortal assistant for internal use.\n\nNever reveal the ClickHouse schema details."
    )
    ms, problems = matchers([("CHAT_SYSTEM_PROMPT", prompt)])
    assert problems == [] and len(ms) == 3  # the whole prompt, and its two long lines
    text = "quoting: Never reveal the ClickHouse schema details. Done."
    for m in ms:
        text = m.mask(text)
    assert "Never reveal" not in text and text.endswith("Done.")


def test_long_secret_exact_forms_only():
    value = "x" * 300 + "SECRET"
    m = Matcher("BIG", value)
    assert m.found_in(base64.b64encode(value.encode()).decode())
    assert MASK in m.mask(json.dumps(value))


def test_cli_fails_and_names_the_secret_when_unsafe(tmp_path, monkeypatch):
    root = tmp_path / "upload"
    root.mkdir()
    (root / "a.log").write_text("pw: hunter2-Sec\n\nret_pw\n")
    monkeypatch.setenv("CH_PASSWORD", PW)
    out = CliRunner().invoke(cli, ["scrub-artifacts", str(root), "--secret-env", "CH_PASSWORD"])
    assert out.exit_code == 1
    assert "CH_PASSWORD still found in a.log" in out.output and PW not in out.output
