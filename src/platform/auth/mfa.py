"""MFA TOTP para usuarios de plataforma (FASE 07).

Enrollment: `enroll_totp` genera un secreto base32 y lo almacena cifrado
(AES-256-GCM con PORTAL_SESSION_KEY); queda pendiente hasta confirmar con un
código (`confirm_totp`). `verify_totp` valida códigos para login y step-up.
"""
from __future__ import annotations

import base64
import binascii
import os
import time
from uuid import UUID

import pyotp
from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_STEP_UP_WINDOW_SECONDS = 600  # 10 min de validez para operaciones críticas


def _aesgcm() -> object:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    settings = get_settings()
    raw = settings.PORTAL_SESSION_KEY.get_secret_value().strip()
    if len(raw) == 64:
        key = bytes.fromhex(raw)
    else:
        pad = "=" * (-len(raw) % 4)
        key = base64.urlsafe_b64decode(raw + pad)
    return AESGCM(key)


def _encrypt_secret(secret: str) -> str:
    nonce = os.urandom(12)
    ct = _aesgcm().encrypt(nonce, secret.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii").rstrip("=")


def _decrypt_secret(blob: str) -> str:
    pad = "=" * (-len(blob) % 4)
    raw = base64.urlsafe_b64decode(blob + pad)
    nonce, ct = raw[:12], raw[12:]
    return _aesgcm().decrypt(nonce, ct, None).decode("utf-8")


def _totp_for(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def otpauth_uri(user_id: UUID, secret: str) -> str:
    return _totp_for(secret).provisioning_uri(
        name=f"zent:{user_id}", issuer_name="Zent Control Center"
    )


async def get_enrollment(user_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT user_id, secret_enc, enabled, confirmed_at "
                    "FROM mfa_totp WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "user_id": row.user_id,
        "enabled": bool(row.enabled),
        "confirmed_at": row.confirmed_at,
    }


async def mfa_enabled(user_id: UUID) -> bool:
    enrollment = await get_enrollment(user_id)
    return bool(enrollment and enrollment["enabled"])


async def save_enrollment(user_id: UUID, secret: str) -> None:
    """Crea/actualiza el secreto pendiente de confirmación."""
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO mfa_totp (user_id, secret_enc, enabled, created_at) "
                "VALUES (:uid, :secret, false, now()) "
                "ON CONFLICT (user_id) DO UPDATE SET secret_enc = :secret, enabled = false"
            ),
            {"uid": user_id, "secret": _encrypt_secret(secret)},
        )
        await session.commit()
    finally:
        await session.close()


async def confirm_enrollment(user_id: UUID, code: str) -> bool:
    """Confirma el enrollment si el código TOTP es válido."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT secret_enc FROM mfa_totp WHERE user_id = :uid"),
                {"uid": user_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return False
    try:
        secret = _decrypt_secret(row.secret_enc)
    except (binascii.Error, ValueError) as exc:
        logger.warning("MFA secret decrypt failed", error=str(exc))
        return False
    if not _totp_for(secret).verify(code, valid_window=1):
        return False
    s = await get_async_session()
    try:
        await s.execute(
            text(
                "UPDATE mfa_totp SET enabled = true, confirmed_at = now() "
                "WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        await s.commit()
    finally:
        await s.close()
    return True


async def disable_mfa(user_id: UUID) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM mfa_totp WHERE user_id = :uid"), {"uid": user_id}
        )
        await session.commit()
    finally:
        await session.close()


async def verify_totp(user_id: UUID, code: str) -> bool:
    """Valida un código TOTP contra el enrollment habilitado."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT secret_enc FROM mfa_totp "
                    "WHERE user_id = :uid AND enabled = true"
                ),
                {"uid": user_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return False
    try:
        secret = _decrypt_secret(row.secret_enc)
    except (binascii.Error, ValueError) as exc:
        logger.warning("MFA secret decrypt failed", error=str(exc))
        return False
    return _totp_for(secret).verify(code, valid_window=1)


def step_up_recent(payload) -> bool:
    """¿La sesión confirmó MFA/password hace menos de STEP_UP_WINDOW_SECONDS?"""
    if getattr(payload, "assurance", None) not in {"totp", "password"}:
        return False
    confirmed = getattr(payload, "mfa_confirmed_at", None)
    if not confirmed:
        return False
    return int(time.time()) - int(confirmed) <= _STEP_UP_WINDOW_SECONDS
