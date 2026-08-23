# =============================================================================
# SecretStore — puerto para credenciales cifradas de conectores
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class SecretStore(ABC):
    """Almacenamiento cifrado de secretos por organization + connector.

    Implementaciones: VaultSecretStore (KV v2) y
    EncryptedPostgresSecretStore (AES-GCM, fallback sin Vault).
    NUNCA devuelve secretos a quien no sea el owner (aislamiento estricto
    por organization_id).
    """

    @abstractmethod
    async def put(
        self,
        organization_id: UUID,
        connector_id: UUID,
        secrets: dict,
    ) -> None: ...

    @abstractmethod
    async def get(
        self,
        organization_id: UUID,
        connector_id: UUID,
    ) -> dict: ...

    @abstractmethod
    async def delete(
        self,
        organization_id: UUID,
        connector_id: UUID,
    ) -> None: ...
