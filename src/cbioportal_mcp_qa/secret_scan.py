"""Find explicitly named secret values in text, in any of the forms they could have been written in.

Used before CI artifacts are uploaded (`scrub-artifacts`). For each secret, masking covers:

- the value, each character written as itself, a JSON `\\uXXXX` escape, a URL `%XX` escape or an HTML character
  reference (`&#NN;`, `&#xHH;`), mixed freely;
- its base64, standard and URL-safe alphabets, with and without padding, at all three byte alignments, so the
  value is also found inside a larger base64 blob;
- any of these broken across lines: a line break (`\\n` or `\\r\\n`, raw or JSON-escaped) plus indentation
  between any two characters.

Detection then looks again at normalized views of the text (whitespace removed, escapes decoded) and reports any
secret still found, so a form the masking missed fails closed instead of being uploaded.

Secrets shorter than MIN_EXPLICIT characters can't be masked without masking ordinary text and are refused
(the caller fails closed). Values longer than FLEX_MAX characters (a system prompt) are matched in their exact
encoded forms only; split them into lines (`secret_pieces`) to catch excerpts.
"""

import base64
import html
import json
import re
from urllib.parse import quote, quote_plus, unquote

MIN_EXPLICIT = 4
FLEX_MAX = 256
MIN_DETECT = 8  # forms shorter than this aren't looked for in whitespace-stripped views (chance matches)
MASK = "[REDACTED]"

# A line break, raw or JSON-escaped, and the indentation after it.
_BREAK = r"(?:\r?\n|\\r\\n|\\n|\\r)[ \t]*"
# Between any two characters of a secret: optionally such a break.
_SEP = f"(?:{_BREAK})?"
_SEP_RE = re.compile(_BREAK)


def _hex_class(n: int, width: int) -> str:
    return "".join(f"[{d.lower()}{d.upper()}]" if d.isalpha() else d for d in f"{n:0{width}x}")


def _char(c: str) -> str:
    """A regex for one character in any of its escaped forms."""
    n = ord(c)
    alts = [re.escape(c)]
    if n < 0x10000:
        alts.append(r"\\u" + _hex_class(n, 4))
    if n < 0x80:
        alts.append("%" + _hex_class(n, 2))
        if c == " ":
            alts.append(r"\+")
    alts += [f"&#0*{n};", "&#[xX]0*" + _hex_class(n, 1).lstrip("0") + ";" if n else "&#[xX]0+;"]
    if c in '"\\/':
        alts.append(re.escape("\\" + c))
    return "(?:" + "|".join(alts) + ")"


