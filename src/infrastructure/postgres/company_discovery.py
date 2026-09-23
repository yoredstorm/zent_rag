# =============================================================================
# Company Discovery — Postgres adapter (migración 130)
# =============================================================================
# SQL crudo + sqlalchemy.text(), como el resto del proyecto. Scoping estricto
# por organization_id y límites siempre. El upsert preserva evidencia previa:
# `evidence` y `support` nunca se pisan con menos datos.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.company_discovery import (
    CandidateKind,
    CandidateSupport,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoverySourceKind,
    DiscoveryStage,
    DiscoveryTrigger,
)
from src.core.ports.company_discovery import CompanyDiscoveryRepository
from src.infrastructure.postgres.session import get_async_session

_COLUMNS = (
    "id, organization_id, workspace_id, kind, stage, natural_key, title, summary, "
    "payload, source_kind, source_ref, discovered_by, confidence, "
    "confidence_factors, support, evidence, resolution, reviewed_by, reviewed_at, "
    "materialized_id, first_observed_at, last_observed_at, created_at, updated_at"
)

_RUN_COLUMNS = (
    "id, organization_id, trigger, status, source_kinds, candidates_found, "
    "candidates_new, candidates_updated, promoted, conflicts, metrics, error, "
    "started_at, completed_at, duration_ms, created_at"
)


def _json(value) -> str:
    return json.dumps(value, default=str)


def _row_to_candidate(row) -> DiscoveryCandidate:
    evidence = (
        tuple(DiscoveryEvidence.from_dict(item) for item in row.evidence)
        if isinstance(row.evidence, list)
        else ()
    )
    return DiscoveryCandidate(
        organization_id=row.organization_id,
        kind=CandidateKind(row.kind),
        natural_key=row.natural_key,
        title=row.title or "",
        summary=row.summary or "",
        payload=row.payload if isinstance(row.payload, dict) else {},
        source_kind=DiscoverySourceKind(row.source_kind),
        source_ref=row.source_ref or "",
        discovered_by=row.discovered_by or "",
        stage=DiscoveryStage(row.stage),
        confidence=float(row.confidence or 0.0),
        confidence_factors=(
            row.confidence_factors if isinstance(row.confidence_factors, dict) else {}
        ),
        support=CandidateSupport.from_dict(row.support or {}),
        evidence=evidence,
        resolution=row.resolution if isinstance(row.resolution, dict) else {},
        workspace_id=row.workspace_id,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        materialized_id=row.materialized_id,
        first_observed_at=row.first_observed_at,
        last_observed_at=row.last_observed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        id=row.id,
    )


def _row_to_run(row) -> DiscoveryRun:
    kinds = row.source_kinds if isinstance(row.source_kinds, list) else []
    return DiscoveryRun(
        organization_id=row.organization_id,
        trigger=DiscoveryTrigger(row.trigger),
        status=DiscoveryRunStatus(row.status),
        source_kinds=tuple(DiscoverySourceKind(item) for item in kinds),
        candidates_found=int(row.candidates_found or 0),
        candidates_new=int(row.candidates_new or 0),
        candidates_updated=int(row.candidates_updated or 0),
        promoted=int(row.promoted or 0),
        conflicts=int(row.conflicts or 0),
        metrics=row.metrics if isinstance(row.metrics, dict) else {},
        error=row.error or "",
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_ms=row.duration_ms,
        created_at=row.created_at,
        id=row.id,
    )


