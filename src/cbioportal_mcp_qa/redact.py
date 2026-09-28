"""Scrub credentials out of text that ends up in results (exception messages, failed commands).

A failed `kubectl exec ... mongosh mongodb://user:PASS@host` raises a CalledProcessError whose message repeats
the whole command, so every recorded exception goes through `redact` before it is saved or printed.

Command-line flags are read as shell words, not with regexes, so a quoted value (`-p "alpha beta"`,
`-p 'alpha;omega'`) is masked in full, and quoting inside other arguments (`--eval "x[0]; y"`) doesn't end the
command early. A printed argv list (`['mongosh', '-p', 'X']`, as in a CalledProcessError) is parsed as a
Python literal and read item by item; each item is also redacted as text, for `sh -c '...'`. Where the quoting
can't be read (an unclosed quote in a flag's value), the rest of the line is masked.

- `--password X`, `--token=X`, ... (any command): the value.
- Short flags only where they are known to carry a password, so `kubectl -n ns`, `ssh -p 2222` or
  `psql -p 5432` (a port) stay readable: after a database client (`mongosh`, `mongo`, `mongodump`, ...,
  `mysql`, `mysqldump`, `mariadb`: `-p`; `redis-cli`: `-a`), that flag's value in any form (`-p X`, `-pX`,
  `-p=X`), up to the end of the command (an unquoted `;`, `|`, `&` or newline). A bare flag followed by another
  flag (`mysql -p -h db`, which prompts) has no value. `psql` takes no password flag (its password comes from
  PGPASSWORD=..., redacted as a key=value pair).
- `-u user:pass` / `--user user:pass` (any command, e.g. curl): the part after the colon.
"""

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass

MASK = "***"

_PATTERNS = [
    # URI userinfo: scheme://user:password@host -> scheme://***@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@'\"]+@"), rf"\1{MASK}@"),
    # Authorization headers and bearer tokens
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {MASK}"),
    # key=value / key: value / "key": "value" pairs with a secret-looking key. A quoted value is masked up to
    # its closing quote (or the end of the line when it has none).
    (
        re.compile(
            # The secret word is the whole key or a _/- separated part of it (LANGFUSE_SECRET_KEY, access_token),
            # so ordinary words like "tokens: 1200" are left alone.
            r"(?i)([\"']?\b(?:[\w-]*(?=passw)|[\w-]*[_-])?(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key)"
            r"(?:[_-][\w-]*)?\b[\"']?\s*[:=]\s*)"
            r"(?:\"(?:[^\"\\\n]|\\.)*(\"?)|'(?:[^'\\\n]|\\.)*('?)|[^\s'\",}&]+)"
        ),
        lambda m: (
            m[1]
            + ('"' if m[2] is not None else "'" if m[3] is not None else "")
            + MASK
            + (m[2] or m[3] or "")
        ),
    ),
    # Well-known key shapes: Anthropic/OpenAI (sk-...), Langfuse (pk-lf-/sk-lf-), AWS access key ids
    (re.compile(r"\b(?:sk|pk)-(?:lf-|ant-)?[A-Za-z0-9_-]{12,}"), MASK),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), MASK),
]

# Database clients and the short flag that carries their password.
DB_CLIENT_PASSWORD_FLAGS = {
    **dict.fromkeys(("mongosh", "mongo", "mongodump", "mongorestore", "mongoexport", "mongoimport"), "-p"),
    **dict.fromkeys(("mysql", "mysqldump", "mysqladmin", "mariadb", "mariadb-dump"), "-p"),
    "redis-cli": "-a",
}
_DB_CLIENT = re.compile(
    r"(?<![\w.-])(?:[\w.-]*/)*(?:"
    + "|".join(sorted(map(re.escape, DB_CLIENT_PASSWORD_FLAGS), key=len, reverse=True))
    + r")(?![\w.-])"
)
_SECRET_FLAG_NAMES = r"(?:password|passwd|pass|token|secret|api[-_]?key|access[-_]?key|secret[-_]?key|auth)"
_SECRET_FLAG = re.compile(rf"(?i)(?<![\w-])--?{_SECRET_FLAG_NAMES}(?![\w-])")
_SECRET_FLAG_WORD = re.compile(rf"(?i)--?{_SECRET_FLAG_NAMES}")
_USER_FLAG = re.compile(r"(?<![\w-])(?:-u|--user)(?![\w-])")

