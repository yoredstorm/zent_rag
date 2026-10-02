# =============================================================================
# Knowledge Model Repository — persistencia del Knowledge OS (FASE 34)
# =============================================================================
# Raw-SQL, org-scoped estricto (organization_id en TODA query), fail-soft con
# errores tipados en la capa de servicio. Tablas de la migración 132; el
# ensure_tables espeja el DDL para dev/test sin alembic.
#
# Reutiliza knowledge_canonical_objects (identidad 102), evidence_ledger (103)
# y context_gaps (079/081) en lugar de duplicarlos.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.domain.knowledge_model import (
    KnowledgeObjectStatus,
    KnowledgeProvenance,
    normalize_object_status,
    normalize_object_type,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_OBJECT_COLS = (
    "id, organization_id, kind, natural_key, name, display_name, description, "
    "domain, status, provenance, confidence, authority_level, source_id, "
    "source_of_truth, evidence_count, assertion_count, verified_by, verified_at, "
    "freshness_at, last_seen_at, metadata, created_at, updated_at"
)

_EDGE_COLS = (
    "id, organization_id, subject_id, predicate, object_id, relationship_type, "
    "confidence, status, provenance, source_id, evidence, metadata, created_at, "
    "updated_at"
)

_ASSERTION_COLS = (
    "id, organization_id, subject_id, subject_label, predicate, object_id, "
    "object_value, assertion_type, confidence, confidence_detail, status, "
    "provenance, method, source_id, evidence_count, version, verified_by, "
    "verified_at, valid_from, valid_to, stale_at, metadata, created_at, updated_at"
)

_EVIDENCE_COLS = (
    "id, organization_id, source_id, document_id, section_id, block_id, chunk_id, "
    "canonical_id, assertion_id, page, section_path, table_reference, "
    "row_reference, database_reference, excerpt, content_hash, evidence_type, "
    "strength, locator, authority, retrieval_score, created_at"
)

_CONFLICT_COLS = (
    "id, organization_id, object_id, subject_label, predicate, assertion_a, "
    "assertion_b, value_a, value_b, source_a, source_b, status, resolution, "
    "resolved_value, resolved_by, resolved_at, reason, detected_at, created_at, "
    "updated_at"
)

_GAP_COLS = (
    "id, organization_id, gap_type, concept, title, description, priority, "
    "priority_score, status, occurrences, question, impact, impact_objects, "
    "object_id, source_id, evidence_hints, first_seen_at, last_seen_at, "
    "resolved_by, resolved_at"
)

_STALE_DAYS_DEFAULT = 14

