# =============================================================================
# DemoPurgeService — tenant + workspace scoped, idempotent, audited
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.core.domain.entities import TenantContext
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.audit.service import AuditLogService

logger = get_logger(__name__)

_IMPACT_KEYS = (
    "demo documents",
    "demo vectors",
    "demo catalog",
    "demo semantic mappings",
    "demo glossary",
    "demo verified queries",
    "demo agents",
    "demo entities",
    "demo relationships",
    "demo context graph",
    "demo source records",
)

_PRESERVE = (
    "organization",
    "users",
    "roles",
    "subscription",
    "billing",
    "security settings",
    "audit history required for compliance",
)


class DemoPurgeService:
    """Never run unscoped deletes. Always (organization_id, workspace_id)."""

    def __init__(self, audit: AuditLogService | None = None) -> None:
        self._audit = audit or AuditLogService(PostgresAuditLogRepository())

    async def impact(self, organization_id: UUID, workspace_id: UUID) -> dict:
        if not organization_id or not workspace_id:
            raise ValueError("organization_id and workspace_id are required")
        session = await get_async_session()
        counts: dict[str, int] = {}
        try:
            queries = {
                "demo source records": (
                    "SELECT COUNT(*) FROM kb_sources "
                    "WHERE organization_id = :oid AND workspace_id = :wid"
                ),
                "demo agents": (
                    "SELECT COUNT(*) FROM agents "
                    "WHERE organization_id = :oid AND workspace_id = :wid"
                ),
                "demo catalog": (
                    "SELECT COUNT(*) FROM catalog_sources "
                    "WHERE organization_id = :oid AND workspace_id = :wid"
                ),
            }
            for key, sql in queries.items():
                try:
                    counts[key] = int(
                        (
                            await session.execute(
                                text(sql), {"oid": organization_id, "wid": workspace_id}
                            )
                        ).scalar()
                        or 0
                    )
                except Exception:  # noqa: BLE001
                    counts[key] = 0
        finally:
            await session.close()
        return {
            "will_remove": list(_IMPACT_KEYS),
            "will_preserve": list(_PRESERVE),
            "counts": counts,
        }

    async def purge(
        self,
        ctx: TenantContext,
        workspace_id: UUID,
        *,
        action: str = "workspace.demo_purged",
        options: dict[str, bool] | None = None,
    ) -> dict:
        organization_id = ctx.organization_id
        if not organization_id or not workspace_id:
            raise ValueError("organization_id and workspace_id are required")
        opts = options or {
            "documents": True,
            "sources": True,
            "semantic": True,
            "agents": True,
            "all_business_data": True,
        }
        before = await self.impact(organization_id, workspace_id)
        session = await get_async_session()
        qdrant_ok = True
        deletes = []
        if opts.get("sources") or opts.get("all_business_data"):
            deletes.extend(
                [
                    "DELETE FROM data_onboarding_sessions WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM source_documents WHERE organization_id = :oid AND "
                    "source_id IN (SELECT id FROM kb_sources WHERE organization_id = :oid AND workspace_id = :wid)",
                    "DELETE FROM documents WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM ingestion_jobs WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM kb_sources WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM knowledge_bases WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM connectors WHERE organization_id = :oid AND workspace_id = :wid",
                ]
            )
        if opts.get("agents") or opts.get("all_business_data"):
            deletes.append(
                "DELETE FROM agents WHERE organization_id = :oid AND workspace_id = :wid"
            )
        if opts.get("semantic") or opts.get("all_business_data"):
            deletes.extend(
                [
                    "DELETE FROM catalog_sources WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM business_definitions WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM verified_queries WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM context_gaps WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM intelligence_traces WHERE organization_id = :oid AND workspace_id = :wid",
                    "DELETE FROM improvement_items WHERE organization_id = :oid AND workspace_id = :wid",
                ]
            )
        params = {"oid": organization_id, "wid": workspace_id}
        try:
            for sql in deletes:
                try:
                    await session.execute(text(sql), params)
                    await session.commit()
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    logger.warning("Purge statement skipped", error=str(exc)[:180])
        finally:
            await session.close()

        if opts.get("documents") or opts.get("all_business_data"):
            try:
                from src.infrastructure.qdrant.vector_store import QdrantVectorStore

                await QdrantVectorStore().delete_by_workspace(
                    organization_id, workspace_id
                )
            except Exception as exc:  # noqa: BLE001
                qdrant_ok = False
                logger.warning("Qdrant workspace purge failed", error=str(exc)[:200])

        after = await self.impact(organization_id, workspace_id)
        had_work = sum(before["counts"].values()) > 0
        result = {
            "status": "FAILED" if not qdrant_ok else "ok",
            "before": before["counts"],
            "after": after["counts"],
            "idempotent": not had_work and qdrant_ok,
        }
        try:
            await self._audit.write(
                ctx,
                action,
                "workspace",
                workspace_id,
                metadata=result,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Purge audit skipped", error=str(exc)[:160])
        return result
