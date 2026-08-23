# =============================================================================
# Secret Redaction — los secretos jamás llegan a logs, respuestas o errores
# =============================================================================
from __future__ import annotations

import re

# Claves sensibles por nombre (case-insensitive, match de substring).
_SENSITIVE_KEY_PATTERNS = (
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"passwd", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"access[_-]?key", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"private[_-]?key", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"session[_-]?key", re.IGNORECASE),
)

# Patrones de valores embebidos en strings (URLs, headers).
_EMBEDDED_SECRET_PATTERNS = (
    re.compile(r"([a-z0-9]+://)[^:/\s]+:([^@/\s]+)@", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(password\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
)

REDACTED = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    return any(p.search(str(key)) for p in _SENSITIVE_KEY_PATTERNS)


def redact(value):
    """Redacta recursivamente dicts/lists/strings sin mutar el original."""
    if isinstance(value, dict):
        return {
            str(k): (REDACTED if _is_sensitive_key(k) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        out = value
        for pattern in _EMBEDDED_SECRET_PATTERNS:
            out = pattern.sub(lambda m: m.group(1) + REDACTED, out)
        return out
    return value
