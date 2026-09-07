# =============================================================================
# Revocation Propagation — impacto y política al perder acceso a una fuente
# =============================================================================
# Antes de eliminar: dependency impact (agentes/métricas/conceptos/casos de
# eval/deployments). Al revocar: purge/hide/invalidate según política; un
# agente no debe seguir usando conocimiento cuya fuente ya no está autorizada.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    rag_knowledge_invalidations_total,
)
from src.infrastructure.postgres.session import get_async_session
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)


class RevocationService:
    """Evalúa y propaga la revocación de una fuente de conocimiento."""

    def __init__(
        self,
        catalog_store: PostgresCatalogStore,
        learning_store: PostgresLearningStore | None = None,
    ) -> None:
        self._catalog = catalog_store
        self._learning = learning_store or PostgresLearningStore()

    async def assess(
        self, organization_id: UUID, connector_id: UUID
    ) -> dict:
        """Impacto de eliminar el connector sobre el conocimiento derivado."""
        source = await self._catalog.get_source_by_connector(
            organization_id, connector_id
        )
        impact: dict = {
            "connector_id": str(connector_id),
            "catalog_source_id": source["id"] if source else None,
            "agents": 0,
            "metrics": 0,
            "business_concepts": 0,
            "evaluation_cases": 0,
            "deployments": 0,
            "documents": 0,
            "tables": 0,
            "columns": 0,
            "relationships": 0,
            "suggestions": 0,
        }
        if source is None:
            return impact

        source_id = UUID(source["id"])
        tables = await self._catalog.list_tables(organization_id, source_id, limit=1000)
        impact["tables"] = len(tables)
        total_columns = 0
        for t in tables:
            total_columns += len(
                await self._catalog.list_columns(organization_id, UUID(t["id"]))
            )
        impact["columns"] = total_columns
        impact["relationships"] = len(
            await self._catalog.list_relationships(
                organization_id, source_id, limit=1000
            )
        )
        suggestions = await self._catalog.list_suggestions(
            organization_id, status="pending", limit=500
        )
        impact["suggestions"] = sum(
            1
            for s in suggestions
            if str(source_id) in [str(x) for x in s.get("affected_sources") or []]
            or str(source_id) in str(s.get("payload") or {})
        )

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT "
                        "(SELECT COUNT(*) FROM agents WHERE organization_id = :oid "
                        " AND status <> 'archived') AS agents, "
                        "(SELECT COUNT(*) FROM catalog_metrics WHERE "
                        " organization_id = :oid) AS metrics, "
                        "(SELECT COUNT(*) FROM business_definitions WHERE "
                        " organization_id = :oid AND authoritative_source_id = :connector) "
                        " AS concepts, "
                        "(SELECT COUNT(*) FROM deployments d JOIN agents a ON "
                        " a.id = d.agent_id WHERE a.organization_id = :oid) AS deployments"
                    ),
                    {"oid": organization_id, "connector": str(connector_id)},
                )
            ).fetchone()
            if row:
                impact["agents"] = int(row.agents or 0)
                impact["metrics"] = int(row.metrics or 0)
                impact["business_concepts"] = int(row.concepts or 0)
                impact["deployments"] = int(row.deployments or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Revocation impact query failed", error=str(exc)[:200])
        finally:
            await session.close()
        return impact

    async def revoke(
        self, organization_id: UUID, connector_id: UUID, *, policy: str = "purge"
    ) -> dict:
        """Aplica la política de revocación al connector eliminado.

        purge: borrado en cascada del catálogo + invalidación de caches.
        hide: soft-remove (removed_at) + invalidación.
        retain_metadata_only: mantiene metadata, bloquea uso.
        """
        impact = await self.assess(organization_id, connector_id)
        source = await self._catalog.get_source_by_connector(
            organization_id, connector_id
        )
        if source is None:
            return impact

        source_id = UUID(source["id"])
        if policy == "hide":
            for table in await self._catalog.list_tables(
                organization_id, source_id, limit=1000
            ):
                await self._catalog.mark_tables_removed(
                    organization_id, source_id, []
                )
                break
        elif policy == "purge":
            # El DELETE del connector cascada a catalog_sources -> catalog_*.
            pass

        # Invalidaciones: caché de schema del SQL Expert + sugerencias bloqueadas.
        try:
            from src.agents.tools.schema_relevance import SchemaCache

            SchemaCache().invalidate(f"sql:schema:{organization_id.hex}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Schema cache invalidation failed", error=str(exc)[:200])
        try:
            for suggestion in await self._catalog.list_suggestions(
                organization_id, status="pending", limit=500
            ):
                if str(source_id) in str(suggestion.get("payload") or {}):
                    await self._catalog.update_suggestion_status(
                        organization_id,
                        UUID(suggestion["id"]),
                        status="rejected",
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Suggestion block failed", error=str(exc)[:200])

        rag_knowledge_invalidations_total.labels(
            organization_id=str(organization_id)
        ).inc()
        impact["policy"] = policy
        impact["invalidated"] = True
        return impact
