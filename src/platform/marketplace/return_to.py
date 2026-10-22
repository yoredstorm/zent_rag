# Vuelta al diseño. La misma regla que portal/src/lib/marketplaceReturn.ts.
from __future__ import annotations

import re

_SAFE_PATH = re.compile(r"^/(?!/)[A-Za-z0-9/_\-?=&%.]*$")
_SAFE_PREFIXES = ("/workflows", "/marketplace", "/agents", "/roles")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SAFE_CAPABILITY = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


def safe_return_to(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not _SAFE_PATH.match(text):
        return None
    if "://" in text or "\\" in text or "//" in text:
        return None
    path = text.split("?", 1)[0]
    if not any(path == prefix or path.startswith(prefix + "/") for prefix in _SAFE_PREFIXES):
        return None
    return text


def safe_id(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    return text if _SAFE_ID.match(text) else None


def safe_capability_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    return text if _SAFE_CAPABILITY.match(text) else None
