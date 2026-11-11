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


# --- structure-aware JSON scrubbing ---------------------------------------------------------------------------

from cbioportal_mcp_qa.secret_scan import decode_layers, secret_in  # noqa: E402


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _strings(v)


def _recoverable(obj, secrets):
    found, _ = matchers(secrets)
    return [s for s in _strings(obj) if secret_in(s, found)]


def test_cli_double_escaped_unicode_tool_output_in_run_json(tmp_path, monkeypatch):
    # The tool returned text with literal \uXXXX escapes; json.dumps escapes the backslashes again in run.json.
    escaped = "".join(f"\\u{ord(c):04x}" for c in PW)
    run = {
        "records": {
            "1:haiku:1": {
                "trace": {
                    "tool_calls": [
                        {"name": "clickhouse_run_select_query", "ok": True, "result": f"pw={escaped}"}
                    ]
                },
                "grade": {"passed": True},
            }
        }
    }
    root = tmp_path / "upload"
    (root / "results").mkdir(parents=True)
    path = root / "results" / "run.json"
    path.write_text(json.dumps(run))
    assert "\\\\u0068\\\\u0075" in path.read_text()  # really double-escaped on disk
    monkeypatch.setenv("CH_PASSWORD", PW)
    out = CliRunner().invoke(cli, ["scrub-artifacts", str(root), "--secret-env", "CH_PASSWORD"])
    assert out.exit_code == 0, out.output
    data = json.loads(path.read_text())
    assert data["records"]["1:haiku:1"]["trace"]["tool_calls"][0]["result"] == MASK
    assert data["records"]["1:haiku:1"]["grade"]["passed"] is True
    assert _recoverable(data, [("CH_PASSWORD", PW)]) == []


def test_run_json_round_trip_keeps_structure_and_values(tmp_path):
    user, pw, token = "true", "1234", "S3cretToken-xyz"
    basic = base64.b64encode(f"admin:{token}".encode()).decode()
    nested = json.dumps({"rows": [{"auth": "".join(f"\\u{ord(c):04x}" for c in token)}]})  # JSON in a string
    run = {
        "run_id": "20261111-1200",
        "repeats": 2,
        "records": {
            "1:haiku:1": {
                "question": {"id": 1, "question": "How many studies?", "track": "data"},
                "reply": {
                    "status": 200,
                    "answer": "There are 523 studies.",
                    "prompt_tokens": 1234,
                    "latency_s": 1.5,
                },
                "grade": {"passed": True, "declined": False, "number_match": None, "invalid_studies": []},
                "trace": {
                    "tool_calls": [
                        {"name": "q", "ok": True, "result": nested},
                        {"name": "q", "ok": False, "error": f"login {user}:{pw} refused"},
                        {"name": "q", "ok": True, "input": f"Authorization: Basic {basic}"},
                    ]
                },
            }
        },
    }
    root = tmp_path / "upload"
    root.mkdir()
    (root / "run.json").write_text(json.dumps(run))
    secrets = [("CLICKHOUSE_USER", user), ("CLICKHOUSE_PASSWORD", pw), ("API_TOKEN", token)]
    _, _, problems = scrub_tree(root, secrets)
    assert problems == []
    data = json.loads((root / "run.json").read_text())  # still valid JSON
    rec = data["records"]["1:haiku:1"]
    # Non-string values are untouched, even when they equal a secret (1234, true).
    assert rec["reply"]["prompt_tokens"] == 1234 and rec["reply"]["latency_s"] == 1.5
    assert rec["grade"] == {"passed": True, "declined": False, "number_match": None, "invalid_studies": []}
    assert data["repeats"] == 2
    # Strings without a secret are unchanged; strings with one, in any layer, are gone whole.
    assert rec["question"]["question"] == "How many studies?"
    assert rec["reply"]["answer"] == "There are 523 studies."
    assert [c.get("result") or c.get("error") or c.get("input") for c in rec["trace"]["tool_calls"]] == [
        MASK
    ] * 3
    assert _recoverable(data, secrets) == []


def test_jsonl_and_invalid_json(tmp_path):
    root = tmp_path / "upload"
    root.mkdir()
    (root / "a.jsonl").write_text(json.dumps({"x": PW, "n": 3}) + "\n" + json.dumps({"y": "ok"}) + "\n")
    (root / "broken.json").write_text('{"x": "' + PW)
    _, removed, problems = scrub_tree(root, [("CH_PASSWORD", PW)])
    assert [json.loads(line) for line in (root / "a.jsonl").read_text().splitlines()] == [
        {"x": MASK, "n": 3},
        {"y": "ok"},
    ]
    # A JSON file that doesn't parse can't be scrubbed by structure: removed, and the upload refused.
    assert "broken.json" in removed and any("broken.json isn't valid JSON" in p for p in problems)


@pytest.mark.parametrize(
    "layered",
    [
        lambda v: base64.b64encode(json.dumps({"pw": v}).encode()).decode(),  # base64 of JSON
        lambda v: quote(json.dumps(json.dumps(v)), safe=""),  # URL-encoded JSON in JSON
        lambda v: json.dumps("".join(f"\\u{ord(c):04x}" for c in v)),  # \u escapes, escaped again
        lambda v: base64.b64encode(base64.b64encode(v.encode())).decode(),  # base64 twice
    ],
)
def test_stacked_encodings_are_decoded_to_a_fixpoint(layered):
    found, _ = matchers([("CH_PASSWORD", PW)])
    assert secret_in(f"note: {layered(PW)} end", found) == "CH_PASSWORD"
    assert any(PW in layer for layer in decode_layers(layered(PW)))


def test_stacked_encoding_in_a_text_file_redacts_the_line(tmp_path):
    blob = base64.b64encode(json.dumps({"pw": PW}).encode()).decode()
    text, problems = _scrub(tmp_path, f"keep this line\nconfig={blob}\nand this one\n")
    assert problems == []
    lines = text.splitlines()
    assert lines[0] == "keep this line" and lines[2] == "and this one"
    found, _ = matchers([("CH_PASSWORD", PW)])
    assert secret_in(lines[1], found) is None and MASK in lines[1]


def test_text_line_with_a_secret_only_in_a_deeper_layer_is_replaced(tmp_path):
    # base64 of base64: no pattern locates it in the raw text; the decoded check replaces the whole line.
    blob = base64.b64encode(base64.b64encode(PW.encode())).decode()
    text, problems = _scrub(tmp_path, f"keep this line\nconfig={blob}\nand this one\n")
    assert problems == []
    assert text.splitlines() == ["keep this line", MASK, "and this one"]
