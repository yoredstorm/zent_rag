# =============================================================================
# Progressive Semantic Ingestion — store Postgres
# =============================================================================
# Una fila de manifiesto por (organización, fuente, external_id):
# responde «¿ZENT procesó toda esta fuente?» con flags reales por etapa.
# Una fila por ventana semántica planificada (checkpoint futuro por ventana).
#
# La escritura de plan es idempotente: mismo documento => mismas ventanas.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import bindparam, text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

from .contracts import (
    SEMANTIC_STATE_VERSION,
    SemanticState,
    SemanticWindowPlan,
    SemanticWindowResult,
    SemanticWindowSpec,
    SourceIngestionManifest,
)
from .fabric import FabricEdge, FabricNode, IdentityCandidate
from .global_model import GlobalSemanticModel
from .regional import RegionalSemanticModel
from .stitcher import StitchedUnit, StitchRelation
from .threads import THREAD_VERSION, SemanticThread

logger = get_logger(__name__)


def _manifest_from_row(row) -> SourceIngestionManifest:
    return SourceIngestionManifest(
        organization_id=UUID(str(row.organization_id)),
        source_id=UUID(str(row.source_id)) if row.source_id else None,
        workspace_id=UUID(str(row.workspace_id)) if row.workspace_id else None,
        document_id=UUID(str(row.document_id)) if row.document_id else None,
        external_id=str(row.external_id or ""),
        source_type=str(row.source_type or ""),
        raw_fingerprint=str(row.raw_fingerprint or ""),
        content_hash=str(row.content_hash or ""),
        total_bytes=int(row.total_bytes or 0),
        estimated_tokens=int(row.estimated_tokens or 0),
        structural_units=int(row.structural_units or 0),
        processed_units=int(row.processed_units or 0),
        semantic_units=int(row.semantic_units or 0),
        unresolved_units=int(row.unresolved_units or 0),
        failed_units=int(row.failed_units or 0),
        windows_total=int(row.windows_total or 0),
        windows_processed=int(row.windows_processed or 0),
        parsing_complete=bool(row.parsing_complete),
        semantic_complete=bool(row.semantic_complete),
        stitching_complete=bool(row.stitching_complete),
        global_synthesis_complete=bool(row.global_synthesis_complete),
        indexing_complete=bool(row.indexing_complete),
        pipeline_complete=bool(getattr(row, "pipeline_complete", False)),
        stages=dict(row.stages or {}),
        versions=dict(row.versions or {}),
        details=dict(row.details or {}),
        started_at=row.started_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


class PostgresSemanticIngestionStore:
    """Store scoped por organización (tenant isolation en cada query)."""

    async def upsert_manifest(self, manifest: SourceIngestionManifest) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_ingestion_manifests (
                        id, organization_id, workspace_id, source_id, document_id,
                        external_id, source_type, raw_fingerprint, content_hash,
                        total_bytes, estimated_tokens, structural_units,
                        processed_units, semantic_units, unresolved_units,
                        failed_units, windows_total, windows_processed,
                        parsing_complete, semantic_complete, stitching_complete,
                        global_synthesis_complete, indexing_complete,
                        pipeline_complete, coverage_ratio, stages, versions,
                        details, started_at, updated_at, completed_at
                    ) VALUES (
                        gen_random_uuid(), :organization_id, :workspace_id, :source_id,
                        :document_id, :external_id, :source_type, :raw_fingerprint,
                        :content_hash, :total_bytes, :estimated_tokens,
                        :structural_units, :processed_units, :semantic_units,
                        :unresolved_units, :failed_units, :windows_total,
                        :windows_processed, :parsing_complete, :semantic_complete,
                        :stitching_complete, :global_synthesis_complete,
                        :indexing_complete, :pipeline_complete, :coverage_ratio,
                        CAST(:stages AS jsonb), CAST(:versions AS jsonb),
                        CAST(:details AS jsonb), :started_at, now(), :completed_at
                    )
                    ON CONFLICT (organization_id, source_id, external_id) DO UPDATE SET
                        workspace_id = EXCLUDED.workspace_id,
                        document_id = EXCLUDED.document_id,
                        source_type = EXCLUDED.source_type,
                        raw_fingerprint = EXCLUDED.raw_fingerprint,
                        content_hash = EXCLUDED.content_hash,
                        total_bytes = EXCLUDED.total_bytes,
                        estimated_tokens = EXCLUDED.estimated_tokens,
                        structural_units = EXCLUDED.structural_units,
                        processed_units = EXCLUDED.processed_units,
                        semantic_units = EXCLUDED.semantic_units,
                        unresolved_units = EXCLUDED.unresolved_units,
                        failed_units = EXCLUDED.failed_units,
                        windows_total = EXCLUDED.windows_total,
                        windows_processed = EXCLUDED.windows_processed,
                        parsing_complete = EXCLUDED.parsing_complete,
                        semantic_complete = EXCLUDED.semantic_complete,
                        stitching_complete = EXCLUDED.stitching_complete,
                        global_synthesis_complete = EXCLUDED.global_synthesis_complete,
                        indexing_complete = EXCLUDED.indexing_complete,
                        pipeline_complete = EXCLUDED.pipeline_complete,
                        coverage_ratio = EXCLUDED.coverage_ratio,
                        stages = EXCLUDED.stages,
                        versions = EXCLUDED.versions,
                        details = EXCLUDED.details,
                        updated_at = now(),
                        completed_at = EXCLUDED.completed_at
                    """
                ),
                {
                    "organization_id": str(manifest.organization_id),
                    "workspace_id": str(manifest.workspace_id)
                    if manifest.workspace_id
                    else None,
                    "source_id": str(manifest.source_id) if manifest.source_id else None,
                    "document_id": str(manifest.document_id)
                    if manifest.document_id
                    else None,
                    "external_id": manifest.external_id[:512],
                    "source_type": manifest.source_type[:40],
                    "raw_fingerprint": manifest.raw_fingerprint[:64],
                    "content_hash": manifest.content_hash[:64],
                    "total_bytes": int(manifest.total_bytes),
                    "estimated_tokens": int(manifest.estimated_tokens),
                    "structural_units": int(manifest.structural_units),
                    "processed_units": int(manifest.processed_units),
                    "semantic_units": int(manifest.semantic_units),
                    "unresolved_units": int(manifest.unresolved_units),
                    "failed_units": int(manifest.failed_units),
                    "windows_total": int(manifest.windows_total),
                    "windows_processed": int(manifest.windows_processed),
                    "parsing_complete": bool(manifest.parsing_complete),
                    "semantic_complete": bool(manifest.semantic_complete),
                    "stitching_complete": bool(manifest.stitching_complete),
                    "global_synthesis_complete": bool(
                        manifest.global_synthesis_complete
                    ),
                    "indexing_complete": bool(manifest.indexing_complete),
                    "pipeline_complete": bool(manifest.pipeline_complete),
                    "coverage_ratio": float(manifest.coverage_ratio),
                    "stages": json.dumps(manifest.stages or {}, default=str),
                    "versions": json.dumps(manifest.versions or {}, default=str),
                    "details": json.dumps(manifest.details or {}, default=str),
                    "started_at": manifest.started_at,
                    "completed_at": manifest.completed_at,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_manifest(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        external_id: str | None = None,
        document_id: UUID | None = None,
    ) -> SourceIngestionManifest | None:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid"]
            params: dict = {"oid": str(organization_id)}
            if source_id is not None:
                where.append("source_id = :sid")
                params["sid"] = str(source_id)
            if external_id is not None:
                where.append("external_id = :eid")
                params["eid"] = str(external_id)[:512]
            if document_id is not None:
                where.append("document_id = :did")
                params["did"] = str(document_id)
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM knowledge_ingestion_manifests WHERE "  # noqa: S608
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY updated_at DESC LIMIT 1"
                    ),
                    params,
                )
            ).fetchone()
            return _manifest_from_row(row) if row is not None else None
        finally:
            await session.close()

    async def list_manifests(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        limit: int = 100,
    ) -> list[SourceIngestionManifest]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid"]
            params: dict = {
                "oid": str(organization_id),
                "limit": max(1, min(int(limit), 500)),
            }
            if source_id is not None:
                where.append("source_id = :sid")
                params["sid"] = str(source_id)
            rows = (
                await session.execute(
                    text(
                        "SELECT * FROM knowledge_ingestion_manifests WHERE "  # noqa: S608
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [_manifest_from_row(row) for row in rows]
        finally:
            await session.close()

    async def coverage_summary(
        self, organization_id: UUID, *, source_id: UUID | None = None
    ) -> dict:
        """Resumen agregado para «¿ZENT procesó toda esta fuente?»."""
        manifests = await self.list_manifests(
            organization_id, source_id=source_id, limit=500
        )
        if not manifests:
            return {
                "documents_total": 0,
                "documents_complete": 0,
                "documents_partial": 0,
                "documents_failed": 0,
                "min_coverage_ratio": None,
                "coverage_ratio": None,
            }
        complete = sum(1 for item in manifests if item.pipeline_complete)
        failed = sum(
            1
            for item in manifests
            if item.stage("parsing") in {"failed", "quarantined"}
            or item.stage("indexing") in {"failed", "quarantined"}
        )
        ratios = [item.coverage_ratio for item in manifests]
        return {
            "documents_total": len(manifests),
            "documents_complete": complete,
            "documents_partial": len(manifests) - complete - failed,
            "documents_failed": failed,
            "min_coverage_ratio": round(min(ratios), 4),
            "coverage_ratio": round(sum(ratios) / len(ratios), 4),
        }

    # ------------------------------------------------------------------
    # Ventanas semánticas
    # ------------------------------------------------------------------
    async def save_window_plan(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None,
        workspace_id: UUID | None,
        document_id: UUID,
        plan: SemanticWindowPlan,
    ) -> None:
        """Reemplaza el plan del documento (idempotente por documento)."""
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_windows "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                {"oid": str(organization_id), "did": str(document_id)},
            )
            for window in plan.windows:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_semantic_windows (
                            id, organization_id, workspace_id, source_id,
                            document_id, window_index, unit_start, unit_end,
                            first_block_id, last_block_id, estimated_tokens,
                            target_tokens, hard_limit_tokens, preserved_units,
                            split_units, status, fingerprint, plan_version,
                            metadata, created_at, updated_at
                        ) VALUES (
                            gen_random_uuid(), :organization_id, :workspace_id,
                            :source_id, :document_id, :window_index, :unit_start,
                            :unit_end, :first_block_id, :last_block_id,
                            :estimated_tokens, :target_tokens, :hard_limit_tokens,
                            :preserved_units, :split_units, :status, :fingerprint,
                            :plan_version, CAST(:metadata AS jsonb), now(), now()
                        )
                        ON CONFLICT (organization_id, document_id, window_index)
                        DO UPDATE SET
                            unit_start = EXCLUDED.unit_start,
                            unit_end = EXCLUDED.unit_end,
                            first_block_id = EXCLUDED.first_block_id,
                            last_block_id = EXCLUDED.last_block_id,
                            estimated_tokens = EXCLUDED.estimated_tokens,
                            target_tokens = EXCLUDED.target_tokens,
                            hard_limit_tokens = EXCLUDED.hard_limit_tokens,
                            preserved_units = EXCLUDED.preserved_units,
                            split_units = EXCLUDED.split_units,
                            status = EXCLUDED.status,
                            fingerprint = EXCLUDED.fingerprint,
                            plan_version = EXCLUDED.plan_version,
                            metadata = EXCLUDED.metadata,
                            updated_at = now()
                        """
                    ),
                    self._window_params(
                        organization_id,
                        source_id=source_id,
                        workspace_id=workspace_id,
                        document_id=document_id,
                        plan=plan,
                        window=window,
                    ),
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @staticmethod
    def _window_params(
        organization_id: UUID,
        *,
        source_id: UUID | None,
        workspace_id: UUID | None,
        document_id: UUID,
        plan: SemanticWindowPlan,
        window: SemanticWindowSpec,
    ) -> dict:
        return {
            "organization_id": str(organization_id),
            "workspace_id": str(workspace_id) if workspace_id else None,
            "source_id": str(source_id) if source_id else None,
            "document_id": str(document_id),
            "window_index": int(window.window_index),
            "unit_start": int(window.unit_start),
            "unit_end": int(window.unit_end),
            "first_block_id": str(window.first_block_id)
            if window.first_block_id
            else None,
            "last_block_id": str(window.last_block_id) if window.last_block_id else None,
            "estimated_tokens": int(window.estimated_tokens),
            "target_tokens": int(window.target_tokens),
            "hard_limit_tokens": int(window.hard_limit_tokens),
            "preserved_units": int(window.preserved_units),
            "split_units": int(window.split_units),
            "status": window.status,
            "fingerprint": plan.fingerprint,
            "plan_version": plan.version,
            "metadata": json.dumps(
                {
                    "model": plan.model,
                    "model_source": plan.model_source,
                    "profile": plan.profile,
                    "reason": window.reason,
                    "char_start": window.char_start,
                    "char_end": window.char_end,
                    "notes": plan.notes,
                },
                default=str,
            ),
        }

    async def list_windows(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        limit: int = 2000,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT window_index, unit_start, unit_end, first_block_id, "
                        "last_block_id, estimated_tokens, target_tokens, "
                        "hard_limit_tokens, preserved_units, split_units, status, "
                        "fingerprint, plan_version, metadata, created_at, updated_at "
                        "FROM knowledge_semantic_windows "
                        "WHERE organization_id = :oid AND document_id = :did "
                        "ORDER BY window_index ASC LIMIT :limit"
                    ),
                    {
                        "oid": str(organization_id),
                        "did": str(document_id),
                        "limit": max(1, min(int(limit), 5000)),
                    },
                )
            ).fetchall()
            return [
                {
                    "window_index": int(row.window_index),
                    "unit_start": int(row.unit_start),
                    "unit_end": int(row.unit_end),
                    "first_block_id": str(row.first_block_id)
                    if row.first_block_id
                    else None,
                    "last_block_id": str(row.last_block_id)
                    if row.last_block_id
                    else None,
                    "estimated_tokens": int(row.estimated_tokens or 0),
                    "target_tokens": int(row.target_tokens or 0),
                    "hard_limit_tokens": int(row.hard_limit_tokens or 0),
                    "preserved_units": int(row.preserved_units or 0),
                    "split_units": int(row.split_units or 0),
                    "status": row.status,
                    "fingerprint": row.fingerprint,
                    "plan_version": row.plan_version,
                    "metadata": row.metadata or {},
                    "created_at": row.created_at.isoformat()
                    if row.created_at
                    else None,
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
                for row in rows
            ]
        finally:
            await session.close()


    # ------------------------------------------------------------------
    # Fase 3: resultados por ventana + estado semántico
    # ------------------------------------------------------------------
    async def save_window_result(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID,
        result: SemanticWindowResult,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_semantic_window_results (
                        id, organization_id, workspace_id, source_id, document_id,
                        window_index, status, fingerprint, carry_fingerprint,
                        confidence, quality, items, item_counts, tokens_used,
                        llm_calls, error, processed_at, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :organization_id, :workspace_id, :source_id,
                        :document_id, :window_index, :status, :fingerprint,
                        :carry_fingerprint, :confidence, CAST(:quality AS jsonb),
                        CAST(:items AS jsonb), CAST(:item_counts AS jsonb),
                        :tokens_used, :llm_calls, :error, now(), now(), now()
                    )
                    ON CONFLICT (organization_id, document_id, window_index)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        fingerprint = EXCLUDED.fingerprint,
                        carry_fingerprint = EXCLUDED.carry_fingerprint,
                        confidence = EXCLUDED.confidence,
                        quality = EXCLUDED.quality,
                        items = EXCLUDED.items,
                        item_counts = EXCLUDED.item_counts,
                        tokens_used = EXCLUDED.tokens_used,
                        llm_calls = EXCLUDED.llm_calls,
                        error = EXCLUDED.error,
                        processed_at = now(),
                        updated_at = now()
                    """
                ),
                {
                    "organization_id": str(organization_id),
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "source_id": str(source_id) if source_id else None,
                    "document_id": str(document_id),
                    "window_index": int(result.window_index),
                    "status": result.status,
                    "fingerprint": result.fingerprint[:64],
                    "carry_fingerprint": result.carry_fingerprint[:64],
                    "confidence": _mean_confidence(result),
                    "quality": json.dumps(result.quality or {}, default=str),
                    "items": json.dumps(
                        [item.to_dict() for item in result.items], default=str
                    ),
                    "item_counts": json.dumps(result.counts, default=str),
                    "tokens_used": int(result.tokens_estimated),
                    "llm_calls": int(result.quality.get("llm_calls") or 0),
                    "error": (result.error or "")[:1000] or None,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_window_result(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        window_index: int,
    ) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT organization_id, workspace_id, source_id, document_id, "
                        "window_index, status, fingerprint, carry_fingerprint, "
                        "confidence, quality, items, item_counts, tokens_used, "
                        "llm_calls, error, processed_at, updated_at "
                        "FROM knowledge_semantic_window_results "
                        "WHERE organization_id = :oid AND document_id = :did "
                        "AND window_index = :idx"
                    ),
                    {
                        "oid": str(organization_id),
                        "did": str(document_id),
                        "idx": int(window_index),
                    },
                )
            ).fetchone()
            if row is None:
                return None
            return _result_row(row, include_items=True)
        finally:
            await session.close()

    async def list_window_results(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        limit: int = 2000,
        include_items: bool = False,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT organization_id, workspace_id, source_id, document_id, "
                        "window_index, status, fingerprint, carry_fingerprint, "
                        "confidence, quality, items, item_counts, tokens_used, "
                        "llm_calls, error, processed_at, updated_at "
                        "FROM knowledge_semantic_window_results "
                        "WHERE organization_id = :oid AND document_id = :did "
                        "ORDER BY window_index ASC LIMIT :limit"
                    ),
                    {
                        "oid": str(organization_id),
                        "did": str(document_id),
                        "limit": max(1, min(int(limit), 5000)),
                    },
                )
            ).fetchall()
            return [_result_row(row, include_items=include_items) for row in rows]
        finally:
            await session.close()

    async def save_state(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID,
        state: SemanticState,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_semantic_states (
                        id, organization_id, workspace_id, source_id, document_id,
                        window_index, fingerprint, state, stats, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :organization_id, :workspace_id, :source_id,
                        :document_id, :window_index, :fingerprint,
                        CAST(:state AS jsonb), CAST(:stats AS jsonb), now(), now()
                    )
                    ON CONFLICT (organization_id, document_id, window_index)
                    DO UPDATE SET
                        fingerprint = EXCLUDED.fingerprint,
                        state = EXCLUDED.state,
                        stats = EXCLUDED.stats,
                        updated_at = now()
                    """
                ),
                {
                    "organization_id": str(organization_id),
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "source_id": str(source_id) if source_id else None,
                    "document_id": str(document_id),
                    "window_index": int(state.window_index),
                    "fingerprint": state.fingerprint[:64],
                    "state": json.dumps(state.to_dict(), default=str),
                    "stats": json.dumps(state.stats or {}, default=str),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_state(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        window_index: int,
    ) -> SemanticState | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT window_index, fingerprint, state, stats, updated_at "
                        "FROM knowledge_semantic_states "
                        "WHERE organization_id = :oid AND document_id = :did "
                        "AND window_index = :idx"
                    ),
                    {
                        "oid": str(organization_id),
                        "did": str(document_id),
                        "idx": int(window_index),
                    },
                )
            ).fetchone()
            return _state_from_row(row) if row is not None else None
        finally:
            await session.close()

    async def latest_state(
        self, organization_id: UUID, *, document_id: UUID
    ) -> SemanticState | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT window_index, fingerprint, state, stats, updated_at "
                        "FROM knowledge_semantic_states "
                        "WHERE organization_id = :oid AND document_id = :did "
                        "ORDER BY window_index DESC LIMIT 1"
                    ),
                    {"oid": str(organization_id), "did": str(document_id)},
                )
            ).fetchone()
            return _state_from_row(row) if row is not None else None
        finally:
            await session.close()

    async def update_window_status(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        window_index: int,
        status: str,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE knowledge_semantic_windows SET status = :status, "
                    "updated_at = now() WHERE organization_id = :oid "
                    "AND document_id = :did AND window_index = :idx"
                ),
                {
                    "status": str(status)[:20],
                    "oid": str(organization_id),
                    "did": str(document_id),
                    "idx": int(window_index),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_window_artifacts(
        self, organization_id: UUID, *, document_id: UUID
    ) -> None:
        """Reset de resultados/estados/threads/stitch/regiones/global/fabric."""
        session = await get_async_session()
        try:
            params = {"oid": str(organization_id), "did": str(document_id)}
            await session.execute(
                text(
                    "DELETE FROM knowledge_fabric_identities "
                    "WHERE organization_id = :oid AND (left_document_id = :did "
                    "OR right_document_id = :did)"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_fabric_edges "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_fabric_nodes "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_global_models "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_regional_models "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_relations "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_units "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_threads "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_states "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_window_results "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "UPDATE knowledge_semantic_windows SET status = 'planned', "
                    "updated_at = now() WHERE organization_id = :oid "
                    "AND document_id = :did"
                ),
                params,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


    # ------------------------------------------------------------------
    # Fase 4: threads semánticos durables
    # ------------------------------------------------------------------
    async def save_threads(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID,
        threads: list[SemanticThread],
    ) -> None:
        if not threads:
            return
        session = await get_async_session()
        try:
            for thread in threads:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_semantic_threads (
                            id, organization_id, workspace_id, source_id,
                            document_id, thread_key, thread_type, status,
                            target_hint, target_kind, scope, source_units,
                            source_windows, opened_at_window, last_seen_window,
                            resolved_at_window, resolved_by_unit, confidence,
                            candidates, evidence, history, version,
                            created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :thread_key, :thread_type, :status,
                            :target_hint, :target_kind, :scope,
                            CAST(:source_units AS jsonb), CAST(:source_windows AS jsonb),
                            :opened_at_window, :last_seen_window,
                            :resolved_at_window, :resolved_by_unit, :confidence,
                            CAST(:candidates AS jsonb), CAST(:evidence AS jsonb),
                            CAST(:history AS jsonb), :version, now(), now()
                        )
                        ON CONFLICT (organization_id, document_id, thread_key)
                        DO UPDATE SET
                            thread_type = EXCLUDED.thread_type,
                            status = EXCLUDED.status,
                            target_hint = EXCLUDED.target_hint,
                            target_kind = EXCLUDED.target_kind,
                            scope = EXCLUDED.scope,
                            source_units = EXCLUDED.source_units,
                            source_windows = EXCLUDED.source_windows,
                            last_seen_window = EXCLUDED.last_seen_window,
                            resolved_at_window = EXCLUDED.resolved_at_window,
                            resolved_by_unit = EXCLUDED.resolved_by_unit,
                            confidence = EXCLUDED.confidence,
                            candidates = EXCLUDED.candidates,
                            evidence = EXCLUDED.evidence,
                            history = EXCLUDED.history,
                            version = EXCLUDED.version,
                            updated_at = now()
                        """
                    ),
                    {
                        "id": str(thread.id),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id),
                        "thread_key": thread.thread_key[:200],
                        "thread_type": thread.thread_type[:30],
                        "status": thread.status[:20],
                        "target_hint": thread.target_hint[:512],
                        "target_kind": (thread.target_kind or "")[:40] or None,
                        "scope": (thread.scope or "")[:200] or None,
                        "source_units": json.dumps(list(thread.source_units), default=str),
                        "source_windows": json.dumps(
                            list(thread.source_windows), default=str
                        ),
                        "opened_at_window": int(thread.opened_at_window),
                        "last_seen_window": int(thread.last_seen_window),
                        "resolved_at_window": thread.resolved_at_window,
                        "resolved_by_unit": thread.resolved_by_unit,
                        "confidence": float(thread.confidence),
                        "candidates": json.dumps(list(thread.candidates), default=str),
                        "evidence": json.dumps(dict(thread.evidence), default=str),
                        "history": json.dumps(list(thread.history), default=str),
                        "version": thread.version,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_threads(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        status: str | None = None,
        thread_type: str | None = None,
        limit: int = 5000,
    ) -> list[SemanticThread]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid", "document_id = :did"]
            params: dict = {
                "oid": str(organization_id),
                "did": str(document_id),
                "limit": max(1, min(int(limit), 10000)),
            }
            if status:
                where.append("status = :status")
                params["status"] = str(status)[:20]
            if thread_type:
                where.append("thread_type = :ttype")
                params["ttype"] = str(thread_type)[:30]
            rows = (
                await session.execute(
                    text(
                        "SELECT * FROM knowledge_semantic_threads WHERE "  # noqa: S608
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY opened_at_window ASC, thread_key ASC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [_thread_from_row(row) for row in rows]
        finally:
            await session.close()


    # ------------------------------------------------------------------
    # Fase 5: unidades + relaciones del stitcher
    # ------------------------------------------------------------------
    async def replace_stitch(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID,
        units: list[StitchedUnit],
        relations: list[StitchRelation],
    ) -> None:
        """Reemplaza el grafo semántico del documento (idempotente por corrida)."""
        session = await get_async_session()
        try:
            params = {"oid": str(organization_id), "did": str(document_id)}
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_relations "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_semantic_units "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            for unit in units:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_semantic_units (
                            id, organization_id, workspace_id, source_id,
                            document_id, unit_key, unit_kind, label, text,
                            confidence, source_windows, block_ids, merged_from,
                            attributes, version, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :unit_key, :unit_kind, :label, :text,
                            :confidence, CAST(:source_windows AS jsonb),
                            CAST(:block_ids AS jsonb), CAST(:merged_from AS jsonb),
                            CAST(:attributes AS jsonb), :version, now(), now()
                        )
                        """
                    ),
                    {
                        "id": str(unit.id),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id),
                        "unit_key": unit.unit_key[:300],
                        "unit_kind": unit.unit_kind[:40],
                        "label": unit.label[:300],
                        "text": unit.text[:4000],
                        "confidence": float(unit.confidence),
                        "source_windows": json.dumps(
                            list(unit.source_windows), default=str
                        ),
                        "block_ids": json.dumps(list(unit.block_ids), default=str),
                        "merged_from": json.dumps(
                            list(unit.merged_from), default=str
                        ),
                        "attributes": json.dumps(dict(unit.attributes), default=str),
                        "version": unit.version,
                    },
                )
            for relation in relations:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_semantic_relations (
                            id, organization_id, workspace_id, source_id,
                            document_id, relation_key, relation_type,
                            subject_key, subject_kind, subject_label,
                            object_key, object_kind, object_label,
                            confidence, method, evidence, windows, attributes,
                            version, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :relation_key, :relation_type,
                            :subject_key, :subject_kind, :subject_label,
                            :object_key, :object_kind, :object_label,
                            :confidence, :method, CAST(:evidence AS jsonb),
                            CAST(:windows AS jsonb), CAST(:attributes AS jsonb),
                            :version, now(), now()
                        )
                        """
                    ),
                    {
                        "id": str(relation.id),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id),
                        "relation_key": relation.relation_key[:700],
                        "relation_type": relation.relation_type[:40],
                        "subject_key": relation.subject_key[:300],
                        "subject_kind": relation.subject_kind[:40],
                        "subject_label": relation.subject_label[:300],
                        "object_key": relation.object_key[:300],
                        "object_kind": relation.object_kind[:40],
                        "object_label": relation.object_label[:300],
                        "confidence": float(relation.confidence),
                        "method": relation.method[:40],
                        "evidence": json.dumps(list(relation.evidence), default=str),
                        "windows": json.dumps(list(relation.windows), default=str),
                        "attributes": json.dumps(
                            dict(relation.attributes), default=str
                        ),
                        "version": relation.version,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_units(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        unit_kind: str | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid", "document_id = :did"]
            params: dict = {
                "oid": str(organization_id),
                "did": str(document_id),
                "limit": max(1, min(int(limit), 20000)),
            }
            if unit_kind:
                where.append("unit_kind = :kind")
                params["kind"] = str(unit_kind)[:40]
            rows = (
                await session.execute(
                    text(
                        "SELECT id, unit_key, unit_kind, label, text, confidence, "  # noqa: S608
                        "source_windows, block_ids, merged_from, attributes, version, "
                        "updated_at FROM knowledge_semantic_units WHERE "
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY unit_kind ASC, unit_key ASC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "unit_key": row.unit_key,
                    "unit_kind": row.unit_kind,
                    "label": row.label,
                    "text": row.text,
                    "confidence": row.confidence,
                    "source_windows": row.source_windows or [],
                    "block_ids": row.block_ids or [],
                    "merged_from": row.merged_from or [],
                    "attributes": row.attributes or {},
                    "version": row.version,
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
                for row in rows
            ]
        finally:
            await session.close()

    async def list_relations(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        relation_type: str | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid", "document_id = :did"]
            params: dict = {
                "oid": str(organization_id),
                "did": str(document_id),
                "limit": max(1, min(int(limit), 50000)),
            }
            if relation_type:
                where.append("relation_type = :rtype")
                params["rtype"] = str(relation_type)[:40]
            rows = (
                await session.execute(
                    text(
                        "SELECT id, relation_key, relation_type, subject_key, "  # noqa: S608
                        "subject_kind, subject_label, object_key, object_kind, "
                        "object_label, confidence, method, evidence, windows, "
                        "attributes, version, updated_at "
                        "FROM knowledge_semantic_relations WHERE "
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY relation_type ASC, relation_key ASC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "relation_key": row.relation_key,
                    "relation_type": row.relation_type,
                    "subject_key": row.subject_key,
                    "subject_kind": row.subject_kind,
                    "subject_label": row.subject_label,
                    "object_key": row.object_key,
                    "object_kind": row.object_kind,
                    "object_label": row.object_label,
                    "confidence": row.confidence,
                    "method": row.method,
                    "evidence": row.evidence or [],
                    "windows": row.windows or [],
                    "attributes": row.attributes or {},
                    "version": row.version,
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
                for row in rows
            ]
        finally:
            await session.close()


    # ------------------------------------------------------------------
    # Fase 6: modelos regionales
    # ------------------------------------------------------------------
    async def replace_regional_models(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID,
        models: list[RegionalSemanticModel],
    ) -> None:
        """Reemplaza los modelos regionales del documento (idempotente)."""
        session = await get_async_session()
        try:
            params = {"oid": str(organization_id), "did": str(document_id)}
            await session.execute(
                text(
                    "DELETE FROM knowledge_regional_models "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            for model in models:
                payload = model.to_dict()
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_regional_models (
                            id, organization_id, workspace_id, source_id,
                            document_id, region_id, label, window_start,
                            window_end, window_indexes, model, stats,
                            fingerprint, version, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :region_id, :label, :window_start,
                            :window_end, CAST(:window_indexes AS jsonb),
                            CAST(:model AS jsonb), CAST(:stats AS jsonb),
                            :fingerprint, :version, now(), now()
                        )
                        """
                    ),
                    {
                        "id": str(model.id),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id),
                        "region_id": model.region_id[:300],
                        "label": model.label[:300],
                        "window_start": int(model.window_start),
                        "window_end": int(model.window_end),
                        "window_indexes": json.dumps(
                            list(model.window_indexes), default=str
                        ),
                        "model": json.dumps(payload, default=str),
                        "stats": json.dumps(dict(model.stats), default=str),
                        "fingerprint": model.fingerprint[:64],
                        "version": model.version,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_regional_models(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        limit: int = 500,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, region_id, label, window_start, window_end, "
                        "window_indexes, model, stats, fingerprint, version, "
                        "updated_at FROM knowledge_regional_models "
                        "WHERE organization_id = :oid AND document_id = :did "
                        "ORDER BY window_start ASC, region_id ASC LIMIT :limit"
                    ),
                    {
                        "oid": str(organization_id),
                        "did": str(document_id),
                        "limit": max(1, min(int(limit), 5000)),
                    },
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "region_id": row.region_id,
                    "label": row.label,
                    "window_start": int(row.window_start or 0),
                    "window_end": int(row.window_end or 0),
                    "window_indexes": row.window_indexes or [],
                    "model": row.model or {},
                    "stats": row.stats or {},
                    "fingerprint": row.fingerprint,
                    "version": row.version,
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
                for row in rows
            ]
        finally:
            await session.close()


    # ------------------------------------------------------------------
    # Fase 7: modelo global
    # ------------------------------------------------------------------
    async def replace_global_model(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID,
        model: GlobalSemanticModel,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_global_models (
                        id, organization_id, workspace_id, source_id,
                        document_id, model, stats, fingerprint, version,
                        created_at, updated_at
                    ) VALUES (
                        :id, :organization_id, :workspace_id, :source_id,
                        :document_id, CAST(:model AS jsonb), CAST(:stats AS jsonb),
                        :fingerprint, :version, now(), now()
                    )
                    ON CONFLICT (organization_id, document_id) DO UPDATE SET
                        model = EXCLUDED.model,
                        stats = EXCLUDED.stats,
                        fingerprint = EXCLUDED.fingerprint,
                        version = EXCLUDED.version,
                        updated_at = now()
                    """
                ),
                {
                    "id": str(model.id),
                    "organization_id": str(organization_id),
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "source_id": str(source_id) if source_id else None,
                    "document_id": str(document_id),
                    "model": json.dumps(model.to_dict(), default=str),
                    "stats": json.dumps(dict(model.stats), default=str),
                    "fingerprint": model.fingerprint[:64],
                    "version": model.version,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_global_model(
        self, organization_id: UUID, *, document_id: UUID
    ) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, model, stats, fingerprint, version, updated_at "
                        "FROM knowledge_global_models "
                        "WHERE organization_id = :oid AND document_id = :did"
                    ),
                    {"oid": str(organization_id), "did": str(document_id)},
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "id": str(row.id),
                "model": row.model or {},
                "stats": row.stats or {},
                "fingerprint": row.fingerprint,
                "version": row.version,
                "updated_at": row.updated_at.isoformat()
                if row.updated_at
                else None,
            }
        finally:
            await session.close()


    # ------------------------------------------------------------------
    # Fase 8: Semantic Fabric (nodos, aristas, identidad cross-source)
    # ------------------------------------------------------------------
    async def replace_fabric(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None,
        source_id: UUID | None,
        document_id: UUID,
        nodes: list[FabricNode],
        edges: list[FabricEdge],
    ) -> None:
        """Reemplaza nodos/aristas del documento e invalida identidades stale."""
        session = await get_async_session()
        try:
            params = {"oid": str(organization_id), "did": str(document_id)}
            await session.execute(
                text(
                    "DELETE FROM knowledge_fabric_identities "
                    "WHERE organization_id = :oid AND (left_document_id = :did "
                    "OR right_document_id = :did)"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_fabric_edges "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            await session.execute(
                text(
                    "DELETE FROM knowledge_fabric_nodes "
                    "WHERE organization_id = :oid AND document_id = :did"
                ),
                params,
            )
            for node in nodes:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_fabric_nodes (
                            id, organization_id, workspace_id, source_id,
                            document_id, node_key, node_type, label, text,
                            confidence, scope, unit_key, block_ids, windows,
                            attributes, version, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :node_key, :node_type, :label, :text,
                            :confidence, :scope, :unit_key,
                            CAST(:block_ids AS jsonb), CAST(:windows AS jsonb),
                            CAST(:attributes AS jsonb), :version, now(), now()
                        )
                        """
                    ),
                    {
                        "id": str(node.id),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id),
                        "node_key": node.node_key[:400],
                        "node_type": node.node_type[:30],
                        "label": node.label[:300],
                        "text": node.text[:4000],
                        "confidence": float(node.confidence),
                        "scope": node.scope[:30],
                        "unit_key": node.unit_key[:300],
                        "block_ids": json.dumps(list(node.block_ids), default=str),
                        "windows": json.dumps(list(node.windows), default=str),
                        "attributes": json.dumps(dict(node.attributes), default=str),
                        "version": node.version,
                    },
                )
            for edge in edges:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_fabric_edges (
                            id, organization_id, workspace_id, source_id,
                            document_id, edge_key, relation_type, subject_id,
                            object_id, subject_key, object_key, confidence,
                            method, evidence, windows, attributes, version,
                            created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :source_id,
                            :document_id, :edge_key, :relation_type, :subject_id,
                            :object_id, :subject_key, :object_key, :confidence,
                            :method, CAST(:evidence AS jsonb), CAST(:windows AS jsonb),
                            CAST(:attributes AS jsonb), :version, now(), now()
                        )
                        """
                    ),
                    {
                        "id": str(edge.id),
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "source_id": str(source_id) if source_id else None,
                        "document_id": str(document_id),
                        "edge_key": edge.edge_key[:800],
                        "relation_type": edge.relation_type[:40],
                        "subject_id": str(edge.subject_id),
                        "object_id": str(edge.object_id),
                        "subject_key": edge.subject_key[:400],
                        "object_key": edge.object_key[:400],
                        "confidence": float(edge.confidence),
                        "method": edge.method[:40],
                        "evidence": json.dumps(list(edge.evidence), default=str),
                        "windows": json.dumps(list(edge.windows), default=str),
                        "attributes": json.dumps(dict(edge.attributes), default=str),
                        "version": edge.version,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def save_identity_candidates(
        self,
        organization_id: UUID,
        *,
        candidates: list[IdentityCandidate],
    ) -> None:
        if not candidates:
            return
        session = await get_async_session()
        try:
            for candidate in candidates:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_fabric_identities (
                            id, organization_id, left_node_id, right_node_id,
                            left_key, right_key, left_label, right_label,
                            left_document_id, right_document_id, left_source_id,
                            right_source_id, identity_status, confidence, reason,
                            evidence, temporal_compatible, scope_compatible,
                            version, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :left_node_id, :right_node_id,
                            :left_key, :right_key, :left_label, :right_label,
                            :left_document_id, :right_document_id, :left_source_id,
                            :right_source_id, :identity_status, :confidence, :reason,
                            CAST(:evidence AS jsonb), :temporal_compatible,
                            :scope_compatible, :version, now(), now()
                        )
                        ON CONFLICT (organization_id, left_node_id, right_node_id)
                        DO UPDATE SET
                            identity_status = EXCLUDED.identity_status,
                            confidence = EXCLUDED.confidence,
                            reason = EXCLUDED.reason,
                            evidence = EXCLUDED.evidence,
                            temporal_compatible = EXCLUDED.temporal_compatible,
                            scope_compatible = EXCLUDED.scope_compatible,
                            version = EXCLUDED.version,
                            updated_at = now()
                        """
                    ),
                    {
                        "id": str(candidate.id),
                        "organization_id": str(organization_id),
                        "left_node_id": str(candidate.left_node_id),
                        "right_node_id": str(candidate.right_node_id),
                        "left_key": candidate.left_key[:400],
                        "right_key": candidate.right_key[:400],
                        "left_label": candidate.left_label[:300],
                        "right_label": candidate.right_label[:300],
                        "left_document_id": str(candidate.left_document_id)
                        if candidate.left_document_id
                        else None,
                        "right_document_id": str(candidate.right_document_id)
                        if candidate.right_document_id
                        else None,
                        "left_source_id": str(candidate.left_source_id)
                        if candidate.left_source_id
                        else None,
                        "right_source_id": str(candidate.right_source_id)
                        if candidate.right_source_id
                        else None,
                        "identity_status": candidate.identity_status[:30],
                        "confidence": float(candidate.confidence),
                        "reason": candidate.reason[:300],
                        "evidence": json.dumps(candidate.evidence or {}, default=str),
                        "temporal_compatible": bool(candidate.temporal_compatible),
                        "scope_compatible": bool(candidate.scope_compatible),
                        "version": candidate.version,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_modeled_document_ids(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None = None,
        limit: int = 8,
    ) -> list[UUID]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid"]
            params: dict = {
                "oid": str(organization_id),
                "limit": max(1, min(int(limit), 50)),
            }
            if workspace_id is not None:
                where.append("workspace_id = :ws")
                params["ws"] = str(workspace_id)
            rows = (
                await session.execute(
                    text(
                        "SELECT document_id FROM knowledge_global_models WHERE "  # noqa: S608
                        + " AND ".join(where)
                        + " ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [row.document_id for row in rows]
        finally:
            await session.close()

    async def list_fabric_nodes(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        node_type: str | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid", "document_id = :did"]
            params: dict = {
                "oid": str(organization_id),
                "did": str(document_id),
                "limit": max(1, min(int(limit), 50000)),
            }
            if node_type:
                where.append("node_type = :ntype")
                params["ntype"] = str(node_type)[:30]
            rows = (
                await session.execute(
                    text(
                        "SELECT id, node_key, node_type, label, text, confidence, "  # noqa: S608
                        "scope, unit_key, block_ids, windows, attributes, version, "
                        "updated_at FROM knowledge_fabric_nodes WHERE "
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY node_type ASC, node_key ASC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "node_key": row.node_key,
                    "node_type": row.node_type,
                    "label": row.label,
                    "text": row.text,
                    "confidence": row.confidence,
                    "scope": row.scope,
                    "unit_key": row.unit_key,
                    "block_ids": row.block_ids or [],
                    "windows": row.windows or [],
                    "attributes": row.attributes or {},
                    "version": row.version,
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
                for row in rows
            ]
        finally:
            await session.close()

    async def list_fabric_edges(
        self,
        organization_id: UUID,
        *,
        document_id: UUID,
        relation_type: str | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid", "document_id = :did"]
            params: dict = {
                "oid": str(organization_id),
                "did": str(document_id),
                "limit": max(1, min(int(limit), 100000)),
            }
            if relation_type:
                where.append("relation_type = :rtype")
                params["rtype"] = str(relation_type)[:40]
            rows = (
                await session.execute(
                    text(
                        "SELECT id, edge_key, relation_type, subject_id, object_id, "  # noqa: S608
                        "subject_key, object_key, confidence, method, evidence, "
                        "windows, attributes, version, updated_at "
                        "FROM knowledge_fabric_edges WHERE "
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY relation_type ASC, edge_key ASC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "edge_key": row.edge_key,
                    "relation_type": row.relation_type,
                    "subject_id": str(row.subject_id),
                    "object_id": str(row.object_id),
                    "subject_key": row.subject_key,
                    "object_key": row.object_key,
                    "confidence": row.confidence,
                    "method": row.method,
                    "evidence": row.evidence or [],
                    "windows": row.windows or [],
                    "attributes": row.attributes or {},
                    "version": row.version,
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
                for row in rows
            ]
        finally:
            await session.close()

    async def list_identity_candidates(
        self,
        organization_id: UUID,
        *,
        document_id: UUID | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid"]
            params: dict = {
                "oid": str(organization_id),
                "limit": max(1, min(int(limit), 5000)),
            }
            if document_id is not None:
                where.append(
                    "(left_document_id = :did OR right_document_id = :did)"
                )
                params["did"] = str(document_id)
            if status:
                where.append("identity_status = :status")
                params["status"] = str(status)[:30]
            rows = (
                await session.execute(
                    text(
                        "SELECT * FROM knowledge_fabric_identities WHERE "  # noqa: S608
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY confidence DESC, updated_at DESC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "identity_status": row.identity_status,
                    "left_node_id": str(row.left_node_id),
                    "right_node_id": str(row.right_node_id),
                    "left_key": row.left_key,
                    "right_key": row.right_key,
                    "left_label": row.left_label,
                    "right_label": row.right_label,
                    "left_document_id": str(row.left_document_id)
                    if row.left_document_id
                    else None,
                    "right_document_id": str(row.right_document_id)
                    if row.right_document_id
                    else None,
                    "confidence": row.confidence,
                    "reason": row.reason,
                    "evidence": row.evidence or {},
                    "temporal_compatible": bool(row.temporal_compatible),
                    "scope_compatible": bool(row.scope_compatible),
                    "version": row.version,
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
                for row in rows
            ]
        finally:
            await session.close()

    async def find_fabric_nodes_by_labels(
        self,
        organization_id: UUID,
        labels: list[str],
        *,
        exclude_document_id: UUID | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Lookup cross-source por label normalizado (para identidad)."""
        normalized = sorted(
            {
                str(label).strip().casefold()
                for label in labels
                if str(label or "").strip()
            }
        )[:500]
        if not normalized:
            return []
        session = await get_async_session()
        try:
            where = [
                "organization_id = :oid",
                "lower(label) IN :labels",
                "node_type <> 'Evidence'",
            ]
            params: dict = {
                "oid": str(organization_id),
                "labels": normalized,
                "limit": max(1, min(int(limit), 5000)),
            }
            if exclude_document_id is not None:
                where.append("document_id <> :exclude")
                params["exclude"] = str(exclude_document_id)
            stmt = text(
                "SELECT id, document_id, source_id, node_key, node_type, label, "  # noqa: S608
                "unit_key, block_ids, windows, attributes FROM knowledge_fabric_nodes "
                "WHERE " + " AND ".join(where) + " LIMIT :limit"
            ).bindparams(bindparam("labels", expanding=True))
            rows = (await session.execute(stmt, params)).fetchall()
            return [
                {
                    "id": str(row.id),
                    "document_id": str(row.document_id),
                    "source_id": str(row.source_id) if row.source_id else None,
                    "node_key": row.node_key,
                    "node_type": row.node_type,
                    "label": row.label,
                    "unit_key": row.unit_key,
                    "block_ids": row.block_ids or [],
                    "windows": row.windows or [],
                    "attributes": row.attributes or {},
                }
                for row in rows
            ]
        finally:
            await session.close()


    async def list_fabric_edges_for_nodes(
        self,
        organization_id: UUID,
        node_ids: list[str],
        *,
        limit: int = 2000,
    ) -> list[dict]:
        """Aristas del fabric que tocan los nodos dados (spreading activation)."""
        ids = []
        for value in node_ids or ():
            text_value = str(value or "").strip()
            if text_value and text_value not in ids:
                ids.append(text_value)
        ids = ids[:200]
        if not ids:
            return []
        session = await get_async_session()
        try:
            stmt = text(
                "SELECT e.id, e.edge_key, e.relation_type, e.subject_id, "
                "e.object_id, e.subject_key, e.object_key, e.confidence, "
                "e.windows, e.attributes, e.document_id, "
                "s.label AS subject_label, s.node_type AS subject_kind, "
                "o.label AS object_label, o.node_type AS object_kind "
                "FROM knowledge_fabric_edges e "
                "LEFT JOIN knowledge_fabric_nodes s ON s.id = e.subject_id "
                "LEFT JOIN knowledge_fabric_nodes o ON o.id = e.object_id "
                "WHERE e.organization_id = :oid "
                "AND (e.subject_id IN :ids_a OR e.object_id IN :ids_b) "
                "LIMIT :limit"
            ).bindparams(
                bindparam("ids_a", expanding=True),
                bindparam("ids_b", expanding=True),
            )
            rows = (
                await session.execute(
                    stmt,
                    {
                        "oid": str(organization_id),
                        "ids_a": ids,
                        "ids_b": ids,
                        "limit": max(1, min(int(limit), 20000)),
                    },
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "edge_key": row.edge_key,
                    "relation_type": row.relation_type,
                    "subject_id": str(row.subject_id),
                    "object_id": str(row.object_id),
                    "subject_key": row.subject_key,
                    "object_key": row.object_key,
                    "subject_label": row.subject_label,
                    "subject_kind": row.subject_kind,
                    "object_label": row.object_label,
                    "object_kind": row.object_kind,
                    "confidence": row.confidence,
                    "windows": row.windows or [],
                    "attributes": row.attributes or {},
                    "document_id": str(row.document_id),
                }
                for row in rows
            ]
        finally:
            await session.close()


def _thread_from_row(row) -> SemanticThread:
    return SemanticThread(
        id=UUID(str(row.id)),
        thread_key=str(row.thread_key or ""),
        thread_type=str(row.thread_type or ""),
        status=str(row.status or ""),
        organization_id=UUID(str(row.organization_id)),
        source_id=_optional_uuid(row.source_id),
        workspace_id=_optional_uuid(row.workspace_id),
        document_id=_optional_uuid(row.document_id),
        target_hint=str(row.target_hint or ""),
        target_kind=str(row.target_kind) if row.target_kind else None,
        scope=str(row.scope) if row.scope else None,
        source_units=tuple(str(value) for value in (row.source_units or ())),
        source_windows=tuple(int(value) for value in (row.source_windows or ())),
        opened_at_window=int(row.opened_at_window or 0),
        last_seen_window=int(row.last_seen_window or 0),
        resolved_at_window=(
            int(row.resolved_at_window)
            if row.resolved_at_window is not None
            else None
        ),
        resolved_by_unit=str(row.resolved_by_unit) if row.resolved_by_unit else None,
        confidence=float(row.confidence or 0.0),
        candidates=tuple(row.candidates or ()),
        evidence=dict(row.evidence or {}),
        history=tuple(row.history or ()),
        version=str(row.version or THREAD_VERSION),
    )


def _mean_confidence(result: SemanticWindowResult) -> float | None:
    if not result.items:
        return None
    values = [float(item.confidence) for item in result.items]
    return round(sum(values) / len(values), 4) if values else None


def _result_row(row, *, include_items: bool) -> dict:
    payload = {
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "source_id": str(row.source_id) if row.source_id else None,
        "document_id": str(row.document_id),
        "window_index": int(row.window_index),
        "status": row.status,
        "fingerprint": row.fingerprint,
        "carry_fingerprint": row.carry_fingerprint,
        "confidence": row.confidence,
        "quality": row.quality or {},
        "item_counts": row.item_counts or {},
        "item_count": sum(int(value) for value in (row.item_counts or {}).values()),
        "tokens_used": int(row.tokens_used or 0),
        "llm_calls": int(row.llm_calls or 0),
        "error": row.error,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_items:
        payload["items"] = row.items or []
    return payload


def _state_from_row(row) -> SemanticState:
    data = dict(row.state or {})
    return SemanticState(
        organization_id=UUID(str(data.get("organization_id") or UUID(int=0))),
        source_id=_optional_uuid(data.get("source_id")),
        workspace_id=_optional_uuid(data.get("workspace_id")),
        document_id=_optional_uuid(data.get("document_id")),
        window_index=int(data.get("window_index", row.window_index)),
        version=str(data.get("version") or SEMANTIC_STATE_VERSION),
        active_concepts=tuple(data.get("active_concepts") or ()),
        known_entities=tuple(data.get("known_entities") or ()),
        glossary=tuple(data.get("glossary") or ()),
        symbol_definitions=tuple(data.get("symbol_definitions") or ()),
        active_rules=tuple(data.get("active_rules") or ()),
        unresolved_references=tuple(data.get("unresolved_references") or ()),
        resolved_references=tuple(data.get("resolved_references") or ()),
        open_continuations=tuple(data.get("open_continuations") or ()),
        current_topics=tuple(data.get("current_topics") or ()),
        temporal_context=tuple(data.get("temporal_context") or ()),
        detected_aliases=tuple(data.get("detected_aliases") or ()),
        pending_relationships=tuple(data.get("pending_relationships") or ()),
        conflicts=tuple(data.get("conflicts") or ()),
        stats=dict(data.get("stats") or row.stats or {}),
    )


def _optional_uuid(value) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["PostgresSemanticIngestionStore"]
