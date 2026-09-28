"""Keep credentials out of everything written under results/ (reported at GitHub Pages).

Two layers, applied to every string `persist` writes:

1. **Known values.** The secrets the benchmark itself loads (`add_secret`: API keys from the settings, the
   cBioAgent Mongo password read from its k8s secret) and every secret-looking environment variable
   (`add_env_secrets`) are masked wherever they appear, also URL-encoded, JSON-escaped, backslash-escaped or
   HTML-escaped. Only values of 6+ characters count, so short values can't mask ordinary text.
2. **Patterns**, for secrets the benchmark never saw (an agent echoing another credential):
   - URI userinfo, bearer/basic tokens, secret-looking key=value / "key": "value" pairs, well-known key shapes.
   - After an assignment to a `*PASSWORD`/`*PASSWD`/`*TOKEN`/`*SECRET` name, a long password flag
     (`--password`, `--token`, ...) or `-u user:`: everything to the end of the line.
   - After a database client (`mongosh`, `mongo*`, `mysql*`, `mariadb*`: `-p`; `redis-cli`: `-a`), that
     client's password flag on the same line (command): everything to the end of the line. A bare flag followed
     by another flag (`mysql -p -h db`, which prompts) is left alone, so `kubectl -n ns`, `ssh -p 2222`,
     `psql -p 5432` and `redis-cli -p 6379` (ports) stay readable.
   Quoting is never parsed; the rules fail closed instead. JSON escapes (`\\t`, `\\n`) read as whitespace
   when finding flags. "The end of the line" runs on across backslash-continued lines, and becomes the end of
   the whole text when the rest holds an escaped quote or a JSON escape, or the masked part leaves a quote open
   (a quoted newline).

Failed commands are never recorded: a failure is described by its executable's name, its exit status and the
(redacted) tail of what it printed (`run_command`, `describe_error`).
"""

import html
import json
import os
import re
import subprocess
from urllib.parse import quote, quote_plus

MASK = "***"
TAIL = 300  # characters of a failed command's output kept

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
            r"(?:\"(?:[^\"\\\n]|\\.)+(\"?)|'(?:[^'\\\n]|\\.)+('?)|[^\s'\",}&]+)"
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
    r"(?<![\w.-])(?:"
    + "|".join(sorted(map(re.escape, DB_CLIENT_PASSWORD_FLAGS), key=len, reverse=True))
    + r")(?![\w.-])"
)
# Where a flag can start: the start of the text, after whitespace, or as a quoted list item ('-p', "-p").
_FLAG_START = r"(?:(?<![^\s])|(?<=[\[,\s]['\"]))"
_SHORT_FLAGS = {
    # Not followed by another flag: `mysql -p -h db` prompts for the password.
    flag: re.compile(_FLAG_START + re.escape(flag) + r"(?!\s*-)")
    for flag in set(DB_CLIENT_PASSWORD_FLAGS.values())
}
_LONG_FLAG = re.compile(
    rf"(?i){_FLAG_START}--?(?:password|passwd|pass|token|secret|api[-_]?key|access[-_]?key|secret[-_]?key|auth)"
    r"(?=[=\s'\"]|$)(?!\s+-)"
)
_USER_PASS = re.compile(rf"{_FLAG_START}(?:-u|--user)(?:=|\s+|['\"]\s*,\s*)['\"]?[^\s:'\"]*:")


# An empty value (`password=""` in sample code, `TOKEN=` alone) holds nothing to mask.
_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w-])(?:[\w-]*[_-])?(?:password|passwd|token|secret)(?:[_-][\w-]*)?\s*="
    r"(?!\s*(?:\"\"|''|[,;)\n]|$))"
)
_JSON_ESCAPE = re.compile(r"\\[tnr]")
# An escaped quote or JSON escape: the remainder's quoting can't be trusted.
_ESCAPES = re.compile(r"\\[\"'\\/bfnrtu]")

# --- Known values -------------------------------------------------------------------------------------------------

MIN_SECRET = 6
_known: set[str] = set()
_known_re: re.Pattern | None = None
known_version = 0  # bumped whenever a value is added, so cached redactions are redone
_SECRET_ENV = re.compile(
    r"(?i)(?:^|_)(?:password|passwd|secret|token|api_?key|access_key|private_key|credentials?|auth_key)(?:_|$)"
)
_USERINFO = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]*:([^\s/@]+)@")


def _forms(value: str) -> set[str]:
    json_escaped = json.dumps(value)[1:-1]
    return {
        value,
        quote(value, safe=""),
        quote_plus(value),
        json_escaped,
        json.dumps(json_escaped)[1:-1],  # JSON inside JSON
        re.sub(r"([\\\"'$`])", r"\\\1", value),
        html.escape(value),
        html.escape(value, quote=False),
    }


