# =============================================================================
# EncryptedPostgresSecretStore — fallback cifrado sin Vault
# =============================================================================
# AES-256-GCM con key derivada de CONNECTOR_SECRETS_KEY. Los secretos
# NUNCA se guardan en texto plano en Postgres. Vault (si configurado) es
# el store primario; este fallback mantiene dev/local funcional.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import os
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text

from src.core.config import get_settings
from src.core.ports.secret_store import SecretStore
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS connector_secrets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    connector_id UUID NOT NULL,
    ciphertext BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, connector_id)
)
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_connector_secrets_org "
    "ON connector_secrets(organization_id)"
)


def _key() -> bytes:
    settings = get_settings()
    raw = settings.CONNECTOR_SECRETS_KEY.get_secret_value()
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _encrypt(plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    aesgcm = AESGCM(_key())
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext  # 12-byte nonce prefixado


def _decrypt(blob: bytes) -> bytes:
    nonce, ciphertext = blob[:12], blob[12:]
    aesgcm = AESGCM(_key())
    return aesgcm.decrypt(nonce, ciphertext, None)


class EncryptedPostgresSecretStore(SecretStore):
    """SecretStore con cifrado AES-GCM en tabla connector_secrets."""

    async def _ensure_table(self) -> None:
        session = await get_async_session()
        try:
            await session.execute(text(_TABLE_SQL))
            await session.commit()
        except Exception:
            await session.rollback()
        try:
            await session.execute(text(_INDEX_SQL))
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()

    async def put(
        self,
        organization_id: UUID,
        connector_id: UUID,
        secrets: dict,
    ) -> None:
        await self._ensure_table()
        blob = _encrypt(json.dumps(secrets).encode("utf-8"))
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO connector_secrets "
                    "(organization_id, connector_id, ciphertext) "
                    "VALUES (:org, :cid, :blob) "
                    "ON CONFLICT (organization_id, connector_id) "
                    "DO UPDATE SET ciphertext = EXCLUDED.ciphertext, "
                    "updated_at = NOW()"
                ),
                {"org": organization_id, "cid": connector_id, "blob": blob},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get(
        self,
        organization_id: UUID,
        connector_id: UUID,
    ) -> dict:
        await self._ensure_table()
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT ciphertext FROM connector_secrets "
                        "WHERE organization_id = :org AND connector_id = :cid"
                    ),
                    {"org": organization_id, "cid": connector_id},
                )
            ).fetchone()
            if row is None:
                return {}
            plaintext = _decrypt(bytes(row.ciphertext))
            parsed = json.loads(plaintext.decode("utf-8"))
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception as exc:
            logger.warning(
                "Failed to read connector secrets",
                connector_id=str(connector_id),
                error=str(exc),
            )
            return {}
        finally:
            await session.close()

    async def delete(
        self,
        organization_id: UUID,
        connector_id: UUID,
    ) -> None:
        await self._ensure_table()
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM connector_secrets "
                    "WHERE organization_id = :org AND connector_id = :cid"
                ),
                {"org": organization_id, "cid": connector_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()
