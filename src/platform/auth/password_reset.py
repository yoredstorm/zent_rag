# =============================================================================
# One-time password reset tokens (no email sender in v1)
# =============================================================================
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_TTL = timedelta(hours=1)
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash VARCHAR(64) NOT NULL UNIQUE,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id)",
)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def ensure_reset_schema() -> None:
    session = await get_async_session()
    try:
        for stmt in _SCHEMA:
            await session.execute(text(stmt))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def issue_reset_token(user_id: UUID) -> str:
    await ensure_reset_schema()
    raw = secrets.token_urlsafe(32)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE password_reset_tokens SET used_at = NOW() "
                "WHERE user_id = :uid AND used_at IS NULL"
            ),
            {"uid": user_id},
        )
        await session.execute(
            text(
                "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
                "VALUES (:uid, :thash, :exp)"
            ),
            {
                "uid": user_id,
                "thash": hash_reset_token(raw),
                "exp": datetime.now(timezone.utc) + _TTL,
            },
        )
        await session.commit()
        logger.info("Password reset token issued", user_id=str(user_id))
        return raw
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def consume_reset_token(token: str) -> UUID:
    await ensure_reset_schema()
    digest = hash_reset_token(token)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, user_id, expires_at, used_at "
                    "FROM password_reset_tokens WHERE token_hash = :thash"
                ),
                {"thash": digest},
            )
        ).fetchone()
        if row is None or row.used_at is not None:
            raise ValueError("invalid reset token")
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise ValueError("expired reset token")
        await session.execute(
            text("UPDATE password_reset_tokens SET used_at = NOW() WHERE id = :id"),
            {"id": row.id},
        )
        await session.commit()
        return row.user_id
    except ValueError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