def add_secret(value: str | None) -> None:
    """Mask `value` (6+ characters) and its encoded forms wherever results are written."""
    global _known_re, known_version
    if not value or len(value) < MIN_SECRET:
        return
    new = {f for f in _forms(value) if len(f) >= MIN_SECRET} - _known
    if new:
        _known.update(new)
        _known_re = re.compile("|".join(map(re.escape, sorted(_known, key=len, reverse=True))))
        known_version += 1


def add_env_secrets(environ=os.environ) -> None:
    """Secret-looking environment variables, and the password of any URI with userinfo in the environment."""
    for key, value in environ.items():
        if _SECRET_ENV.search(key):
            add_secret(value)
        for m in _USERINFO.finditer(value):
            add_secret(m[1])


def mask_known(text: str) -> str:
    return _known_re.sub(MASK, text) if _known_re and text else text


# --- Patterns -----------------------------------------------------------------------------------------------------


def _line_end(norm: str, pos: int) -> int:
    """End of the line from `pos`, running on across backslash-continued lines."""
    end = norm.find("\n", pos)
    while end > 0 and norm[end - 1] == "\\":
        end = norm.find("\n", end + 1)
    return len(norm) if end < 0 else end


def _open_quote(part: str) -> bool:
    return bool(part.count('"') % 2 or part.count("'") % 2)


def _mask_from(text: str, norm: str, starts: list[int]) -> str:
    """Mask from each start to the end of its line, or of the text when the quoting after it can't be trusted:
    an escaped quote or JSON escape anywhere after it, or a quote the masked part leaves open."""
    last_escape = max((m.start() for m in _ESCAPES.finditer(text)), default=-1)
    out, last = [], 0
    for start in sorted(starts):
        if start < last:
            continue  # already masked
        end = len(text) if last_escape >= start else _line_end(norm, start)
        if _open_quote(text[start:end]):
            end = len(text)
        out.append(text[last:start] + (" " if text[start : start + 1].isspace() else "") + MASK)
        last = end
    return "".join(out) + text[last:]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    text = mask_known(text)
    # JSON escapes read as whitespace when finding flags; `norm` keeps `text`'s positions.
    norm = _JSON_ESCAPE.sub("  ", text)
    starts = [m.end() for p in (_LONG_FLAG, _USER_PASS, _ASSIGNMENT) for m in p.finditer(norm)]
    searched = dict.fromkeys(_SHORT_FLAGS, 0)  # per flag, how far the text has been searched
    for m in _DB_CLIENT.finditer(norm):
        flag = DB_CLIENT_PASSWORD_FLAGS[m[0]]
        if m.end() < searched[flag]:
            continue  # an earlier client's command already covers this one
        # The client's command: the rest of its line, or of the text when the line leaves a quote open.
        end = _line_end(norm, m.end())
        end = len(norm) if _open_quote(norm[m.end() : end]) else end
        starts += [f.end() for f in _SHORT_FLAGS[flag].finditer(norm, m.end(), end)]
        searched[flag] = end
    text = _mask_from(text, norm, starts)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _executable(cmd) -> str:
    """The name of a command's executable, never its arguments."""
    if isinstance(cmd, list | tuple):
        first = str(cmd[0]) if cmd else ""
    else:
        first = (str(cmd or "").split() or [""])[0]
    name = os.path.basename(first)
    return name if re.fullmatch(r"[\w.+-]{1,64}", name) else "command"


def _output_tail(exc: BaseException) -> str:
    for stream in (getattr(exc, "stderr", None), getattr(exc, "stdout", None)):
        if isinstance(stream, bytes):
            stream = stream.decode(errors="replace")
        if isinstance(stream, str) and stream.strip():
            # Redact the whole output before cutting, so a cut can't split a secret away from its flag.
            return redact(stream.strip())[-TAIL:]
    return ""


class CommandFailed(RuntimeError):
    """A failed command, described without its arguments."""


def command_failure(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> str:
    """`<executable> exited with status N` (or timed out), and the redacted tail of its stderr/stdout."""
    if isinstance(exc, subprocess.TimeoutExpired):
        what = f"{_executable(exc.cmd)} timed out after {exc.timeout:g}s"
    else:
        what = f"{_executable(exc.cmd)} exited with status {exc.returncode}"
    tail = _output_tail(exc)
    return f"{what}: {tail}" if tail else what


def run_command(cmd: list[str], timeout: float) -> str:
    """stdout of a command that must succeed; a failure raises CommandFailed, which doesn't carry the command."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        failure = command_failure(exc)
    # Raised outside the except block, so the original exception (and its argv) isn't kept as __context__.
    raise CommandFailed(failure)


def describe_error(exc: BaseException, limit: int = 200) -> str:
    """`Type: message` for recording, with credentials removed before truncating (so no secret is half-kept).
    A failed command is described by `command_failure`, never by its arguments."""
    if isinstance(exc, subprocess.CalledProcessError | subprocess.TimeoutExpired):
        return f"{type(exc).__name__}: {command_failure(exc)}"[:limit]
    text = f"{type(exc).__name__}: {exc}"
    tail = _output_tail(exc)
    if tail:
        text += f" (stderr: {tail})"
    return redact(text)[:limit]
