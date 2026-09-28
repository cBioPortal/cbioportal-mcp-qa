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
from collections.abc import Callable
from pathlib import Path

from . import redact as redact_mod
from .redact import add_env_secrets, mask_known, redact

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


def _scrub(obj):
    if isinstance(obj, str):
        if (out := _cache.get(obj)) is None:
            out = _cache[obj] = redact(obj)
        return out
    if isinstance(obj, dict):
        out = copy.copy(obj)  # keeps the type (Counter, defaultdict and its factory)
        out.clear()
        dict.update(out, ((_scrub(k), _scrub(v)) for k, v in obj.items()))  # Counter.update would add
        return out
    if isinstance(obj, list | tuple | set | frozenset):
        return type(obj)(_scrub(v) for v in obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        # Copy field by field: fields that aren't init args (derived values) keep their computed value.
        fields = {f.name: _scrub(getattr(obj, f.name)) for f in dataclasses.fields(obj) if f.init}
        return dataclasses.replace(obj, **fields)
    return obj


def write_json(path: Path, obj, **dump_kwargs) -> None:
    path.write_text(json.dumps(scrub(obj), **dump_kwargs))


def write_text(path: Path, text: str) -> None:
    path.write_text(scrub(text))


def write_rendered(path: Path, render: Callable[..., str], **context) -> None:
    """Render a document (HTML, Markdown) from scrubbed data, then mask any known secret left in the output
    (a template can join or escape values). Only the data is pattern-redacted: the document's own markup
    must not be."""
    path.write_text(mask_known(render(**scrub(context))))
