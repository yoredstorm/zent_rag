# =============================================================================
# Agent embed tokens — opaque public_id + hashed zent_emb_ secret
# =============================================================================
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_TOKEN_PREFIX = "zent_emb_"  # noqa: S105 — public prefix, not a secret

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS agent_embed_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        public_id VARCHAR(64) NOT NULL UNIQUE,
        agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL,
        token_hash VARCHAR(64) NOT NULL UNIQUE,
        token_prefix VARCHAR(20) NOT NULL,
        allowed_origins TEXT[] NOT NULL DEFAULT '{}',
        revoked_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_embed_tokens_agent ON agent_embed_tokens(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_embed_tokens_public ON agent_embed_tokens(public_id)",
)


@dataclass
class EmbedTokenRow:
    public_id: str
    agent_id: UUID
    organization_id: UUID
    token_prefix: str
    allowed_origins: list[str]
    revoked_at: datetime | None


def hash_embed_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_embed_token() -> str:
    return f"{_TOKEN_PREFIX}{secrets.token_hex(24)}"


def generate_public_id() -> str:
    return secrets.token_urlsafe(18)


async def ensure_embed_schema() -> None:
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


def origin_allowed(origin: str, allowed: list[str]) -> bool:
    got = (origin or "").strip().rstrip("/")
    if not got:
        return False
    for item in allowed:
        want = (item or "").strip().rstrip("/")
        if want and got.lower() == want.lower():
            return True
    return False


def _row(row) -> EmbedTokenRow:
    origins = row.allowed_origins or []
    if not isinstance(origins, list):
        origins = list(origins)
    return EmbedTokenRow(
        public_id=row.public_id,
        agent_id=row.agent_id,
        organization_id=row.organization_id,
        token_prefix=row.token_prefix,
        allowed_origins=[str(o) for o in origins],
        revoked_at=row.revoked_at,
    )


async def mint_embed_token(
    organization_id: UUID,
    agent_id: UUID,
    allowed_origins: list[str],
) -> tuple[str, EmbedTokenRow]:
    await ensure_embed_schema()
    raw = generate_embed_token()
    public_id = generate_public_id()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE agent_embed_tokens SET revoked_at = NOW() "
                "WHERE agent_id = :aid AND organization_id = :oid AND revoked_at IS NULL"
            ),
            {"aid": agent_id, "oid": organization_id},
        )
        result = await session.execute(
            text(
                "INSERT INTO agent_embed_tokens "
                "(public_id, agent_id, organization_id, token_hash, token_prefix, allowed_origins) "
                "VALUES (:pid, :aid, :oid, :thash, :prefix, :origins) "
                "RETURNING public_id, agent_id, organization_id, token_prefix, "
                "allowed_origins, revoked_at"
            ).bindparams(bindparam("origins", type_=ARRAY(TEXT))),
            {
                "pid": public_id,
                "aid": agent_id,
                "oid": organization_id,
                "thash": hash_embed_token(raw),
                "prefix": _TOKEN_PREFIX,
                "origins": allowed_origins,
            },
        )
        row = result.fetchone()
        await session.commit()
        logger.info(
            "Embed token minted",
            agent_id=str(agent_id),
            public_id=public_id,
            token_prefix=_TOKEN_PREFIX,
        )
        return raw, _row(row)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_embed_for_agent(
    organization_id: UUID, agent_id: UUID
) -> EmbedTokenRow | None:
    await ensure_embed_schema()
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT public_id, agent_id, organization_id, token_prefix, "
                "allowed_origins, revoked_at FROM agent_embed_tokens "
                "WHERE agent_id = :aid AND organization_id = :oid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"aid": agent_id, "oid": organization_id},
        )
        row = result.fetchone()
        return _row(row) if row else None
    finally:
        await session.close()


async def get_embed_by_public_id(public_id: str) -> EmbedTokenRow | None:
    await ensure_embed_schema()
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT public_id, agent_id, organization_id, token_prefix, "
                "allowed_origins, revoked_at FROM agent_embed_tokens "
                "WHERE public_id = :pid"
            ),
            {"pid": public_id},
        )
        row = result.fetchone()
        return _row(row) if row else None
    finally:
        await session.close()


async def revoke_embed_token(organization_id: UUID, agent_id: UUID) -> None:
    await ensure_embed_schema()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE agent_embed_tokens SET revoked_at = NOW() "
                "WHERE agent_id = :aid AND organization_id = :oid AND revoked_at IS NULL"
            ),
            {"aid": agent_id, "oid": organization_id},
        )
        await session.commit()
        logger.info("Embed token revoked", agent_id=str(agent_id))
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
