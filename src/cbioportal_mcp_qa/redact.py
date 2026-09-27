"""Scrub credentials out of text that ends up in results (exception messages, failed commands).

A failed `kubectl exec ... mongosh mongodb://user:PASS@host` raises a CalledProcessError whose message repeats
the whole command, so every recorded exception goes through `redact` before it is saved or printed."""

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
            r"(?i)([\"']?\b(?:[\w-]*[_-])?(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key)"
            r"(?:[_-][\w-]*)?\b[\"']?\s*[:=]\s*[\"']?)[^\s'\",}&]+"
        ),
        rf"\1{MASK}",
    ),
    # Well-known key shapes: Anthropic/OpenAI (sk-...), Langfuse (pk-lf-/sk-lf-), AWS access key ids
    (re.compile(r"\b(?:sk|pk)-(?:lf-|ant-)?[A-Za-z0-9_-]{12,}"), MASK),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), MASK),
]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def describe_error(exc: BaseException, limit: int = 200) -> str:
    """`Type: message` for recording, with credentials removed before truncating (so no secret is half-kept)."""
    text = f"{type(exc).__name__}: {exc}"
    stderr = getattr(exc, "stderr", None)
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    if isinstance(stderr, str) and stderr.strip():
        text += f" (stderr: {stderr.strip()})"
    return redact(text)[:limit]
