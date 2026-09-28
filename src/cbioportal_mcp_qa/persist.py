"""The one way anything is written under results/: every object and text is redacted on the way out.

Results are published (GitHub Pages), and secrets can reach a run from many places: exception messages, the
agent's tool inputs and errors in Claude's stream or Langfuse traces, transcripts. Rather than redacting each
of those where it is captured, everything written goes through `scrub`, which walks the whole object (dict
keys and values, lists, dataclasses, strings) and redacts every string. A report rendered from data renders a
scrubbed copy, and its output is checked once more for known secret values.
"""

import copy
import dataclasses
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from . import redact as redact_mod
from .redact import MASK, add_env_secrets, mask_known, redact

# A run is saved after every answer and grade: redact each distinct string once, until the known values change.
_cache: dict[str, str] = {}
_cache_version = -1


def scrub(obj):
    """A copy of `obj` with every string in it redacted."""
    global _cache_version
    add_env_secrets()
    if _cache_version != redact_mod.known_version or len(_cache) > 200_000:
        _cache.clear()
        _cache_version = redact_mod.known_version
    return _scrub(obj)


# A dict key naming a credential: every string under it is masked, however nested. The key ends in the secret
# word (`password`, `db_password`, `apiToken`, `X-Api-Key`, `Set-Cookie`, `mongo_pass`), so `prompt_tokens`
# and the outcome count `pass` aren't secret keys.
_SECRET_KEY = re.compile(
    r"(?i)(?:password|passwd|[_-]pass|passphrase|pwd|secret|token|(?:api|access|private|secret|signing|auth)[-_]?key|"
    r"auth|authorization|cookie|credentials?)$"
)
# Keys that unambiguously hold a credential: numbers under them (a numeric password or PIN) are masked too.
# `token` isn't one of them: a number under it is more likely a count.
_CREDENTIAL_KEY = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|api[-_]?key|apikey|secret[-_]?key|authorization|credentials?|cookie|auth)$"
)
# Counters, never credentials: `pass` (an outcome count), `*tokens`, `token_count`, `*_count`, `*_total`.
_COUNTER_KEY = re.compile(r"(?i)^pass$|tokens$|_?count$|_total$")


def _secret_context(key) -> tuple[bool, bool]:
    """Whether a key's value is secret, and whether numbers in it are too."""
    if not isinstance(key, str) or _COUNTER_KEY.search(key) or not _SECRET_KEY.search(key):
        return False, False
    return True, bool(_CREDENTIAL_KEY.search(key))


def _mask_all(obj, numbers: bool):
    """`obj` with the same structure, every non-empty string (and number, if `numbers`) in it masked. Bools and
    None stay: they give nothing away."""
    if isinstance(obj, str):
        return MASK if obj.strip() else obj
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int | float):
        return MASK if numbers else obj
    if isinstance(obj, dict):
        out = copy.copy(obj)
        out.clear()
        dict.update(out, ((_scrub(k), _mask_all(v, numbers)) for k, v in obj.items()))
        return out
    if isinstance(obj, list | tuple | set | frozenset):
        return type(obj)(_mask_all(v, numbers) for v in obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        fields = {f.name: _mask_all(getattr(obj, f.name), numbers) for f in dataclasses.fields(obj) if f.init}
        return dataclasses.replace(obj, **fields)
    return MASK  # anything else under a secret key: its repr could carry the secret


def _scrub(obj):
    if isinstance(obj, str):
        if (out := _cache.get(obj)) is None:
            out = _cache[obj] = redact(obj)
        return out
    if isinstance(obj, dict):
        out = copy.copy(obj)  # keeps the type (Counter, defaultdict and its factory)
        out.clear()
        for key, value in obj.items():
            secret, numbers = _secret_context(key)
            key = _scrub(key)
            # Keys that redact to the same text keep every entry: `mongosh -p ***`, `mongosh -p *** #2`.
            base, n = key, 1
            while key in out:
                n += 1
                key = f"{base} #{n}"
            dict.__setitem__(
                out, key, _mask_all(value, numbers) if secret else _scrub(value)
            )  # not Counter.update
        return out
    if isinstance(obj, list | tuple | set | frozenset):
        items = [_scrub(v) for v in obj]
        if isinstance(obj, list | tuple) and len(items) > 1 and all(isinstance(v, str) for v in items):
            items = _scrub_argv(items)
        return type(obj)(items)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        # Copy field by field: fields that aren't init args (derived values) keep their computed value.
        fields = {f.name: _scrub(getattr(obj, f.name)) for f in dataclasses.fields(obj) if f.init}
        return dataclasses.replace(obj, **fields)
    return obj


def _scrub_argv(items: list[str]) -> list[str]:
    """A list of strings may be a command (`["mongosh", "-p", "X"]`): the command-line rules run on the items
    joined with spaces, and every item from the first masked position on is masked (fail closed)."""
    joined = " ".join(items)
    redacted = _scrub(joined)
    if redacted == joined:
        return items
    first = next(
        (i for i, (a, b) in enumerate(zip(joined, redacted, strict=False)) if a != b),
        min(len(joined), len(redacted)),
    )
    out, offset = [], 0
    for item in items:
        end = offset + len(item)
        if end <= first:
            out.append(item)  # before the mask
        elif offset >= first:
            out.append(MASK)
        else:
            out.append(item[: first - offset] + MASK)  # a value attached to its flag (`-pX`)
        offset = end + 1
    return out


def write_json(path: Path, obj, **dump_kwargs) -> None:
    """Written to a temp file first, then moved into place, so an interrupted save never leaves half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(scrub(obj), **dump_kwargs))
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.write_text(scrub(text))


def write_rendered(path: Path, render: Callable[..., str], **context) -> None:
    """Render a document (HTML, Markdown) from scrubbed data, then mask any known secret left in the output
    (a template can join or escape values). Only the data is pattern-redacted: the document's own markup
    must not be."""
    path.write_text(mask_known(render(**scrub(context))))


def write_private_json(path: str | Path, obj) -> None:
    """A config file a tool needs as is (Claude's MCP config, which may carry credentials), never under results/:
    only inside the temp directory, and not redacted. Symlinks out of it are resolved and refused; a hard link
    to a file outside can't be told apart from a file inside, so callers pass paths in a directory they created."""
    if not Path(path).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError(f"private files go in the temp directory, not {path}")
    Path(path).write_text(json.dumps(obj))


async def write_screenshot(page, path: Path) -> None:
    """A JPEG of a rendered page. Screenshots are pixels, so they can't be redacted: they are only taken of the
    public cBioPortal pages an answer linked to (`render --no-screenshots` skips them)."""
    await page.screenshot(path=path, type="jpeg", quality=60)
