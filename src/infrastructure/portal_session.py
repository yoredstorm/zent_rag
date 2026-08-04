# =============================================================================
# Portal session tokens — AES-256-GCM opaque tokens (rag_sess_…)
# =============================================================================
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import get_settings

SESSION_PREFIX = "rag_sess_"
_NONCE_LEN = 12


class SessionTokenError(Exception):
    """Invalid, expired, or tampered portal session token."""


@dataclass(frozen=True)
class SessionPayload:
    user_id: UUID
    tenant_id: UUID
    exp: int
    typ: str = "portal"


def _decode_key(raw: str) -> bytes:
    value = raw.strip()
    if len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        key = bytes.fromhex(value)
    else:
        pad = "=" * (-len(value) % 4)
        key = base64.urlsafe_b64decode(value + pad)
    if len(key) != 32:
        raise ValueError(
            "PORTAL_SESSION_KEY must decode to exactly 32 bytes (AES-256)"
        )
    return key


def _aesgcm() -> AESGCM:
    settings = get_settings()
    return AESGCM(_decode_key(settings.PORTAL_SESSION_KEY.get_secret_value()))


def encrypt_session(
    user_id: UUID,
    tenant_id: UUID,
    *,
    ttl_hours: int | None = None,
) -> str:
    settings = get_settings()
    hours = ttl_hours if ttl_hours is not None else settings.PORTAL_SESSION_TTL_HOURS
    payload = {
        "uid": str(user_id),
        "tid": str(tenant_id),
        "exp": int(time.time()) + int(hours * 3600),
        "typ": "portal",
    }
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = _aesgcm().encrypt(nonce, plaintext, None)
    blob = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    return f"{SESSION_PREFIX}{blob}"


def decrypt_session(token: str) -> SessionPayload:
    if not token.startswith(SESSION_PREFIX):
        raise SessionTokenError("Not a portal session token")
    blob = token[len(SESSION_PREFIX) :]
    pad = "=" * (-len(blob) % 4)
    try:
        raw = base64.urlsafe_b64decode(blob + pad)
    except Exception as exc:
        raise SessionTokenError("Malformed session token") from exc
    if len(raw) < _NONCE_LEN + 16:
        raise SessionTokenError("Malformed session token")
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    try:
        plaintext = _aesgcm().decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise SessionTokenError("Invalid or tampered session token") from exc
    try:
        data = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise SessionTokenError("Corrupt session payload") from exc
    if data.get("typ") != "portal":
        raise SessionTokenError("Invalid session type")
    exp = int(data.get("exp", 0))
    if exp <= int(time.time()):
        raise SessionTokenError("Session expired")
    try:
        return SessionPayload(
            user_id=UUID(data["uid"]),
            tenant_id=UUID(data["tid"]),
            exp=exp,
            typ="portal",
        )
    except (KeyError, ValueError) as exc:
        raise SessionTokenError("Invalid session claims") from exc


def is_portal_session_token(token: str) -> bool:
    return token.startswith(SESSION_PREFIX)