# A printed list of strings: repr(argv) in a CalledProcessError, or a JSON array.
_STR = r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\""
_STR_LIST = re.compile(rf"\[\s*(?:{_STR})(?:\s*,\s*(?:{_STR}))*\s*,?\s*\]")


@dataclass
class _Word:
    start: int
    end: int
    value: str  # with quotes and escapes removed
    quoted: bool
    # A quote with no closing quote on its line: the word is just that quote, and `rest` is the end of the line.
    unclosed: bool = False
    rest: int = 0


def _closing(text: str, pos: int) -> int | None:
    """Index of the quote closing the one at `pos`, on the same line (`\\` escapes only inside double quotes)."""
    quote, i = text[pos], pos + 1
    while i < len(text) and text[i] != "\n":
        if quote == '"' and text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i
        i += 1
    return None


def _words(text: str, pos: int) -> Iterator[_Word]:
    """Shell words from `pos` to the end of the command: an unquoted `;`, `|`, `&` or newline, or the end."""
    n = len(text)
    while True:
        while pos < n and text[pos] in " \t":
            pos += 1
        if pos >= n or text[pos] in ";|&\n":
            return
        start, value, quoted = pos, [], False
        while pos < n and text[pos] not in " \t;|&\n":
            char = text[pos]
            if char == "\\" and pos + 1 < n:
                value.append(text[pos + 1])
                pos += 2
            elif char in "'\"":
                close = _closing(text, pos)
                if close is None:
                    break  # a stray quote ends the word
                inner = text[pos + 1 : close]
                value.append(re.sub(r"\\(.)", r"\1", inner) if char == '"' else inner)
                quoted, pos = True, close + 1
            else:
                value.append(char)
                pos += 1
        if pos == start:  # a word starting with a stray quote: yield the quote alone, then read on after it
            eol = text.find("\n", pos)
            yield _Word(start, start + 1, text[start], False, unclosed=True, rest=n if eol < 0 else eol)
            pos += 1
            continue
        yield _Word(start, pos, "".join(value), quoted)


def _value_span(word: _Word) -> tuple[int, int] | None:
    """The span to mask when `word` follows a password flag, or None when it's another flag instead."""
    if word.unclosed:
        return word.start, word.rest
    if not word.quoted and word.value.startswith("-"):
        return None
    return word.start, word.end


def _attached(text: str, word: _Word, flag_len: int) -> tuple[int, int]:
    """The span of a value attached to a flag (`-pX`, `-p=X`, `--password=X`)."""
    start = word.start + flag_len
    if text[word.start : start].lower() != word.value[:flag_len].lower():
        return word.start, word.end  # the flag itself is quoted: mask the whole word
    return (start + 1 if text[start : start + 1] == "=" else start), word.end


def _db_command_spans(text: str, pos: int, flag: str) -> Iterator[tuple[int, int]]:
    words = _words(text, pos)
    for word in words:
        if word.unclosed:
            continue
        if word.value == flag:
            value = next(words, None)
            if value and (span := _value_span(value)):
                yield span
        elif word.value.startswith(flag) and not word.value.startswith("--"):
            yield _attached(text, word, len(flag))


def _flag_value_spans(text: str, pos: int) -> Iterator[tuple[int, int]]:
    words = _words(text, pos)
    word = next(words, None)
    name, attached, _ = word.value.partition("=") if word else ("", "", "")
    if not _SECRET_FLAG_WORD.fullmatch(name):
        return
    if attached:
        yield _attached(text, word, len(name))
    elif (value := next(words, None)) and (span := _value_span(value)):
        yield span


