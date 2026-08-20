# =============================================================================
# Audit Service — Registro inmutable de acciones sensibles
# =============================================================================
# Todo servicio mutador invoca write() con el TenantContext en mano.
# Las entradas se escriben con la organización del CONTEXTO AUTENTICADO —
# nunca con un organization_id proveniente del body del cliente.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.entities import AuditLogEntry, TenantContext
from src.core.ports import AuditLogRepository
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


class AuditLogService:
    def __init__(self, repo: AuditLogRepository):
        self._repo = repo

    async def write(
        self,
        ctx: TenantContext,
        action: str,
        resource_type: str,
        resource_id: UUID | str | None = None,
        *,
        ip_address: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Escribe una entrada con la identidad del contexto autenticado."""
        try:
            await self._repo.write(
                AuditLogEntry(
                    organization_id=ctx.tenant_id,
                    actor_user_id=ctx.user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    ip_address=ip_address,
                    metadata=metadata or {},
                )
            )
        except Exception as exc:
            # La auditoría falla en silencio para no romper el flujo principal,
            # pero deja rastro en logs (el observability team lo correlaciona).
            logger.warning("Audit write failed", action=action, error=str(exc))

    async def list_entries(
        self,
        ctx: TenantContext,
        *,
        limit: int = 100,
        offset: int = 0,
        resource_type: str | None = None,
    ) -> list[AuditLogEntry]:
        return await self._repo.list_entries(
            ctx.tenant_id,
            limit=limit,
            offset=offset,
            resource_type=resource_type,
        )