#: Kinds canónicos resolubles en runtime por nombre exacto (C2).
_LOOKUP_KINDS = ("entity", "concept", "process", "rule", "business_rule", "kpi")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _object_row(row) -> dict:
    return {
        "id": str(row.id),
        "type": normalize_object_type(row.kind),
        "kind": row.kind,
        "natural_key": row.natural_key,
        "name": row.name or row.display_name or row.natural_key,
        "display_name": row.display_name or row.name or row.natural_key,
        "description": row.description,
        "domain": row.domain,
        "status": normalize_object_status(row.status),
        "provenance": row.provenance,
        "confidence": row.confidence,
        "confidence_label": None,
        "authority_level": row.authority_level,
        "source_id": str(row.source_id) if row.source_id else None,
        "source_of_truth": row.source_of_truth,
        "evidence_count": row.evidence_count or 0,
        "assertion_count": row.assertion_count or 0,
        "verified_at": _iso(row.verified_at),
        "freshness_at": _iso(row.freshness_at),
        "last_seen_at": _iso(row.last_seen_at),
        "metadata": _loads(row.metadata, {}),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _edge_row(row) -> dict:
    return {
        "id": str(row.id),
        "subject_id": str(row.subject_id),
        "predicate": row.predicate,
        "object_id": str(row.object_id),
        "relationship_type": row.relationship_type,
        "confidence": row.confidence,
        "status": row.status,
        "provenance": row.provenance,
        "source_id": str(row.source_id) if row.source_id else None,
        "evidence": _loads(row.evidence, []),
        "metadata": _loads(row.metadata, {}),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _assertion_row(row) -> dict:
    return {
        "id": str(row.id),
        "subject_id": str(row.subject_id) if row.subject_id else None,
        "subject_label": row.subject_label,
        "predicate": row.predicate,
        "object_id": str(row.object_id) if row.object_id else None,
        "object_value": row.object_value,
        "assertion_type": row.assertion_type,
        "confidence": row.confidence,
        "confidence_detail": _loads(row.confidence_detail, {}),
        "status": row.status,
        "provenance": row.provenance,
        "method": row.method,
        "source_id": str(row.source_id) if row.source_id else None,
        "evidence_count": row.evidence_count or 0,
        "version": row.version or 1,
        "valid_from": _iso(row.valid_from),
        "valid_to": _iso(row.valid_to),
        "verified_at": _iso(row.verified_at),
        "stale_at": _iso(row.stale_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _evidence_row(row) -> dict:
    return {
        "id": str(row.id),
        "source_id": str(row.source_id) if row.source_id else None,
        "document_id": str(row.document_id) if row.document_id else None,
        "page": row.page,
        "section_path": _loads(row.section_path, []),
        "locator": row.locator,
        "table_reference": row.table_reference,
        "database_reference": row.database_reference,
        "excerpt": row.excerpt,
        "evidence_type": row.evidence_type,
        "strength": row.strength,
        "authority": row.authority,
        "retrieval_score": row.retrieval_score,
        "content_hash": row.content_hash,
        "created_at": _iso(row.created_at),
    }


def _conflict_row(row) -> dict:
    return {
        "id": str(row.id),
        "object_id": str(row.object_id) if row.object_id else None,
        "subject_label": row.subject_label,
        "predicate": row.predicate,
        "assertion_a": str(row.assertion_a) if row.assertion_a else None,
        "assertion_b": str(row.assertion_b) if row.assertion_b else None,
        "value_a": row.value_a,
        "value_b": row.value_b,
        "source_a": row.source_a,
        "source_b": row.source_b,
        "status": row.status,
        "resolution": row.resolution,
        "resolved_value": row.resolved_value,
        "resolved_by": str(row.resolved_by) if row.resolved_by else None,
        "resolved_at": _iso(row.resolved_at),
        "reason": row.reason,
        "detected_at": _iso(row.detected_at),
        "created_at": _iso(row.created_at),
    }


def _gap_row(row) -> dict:
    return {
        "id": str(row.id),
        "type": row.gap_type,
        "concept": row.concept,
        "title": row.title or row.question or row.concept,
        "description": row.description,
        "priority": row.priority or "medium",
        "priority_score": row.priority_score or 0.0,
        "status": row.status,
        "occurrences": row.occurrences or 1,
        "question": row.question,
        "impact": _loads(row.impact, {}),
        "impact_objects": row.impact_objects or 0,
        "object_id": str(row.object_id) if row.object_id else None,
        "source_id": str(row.source_id) if row.source_id else None,
        "evidence_hints": _loads(row.evidence_hints, []),
        "first_seen_at": _iso(row.first_seen_at),
        "last_seen_at": _iso(row.last_seen_at),
        "resolved_at": _iso(row.resolved_at),
    }


def _object_fields_changed(
    existing,
    *,
    name: str,
    description: str | None,
    domain: str | None,
    confidence: float | None,
    status: str,
) -> bool:
    """True si algún campo que el UPDATE pisaría difiere del persistido.

    Respeta los COALESCE del UPDATE: un valor nuevo None no cambia el previo.
    `confidence` se compara como float (la DB devuelve Decimal).
    """
    if existing.name != name[:512]:
        return True
    if description is not None and existing.description != description:
        return True
    if domain and existing.domain != domain:
        return True
    if confidence is not None:
        previous = existing.confidence
        if previous is None or float(previous) != float(confidence):
            return True
    return existing.status != status


# -----------------------------------------------------------------------------
# DDL espejo (dev/test sin alembic) — idempotente
# -----------------------------------------------------------------------------

_CREATE_TABLES = [
    """CREATE TABLE IF NOT EXISTS knowledge_edges (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        subject_id UUID NOT NULL,
        predicate VARCHAR(120) NOT NULL,
        object_id UUID NOT NULL,
        relationship_type VARCHAR(20) NOT NULL DEFAULT 'logical',
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
        status VARCHAR(16) NOT NULL DEFAULT 'inferred',
        provenance VARCHAR(16) NOT NULL DEFAULT 'INFERRED',
        source_id UUID,
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (organization_id, subject_id, predicate, object_id)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_assertions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        subject_id UUID,
        subject_label VARCHAR(512) NOT NULL DEFAULT '',
        predicate VARCHAR(200) NOT NULL,
        object_id UUID,
        object_value TEXT,
        assertion_type VARCHAR(40) NOT NULL DEFAULT 'fact',
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
        confidence_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(16) NOT NULL DEFAULT 'candidate',
        provenance VARCHAR(16) NOT NULL DEFAULT 'INFERRED',
        method VARCHAR(40) NOT NULL DEFAULT 'deterministic',
        source_id UUID,
        evidence_count INT NOT NULL DEFAULT 0,
        version INT NOT NULL DEFAULT 1,
        verified_by UUID,
        verified_at TIMESTAMPTZ,
        valid_from TIMESTAMPTZ,
        valid_to TIMESTAMPTZ,
        stale_at TIMESTAMPTZ,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (organization_id, subject_label, predicate, object_value)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_object_versions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        object_id UUID NOT NULL,
        version INT NOT NULL DEFAULT 1,
        change_kind VARCHAR(24) NOT NULL DEFAULT 'updated',
        snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        changed_by UUID,
        reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (object_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_conflicts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        object_id UUID,
        subject_label VARCHAR(512) NOT NULL DEFAULT '',
        predicate VARCHAR(200) NOT NULL,
        assertion_a UUID,
        assertion_b UUID,
        value_a TEXT,
        value_b TEXT,
        source_a VARCHAR(200),
        source_b VARCHAR(200),
        status VARCHAR(16) NOT NULL DEFAULT 'open',
        resolution VARCHAR(24),
        resolved_value TEXT,
        resolved_by UUID,
        resolved_at TIMESTAMPTZ,
        reason TEXT,
        detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
]

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_knowledge_edges_org_subject "
    "ON knowledge_edges(organization_id, subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_edges_org_object "
    "ON knowledge_edges(organization_id, object_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_assertions_org_subject "
    "ON knowledge_assertions(organization_id, subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_assertions_org_status "
    "ON knowledge_assertions(organization_id, status, confidence)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_conflicts_org_status "
    "ON knowledge_conflicts(organization_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_object_versions_org "
    "ON knowledge_object_versions(organization_id, object_id, version DESC)",
]

_KINDS_SQL = (
    "'source','document','section','block','chunk','entity','fact','rule','metric',"
    "'glossary_term','relationship','question','claim','evidence','artifact',"
    "'domain','concept','attribute','kpi','process','term','synonym','event',"
    "'constraint','table','column','verified_query'"
)
_STATUSES_SQL = (
    "'draft','discovered','observed','inferred','verified','approved','rejected',"
    "'deprecated','archived'"
)

_ALTERS = [
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS name VARCHAR(512) NOT NULL DEFAULT ''",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS display_name VARCHAR(512) NOT NULL DEFAULT ''",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS description TEXT",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS domain VARCHAR(128)",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS source_of_truth VARCHAR(200)",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS source_id UUID",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS verified_by UUID",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS freshness_at TIMESTAMPTZ",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS evidence_count INT NOT NULL DEFAULT 0",
    "ALTER TABLE knowledge_canonical_objects ADD COLUMN IF NOT EXISTS assertion_count INT NOT NULL DEFAULT 0",
    "ALTER TABLE knowledge_canonical_objects DROP CONSTRAINT IF EXISTS knowledge_canonical_objects_kind_check",
    "ALTER TABLE knowledge_canonical_objects DROP CONSTRAINT IF EXISTS knowledge_canonical_objects_status_check",
    "ALTER TABLE knowledge_canonical_objects DROP CONSTRAINT IF EXISTS ck_canonical_approval_law",
    "ALTER TABLE knowledge_canonical_objects "
    "ADD CONSTRAINT knowledge_canonical_objects_kind_check "
    f"CHECK (kind IN ({_KINDS_SQL}))",
    "ALTER TABLE knowledge_canonical_objects "
    "ADD CONSTRAINT knowledge_canonical_objects_status_check "
    f"CHECK (status IN ({_STATUSES_SQL}))",
    "ALTER TABLE knowledge_canonical_objects ADD CONSTRAINT ck_canonical_approval_law "
    "CHECK (status NOT IN ('approved','verified') OR provenance = 'APPROVED')",
    "ALTER TABLE evidence_ledger ADD COLUMN IF NOT EXISTS evidence_type VARCHAR(24) NOT NULL DEFAULT 'document'",
    "ALTER TABLE evidence_ledger ADD COLUMN IF NOT EXISTS strength DOUBLE PRECISION",
    "ALTER TABLE evidence_ledger ADD COLUMN IF NOT EXISTS locator TEXT",
    "ALTER TABLE evidence_ledger ADD COLUMN IF NOT EXISTS assertion_id UUID",
    "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS title VARCHAR(400)",
    "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS description TEXT",
    "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS priority VARCHAR(10) NOT NULL DEFAULT 'medium'",
    "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS priority_score DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS object_id UUID",
    "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS source_id UUID",
    "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS impact_objects INT NOT NULL DEFAULT 0",
    "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_gap_type_check",
    "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_status_check",
    "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_priority_check",
    "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_status_check "
    "CHECK (status IN ('open','investigating','resolved','ignored','acknowledged'))",
    "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_priority_check "
    "CHECK (priority IN ('critical','high','medium','low'))",
]


class PostgresKnowledgeModelRepository:
    """Acceso org-scoped al modelo de conocimiento."""

    async def ensure_tables(self) -> None:
        session = await get_async_session()
        try:
            for stmt in _ALTERS + _CREATE_TABLES:
                try:
                    await session.execute(text(stmt))
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    logger.warning("knowledge model ddl skipped", error=str(exc)[:160])
            for stmt in _CREATE_INDEXES:
                try:
                    await session.execute(text(stmt))
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    logger.warning("knowledge model index skipped", error=str(exc)[:160])
            await session.commit()
        finally:
            await session.close()

    # --------------------------------------------------------------- escritura
    async def upsert_object(
        self,
        organization_id: UUID,
        **kwargs,
    ) -> bool:
        """Upsert idempotente. Devuelve True si el objeto ya existía."""
        existed, _changed = await self.upsert_object_with_status(
            organization_id, **kwargs
        )
        return existed

    async def upsert_object_with_status(
        self,
        organization_id: UUID,
        *,
        object_id: UUID,
        kind: str,
        natural_key: str,
        name: str,
        display_name: str = "",
        description: str | None = None,
        domain: str | None = None,
        status: str = KnowledgeObjectStatus.DISCOVERED.value,
        provenance: str = KnowledgeProvenance.OBSERVED.value,
        confidence: float | None = None,
        source_of_truth: str | None = None,
        source_id: UUID | None = None,
        authority_level: str | None = None,
        workspace_id: UUID | None = None,
        metadata: dict | None = None,
        freshness_at: datetime | None = None,
        touch_existing: bool = True,
    ) -> tuple[bool, bool]:
        """Upsert idempotente. Devuelve (ya_existía, cambió_real).

        `changed` compara name/description/domain/confidence/status contra la
        fila previa (mismo SELECT que ya hacía el upsert): re-observar un objeto
        idéntico devuelve (True, False) y no dispara eventos de alto impacto.
        Fila nueva → (False, True).
        """
        session = await get_async_session()
        try:
            existing = (
                await session.execute(
                    text(
                        "SELECT id, name, description, domain, confidence, status "
                        "FROM knowledge_canonical_objects "
                        "WHERE organization_id = :org AND id = :oid"
                    ),
                    {"org": organization_id, "oid": object_id},
                )
            ).first()
            payload = {
                "org": organization_id,
                "oid": object_id,
                "workspace": workspace_id,
                "kind": kind,
                "key": natural_key[:768],
                "name": name[:512],
                "display": (display_name or name)[:512],
                "description": description,
                "domain": (domain or None),
                "status": status,
                "provenance": provenance,
                "confidence": confidence,
                "source_of_truth": (source_of_truth or None),
                "source_id": source_id,
                "authority": authority_level,
                "metadata": json.dumps(metadata or {}, default=str),
                "freshness": freshness_at or datetime.now(timezone.utc),
            }
            if existing is None:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_canonical_objects (
                            id, organization_id, workspace_id, kind, natural_key,
                            title, name, display_name, description, domain,
                            provenance, status, confidence, authority_level,
                            source_id, source_of_truth, freshness_at,
                            last_seen_at, metadata
                        ) VALUES (
                            :oid, :org, :workspace, :kind, :key,
                            :name, :name, :display, :description, :domain,
                            :provenance, :status, :confidence, :authority,
                            :source_id, :source_of_truth, :freshness,
                            now(), CAST(:metadata AS jsonb)
                        )
                        ON CONFLICT (organization_id, kind, natural_key) DO NOTHING
                        """
                    ),
                    payload,
                )
                await session.commit()
                return False, True
            changed = _object_fields_changed(
                existing,
                name=name,
                description=description,
                domain=domain,
                confidence=confidence,
                status=status,
            )
            if touch_existing:
                await session.execute(
                    text(
                        """
                        UPDATE knowledge_canonical_objects SET
                            name = :name,
                            display_name = :display,
                            description = COALESCE(:description, description),
                            domain = COALESCE(:domain, domain),
                            status = :status,
                            provenance = :provenance,
                            confidence = COALESCE(:confidence, confidence),
                            authority_level = COALESCE(:authority, authority_level),
                            source_id = COALESCE(:source_id, source_id),
                            source_of_truth = COALESCE(:source_of_truth, source_of_truth),
                            freshness_at = COALESCE(:freshness, freshness_at),
                            last_seen_at = now(),
                            metadata = metadata || CAST(:metadata AS jsonb),
                            updated_at = now()
                        WHERE organization_id = :org AND id = :oid
                        """
                    ),
                    payload,
                )
                await session.commit()
            return True, changed
        finally:
            await session.close()

    async def upsert_edge(
        self,
        organization_id: UUID,
        *,
        subject_id: UUID,
        predicate: str,
        object_id: UUID,
        relationship_type: str,
        confidence: float,
        status: str,
        provenance: str,
        source_id: UUID | None = None,
        evidence: list | None = None,
        metadata: dict | None = None,
        workspace_id: UUID | None = None,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_edges (
                        organization_id, workspace_id, subject_id, predicate,
                        object_id, relationship_type, confidence, status,
                        provenance, source_id, evidence, metadata
                    ) VALUES (
                        :org, :workspace, :subject, :predicate, :object, :rtype,
                        :confidence, :status, :provenance, :source_id,
                        CAST(:evidence AS jsonb), CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (organization_id, subject_id, predicate, object_id)
                    DO UPDATE SET
                        confidence = EXCLUDED.confidence,
                        status = EXCLUDED.status,
                        relationship_type = EXCLUDED.relationship_type,
                        provenance = EXCLUDED.provenance,
                        evidence = EXCLUDED.evidence,
                        metadata = knowledge_edges.metadata || EXCLUDED.metadata,
                        updated_at = now()
                    """
                ),
                {
                    "org": organization_id,
                    "workspace": workspace_id,
                    "subject": subject_id,
                    "predicate": predicate[:120],
                    "object": object_id,
                    "rtype": relationship_type,
                    "confidence": max(0.0, min(1.0, float(confidence))),
                    "status": status,
                    "provenance": provenance,
                    "source_id": source_id,
                    "evidence": json.dumps(evidence or [], default=str),
                    "metadata": json.dumps(metadata or {}, default=str),
                },
            )
            await session.commit()
        finally:
            await session.close()

    async def upsert_assertion(
        self,
        organization_id: UUID,
        *,
        subject_id: UUID | None,
        subject_label: str,
        predicate: str,
        object_value: str | None = None,
        object_id: UUID | None = None,
        assertion_type: str = "fact",
        confidence: float = 0.0,
        confidence_detail: dict | None = None,
        status: str = "candidate",
        provenance: str = KnowledgeProvenance.INFERRED.value,
        method: str = "deterministic",
        source_id: UUID | None = None,
        evidence_count: int = 0,
        metadata: dict | None = None,
        workspace_id: UUID | None = None,
        stale_at: datetime | None = None,
    ) -> UUID:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_assertions (
                            organization_id, workspace_id, subject_id, subject_label,
                            predicate, object_id, object_value, assertion_type,
                            confidence, confidence_detail, status, provenance,
                            method, source_id, evidence_count, metadata, stale_at
                        ) VALUES (
                            :org, :workspace, :subject, :label, :predicate, :object_id,
                            :object_value, :atype, :confidence,
                            CAST(:detail AS jsonb), :status, :provenance, :method,
                            :source_id, :evidence_count, CAST(:metadata AS jsonb),
                            :stale_at
                        )
                        ON CONFLICT (organization_id, subject_label, predicate, object_value)
                        DO UPDATE SET
                            confidence = EXCLUDED.confidence,
                            confidence_detail = EXCLUDED.confidence_detail,
                            status = EXCLUDED.status,
                            provenance = EXCLUDED.provenance,
                            method = EXCLUDED.method,
                            source_id = EXCLUDED.source_id,
                            evidence_count = EXCLUDED.evidence_count,
                            subject_id = COALESCE(EXCLUDED.subject_id, knowledge_assertions.subject_id),
                            object_id = COALESCE(EXCLUDED.object_id, knowledge_assertions.object_id),
                            stale_at = EXCLUDED.stale_at,
                            updated_at = now()
                        RETURNING id
                        """
                    ),
                    {
                        "org": organization_id,
                        "workspace": workspace_id,
                        "subject": subject_id,
                        "label": (subject_label or "unknown")[:512],
                        "predicate": predicate[:200],
                        "object_id": object_id,
                        "object_value": object_value,
                        "atype": assertion_type,
                        "confidence": max(0.0, min(1.0, float(confidence))),
                        "detail": json.dumps(confidence_detail or {}, default=str),
                        "status": status,
                        "provenance": provenance,
                        "method": method,
                        "source_id": source_id,
                        "evidence_count": int(evidence_count),
                        "metadata": json.dumps(metadata or {}, default=str),
                        "stale_at": stale_at,
                    },
                )
            ).first()
            await session.commit()
            return UUID(str(row.id))
        finally:
            await session.close()

    async def add_evidence(
        self,
        organization_id: UUID,
        *,
        canonical_id: UUID | None,
        assertion_id: UUID | None,
        source_id: UUID | None,
        evidence_type: str,
        locator: str,
        excerpt: str,
        content_hash: str,
        strength: float,
        authority: str | None = None,
        page: int | None = None,
        table_reference: str | None = None,
        database_reference: str | None = None,
        section_path: list | None = None,
        document_id: UUID | None = None,
        workspace_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO evidence_ledger (
                            organization_id, workspace_id, source_id, document_id,
                            canonical_id, assertion_id, page, section_path,
                            table_reference, database_reference, excerpt,
                            content_hash, evidence_type, strength, locator,
                            authority, metadata
                        ) VALUES (
                            :org, :workspace, :source_id, :document_id,
                            :canonical_id, :assertion_id, :page,
                            CAST(:section_path AS jsonb), :table_ref, :db_ref,
                            :excerpt, :content_hash, :evidence_type, :strength,
                            :locator, :authority, CAST(:metadata AS jsonb)
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "org": organization_id,
                        "workspace": workspace_id,
                        "source_id": source_id,
                        "document_id": document_id,
                        "canonical_id": canonical_id,
                        "assertion_id": assertion_id,
                        "page": page,
                        "section_path": json.dumps(section_path or [], default=str),
                        "table_ref": table_reference,
                        "db_ref": database_reference,
                        "excerpt": excerpt[:4000],
                        "content_hash": content_hash[:64],
                        "evidence_type": evidence_type,
                        "strength": max(0.0, min(1.0, float(strength))),
                        "locator": locator[:1000],
                        "authority": authority,
                        "metadata": json.dumps(metadata or {}, default=str),
                    },
                )
            ).first()
            await session.commit()
            return UUID(str(row.id))
        finally:
            await session.close()

    async def record_version(
        self,
        organization_id: UUID,
        object_id: UUID,
        *,
        change_kind: str,
        snapshot: dict,
        changed_by: UUID | None = None,
        reason: str | None = None,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_object_versions (
                        organization_id, object_id, version, change_kind,
                        snapshot, changed_by, reason
                    )
                    SELECT :org, :oid,
                           COALESCE(MAX(version), 0) + 1, :kind,
                           CAST(:snapshot AS jsonb), :by, :reason
                    FROM knowledge_object_versions
                    WHERE organization_id = :org AND object_id = :oid
                    """
                ),
                {
                    "org": organization_id,
                    "oid": object_id,
                    "kind": change_kind,
                    "snapshot": json.dumps(snapshot, default=str),
                    "by": changed_by,
                    "reason": reason,
                },
            )
            await session.commit()
        finally:
            await session.close()

    async def refresh_object_counters(
        self, organization_id: UUID, object_ids: list[UUID] | None = None
    ) -> None:
        """Recalcula evidence_count/assertion_count desde las tablas reales."""
        session = await get_async_session()
        try:
            params: dict = {"org": organization_id}
            ids_clause = ""
            if object_ids:
                params["ids"] = list(object_ids)
                ids_clause = " AND o.id = ANY(:ids)"
            await session.execute(
                text(
                    """
                    UPDATE knowledge_canonical_objects o SET
                        evidence_count = COALESCE((
                            SELECT COUNT(*) FROM evidence_ledger e
                            WHERE e.organization_id = o.organization_id
                              AND e.canonical_id = o.id
                        ), 0),
                        assertion_count = COALESCE((
                            SELECT COUNT(*) FROM knowledge_assertions a
                            WHERE a.organization_id = o.organization_id
                              AND a.subject_id = o.id
                        ), 0)
                    WHERE o.organization_id = :org"""
                    + ids_clause
                ),
                params,
            )
            await session.commit()
        finally:
            await session.close()

    async def detect_conflicts(self, organization_id: UUID) -> int:
        """Conflicto real: mismo sujeto+predicado, distinto valor, distinta fuente."""
        session = await get_async_session()
        try:
            pairs = (
                await session.execute(
                    text(
                        """
                        SELECT a.id AS a_id, b.id AS b_id,
                               a.subject_id, a.subject_label, a.predicate,
                               a.object_value AS value_a, b.object_value AS value_b,
                               a.source_id AS source_a, b.source_id AS source_b
                        FROM knowledge_assertions a
                        JOIN knowledge_assertions b
                          ON b.organization_id = a.organization_id
                         AND b.subject_label = a.subject_label
                         AND b.predicate = a.predicate
                         AND b.id > a.id
                         AND COALESCE(b.object_value, '') <> COALESCE(a.object_value, '')
                        WHERE a.organization_id = :org
                          AND a.status NOT IN ('rejected')
                          AND b.status NOT IN ('rejected')
                          AND COALESCE(a.object_value, '') <> ''
                          AND COALESCE(b.object_value, '') <> ''
                        LIMIT 200
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            created = 0
            for pair in pairs:
                exists = (
                    await session.execute(
                        text(
                            """
                            SELECT 1 FROM knowledge_conflicts
                            WHERE organization_id = :org
                              AND subject_label = :label
                              AND predicate = :predicate
                              AND ((assertion_a = :a AND assertion_b = :b)
                                OR (assertion_a = :b AND assertion_b = :a))
                            """
                        ),
                        {
                            "org": organization_id,
                            "label": pair.subject_label,
                            "predicate": pair.predicate,
                            "a": pair.a_id,
                            "b": pair.b_id,
                        },
                    )
                ).first()
                if exists:
                    continue
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_conflicts (
                            organization_id, object_id, subject_label, predicate,
                            assertion_a, assertion_b, value_a, value_b,
                            source_a, source_b, status
                        ) VALUES (
                            :org, :object_id, :label, :predicate,
                            :a, :b, :value_a, :value_b,
                            CAST(:source_a AS varchar), CAST(:source_b AS varchar),
                            'open'
                        )
                        """
                    ),
                    {
                        "org": organization_id,
                        "object_id": pair.subject_id,
                        "label": pair.subject_label,
                        "predicate": pair.predicate,
                        "a": pair.a_id,
                        "b": pair.b_id,
                        "value_a": pair.value_a,
                        "value_b": pair.value_b,
                        "source_a": str(pair.source_a) if pair.source_a else None,
                        "source_b": str(pair.source_b) if pair.source_b else None,
                    },
                )
                created += 1
            if created:
                await session.execute(
                    text(
                        """
                        UPDATE knowledge_assertions SET status = 'conflicted', updated_at = now()
                        WHERE organization_id = :org AND id IN (
                            SELECT assertion_a FROM knowledge_conflicts
                            WHERE organization_id = :org AND status = 'open'
                            UNION
                            SELECT assertion_b FROM knowledge_conflicts
                            WHERE organization_id = :org AND status = 'open'
                        ) AND status NOT IN ('verified','rejected')
                        """
                    ),
                    {"org": organization_id},
                )
            await session.commit()
            return created
        finally:
            await session.close()

    # ------------------------------------------------------------------ lectura
    async def count_objects(
        self,
        organization_id: UUID,
        *,
        kinds: list[str] | None = None,
        domain: str | None = None,
        status: str | None = None,
        source_id: UUID | None = None,
    ) -> int:
        session = await get_async_session()
        try:
            clauses = ["organization_id = :org"]
            params: dict = {"org": organization_id}
            if kinds:
                clauses.append("kind = ANY(:kinds)")
                params["kinds"] = kinds
            if domain:
                clauses.append("domain = :domain")
                params["domain"] = domain
            if status:
                clauses.append("status = :status")
                params["status"] = status
            if source_id:
                clauses.append("source_id = :source_id")
                params["source_id"] = source_id
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM knowledge_canonical_objects "
                        "WHERE " + " AND ".join(clauses)
                    ),
                    params,
                )
            ).first()
            return int(row.total or 0)
        finally:
            await session.close()

    async def list_objects(
        self,
        organization_id: UUID,
        *,
        kinds: list[str] | None = None,
        domain: str | None = None,
        status: str | None = None,
        source_id: UUID | None = None,
        q: str | None = None,
        min_confidence: float | None = None,
        order_by: str = "updated_at",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            clauses = ["organization_id = :org"]
            params: dict = {"org": organization_id}
            if kinds:
                clauses.append("kind = ANY(:kinds)")
                params["kinds"] = kinds
            if domain:
                clauses.append("domain = :domain")
                params["domain"] = domain
            if status:
                clauses.append("status = :status")
                params["status"] = status
            if source_id:
                clauses.append("source_id = :source_id")
                params["source_id"] = source_id
            if q:
                clauses.append(
                    "(name ILIKE :like OR display_name ILIKE :like "
                    "OR description ILIKE :like OR natural_key ILIKE :like)"
                )
                params["like"] = f"%{q.strip()}%"
            if min_confidence is not None:
                clauses.append("confidence IS NOT NULL AND confidence >= :min_conf")
                params["min_conf"] = float(min_confidence)
            order = {
                "confidence": "confidence DESC NULLS LAST",
                "name": "lower(name) ASC",
                "evidence": "evidence_count DESC, updated_at DESC",
            }.get(order_by, "updated_at DESC")
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_OBJECT_COLS} FROM knowledge_canonical_objects "
                        f"WHERE {' AND '.join(clauses)} "
                        f"ORDER BY {order} LIMIT :limit OFFSET :offset"
                    ),
                    {**params, "limit": min(max(limit, 1), 200), "offset": max(offset, 0)},
                )
            ).fetchall()
            return [_object_row(r) for r in rows]
        finally:
            await session.close()

    async def get_object(self, organization_id: UUID, object_id: UUID) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_OBJECT_COLS} FROM knowledge_canonical_objects "
                        "WHERE organization_id = :org AND id = :oid"
                    ),
                    {"org": organization_id, "oid": object_id},
                )
            ).first()
            return _object_row(row) if row else None
        finally:
            await session.close()

    async def object_edges(
        self,
        organization_id: UUID,
        object_id: UUID,
        *,
        limit: int = 200,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> dict:
        session = await get_async_session()
        try:
            params: dict = {
                "org": organization_id,
                "oid": object_id,
                "limit": min(limit, 500),
            }
            source_clause = ""
            if source_ids:
                params["source_ids"] = list(source_ids)
                source_clause = (
                    " AND (e.source_id = ANY(:source_ids) OR e.source_id IS NULL)"
                )
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT e.id, e.organization_id, e.subject_id, e.predicate,
                               e.object_id, e.relationship_type, e.confidence,
                               e.status, e.provenance, e.source_id, e.evidence,
                               e.metadata, e.created_at, e.updated_at,
                               s.name AS subject_name, s.kind AS subject_kind,
                               o.name AS object_name, o.kind AS object_kind
                        FROM knowledge_edges e
                        JOIN knowledge_canonical_objects s
                          ON s.id = e.subject_id AND s.organization_id = e.organization_id
                        JOIN knowledge_canonical_objects o
                          ON o.id = e.object_id AND o.organization_id = e.organization_id
                        WHERE e.organization_id = :org
                          AND (e.subject_id = :oid OR e.object_id = :oid)"""
                        + source_clause
                        + """
                        ORDER BY e.confidence DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).fetchall()
            edges = []
            for r in rows:
                item = _edge_row(r)
                item["subject_name"] = r.subject_name
                item["subject_type"] = normalize_object_type(r.subject_kind)
                item["object_name"] = r.object_name
                item["object_type"] = normalize_object_type(r.object_kind)
                item["direction"] = "out" if str(r.subject_id) == str(object_id) else "in"
                edges.append(item)
            return {"edges": edges, "count": len(edges)}
        finally:
            await session.close()

    async def object_assertions(
        self,
        organization_id: UUID,
        object_id: UUID,
        *,
        limit: int = 100,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            params: dict = {
                "org": organization_id,
                "oid": object_id,
                "limit": min(limit, 300),
            }
            source_clause = ""
            if source_ids:
                params["source_ids"] = list(source_ids)
                source_clause = (
                    " AND (source_id = ANY(:source_ids) OR source_id IS NULL)"
                )
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_ASSERTION_COLS} FROM knowledge_assertions "
                        "WHERE organization_id = :org "
                        "AND (subject_id = :oid OR object_id = :oid)"
                        + source_clause
                        + " ORDER BY confidence DESC, updated_at DESC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [_assertion_row(r) for r in rows]
        finally:
            await session.close()

    async def object_evidence(
        self, organization_id: UUID, object_id: UUID, *, limit: int = 100
    ) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_EVIDENCE_COLS} FROM evidence_ledger "
                        "WHERE organization_id = :org AND (canonical_id = :oid OR assertion_id IN ("
                        "  SELECT id FROM knowledge_assertions "
                        "  WHERE organization_id = :org AND subject_id = :oid"
                        ")) ORDER BY strength DESC NULLS LAST, created_at DESC LIMIT :limit"
                    ),
                    {"org": organization_id, "oid": object_id, "limit": min(limit, 300)},
                )
            ).fetchall()
            return [_evidence_row(r) for r in rows]
        finally:
            await session.close()

    async def object_versions(
        self, organization_id: UUID, object_id: UUID, *, limit: int = 50
    ) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT version, change_kind, snapshot, changed_by, reason, created_at
                        FROM knowledge_object_versions
                        WHERE organization_id = :org AND object_id = :oid
                        ORDER BY version DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "oid": object_id, "limit": min(limit, 200)},
                )
            ).fetchall()
            return [
                {
                    "version": r.version,
                    "change_kind": r.change_kind,
                    "snapshot": _loads(r.snapshot, {}),
                    "changed_by": str(r.changed_by) if r.changed_by else None,
                    "reason": r.reason,
                    "created_at": _iso(r.created_at),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def lineage(self, organization_id: UUID, object_id: UUID) -> dict:
        """Lineage real vía knowledge_canonical_links + catalog_lineage."""
        session = await get_async_session()
        try:
            links = (
                await session.execute(
                    text(
                        """
                        SELECT system, object_type, object_ref
                        FROM knowledge_canonical_links
                        WHERE organization_id = :org AND canonical_id = :oid
                        """
                    ),
                    {"org": organization_id, "oid": object_id},
                )
            ).fetchall()
            refs = [(r.object_type, str(r.object_ref)) for r in links]
            lineage_rows: list[dict] = []
            if refs:
                for object_type, object_ref in refs[:20]:
                    rows = (
                        await session.execute(
                            text(
                                """
                                SELECT upstream_type, upstream_id, downstream_type,
                                       downstream_id, relation, metadata
                                FROM catalog_lineage
                                WHERE organization_id = :org
                                  AND ((upstream_type = :otype AND upstream_id = :oref)
                                    OR (downstream_type = :otype AND downstream_id = :oref))
                                LIMIT 100
                                """
                            ),
                            {
                                "org": organization_id,
                                "otype": object_type,
                                "oref": object_ref,
                            },
                        )
                    ).fetchall()
                    for r in rows:
                        lineage_rows.append(
                            {
                                "upstream_type": r.upstream_type,
                                "upstream_id": r.upstream_id,
                                "downstream_type": r.downstream_type,
                                "downstream_id": r.downstream_id,
                                "relation": r.relation,
                                "metadata": _loads(r.metadata, {}),
                            }
                        )
            return {
                "physical_refs": [
                    {"system": r.system, "object_type": r.object_type, "object_ref": r.object_ref}
                    for r in links
                ],
                "lineage": lineage_rows,
                "count": len(lineage_rows),
            }
        finally:
            await session.close()

    async def impact(self, organization_id: UUID, object_id: UUID) -> dict:
        """WHAT DEPENDS ON THIS: edges, assertions, agentes y workflows reales."""
        session = await get_async_session()
        try:
            obj = (
                await session.execute(
                    text(
                        "SELECT id, kind, name, source_id, metadata FROM knowledge_canonical_objects "
                        "WHERE organization_id = :org AND id = :oid"
                    ),
                    {"org": organization_id, "oid": object_id},
                )
            ).first()
            if obj is None:
                return {"object": None, "dependents": [], "count": 0}
            dependents: list[dict] = []
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT e.predicate, e.relationship_type, e.confidence, e.status,
                               o.id AS other_id, o.kind AS other_kind, o.name AS other_name
                        FROM knowledge_edges e
                        JOIN knowledge_canonical_objects o
                          ON o.id = CASE WHEN e.subject_id = :oid
                                         THEN e.object_id ELSE e.subject_id END
                         AND o.organization_id = e.organization_id
                        WHERE e.organization_id = :org
                          AND (e.subject_id = :oid OR e.object_id = :oid)
                        LIMIT 200
                        """
                    ),
                    {"org": organization_id, "oid": object_id},
                )
            ).fetchall()
            for r in rows:
                dependents.append(
                    {
                        "kind": "object",
                        "id": str(r.other_id),
                        "type": normalize_object_type(r.other_kind),
                        "name": r.other_name,
                        "via": r.predicate,
                        "relationship_type": r.relationship_type,
                        "confidence": r.confidence,
                        "status": r.status,
                    }
                )
            assertion_rows = (
                await session.execute(
                    text(
                        "SELECT id, predicate, object_value, status, confidence "
                        "FROM knowledge_assertions "
                        "WHERE organization_id = :org AND (subject_id = :oid OR object_id = :oid) "
                        "LIMIT 200"
                    ),
                    {"org": organization_id, "oid": object_id},
                )
            ).fetchall()
            for r in assertion_rows:
                dependents.append(
                    {
                        "kind": "assertion",
                        "id": str(r.id),
                        "type": r.predicate,
                        "name": r.object_value or r.predicate,
                        "status": r.status,
                        "confidence": r.confidence,
                    }
                )
            # Agentes que referencian la fuente física del objeto.
            source_id = obj.source_id
            if source_id is not None:
                try:
                    agent_rows = (
                        await session.execute(
                            text(
                                "SELECT id, name FROM agents WHERE organization_id = :org "
                                "AND config_json::text LIKE :needle LIMIT 50"
                            ),
                            {"org": organization_id, "needle": f"%{source_id}%"},
                        )
                    ).fetchall()
                    for r in agent_rows:
                        dependents.append(
                            {
                                "kind": "agent",
                                "id": str(r.id),
                                "type": "agent",
                                "name": r.name,
                                "via": "source_reference",
                            }
                        )
                except Exception:  # noqa: BLE001
                    pass
            try:
                wf_rows = (
                    await session.execute(
                        text(
                            "SELECT id, name FROM workflow_definitions "
                            "WHERE organization_id = :org AND steps::text ILIKE :needle "
                            "LIMIT 50"
                        ),
                        {"org": organization_id, "needle": f"%{obj.name}%"},
                    )
                ).fetchall()
                for r in wf_rows:
                    dependents.append(
                        {
                            "kind": "workflow",
                            "id": str(r.id),
                            "type": "workflow",
                            "name": r.name,
                            "via": "name_reference",
                        }
                    )
            except Exception:  # noqa: BLE001
                pass
            return {"object": str(object_id), "dependents": dependents, "count": len(dependents)}
        finally:
            await session.close()

    async def domains(self, organization_id: UUID) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(domain, 'Sin dominio') AS domain,
                               COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status IN ('verified','approved')) AS verified,
                               COUNT(*) FILTER (WHERE confidence IS NOT NULL) AS scored,
                               AVG(confidence) AS avg_confidence,
                               COUNT(DISTINCT source_id) AS sources
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND kind NOT IN ('source','table','column','document','section','chunk')
                        GROUP BY 1
                        ORDER BY total DESC
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            return [
                {
                    "name": r.domain,
                    "objects": int(r.total or 0),
                    "verified": int(r.verified or 0),
                    "measured": int(r.scored or 0) > 0,
                    "avg_confidence": round(float(r.avg_confidence), 4)
                    if r.avg_confidence is not None
                    else None,
                    "sources": int(r.sources or 0),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def search(
        self, organization_id: UUID, q: str, *, limit: int = 10
    ) -> dict:
        session = await get_async_session()
        try:
            like = f"%{q.strip()}%"
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT kind, COUNT(*) AS total
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND (name ILIKE :like OR display_name ILIKE :like
                               OR description ILIKE :like OR natural_key ILIKE :like)
                        GROUP BY kind ORDER BY total DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "like": like, "limit": limit},
                )
            ).fetchall()
            groups = [
                {"type": normalize_object_type(r.kind), "count": int(r.total or 0)}
                for r in rows
            ]
            items = await self.list_objects(organization_id, q=q, limit=limit, order_by="name")
            return {"groups": groups, "items": items, "count": len(items)}
        finally:
            await session.close()

    async def lookup_aliases(
        self,
        organization_id: UUID,
        normalized: list[str],
        *,
        limit: int = 50,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> list[dict]:
        """Alias normalizados -> objeto canónico (scoped, determinista)."""
        names = [str(item).strip().lower() for item in normalized if str(item).strip()]
        if not names:
            return []
        session = await get_async_session()
        try:
            params: dict = {
                "org": organization_id,
                "names": names[:50],
                "limit": min(max(int(limit), 1), 200),
            }
            source_clause = ""
            if source_ids:
                params["source_ids"] = list(source_ids)
                source_clause = (
                    " AND (o.source_id = ANY(:source_ids) OR o.source_id IS NULL)"
                )
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT a.normalized, a.alias, a.confidence,
                               o.id AS entity_id,
                               COALESCE(
                                 NULLIF(o.name, ''),
                                 NULLIF(o.display_name, ''),
                                 o.title,
                                 o.natural_key
                               ) AS name,
                               o.kind
                        FROM knowledge_entity_aliases a
                        JOIN knowledge_canonical_objects o
                          ON o.id = a.entity_id
                         AND o.organization_id = a.organization_id
                        WHERE a.organization_id = :org
                          AND a.normalized = ANY(:names)"""
                        + source_clause
                        + """
                        ORDER BY a.confidence DESC, o.id
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "normalized": str(r.normalized),
                    "alias": str(r.alias),
                    "confidence": float(r.confidence or 0.0),
                    "entity_id": str(r.entity_id),
                    "name": str(r.name or ""),
                    "kind": str(r.kind or ""),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def find_objects_by_names(
        self,
        organization_id: UUID,
        names: list[str],
        *,
        kinds: tuple[str, ...] = _LOOKUP_KINDS,
        limit: int = 20,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> list[dict]:
        """Objetos canónicos por nombre exacto (lower) entre los kinds resolubles."""
        wanted = [str(item).strip().lower() for item in names if str(item).strip()]
        if not wanted:
            return []
        session = await get_async_session()
        try:
            params: dict = {
                "org": organization_id,
                "kinds": list(kinds),
                "names": wanted[:50],
                "limit": min(max(int(limit), 1), 100),
            }
            source_clause = ""
            if source_ids:
                params["source_ids"] = list(source_ids)
                source_clause = (
                    " AND (source_id = ANY(:source_ids) OR source_id IS NULL)"
                )
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, natural_key, name, display_name, title,
                               confidence, status, provenance
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND kind = ANY(:kinds)
                          AND lower(COALESCE(
                                NULLIF(name, ''),
                                NULLIF(display_name, ''),
                                title,
                                natural_key
                              )) = ANY(:names)"""
                        + source_clause
                        + """
                        ORDER BY confidence DESC NULLS LAST, id
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "kind": str(r.kind),
                    "type": normalize_object_type(r.kind),
                    "natural_key": str(r.natural_key),
                    "name": str(
                        r.name or r.display_name or r.title or r.natural_key or ""
                    ),
                    "display_name": str(
                        r.display_name or r.name or r.title or r.natural_key or ""
                    ),
                    "confidence": r.confidence,
                    "status": r.status,
                    "provenance": r.provenance,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def graph(
        self,
        organization_id: UUID,
        *,
        focus_id: UUID | None = None,
        depth: int = 1,
        kinds: list[str] | None = None,
        domains: list[str] | None = None,
        min_confidence: float | None = None,
        limit_nodes: int = 120,
        limit_edges: int = 300,
    ) -> dict:
        """Vecindario inicial + expansión on-demand. Deriva del modelo real."""
        session = await get_async_session()
        try:
            params: dict = {
                "org": organization_id,
                "limit_nodes": min(max(limit_nodes, 1), 400),
                "limit_edges": min(max(limit_edges, 1), 800),
            }
            edge_clauses = ["e.organization_id = :org"]
            if kinds:
                edge_clauses.append("(s.kind = ANY(:kinds) OR o.kind = ANY(:kinds))")
                params["kinds"] = kinds
            if domains:
                edge_clauses.append(
                    "(s.domain = ANY(:domains) OR o.domain = ANY(:domains))"
                )
                params["domains"] = domains
            if min_confidence is not None:
                edge_clauses.append("e.confidence >= :min_conf")
                params["min_conf"] = float(min_confidence)

            if focus_id is not None:
                edge_clauses.append(
                    "(e.subject_id = :focus OR e.object_id = :focus)"
                )
                params["focus"] = focus_id
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT e.id, e.subject_id, e.predicate, e.object_id,
                               e.relationship_type, e.confidence, e.status,
                               e.provenance, e.evidence,
                               s.id AS s_id, s.kind AS s_kind, s.name AS s_name,
                               s.domain AS s_domain, s.status AS s_status,
                               s.confidence AS s_confidence, s.evidence_count AS s_evidence,
                               o.id AS o_id, o.kind AS o_kind, o.name AS o_name,
                               o.domain AS o_domain, o.status AS o_status,
                               o.confidence AS o_confidence, o.evidence_count AS o_evidence
                        FROM knowledge_edges e
                        JOIN knowledge_canonical_objects s
                          ON s.id = e.subject_id AND s.organization_id = e.organization_id
                        JOIN knowledge_canonical_objects o
                          ON o.id = e.object_id AND o.organization_id = e.organization_id
                        WHERE """
                        + " AND ".join(edge_clauses)
                        + " ORDER BY e.confidence DESC LIMIT :limit_edges"
                    ),
                    params,
                )
            ).fetchall()

            nodes: dict[str, dict] = {}
            edges: list[dict] = []

            def add_node(
                node_id, kind, name, domain, status, confidence, evidence_count
            ):
                if str(node_id) in nodes:
                    return
                if len(nodes) >= params["limit_nodes"]:
                    return
                nodes[str(node_id)] = {
                    "id": str(node_id),
                    "type": normalize_object_type(kind),
                    "name": name,
                    "domain": domain,
                    "status": normalize_object_status(status),
                    "confidence": confidence,
                    "evidence_count": evidence_count or 0,
                    "degree": 0,
                }

            for r in rows:
                add_node(
                    r.s_id, r.s_kind, r.s_name, r.s_domain, r.s_status,
                    r.s_confidence, r.s_evidence,
                )
                add_node(
                    r.o_id, r.o_kind, r.o_name, r.o_domain, r.o_status,
                    r.o_confidence, r.o_evidence,
                )
                if str(r.s_id) not in nodes or str(r.o_id) not in nodes:
                    continue
                nodes[str(r.s_id)]["degree"] += 1
                nodes[str(r.o_id)]["degree"] += 1
                edges.append(
                    {
                        "id": str(r.id),
                        "source": str(r.subject_id),
                        "target": str(r.object_id),
                        "predicate": r.predicate,
                        "relationship_type": r.relationship_type,
                        "confidence": r.confidence,
                        "status": r.status,
                        "provenance": r.provenance,
                        "evidence": _loads(r.evidence, []),
                    }
                )
            if not nodes:
                # Sin aristas: mostrar objetos reales igual (grafo vacío ≠ error).
                object_rows = await self.list_objects(
                    organization_id,
                    kinds=kinds,
                    limit=params["limit_nodes"],
                    order_by="evidence",
                )
                for item in object_rows:
                    add_node(
                        item["id"], item["kind"], item["name"], item["domain"],
                        item["status"], item["confidence"], item["evidence_count"],
                    )
            return {
                "nodes": list(nodes.values()),
                "edges": edges,
                "counts": {"nodes": len(nodes), "edges": len(edges)},
                "truncated": len(edges) >= params["limit_edges"],
                "focus_id": str(focus_id) if focus_id else None,
                "depth": depth,
            }
        finally:
            await session.close()

    async def stats(self, organization_id: UUID) -> dict:
        """Señales reales para overview/health. Cero real vs error se separa."""
        session = await get_async_session()
        try:
            by_kind = (
                await session.execute(
                    text(
                        """
                        SELECT kind, COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status IN ('verified','approved')) AS verified,
                               COUNT(*) FILTER (WHERE status = 'inferred') AS inferred,
                               COUNT(*) FILTER (WHERE confidence IS NULL) AS unscored
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                        GROUP BY kind
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            totals = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status IN ('verified','approved')) AS verified,
                               COUNT(*) FILTER (WHERE status = 'inferred') AS inferred,
                               COUNT(*) FILTER (WHERE status = 'discovered') AS discovered,
                               COUNT(*) FILTER (WHERE evidence_count = 0) AS unsupported,
                               COUNT(*) FILTER (WHERE description IS NULL OR description = '') AS undescribed,
                               MAX(updated_at) AS last_updated
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND kind NOT IN ('source','table','column','document','section','chunk')
                        """
                    ),
                    {"org": organization_id},
                )
            ).first()
            assertions = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status = 'verified') AS verified,
                               COUNT(*) FILTER (WHERE status = 'conflicted') AS conflicted,
                               COUNT(*) FILTER (WHERE status = 'stale') AS stale,
                               COUNT(*) FILTER (WHERE evidence_count = 0) AS unsupported,
                               COUNT(*) FILTER (WHERE confidence < 0.6
                                                AND status NOT IN ('verified','rejected')) AS low_confidence,
                               MAX(updated_at) AS last_updated
                        FROM knowledge_assertions
                        WHERE organization_id = :org
                        """
                    ),
                    {"org": organization_id},
                )
            ).first()
            evidence = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM evidence_ledger "
                        "WHERE organization_id = :org"
                    ),
                    {"org": organization_id},
                )
            ).first()
            edges = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status = 'verified') AS verified,
                               COUNT(*) FILTER (WHERE relationship_type = 'physical') AS physical,
                               COUNT(*) FILTER (WHERE relationship_type <> 'physical') AS semantic
                        FROM knowledge_edges WHERE organization_id = :org
                        """
                    ),
                    {"org": organization_id},
                )
            ).first()
            conflicts = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM knowledge_conflicts "
                        "WHERE organization_id = :org AND status IN ('open','investigating')"
                    ),
                    {"org": organization_id},
                )
            ).first()
            gaps = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE priority IN ('critical','high')) AS high,
                               COUNT(*) FILTER (WHERE status = 'resolved') AS resolved
                        FROM context_gaps WHERE organization_id = :org
                        """
                    ),
                    {"org": organization_id},
                )
            ).first()
            questions = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS pending FROM knowledge_questions "
                        "WHERE organization_id = :org AND status = 'pending'"
                    ),
                    {"org": organization_id},
                )
            ).first()
            sources = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE phase IN ('FAILED','PARTIAL')) AS degraded,
                               COUNT(*) FILTER (WHERE last_scan_at IS NULL
                                   OR last_scan_at < now() - make_interval(days => :days)) AS stale
                        FROM catalog_sources WHERE organization_id = :org
                        """
                    ),
                    {"org": organization_id, "days": _STALE_DAYS_DEFAULT},
                )
            ).first()
            indexed = (
                await session.execute(
                    text(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM kb_sources
                             WHERE organization_id = :org) AS sources,
                            (SELECT COUNT(*) FROM source_documents
                             WHERE organization_id = :org
                               AND status = 'active') AS documents
                        """
                    ),
                    {"org": organization_id},
                )
            ).first()
            kinds = {
                normalize_object_type(r.kind): {
                    "total": int(r.total or 0),
                    "verified": int(r.verified or 0),
                    "inferred": int(r.inferred or 0),
                    "unscored": int(r.unscored or 0),
                }
                for r in by_kind
            }
            return {
                "objects": {
                    "total": int(totals.total or 0),
                    "verified": int(totals.verified or 0),
                    "inferred": int(totals.inferred or 0),
                    "discovered": int(totals.discovered or 0),
                    "unsupported": int(totals.unsupported or 0),
                    "undescribed": int(totals.undescribed or 0),
                    "last_updated": _iso(totals.last_updated),
                },
                "by_kind": kinds,
                "assertions": {
                    "total": int(assertions.total or 0),
                    "verified": int(assertions.verified or 0),
                    "conflicted": int(assertions.conflicted or 0),
                    "stale": int(assertions.stale or 0),
                    "unsupported": int(assertions.unsupported or 0),
                    "low_confidence": int(assertions.low_confidence or 0),
                    "last_updated": _iso(assertions.last_updated),
                },
                "evidence": {"total": int(evidence.total or 0)},
                "edges": {
                    "total": int(edges.total or 0),
                    "verified": int(edges.verified or 0),
                    "physical": int(edges.physical or 0),
                    "semantic": int(edges.semantic or 0),
                },
                "conflicts": {"open": int(conflicts.total or 0)},
                "gaps": {
                    "total": int(gaps.total or 0),
                    "high": int(gaps.high or 0),
                    "resolved": int(gaps.resolved or 0),
                },
                "questions": {"pending": int(questions.pending or 0)},
                "sources": {
                    "total": int(sources.total or 0),
                    "degraded": int(sources.degraded or 0),
                    "stale": int(sources.stale or 0),
                },
                "indexed": {
                    "sources": int(indexed.sources or 0),
                    "documents": int(indexed.documents or 0),
                },
            }
        finally:
            await session.close()

    async def retrieval_signals(self, organization_id: UUID) -> dict:
        """Calidad RAG real: eval runs + trazas fallidas recientes."""
        session = await get_async_session()
        try:
            evaluation = None
            try:
                evaluation = (
                    await session.execute(
                        text(
                            """
                            SELECT summary, created_at FROM eval_runs
                            WHERE organization_id = :org
                              AND summary ? 'quality'
                            ORDER BY created_at DESC LIMIT 1
                            """
                        ),
                        {"org": organization_id},
                    )
                ).first()
            except Exception:  # noqa: BLE001
                evaluation = None
            traces = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status <> 'ANSWERABLE') AS failed
                        FROM intelligence_traces
                        WHERE organization_id = :org
                          AND created_at >= now() - interval '30 days'
                        """
                    ),
                    {"org": organization_id},
                )
            ).first()
            return {
                "evaluation": (
                    {
                        "summary": _loads(evaluation.summary, {}),
                        "created_at": _iso(evaluation.created_at),
                    }
                    if evaluation is not None
                    else None
                ),
                "traces": {
                    "total": int(traces.total or 0),
                    "failed": int(traces.failed or 0),
                },
            }
        finally:
            await session.close()

    # ------------------------------------------------------------------- gaps
    async def list_gaps(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        gap_type: str | None = None,
        priority: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            clauses = ["organization_id = :org"]
            params: dict = {"org": organization_id}
            if status:
                clauses.append("status = :status")
                params["status"] = status
            if gap_type:
                clauses.append("gap_type = :gap_type")
                params["gap_type"] = gap_type
            if priority:
                clauses.append("priority = :priority")
                params["priority"] = priority
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_GAP_COLS} FROM context_gaps "
                        f"WHERE {' AND '.join(clauses)} "
                        "ORDER BY priority_score DESC, last_seen_at DESC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    {**params, "limit": min(max(limit, 1), 300), "offset": max(offset, 0)},
                )
            ).fetchall()
            return [_gap_row(r) for r in rows]
        finally:
            await session.close()

    async def upsert_gap(
        self,
        organization_id: UUID,
        *,
        gap_type: str,
        concept: str,
        title: str,
        description: str | None = None,
        priority: str = "medium",
        priority_score: float = 0.0,
        object_id: UUID | None = None,
        source_id: UUID | None = None,
        impact: dict | None = None,
        impact_objects: int = 0,
        question: str | None = None,
        evidence_hints: list | None = None,
    ) -> UUID:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO context_gaps (
                            organization_id, gap_type, concept, title, description,
                            priority, priority_score, object_id, source_id, impact,
                            impact_objects, question, evidence_hints, status
                        ) VALUES (
                            :org, :gap_type, :concept, :title, :description,
                            :priority, :score, :object_id, :source_id,
                            CAST(:impact AS jsonb), :impact_objects, :question,
                            CAST(:hints AS jsonb), 'open'
                        )
                        ON CONFLICT (organization_id, gap_type, concept)
                        DO UPDATE SET
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            priority = EXCLUDED.priority,
                            priority_score = EXCLUDED.priority_score,
                            object_id = COALESCE(EXCLUDED.object_id, context_gaps.object_id),
                            source_id = COALESCE(EXCLUDED.source_id, context_gaps.source_id),
                            impact = EXCLUDED.impact,
                            impact_objects = EXCLUDED.impact_objects,
                            question = EXCLUDED.question,
                            occurrences = context_gaps.occurrences + 1,
                            last_seen_at = now(),
                            status = CASE WHEN context_gaps.status = 'resolved'
                                          THEN 'open' ELSE context_gaps.status END
                        RETURNING id
                        """
                    ),
                    {
                        "org": organization_id,
                        "gap_type": gap_type,
                        "concept": concept[:160],
                        "title": (title or concept)[:400],
                        "description": description,
                        "priority": priority,
                        "score": float(priority_score),
                        "object_id": object_id,
                        "source_id": source_id,
                        "impact": json.dumps(impact or {}, default=str),
                        "impact_objects": int(impact_objects),
                        "question": question,
                        "hints": json.dumps(evidence_hints or [], default=str),
                    },
                )
            ).first()
            await session.commit()
            return UUID(str(row.id))
        finally:
            await session.close()

    async def resolve_gap(
        self,
        organization_id: UUID,
        gap_id: UUID,
        *,
        user_id: UUID | None,
        status: str = "resolved",
        note: str | None = None,
    ) -> bool:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    """
                    UPDATE context_gaps SET
                        status = :status,
                        resolved_by = :user,
                        resolved_at = CASE WHEN :status IN ('resolved','ignored')
                                           THEN now() ELSE resolved_at END,
                        description = COALESCE(:note, description)
                    WHERE organization_id = :org AND id = :gid
                    """
                ),
                {
                    "org": organization_id,
                    "gid": gap_id,
                    "status": status,
                    "user": user_id,
                    "note": note,
                },
            )
            await session.commit()
            return bool(result.rowcount)
        finally:
            await session.close()

    # -------------------------------------------------------------- conflictos
    async def list_conflicts(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            clauses = ["organization_id = :org"]
            params: dict = {"org": organization_id}
            if status:
                clauses.append("status = :status")
                params["status"] = status
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_CONFLICT_COLS} FROM knowledge_conflicts "
                        f"WHERE {' AND '.join(clauses)} "
                        "ORDER BY (status = 'open') DESC, detected_at DESC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    {**params, "limit": min(max(limit, 1), 300), "offset": max(offset, 0)},
                )
            ).fetchall()
            return [_conflict_row(r) for r in rows]
        finally:
            await session.close()

    async def resolve_conflict(
        self,
        organization_id: UUID,
        conflict_id: UUID,
        *,
        resolution: str,
        resolved_value: str | None,
        user_id: UUID | None,
        reason: str | None,
    ) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"""
                        UPDATE knowledge_conflicts SET
                            status = 'resolved', resolution = :resolution,
                            resolved_value = :value, resolved_by = :user,
                            resolved_at = now(), reason = :reason, updated_at = now()
                        WHERE organization_id = :org AND id = :cid
                        RETURNING {_CONFLICT_COLS}
                        """
                    ),
                    {
                        "org": organization_id,
                        "cid": conflict_id,
                        "resolution": resolution,
                        "value": resolved_value,
                        "user": user_id,
                        "reason": reason,
                    },
                )
            ).first()
            if row is None:
                return None
            # La assertion canónica elegida pasa a verified/accepted.
            chosen = row.assertion_a if resolution == "chose_a" else row.assertion_b
            if resolution in ("chose_a", "chose_b") and chosen is not None:
                await session.execute(
                    text(
                        """
                        UPDATE knowledge_assertions SET
                            status = 'verified', provenance = 'APPROVED',
                            confidence = GREATEST(confidence, 0.9),
                            verified_by = :user, verified_at = now(), updated_at = now()
                        WHERE organization_id = :org AND id = :chosen
                        """
                    ),
                    {"org": organization_id, "chosen": chosen, "user": user_id},
                )
                other = row.assertion_b if resolution == "chose_a" else row.assertion_a
                if other is not None:
                    await session.execute(
                        text(
                            """
                            UPDATE knowledge_assertions SET
                                status = 'rejected', provenance = 'REJECTED', updated_at = now()
                            WHERE organization_id = :org AND id = :other
                            """
                        ),
                        {"org": organization_id, "other": other},
                    )
            await session.commit()
            return _conflict_row(row)
        finally:
            await session.close()

    # ------------------------------------------------------ verificación humana
    async def verify_object(
        self, organization_id: UUID, object_id: UUID, *, user_id: UUID | None
    ) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"""
                        UPDATE knowledge_canonical_objects SET
                            status = 'verified', provenance = 'APPROVED',
                            verified_by = :user, verified_at = now(), updated_at = now()
                        WHERE organization_id = :org AND id = :oid
                        RETURNING {_OBJECT_COLS}
                        """
                    ),
                    {"org": organization_id, "oid": object_id, "user": user_id},
                )
            ).first()
            await session.commit()
            return _object_row(row) if row else None
        finally:
            await session.close()

    async def verify_assertion(
        self, organization_id: UUID, assertion_id: UUID, *, user_id: UUID | None
    ) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"""
                        UPDATE knowledge_assertions SET
                            status = 'verified', provenance = 'APPROVED',
                            confidence = GREATEST(confidence, 0.9),
                            verified_by = :user, verified_at = now(),
                            version = version + 1, updated_at = now()
                        WHERE organization_id = :org AND id = :aid
                        RETURNING {_ASSERTION_COLS}
                        """
                    ),
                    {"org": organization_id, "aid": assertion_id, "user": user_id},
                )
            ).first()
            await session.commit()
            return _assertion_row(row) if row else None
        finally:
            await session.close()

    # --------------------------------------------------------------- actividad
    async def activity(
        self, organization_id: UUID, *, limit: int = 50, days: int = 30
    ) -> list[dict]:
        session = await get_async_session()
        try:
            items: list[dict] = []
            event_rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, event_type, message, severity, category, created_at
                        FROM knowledge_events
                        WHERE organization_id = :org
                        ORDER BY seq DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": min(limit, 200)},
                )
            ).fetchall()
            for r in event_rows:
                items.append(
                    {
                        "kind": "event",
                        "id": str(r.id),
                        "type": r.event_type,
                        "title": r.message or r.event_type,
                        "severity": r.severity,
                        "category": r.category,
                        "at": _iso(r.created_at),
                    }
                )
            object_rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, name, status, created_at, updated_at
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND updated_at >= now() - make_interval(days => :days)
                        ORDER BY updated_at DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "days": days, "limit": min(limit, 200)},
                )
            ).fetchall()
            for r in object_rows:
                change = (
                    "created"
                    if r.created_at is not None
                    and r.updated_at is not None
                    and abs((r.updated_at - r.created_at).total_seconds()) < 5
                    else "updated"
                )
                items.append(
                    {
                        "kind": "object",
                        "id": str(r.id),
                        "type": normalize_object_type(r.kind),
                        "title": f"{'Nuevo' if change == 'created' else 'Actualizado'}: {r.name}",
                        "status": normalize_object_status(r.status),
                        "at": _iso(r.updated_at),
                    }
                )
            assertion_rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, subject_label, predicate, object_value, status, created_at
                        FROM knowledge_assertions
                        WHERE organization_id = :org
                          AND created_at >= now() - make_interval(days => :days)
                        ORDER BY created_at DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "days": days, "limit": min(limit, 200)},
                )
            ).fetchall()
            for r in assertion_rows:
                items.append(
                    {
                        "kind": "assertion",
                        "id": str(r.id),
                        "type": "assertion",
                        "title": f"{r.subject_label} {r.predicate} {r.object_value or ''}".strip(),
                        "status": r.status,
                        "at": _iso(r.created_at),
                    }
                )
            items.sort(key=lambda i: i.get("at") or "", reverse=True)
            return items[: min(limit, 200)]
        finally:
            await session.close()

    async def last_run_summary(self, organization_id: UUID) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, catalog_source_id, status, current_stage,
                               overall_progress, entities_detected, fields_detected,
                               relationships_detected, metrics, error_summary,
                               started_at, finished_at, created_at
                        FROM knowledge_learning_runs
                        WHERE organization_id = :org
                        ORDER BY created_at DESC LIMIT 1
                        """
                    ),
                    {"org": organization_id},
                )
            ).first()
            if row is None:
                return None
            duration_ms = None
            if row.started_at and row.finished_at:
                duration_ms = round(
                    (row.finished_at - row.started_at).total_seconds() * 1000, 1
                )
            return {
                "id": str(row.id),
                "source_id": str(row.catalog_source_id) if row.catalog_source_id else None,
                "status": row.status,
                "current_stage": row.current_stage,
                "overall_progress": row.overall_progress,
                "entities_detected": row.entities_detected,
                "fields_detected": row.fields_detected,
                "relationships_detected": row.relationships_detected,
                "metrics": _loads(row.metrics, {}),
                "error_summary": _loads(row.error_summary, {}),
                "duration_ms": duration_ms,
                "started_at": _iso(row.started_at),
                "finished_at": _iso(row.finished_at),
                "created_at": _iso(row.created_at),
            }
        finally:
            await session.close()

    # ---------------------------------------------------------------- quality
    async def quality_findings(self, organization_id: UUID, *, limit: int = 25) -> dict:
        """Hallazgos reales de calidad. Cada lista viene de una tabla real."""
        session = await get_async_session()
        try:
            findings: dict[str, list[dict]] = {}
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, subject_label, predicate, object_value, confidence,
                               status, method, source_id, updated_at
                        FROM knowledge_assertions
                        WHERE organization_id = :org
                          AND confidence < 0.6
                          AND status NOT IN ('verified','rejected')
                        ORDER BY confidence ASC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": limit},
                )
            ).fetchall()
            findings["low_confidence_assertions"] = [
                {
                    "id": str(r.id),
                    "subject": r.subject_label,
                    "predicate": r.predicate,
                    "value": r.object_value,
                    "confidence": r.confidence,
                    "status": r.status,
                    "method": r.method,
                    "source_id": str(r.source_id) if r.source_id else None,
                    "updated_at": _iso(r.updated_at),
                }
                for r in rows
            ]
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, subject_label, predicate, object_value, confidence,
                               method, updated_at
                        FROM knowledge_assertions
                        WHERE organization_id = :org AND evidence_count = 0
                          AND status NOT IN ('rejected')
                        ORDER BY updated_at DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": limit},
                )
            ).fetchall()
            findings["unsupported_assertions"] = [
                {
                    "id": str(r.id),
                    "subject": r.subject_label,
                    "predicate": r.predicate,
                    "value": r.object_value,
                    "confidence": r.confidence,
                    "method": r.method,
                    "updated_at": _iso(r.updated_at),
                }
                for r in rows
            ]
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, name, domain, status, confidence, freshness_at,
                               updated_at
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND freshness_at IS NOT NULL
                          AND freshness_at < now() - make_interval(days => :days)
                          AND kind NOT IN ('source','table','column')
                        ORDER BY freshness_at ASC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": limit, "days": _STALE_DAYS_DEFAULT},
                )
            ).fetchall()
            findings["stale_objects"] = [
                {
                    "id": str(r.id),
                    "type": normalize_object_type(r.kind),
                    "name": r.name,
                    "domain": r.domain,
                    "status": normalize_object_status(r.status),
                    "confidence": r.confidence,
                    "freshness_at": _iso(r.freshness_at),
                    "updated_at": _iso(r.updated_at),
                }
                for r in rows
            ]
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT e.id, e.name, e.domain, e.status, e.confidence,
                               (SELECT COUNT(*) FROM knowledge_edges g
                                WHERE g.organization_id = e.organization_id
                                  AND (g.subject_id = e.id OR g.object_id = e.id)) AS degree
                        FROM knowledge_canonical_objects e
                        WHERE e.organization_id = :org AND e.kind = 'entity'
                          AND NOT EXISTS (
                            SELECT 1 FROM knowledge_canonical_objects a
                            WHERE a.organization_id = e.organization_id
                              AND a.kind = 'attribute'
                              AND EXISTS (
                                SELECT 1 FROM knowledge_edges x
                                WHERE x.organization_id = e.organization_id
                                  AND x.subject_id = e.id AND x.object_id = a.id
                              )
                          )
                        ORDER BY e.name LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": limit},
                )
            ).fetchall()
            findings["orphan_entities"] = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "domain": r.domain,
                    "status": normalize_object_status(r.status),
                    "confidence": r.confidence,
                    "degree": int(r.degree or 0),
                }
                for r in rows
            ]
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, name, domain FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND (description IS NULL OR description = '')
                          AND kind IN ('entity','metric','business_rule','term','process','concept')
                        ORDER BY name LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": limit},
                )
            ).fetchall()
            findings["missing_descriptions"] = [
                {
                    "id": str(r.id),
                    "type": normalize_object_type(r.kind),
                    "name": r.name,
                    "domain": r.domain,
                }
                for r in rows
            ]
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT trace_id, user_query, status, created_at
                        FROM intelligence_traces
                        WHERE organization_id = :org AND status <> 'ANSWERABLE'
                          AND created_at >= now() - interval '30 days'
                        ORDER BY created_at DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": limit},
                )
            ).fetchall()
            findings["retrieval_failures"] = [
                {
                    "id": r.trace_id,
                    "query": r.user_query,
                    "status": r.status,
                    "at": _iso(r.created_at),
                }
                for r in rows
            ]
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT s.id, s.phase, s.scan_error, s.last_scan_at,
                               c.name AS connector_name
                        FROM catalog_sources s
                        LEFT JOIN connectors c ON c.id = s.connector_id
                        WHERE s.organization_id = :org
                          AND (s.phase IN ('FAILED','PARTIAL') OR s.scan_error IS NOT NULL)
                        ORDER BY s.updated_at DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": limit},
                )
            ).fetchall()
            findings["source_failures"] = [
                {
                    "id": str(r.id),
                    "name": r.connector_name or "Fuente",
                    "phase": r.phase,
                    "error": (r.scan_error or "")[:400] or None,
                    "last_scan_at": _iso(r.last_scan_at),
                }
                for r in rows
            ]
            return findings
        finally:
            await session.close()

    async def pending_questions(
        self, organization_id: UUID, *, limit: int = 100
    ) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, question_type, title, body, evidence, priority,
                               priority_score, impact, status, source_id, entity_id,
                               created_at
                        FROM knowledge_questions
                        WHERE organization_id = :org AND status = 'pending'
                        ORDER BY priority_score DESC, created_at DESC LIMIT :limit
                        """
                    ),
                    {"org": organization_id, "limit": min(limit, 300)},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "question_type": r.question_type,
                    "title": r.title,
                    "body": r.body,
                    "evidence": _loads(r.evidence, []),
                    "priority": r.priority,
                    "priority_score": r.priority_score,
                    "impact": _loads(r.impact, {}),
                    "status": r.status,
                    "source_id": str(r.source_id) if r.source_id else None,
                    "entity_id": str(r.entity_id) if r.entity_id else None,
                    "created_at": _iso(r.created_at),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def source_authority_map(self, organization_id: UUID) -> dict[str, str]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT source_name, authority_level FROM catalog_authority
                        WHERE organization_id = :org
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            return {
                str(r.source_name): str(r.authority_level) for r in rows
            }
        finally:
            await session.close()