def base64_fragments(value: str) -> set[str]:
    """The base64 characters that encode only `value`'s bytes, at each of the three alignments it can start at
    inside a larger encoded blob, in both alphabets, plus the whole encodings with and without padding."""
    raw = value.encode()
    out: set[str] = set()
    for k in range(3):
        bits_start, bits_end = 8 * k, 8 * (k + len(raw))
        start, end = -(-bits_start // 6), bits_end // 6
        for enc in (base64.b64encode, base64.urlsafe_b64encode):
            encoded = enc(bytes(k) + raw).decode()
            if end > start:
                out.add(encoded[start:end])
            if k == 0:
                out.add(encoded)
                out.add(encoded.rstrip("="))
    return {f for f in out if f}


def exact_forms(value: str) -> set[str]:
    """Whole-value encodings: literal, URL, JSON (and JSON in JSON, all-\\u), HTML, backslash-escaped, base64."""
    json_escaped = json.dumps(value)[1:-1]
    forms = {
        value,
        quote(value, safe=""),
        quote_plus(value),
        json_escaped,
        json.dumps(json_escaped)[1:-1],
        "".join(f"\\u{ord(c):04x}" for c in value),
        "".join(f"\\u{ord(c):04X}" for c in value),
        html.escape(value),
        html.escape(value, quote=False),
        re.sub(r"([\\\"'$`])", r"\\\1", value),
    }
    return {f for f in forms if f} | base64_fragments(value)


class SecretTooShort(ValueError):
    pass


def _b64_char(c: str) -> str:
    return r"(?:/|\\/)" if c == "/" else re.escape(c)


class Matcher:
    """Masks and detects one secret value. `deep`: base64 forms are also matched across line breaks (credentials);
    otherwise exactly (the lines of a prompt, to keep the patterns small)."""

    def __init__(self, name: str, value: str, deep: bool = True):
        if len(value) < MIN_EXPLICIT:
            raise SecretTooShort(
                f"{name} is {len(value)} characters: too short to mask without masking ordinary text"
            )
        self.name = name
        self.forms = exact_forms(value)
        patterns = []
        if len(value) <= FLEX_MAX:
            patterns.append(_SEP.join(_char(c) for c in value))
            if deep:
                fragments = sorted(base64_fragments(value), key=len, reverse=True)
                patterns += [_SEP.join(_b64_char(c) for c in f) for f in fragments]
        patterns += [re.escape(f) for f in sorted(self.forms, key=len, reverse=True)]
        self.regex = re.compile("|".join(patterns))
        self.stripped_forms = {s for f in self.forms if len(s := re.sub(r"\s+", "", f)) >= MIN_DETECT}

    def mask(self, text: str) -> str:
        return self.regex.sub(MASK, text)

    def found_in(self, text: str, views: list[tuple[str, str]] | None = None) -> bool:
        """Whether the secret is still in `text`, in any form, or in a normalized view of it (`views(text)`)."""
        if self.regex.search(text):
            return True
        for view, stripped in views if views is not None else text_views(text):
            if any(f in view for f in self.forms) or any(f in stripped for f in self.stripped_forms):
                return True
        return False


_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def text_views(text: str) -> list[tuple[str, str]]:
    """The text with line wraps removed and escapes decoded, alone and combined; each with all whitespace removed
    too."""
    unwrapped = _SEP_RE.sub("", text)
    views = []
    for base in (text, unwrapped):
        decoded = _UNICODE_ESCAPE.sub(lambda m: chr(int(m[1], 16)), base)
        views += [base, decoded, unquote(base), html.unescape(base), html.unescape(unquote(decoded))]
    unique = list(dict.fromkeys(views))
    return [(v, re.sub(r"\s+", "", v)) for v in unique]


LINE_CHARS = 24  # lines of a multi-line secret at least this long are masked on their own too


def matchers(secrets: list[tuple[str, str]]) -> tuple[list[Matcher], list[str]]:
    """Matchers for the non-empty secrets (a multi-line one also line by line), and a problem for each one too
    short to mask."""
    out, problems = [], []
    for name, value in secrets:
        if not value:
            continue
        try:
            out.append(Matcher(name, value, deep="\n" not in value))
        except SecretTooShort as exc:
            problems.append(str(exc))
            continue
        if "\n" in value:
            for i, line in enumerate(value.splitlines(), 1):
                line = line.strip()
                if len(line) >= LINE_CHARS:
                    out.append(Matcher(f"{name} (line {i})", line, deep=False))
    return out, problems


# --- Iterative decoding: a secret under any stack of encodings ---------------------------------------------------

DECODE_ROUNDS = 5
MAX_LAYERS = 64
CHUNK = 50_000  # long lines are checked in overlapping chunks, so decoding stays bounded
_JSON_ESC = re.compile(r'\\(u[0-9a-fA-F]{4}|["\\/bfnrt])')
_JSON_ESC_CHARS = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_B64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{12,}={0,2}")


def _json_unescape(s: str) -> str:
    return _JSON_ESC.sub(lambda m: chr(int(m[1][1:], 16)) if m[1][0] == "u" else _JSON_ESC_CHARS[m[1]], s)


def _printable(text: str) -> bool:
    return bool(text) and sum(c.isprintable() or c in "\n\r\t" for c in text) >= 0.9 * len(text)


def _base64_decodings(s: str) -> list[str]:
    """Every substring that decodes as base64 (either alphabet) to mostly printable text, decoded."""
    out = []
    for m in _B64_TOKEN.finditer(s):
        token = m[0].rstrip("=")
        for decode in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                raw = decode(token + "=" * (-len(token) % 4))
            except ValueError:
                continue
            text = raw.decode("utf-8", errors="ignore")
            if _printable(text):
                out.append(text)
        if len(out) >= 16:
            break
    return out


def decode_layers(s: str, rounds: int = DECODE_ROUNDS, limit: int = MAX_LAYERS) -> list[str]:
    """`s` and everything reachable from it by up to `rounds` decodings, in any order: JSON-string unescape
    (`\\uXXXX`, `\\n`, `\\"` …), URL-decode, HTML-unescape, removing line wraps, and base64-decoding any substring that
    decodes to text. At most `limit` distinct strings."""
    seen = {s}
    frontier = [s]
    for _ in range(rounds):
        nxt = []
        for x in frontier:
            for c in (
                _json_unescape(x),
                unquote(x),
                html.unescape(x),
                _SEP_RE.sub("", x),
                *_base64_decodings(x),
            ):
                if c not in seen and len(seen) < limit:
                    seen.add(c)
                    nxt.append(c)
        if not nxt:
            break
        frontier = nxt
    return list(seen)


def _hit(m: Matcher, s: str) -> bool:
    if m.regex.search(s) or any(f in s for f in m.forms):
        return True
    stripped = re.sub(r"\s+", "", s)
    return any(f in stripped for f in m.stripped_forms)


def secret_in(s: str, found: list[Matcher]) -> str | None:
    """The name of the first secret in any decoded layer of `s` (checked in overlapping chunks when long)."""
    if not s or not found:
        return None
    pieces = [s] if len(s) <= CHUNK else [s[i : i + CHUNK + 1024] for i in range(0, len(s), CHUNK)]
    for piece in pieces:
        for layer in decode_layers(piece):
            for m in found:
                if _hit(m, layer):
                    return m.name
    return None


def redact_json(obj, found: list[Matcher]):
    """`obj` with every string value and key that holds a secret, in any decoded layer, replaced whole by MASK.
    Numbers, booleans and null are never touched: a secret like `1234` or `true` in a non-string position isn't
    a leak, and masking it would break the JSON."""
    if isinstance(obj, str):
        return MASK if secret_in(obj, found) else obj
    if isinstance(obj, list):
        return [redact_json(v, found) for v in obj]
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            new = MASK if secret_in(key, found) else key
            base, n = new, 1
            while new in out:
                n += 1
                new = f"{base} #{n}"
            out[new] = redact_json(value, found)
        return out
    return obj


def json_leaks(obj, found: list[Matcher], path: str = "$") -> list[str]:
    """Where in `obj` (JSON paths) a string value or key still holds a secret, with the secret's name."""
    out = []
    if isinstance(obj, str):
        if name := secret_in(obj, found):
            out.append(f"{name} at {path}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += json_leaks(v, found, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if name := secret_in(k, found):
                out.append(f"{name} in a key at {path}")
                out += json_leaks(v, found, f"{path}.<redacted key>")
            else:
                out += json_leaks(v, found, f"{path}.{k}")
    return out
