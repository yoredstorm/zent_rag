# =============================================================================
# Robust JSON extraction for LLM output.
#
# Providers may wrap JSON in markdown, reasoning text or DSML/tool-call markup.
# A greedy `{.*}` regex destroys a valid first object when a second brace or
# markup follows. These helpers decode complete objects with raw_decode and
# never evaluate arbitrary text.
# =============================================================================
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any


def iter_json_objects(text: str) -> Iterator[dict[str, Any]]:
    """Yield every complete JSON object embedded in arbitrary text."""
    raw = str(text or "")
    decoder = json.JSONDecoder()
    position = 0
    while position < len(raw):
        start = raw.find("{", position)
        if start < 0:
            return
        try:
            data, end = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            position = start + 1
            continue
        if isinstance(data, dict):
            yield data
        position = start + max(1, end)


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Return the first complete JSON object, ignoring later markup/text."""
    return next(iter_json_objects(text), None)


def parse_json_object_with_key(text: str, key: str) -> dict[str, Any] | None:
    """Return the first complete object that contains `key`."""
    for data in iter_json_objects(text):
        if key in data:
            return data
    return None


__all__ = ["iter_json_objects", "parse_json_object", "parse_json_object_with_key"]
