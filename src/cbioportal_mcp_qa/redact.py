"""Keep credentials out of text that ends up in results (exception messages, failed commands).

A failed `kubectl exec ... mongosh -p PASS` raises a CalledProcessError whose message repeats the whole
command. Commands are never recorded: a failed command is described by its executable's name, its exit status
and the (redacted) tail of what it printed (`run_command`, `describe_error`).

Free text can still echo a command (stderr, other exceptions), so every recorded message goes through
`redact`, which fails closed rather than parsing shell quoting:

- URI userinfo, bearer/basic tokens, secret-looking key=value pairs and well-known key shapes are masked.
- A long password flag (`--password`, `--token`, `--api-key`, ...), in any command: everything after it to the
  end of the line.
- `-u user:...` / `--user user:...` (e.g. curl): everything after the colon to the end of the line.
- When the text names a database client (`mongosh`, `mongo`, `mongodump`, ..., `mysql`, `mysqldump`,
  `mariadb`: `-p`; `redis-cli`: `-a`), everything after that client's password flag to the end of the line.
  The flag stands alone (after whitespace, or as a quoted list item) or has its value attached (`-pX`,
  `-p=X`); a bare flag followed by another flag (`mysql -p -h db`, which prompts) is left alone. So
  `kubectl -n ns`, `ssh -p 2222`, `psql -p 5432` and `redis-cli -p 6379` (ports) stay readable. `psql` takes
  no password flag (its password comes from PGPASSWORD=..., a key=value pair).

"The end of the line" runs on across backslash-continued lines, and to the end of the text when the masked
part holds an unclosed quote (a quoted newline). Masking the rest of such a line is the price of never
reading quoting wrong.
"""

import os
import re
import subprocess

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


def _line_end(text: str, pos: int) -> int:
    """End of the line from `pos`, running on across backslash-continued lines, or the end of the text when
    the part up to it holds an unclosed quote."""
    end = text.find("\n", pos)
    while end > 0 and text[end - 1] == "\\":
        end = text.find("\n", end + 1)
    end = len(text) if end < 0 else end
    part = text[pos:end]
    return len(text) if part.count('"') % 2 or part.count("'") % 2 else end


def _mask_from(text: str, starts: list[int]) -> str:
    out, last = [], 0
    for start in sorted(starts):
        if start < last:
            continue  # already masked
        end = _line_end(text, start)
        out.append(text[last:start] + (" " if text[start : start + 1].isspace() else "") + MASK)
        last = end
    return "".join(out) + text[last:]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    starts = [m.end() for m in _LONG_FLAG.finditer(text)] + [m.end() for m in _USER_PASS.finditer(text)]
    for flag in {DB_CLIENT_PASSWORD_FLAGS[m[0]] for m in _DB_CLIENT.finditer(text)}:
        starts += [m.end() for m in _SHORT_FLAGS[flag].finditer(text)]
    return _mask_from(text, starts)


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
        raise CommandFailed(command_failure(exc)) from None


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
