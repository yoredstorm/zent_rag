# =============================================================================
# Portal session tokens — AES-256-GCM opaque tokens (rag_sess_…)
# =============================================================================
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

SESSION_PREFIX = "rag_sess_"
_NONCE_LEN = 12

# Fallback in-memory de la lista de revocación cuando Redis no está
# disponible (CI, single-process dev). Mismo patrón que auth_rate_limit.
_mem_lock = threading.Lock()
_mem_revoked: dict[str, float] = {}  # sid -> expires_at (epoch)


def _mem_revoke(sid: str, ttl_seconds: int) -> None:
    with _mem_lock:
        _mem_revoked[sid] = time.time() + ttl_seconds


def _mem_is_revoked(sid: str) -> bool:
    now = time.time()
    with _mem_lock:
        exp = _mem_revoked.get(sid)
        if exp is None:
            return False
        if now >= exp:
            del _mem_revoked[sid]
            return False
        return True


# Revocación total por usuario: uid -> (revoked_before, expires_at epoch).
_mem_user_revoked: dict[str, tuple[float, float]] = {}


def _mem_revoke_user(uid: str, ttl_seconds: int) -> float:
    marker = time.time()
    with _mem_lock:
        _mem_user_revoked[uid] = (marker, marker + ttl_seconds)
    return marker


def _mem_user_revoked_before(uid: str) -> float | None:
    now = time.time()
    with _mem_lock:
        entry = _mem_user_revoked.get(uid)
        if entry is None:
            return None
        marker, exp = entry
        if now >= exp:
            del _mem_user_revoked[uid]
            return None
        return marker


class SessionTokenError(Exception):
    """Invalid, expired, or tampered portal session token."""


@dataclass(frozen=True)
class SessionPayload:
    user_id: UUID
    organization_id: UUID | None
    exp: int
    issued_at: float = 0.0  # epoch (segundos, sub-segundo); 0 = token legacy
    typ: str = "portal"
    sid: str | None = None  # session id for server-side revocation
    assurance: str | None = None  # FASE 07: "totp" cuando el login pasó MFA
    mfa_confirmed_at: int | None = None  # epoch; freshness para step-up
    imp_by: UUID | None = None  # FASE 09: platform admin que impersona al tenant


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
    organization_id: UUID | None = None,
    *,
    typ: str = "portal",
    ttl_hours: int | None = None,
    assurance: str | None = None,
    mfa_confirmed_at: int | None = None,
    imp_by: UUID | None = None,
) -> str:
    if typ not in ("portal", "platform", "mfa_challenge"):
        raise ValueError("session typ must be portal, platform or mfa_challenge")
    if typ in ("portal", "mfa_challenge") and organization_id is None and typ == "portal":
        raise ValueError("portal session requires organization_id")
    if typ == "platform":
        organization_id = None
    settings = get_settings()
    hours = ttl_hours if ttl_hours is not None else settings.PORTAL_SESSION_TTL_HOURS
    sid = secrets.token_hex(16)
    payload = {
        "uid": str(user_id),
        "tid": str(organization_id) if organization_id is not None else None,
        "sid": sid,
        "exp": int(time.time()) + int(hours * 3600),
        "iat": time.time(),
        "typ": typ,
    }
    if assurance:
        payload["assurance"] = assurance
    if mfa_confirmed_at:
        payload["mfa_confirmed_at"] = mfa_confirmed_at
    if imp_by is not None:
        payload["imp_by"] = str(imp_by)
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = _aesgcm().encrypt(nonce, plaintext, None)
    blob = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    return f"{SESSION_PREFIX}{blob}"


async def revoke_session(token: str) -> None:
    """Invalida una sesión portal (logout): añade su sid a la lista de revocación.

    Diseño libre de carreras: la sesión es válida por defecto; solo el logout
    (con el token en mano) escribe la revocación con TTL hasta su expiración.
    """
    try:
        payload = decrypt_session(token)
    except SessionTokenError:
        return
    if not payload.sid:
        return
    ttl_seconds = max(int(payload.exp - time.time()), 1)
    try:
        from src.infrastructure.redis.cache import _get_redis

        client = await _get_redis()
        await client.set(f"rag:session:revoked:{payload.sid}", "1", ex=ttl_seconds)
    except Exception as exc:
        logger.warning(
            "Redis unavailable; recording revocation in-memory",
            error=str(exc),
        )
        _mem_revoke(payload.sid, ttl_seconds)


async def revoke_user_sessions(user_id: UUID) -> None:
    """Revoca TODAS las sesiones activas de un usuario.

    Escribe el marcador `rag:user:revoked:{uid}` (epoch actual): todo token
    emitido antes (issued_at <= marker) deja de valer. TTL = máximo TTL de
    sesión (168 h). Usado por suspensión, reset de contraseña y logout forzado.
    """
    ttl_seconds = 168 * 3600
    uid = str(user_id)
    try:
        from src.infrastructure.redis.cache import _get_redis

        client = await _get_redis()
        await client.set(f"rag:user:revoked:{uid}", str(time.time()), ex=ttl_seconds)
    except Exception as exc:
        logger.warning(
            "Redis unavailable; recording user revocation in-memory",
            error=str(exc),
        )
        _mem_revoke_user(uid, ttl_seconds)


async def _user_revoked_before(uid: str) -> float | None:
    try:
        from src.infrastructure.redis.cache import _get_redis

        client = await _get_redis()
        raw = await client.get(f"rag:user:revoked:{uid}")
        return float(raw) if raw is not None else None
    except Exception as exc:
        logger.warning("User revocation registry unavailable; using in-memory", error=str(exc))
        return _mem_user_revoked_before(uid)


async def session_is_active(
    sid: str | None,
    *,
    user_id: UUID | None = None,
    issued_at: float | None = None,
) -> bool:
    """False si la sesión fue revocada (logout o suspensión del usuario).

    Sid None (tokens legacy) -> True salvo que exista marcador de revocación
    del usuario posterior a la emisión.
    """
    if sid:
        try:
            from src.infrastructure.redis.cache import _get_redis

            client = await _get_redis()
            revoked = await client.exists(f"rag:session:revoked:{sid}")
            if revoked:
                return False
        except Exception as exc:
            logger.warning("Session registry unavailable; using in-memory", error=str(exc))
            if _mem_is_revoked(sid):
                return False
    if user_id is not None:
        marker = await _user_revoked_before(str(user_id))
        if marker is not None and (issued_at or 0.0) <= marker:
            return False
    return True


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
    if data.get("typ") not in ("portal", "platform", "mfa_challenge"):
        raise SessionTokenError("Invalid session type")
    exp = int(data.get("exp", 0))
    if exp <= int(time.time()):
        raise SessionTokenError("Session expired")
    try:
        typ = data["typ"]
        tid_raw = data.get("tid")
        if typ in ("platform", "mfa_challenge"):
            organization_id = None
        else:
            organization_id = UUID(tid_raw)
        return SessionPayload(
            user_id=UUID(data["uid"]),
            organization_id=organization_id,
            exp=exp,
            issued_at=float(data.get("iat", 0)),
            typ=typ,
            sid=data.get("sid"),
            assurance=data.get("assurance"),
            mfa_confirmed_at=data.get("mfa_confirmed_at"),
            imp_by=UUID(data["imp_by"]) if data.get("imp_by") else None,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise SessionTokenError("Invalid session claims") from exc


def is_portal_session_token(token: str) -> bool:
    return token.startswith(SESSION_PREFIX)