class PostgresCompanyDiscoveryRepository(CompanyDiscoveryRepository):
    """Backend Postgres del motor de descubrimiento."""

    async def upsert_candidate(
        self, candidate: DiscoveryCandidate
    ) -> tuple[DiscoveryCandidate, bool]:
        session = await get_async_session()
        try:
            existing = await session.execute(
                text(
                    "SELECT id FROM company_discovery_candidates "
                    "WHERE organization_id = :oid AND kind = :kind "
                    "AND natural_key = :key"
                ),
                {
                    "oid": str(candidate.organization_id),
                    "kind": candidate.kind.value,
                    "key": candidate.natural_key,
                },
            )
            is_new = existing.fetchone() is None
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO company_discovery_candidates ({_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :kind, :stage,
                        :natural_key, :title, :summary,
                        CAST(:payload AS jsonb), :source_kind, :source_ref,
                        :discovered_by, :confidence, CAST(:confidence_factors AS jsonb),
                        CAST(:support AS jsonb), CAST(:evidence AS jsonb),
                        CAST(:resolution AS jsonb), :reviewed_by, :reviewed_at,
                        :materialized_id, :first_observed_at, :last_observed_at,
                        now(), now()
                    )
                    ON CONFLICT (organization_id, kind, natural_key)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        payload = EXCLUDED.payload,
                        stage = EXCLUDED.stage,
                        confidence = EXCLUDED.confidence,
                        confidence_factors = EXCLUDED.confidence_factors,
                        support = EXCLUDED.support,
                        evidence = EXCLUDED.evidence,
                        resolution = EXCLUDED.resolution,
                        source_kind = EXCLUDED.source_kind,
                        source_ref = EXCLUDED.source_ref,
                        last_observed_at = EXCLUDED.last_observed_at,
                        reviewed_by = COALESCE(
                            EXCLUDED.reviewed_by,
                            company_discovery_candidates.reviewed_by
                        ),
                        reviewed_at = COALESCE(
                            EXCLUDED.reviewed_at,
                            company_discovery_candidates.reviewed_at
                        ),
                        materialized_id = COALESCE(
                            EXCLUDED.materialized_id,
                            company_discovery_candidates.materialized_id
                        ),
                        updated_at = now()
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "id": str(candidate.id),
                    "organization_id": str(candidate.organization_id),
                    "workspace_id": (
                        str(candidate.workspace_id) if candidate.workspace_id else None
                    ),
                    "kind": candidate.kind.value,
                    "stage": candidate.stage.value,
                    "natural_key": candidate.natural_key,
                    "title": candidate.title[:320],
                    "summary": candidate.summary,
                    "payload": _json(candidate.payload),
                    "source_kind": candidate.source_kind.value,
                    "source_ref": candidate.source_ref[:512],
                    "discovered_by": candidate.discovered_by[:120],
                    "confidence": candidate.confidence,
                    "confidence_factors": _json(candidate.confidence_factors),
                    "support": _json(candidate.support.to_dict()),
                    "evidence": _json([item.to_dict() for item in candidate.evidence]),
                    "resolution": _json(candidate.resolution),
                    "reviewed_by": (
                        str(candidate.reviewed_by) if candidate.reviewed_by else None
                    ),
                    "reviewed_at": candidate.reviewed_at,
                    "materialized_id": (
                        str(candidate.materialized_id)
                        if candidate.materialized_id
                        else None
                    ),
                    "first_observed_at": candidate.first_observed_at,
                    "last_observed_at": candidate.last_observed_at,
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_candidate(row), is_new
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_candidate(
        self, organization_id: UUID, candidate_id: UUID
    ) -> DiscoveryCandidate | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM company_discovery_candidates "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(candidate_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_candidate(row) if row is not None else None
        finally:
            await session.close()

    async def get_by_natural_key(
        self, organization_id: UUID, kind: CandidateKind, natural_key: str
    ) -> DiscoveryCandidate | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM company_discovery_candidates "
                    "WHERE organization_id = :oid AND kind = :kind "
                    "AND natural_key = :key"
                ),
                {
                    "oid": str(organization_id),
                    "kind": kind.value,
                    "key": natural_key,
                },
            )
            row = result.fetchone()
            return _row_to_candidate(row) if row is not None else None
        finally:
            await session.close()

    async def find_candidates(
        self,
        organization_id: UUID,
        *,
        kinds: tuple[CandidateKind, ...] = (),
        stages: tuple[DiscoveryStage, ...] = (),
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
        min_confidence: float | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DiscoveryCandidate]:
        where, params = self._filters(
            kinds=kinds,
            stages=stages,
            source_kinds=source_kinds,
            min_confidence=min_confidence,
            query=query,
        )
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM company_discovery_candidates "
                    f"WHERE {where} "
                    "ORDER BY confidence DESC, last_observed_at DESC, id "
                    "LIMIT :limit OFFSET :offset"
                ),
                {
                    "oid": str(organization_id),
                    **params,
                    "limit": limit,
                    "offset": offset,
                },
            )
            return [_row_to_candidate(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def count_candidates(
        self,
        organization_id: UUID,
        *,
        kinds: tuple[CandidateKind, ...] = (),
        stages: tuple[DiscoveryStage, ...] = (),
    ) -> int:
        where, params = self._filters(kinds=kinds, stages=stages)
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM company_discovery_candidates "
                    f"WHERE {where}"
                ),
                {"oid": str(organization_id), **params},
            )
            return int(result.fetchone().n or 0)
        finally:
            await session.close()

    async def update_candidate_state(
        self, candidate: DiscoveryCandidate
    ) -> DiscoveryCandidate:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    UPDATE company_discovery_candidates SET
                        stage = :stage,
                        confidence = :confidence,
                        confidence_factors = CAST(:confidence_factors AS jsonb),
                        support = CAST(:support AS jsonb),
                        resolution = CAST(:resolution AS jsonb),
                        reviewed_by = :reviewed_by,
                        reviewed_at = :reviewed_at,
                        materialized_id = :materialized_id,
                        updated_at = now()
                    WHERE id = :id AND organization_id = :oid
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "id": str(candidate.id),
                    "oid": str(candidate.organization_id),
                    "stage": candidate.stage.value,
                    "confidence": candidate.confidence,
                    "confidence_factors": _json(candidate.confidence_factors),
                    "support": _json(candidate.support.to_dict()),
                    "resolution": _json(candidate.resolution),
                    "reviewed_by": (
                        str(candidate.reviewed_by) if candidate.reviewed_by else None
                    ),
                    "reviewed_at": candidate.reviewed_at,
                    "materialized_id": (
                        str(candidate.materialized_id)
                        if candidate.materialized_id
                        else None
                    ),
                },
            )
            row = result.fetchone()
            if row is None:
                raise ValueError("candidate not found for this organization")
            await session.commit()
            return _row_to_candidate(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def stats(self, organization_id: UUID) -> dict:
        session = await get_async_session()
        try:
            rows = await session.execute(
                text(
                    "SELECT kind, stage, COUNT(*) AS n, "
                    "COALESCE(AVG(confidence), 0) AS avg_confidence "
                    "FROM company_discovery_candidates "
                    "WHERE organization_id = :oid "
                    "GROUP BY kind, stage"
                ),
                {"oid": str(organization_id)},
            )
            by_kind: dict[str, int] = {}
            by_stage: dict[str, int] = {}
            confidence: dict[str, float] = {}
            for row in rows.fetchall():
                by_kind[row.kind] = by_kind.get(row.kind, 0) + int(row.n)
                by_stage[row.stage] = by_stage.get(row.stage, 0) + int(row.n)
                confidence[row.kind] = round(float(row.avg_confidence), 4)
            return {
                "by_kind": by_kind,
                "by_stage": by_stage,
                "avg_confidence_by_kind": confidence,
                "total": sum(by_kind.values()),
            }
        finally:
            await session.close()

    # -- corridas -------------------------------------------------------
    async def enqueue_run(
        self,
        organization_id: UUID,
        *,
        trigger: str,
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
    ) -> DiscoveryRun:
        run = DiscoveryRun(
            organization_id=organization_id,
            trigger=DiscoveryTrigger(trigger),
            status=DiscoveryRunStatus.PENDING,
            source_kinds=source_kinds,
        )
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    f"INSERT INTO company_discovery_runs ({_RUN_COLUMNS}) "
                    "VALUES (:id, :oid, :trigger, :status, "
                    "CAST(:source_kinds AS jsonb), 0, 0, 0, 0, 0, '{}'::jsonb, "
                    "NULL, NULL, NULL, NULL, now())"
                ),
                {
                    "id": str(run.id),
                    "oid": str(organization_id),
                    "trigger": run.trigger.value,
                    "status": run.status.value,
                    "source_kinds": _json([k.value for k in source_kinds]),
                },
            )
            await session.commit()
            return run
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def start_run(
        self,
        organization_id: UUID,
        *,
        trigger: str,
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
    ) -> DiscoveryRun:
        """Abre una corrida ya en ejecución (el request la corre ahora)."""
        run = DiscoveryRun(
            organization_id=organization_id,
            trigger=DiscoveryTrigger(trigger),
            status=DiscoveryRunStatus.RUNNING,
            source_kinds=source_kinds,
        )
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"INSERT INTO company_discovery_runs ({_RUN_COLUMNS}) "
                    "VALUES (:id, :oid, :trigger, :status, "
                    "CAST(:source_kinds AS jsonb), 0, 0, 0, 0, 0, '{}'::jsonb, "
                    "NULL, now(), NULL, NULL, now()) "
                    f"RETURNING {_RUN_COLUMNS}"
                ),
                {
                    "id": str(run.id),
                    "oid": str(organization_id),
                    "trigger": run.trigger.value,
                    "status": run.status.value,
                    "source_kinds": _json([k.value for k in source_kinds]),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_run(row) if row is not None else run
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def claim_pending_run(self) -> DiscoveryRun | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    UPDATE company_discovery_runs SET
                        status = 'running',
                        started_at = now()
                    WHERE id = (
                        SELECT id FROM company_discovery_runs
                        WHERE status = 'pending'
                        ORDER BY created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING {_RUN_COLUMNS}
                    """
                )
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_run(row) if row is not None else None
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def save_run(self, run: DiscoveryRun) -> DiscoveryRun:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    UPDATE company_discovery_runs SET
                        status = :status,
                        candidates_found = :found,
                        candidates_new = :new,
                        candidates_updated = :updated,
                        promoted = :promoted,
                        conflicts = :conflicts,
                        metrics = CAST(:metrics AS jsonb),
                        error = :error,
                        completed_at = :completed_at,
                        duration_ms = :duration_ms
                    WHERE id = :id AND organization_id = :oid
                    RETURNING {_RUN_COLUMNS}
                    """
                ),
                {
                    "id": str(run.id),
                    "oid": str(run.organization_id),
                    "status": run.status.value,
                    "found": run.candidates_found,
                    "new": run.candidates_new,
                    "updated": run.candidates_updated,
                    "promoted": run.promoted,
                    "conflicts": run.conflicts,
                    "metrics": _json(run.metrics),
                    "error": run.error[:2000] if run.error else None,
                    "completed_at": run.completed_at,
                    "duration_ms": run.duration_ms,
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_run(row) if row is not None else run
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_runs(
        self, organization_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> list[DiscoveryRun]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_RUN_COLUMNS} FROM company_discovery_runs "
                    "WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"oid": str(organization_id), "limit": limit, "offset": offset},
            )
            return [_row_to_run(row) for row in result.fetchall()]
        finally:
            await session.close()

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _filters(
        *,
        kinds: tuple[CandidateKind, ...] = (),
        stages: tuple[DiscoveryStage, ...] = (),
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
        min_confidence: float | None = None,
        query: str | None = None,
    ) -> tuple[str, dict]:
        clauses = ["organization_id = :oid"]
        params: dict = {}
        if kinds:
            clauses.append("kind = ANY(:kinds)")
            params["kinds"] = [kind.value for kind in kinds]
        if stages:
            clauses.append("stage = ANY(:stages)")
            params["stages"] = [stage.value for stage in stages]
        if source_kinds:
            clauses.append("source_kind = ANY(:source_kinds)")
            params["source_kinds"] = [kind.value for kind in source_kinds]
        if min_confidence is not None:
            clauses.append("confidence >= :min_confidence")
            params["min_confidence"] = min_confidence
        if query:
            clauses.append("(title ILIKE :q OR natural_key ILIKE :q)")
            params["q"] = f"%{query.strip()}%"
        return " AND ".join(clauses), params
