# =============================================================================
# SecretStore resolver — Vault primario, fallback cifrado Postgres
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.ports.secret_store import SecretStore
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


class FallbackSecretStore(SecretStore):
    """Vault primario; si falla o no está configurado, Postgres cifrado."""

    def __init__(self) -> None:
        from src.infrastructure.secrets.encrypted_secret_store import (
            EncryptedPostgresSecretStore,
        )

        self._encrypted = EncryptedPostgresSecretStore()

    def _vault_available(self) -> bool:
        from src.infrastructure.secrets.vault import _get_vault_client

        return _get_vault_client() is not None

    async def put(
        self,
        organization_id: UUID,
        connector_id: UUID,
        secrets: dict,
    ) -> None:
        if self._vault_available():
            try:
                from src.infrastructure.secrets.vault import (
                    put_connector_secrets,
                )

                put_connector_secrets(
                    str(organization_id), str(connector_id), secrets
                )
                return
            except Exception as exc:
                logger.warning(
                    "Vault put failed, falling back to encrypted store",
                    error=str(exc),
                )
        await self._encrypted.put(organization_id, connector_id, secrets)

    async def get(
        self,
        organization_id: UUID,
        connector_id: UUID,
    ) -> dict:
        if self._vault_available():
            try:
                from src.infrastructure.secrets.vault import (
                    get_connector_secrets,
                )

                return get_connector_secrets(
                    str(organization_id), str(connector_id)
                )
            except Exception as exc:
                logger.warning(
                    "Vault get failed, falling back to encrypted store",
                    error=str(exc),
                )
        return await self._encrypted.get(organization_id, connector_id)

    async def delete(
        self,
        organization_id: UUID,
        connector_id: UUID,
    ) -> None:
        if self._vault_available():
            try:
                from src.infrastructure.secrets.vault import (
                    delete_connector_secrets,
                )

                delete_connector_secrets(str(organization_id), str(connector_id))
            except Exception:
                pass
        await self._encrypted.delete(organization_id, connector_id)


def get_secret_store() -> SecretStore:
    """Instancia única del SecretStore (resolver en composition root)."""
    global _store
    if _store is None:
        _store = FallbackSecretStore()
    return _store


_store: SecretStore | None = None
