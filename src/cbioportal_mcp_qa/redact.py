"""Scrub credentials out of text that ends up in results (exception messages, failed commands).

A failed `kubectl exec ... mongosh mongodb://user:PASS@host` raises a CalledProcessError whose message repeats
the whole command, so every recorded exception goes through `redact` before it is saved or printed.

Short flags are only redacted where they are known to carry a password, so `kubectl -n ns`, `-p 8080` or
`psql -p 5432` (a port) stay readable:

- After a database client in a command (`mongosh`, `mongo`, `mongodump`, ..., `mysql`, `mysqldump`, `mariadb`:
  `-p`; `redis-cli`: `-a`), the value of that flag in any form: `-p SECRET`, `-pSECRET`, `-p=SECRET`, or
  `'-p', 'SECRET'` in a printed argv list. The command runs to the end of the argv list or line, or to `;`, `|`
  or `&`. `psql` takes no password flag (its password comes from PGPASSWORD=..., redacted as a key=value pair).
- `-u user:pass` / `--user user:pass` (any command, e.g. curl): the part after the colon.
"""

import re

MASK = "***"

_PATTERNS = [
    # URI userinfo: scheme://user:password@host -> scheme://***@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@'\"]+@"), rf"\1{MASK}@"),
    # Authorization headers and bearer tokens
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {MASK}"),
    # --password X, --password=X, --token X, ... (also as separate list items in a printed command)
    (
        re.compile(
            r"(?i)(--?(?:password|passwd|pass|token|secret|api[-_]?key|access[-_]?key|secret[-_]?key|auth)"
            r"(?:=|['\"]?,?\s+['\"]?))[^\s'\",\]]+"
        ),
        rf"\1{MASK}",
    ),
    # key=value / key: value / "key": "value" pairs with a secret-looking key
    (
        re.compile(
            # The secret word is the whole key or a _/- separated part of it (LANGFUSE_SECRET_KEY, access_token),
            # so ordinary words like "tokens: 1200" are left alone.
            r"(?i)([\"']?\b(?:[\w-]*(?=passw)|[\w-]*[_-])?(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key)"
            r"(?:[_-][\w-]*)?\b[\"']?\s*[:=]\s*[\"']?)[^\s'\",}&]+"
        ),
        rf"\1{MASK}",
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
_DB_COMMAND = re.compile(
    r"(?<![\w.-])(?:[\w.-]*/)*(?P<client>"
    + "|".join(sorted(map(re.escape, DB_CLIENT_PASSWORD_FLAGS), key=len, reverse=True))
    + r")(?![\w.-])(?P<args>[^\]\n;|&]*)"
)
# A flag's value: attached (-pX), after = (-p=X), after whitespace, or as the next item of a printed list
# (-p', 'X). A following flag (-p -h host: mysql prompts) is not a value.
_VALUE = r"(=|['\"]?,?\s*['\"]?)(?![-'\"])([^\s'\",\]]+)"
_USER_PASS = re.compile(r"(?<![\w-])(-u|--user)(=|['\"]?,?\s*['\"]?)([^\s'\",:\]]+):([^\s'\",\]]+)")


def _redact_db_command(m: re.Match) -> str:
    flag = DB_CLIENT_PASSWORD_FLAGS[m["client"]]
    args = re.sub(rf"(?<![\w-])({re.escape(flag)}){_VALUE}", rf"\1\2{MASK}", m["args"])
    return m.group(0)[: m.start("args") - m.start()] + args


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    text = _DB_COMMAND.sub(_redact_db_command, text)
    return _USER_PASS.sub(rf"\1\2\3:{MASK}", text)


def describe_error(exc: BaseException, limit: int = 200) -> str:
    """`Type: message` for recording, with credentials removed before truncating (so no secret is half-kept)."""
    text = f"{type(exc).__name__}: {exc}"
    stderr = getattr(exc, "stderr", None)
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    if isinstance(stderr, str) and stderr.strip():
        text += f" (stderr: {stderr.strip()})"
    return redact(text)[:limit]