def _user_pass_spans(text: str, pos: int) -> Iterator[tuple[int, int]]:
    words = _words(text, pos)
    word = next(words, None)
    if word is None:
        return
    if word.value.startswith("--user="):
        value = word
    elif word.value in ("-u", "--user"):
        value = next(words, None)
    else:
        return
    if value is None or value.unclosed:
        return
    colon = text.find(":", value.start, value.end)
    if ":" in value.value and colon >= 0:
        end = value.end - 1 if value.quoted and text[value.end - 1] in "'\"" else value.end
        yield colon + 1, max(end, colon + 1)


def _redact_argv(argv: list[str]) -> list[str]:
    """Each item redacted as text (for `sh -c '...'`), then password flags' values masked item by item."""
    argv = [redact(a) for a in argv]
    db_flag = None
    for i, arg in enumerate(argv):
        nxt = i + 1 < len(argv)
        if (client := arg.rsplit("/", 1)[-1]) in DB_CLIENT_PASSWORD_FLAGS:
            db_flag = DB_CLIENT_PASSWORD_FLAGS[client]
        elif db_flag and arg == db_flag or _SECRET_FLAG_WORD.fullmatch(arg):
            if nxt and not argv[i + 1].startswith("-"):
                argv[i + 1] = MASK
        elif db_flag and arg.startswith(db_flag) and not arg.startswith("--"):
            argv[i] = db_flag + ("=" if arg[len(db_flag) :].startswith("=") else "") + MASK
        elif _SECRET_FLAG_WORD.fullmatch((parts := arg.partition("="))[0]) and parts[1]:
            argv[i] = parts[0] + "=" + MASK
        elif arg.startswith("--user=") and ":" in arg:
            argv[i] = arg.split(":", 1)[0] + ":" + MASK
        elif arg in ("-u", "--user") and nxt and ":" in argv[i + 1]:
            argv[i + 1] = argv[i + 1].split(":", 1)[0] + ":" + MASK
    return argv


def _redact_argv_lists(text: str) -> tuple[str, list[tuple[int, int]]]:
    """`text` with each printed list of strings redacted as an argv, and the lists' spans in the result."""
    out, spans, last = [], [], 0
    for m in _STR_LIST.finditer(text):
        try:
            argv = ast.literal_eval(m[0])
        except (ValueError, SyntaxError):
            continue
        redacted = _redact_argv(argv)
        out.append(text[last : m.start()])
        start = sum(map(len, out))
        out.append(repr(redacted) if redacted != argv else m[0])
        spans.append((start, start + len(out[-1])))
        last = m.end()
    return "".join(out) + text[last:], spans


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    out, last = [], 0
    for start, end in sorted(spans):
        if end <= last:
            continue
        start = max(start, last)
        out.append(text[last:start] + MASK)
        last = end
    return "".join(out) + text[last:]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    text, lists = _redact_argv_lists(text)
    spans = []

    def anchors(pattern: re.Pattern) -> Iterator[re.Match]:
        # A command inside a printed list was already read item by item.
        return (m for m in pattern.finditer(text) if not any(a <= m.start() < b for a, b in lists))

    for m in anchors(_DB_CLIENT):
        spans += _db_command_spans(text, m.end(), DB_CLIENT_PASSWORD_FLAGS[m[0].rsplit("/", 1)[-1]])
    for m in anchors(_SECRET_FLAG):
        spans += _flag_value_spans(text, m.start())
    for m in anchors(_USER_FLAG):
        spans += _user_pass_spans(text, m.start())
    return _mask(text, spans)


def describe_error(exc: BaseException, limit: int = 200) -> str:
    """`Type: message` for recording, with credentials removed before truncating (so no secret is half-kept)."""
    text = f"{type(exc).__name__}: {exc}"
    stderr = getattr(exc, "stderr", None)
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    if isinstance(stderr, str) and stderr.strip():
        text += f" (stderr: {stderr.strip()})"
    return redact(text)[:limit]
