# =============================================================================
# Memory content guard — no chain-of-thought, no secrets, no full documents.
# =============================================================================
from __future__ import annotations

import re
from typing import Any

_COT_KEYS = frozenset(
    {
        "chain_of_thought",
        "chainofthought",
        "reasoning",
        "hidden_reasoning",
        "scratchpad",
        "thought",
        "thoughts",
        "cot",
        "inner_monologue",
        "monologue",
    }
)
_SECRET_KEYS = frozenset(
    {
        "password",
        "secret",
        "api_key",
        "apikey",
        "token",
        "credential",
        "credentials",
        "authorization",
        "access_token",
        "refresh_token",
    }
)
_COT_TEXT = re.compile(
    r"\b(i first thought|i reasoned|chain of thought|my reasoning was|"
    r"primero pens[eé] que|luego razon)\b",
    re.IGNORECASE,
)
_MAX_TEXT = 2000
_MAX_META_VALUE = 500


class MemoryContentError(ValueError):
    """Contenido que no puede persistirse en memoria."""


def assert_safe_text(value: str, *, field_name: str) -> str:
    text = (value or "").strip()
    if len(text) > _MAX_TEXT:
        raise MemoryContentError(f"{field_name} exceeds {_MAX_TEXT} characters")
    if _COT_TEXT.search(text):
        raise MemoryContentError(f"{field_name} contains chain-of-thought")
    return text


def sanitize_metadata(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Rechaza CoT y secretos. No los recorta en silencio."""
    if not raw:
        return {}
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        normalized = str(key).strip().lower().replace("-", "_")
        if normalized in _COT_KEYS:
            raise MemoryContentError(f"metadata.{key} is chain-of-thought")
        if normalized in _SECRET_KEYS:
            raise MemoryContentError(f"metadata.{key} is a secret")
        if isinstance(value, dict):
            clean[str(key)] = sanitize_metadata(value)
            continue
        if isinstance(value, list):
            if len(value) > 20:
                raise MemoryContentError(f"metadata.{key} list is too large")
            clean[str(key)] = [
                sanitize_metadata(item) if isinstance(item, dict) else _scalar(item, key)
                for item in value
            ]
            continue
        clean[str(key)] = _scalar(value, str(key))
    return clean


def _scalar(value: Any, key: str) -> Any:
    if isinstance(value, str):
        if len(value) > _MAX_META_VALUE:
            raise MemoryContentError(f"metadata.{key} value is too large")
        if _COT_TEXT.search(value):
            raise MemoryContentError(f"metadata.{key} contains chain-of-thought")
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    raise MemoryContentError(f"metadata.{key} type is not allowed")
