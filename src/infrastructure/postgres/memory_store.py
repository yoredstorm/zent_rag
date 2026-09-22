# =============================================================================
# Memory foundation — Postgres, tenant-scoped.
# memory_events es append-only. Los UPDATE de memory_records filtran
# organization_id. No hay aprendizaje global entre tenants.
# =============================================================================
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.memory import (
    MemoryEvent,
    MemoryEventType,
    MemoryEvidenceKind,
    MemoryEvidenceLink,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from src.core.ports.memory import MemoryRepository
from src.infrastructure.postgres.session import get_async_session
from src.memory.repository import _match_score

_tx: ContextVar[AsyncSession | None] = ContextVar("memory_pg_tx", default=None)

_LEDGER_EXISTS = {
    MemoryEvidenceKind.CLAIM: (
        "SELECT 1 FROM claim_ledger WHERE organization_id = :oid AND id = :id LIMIT 1"
    ),
    MemoryEvidenceKind.EVIDENCE_LEDGER: (
        "SELECT 1 FROM evidence_ledger WHERE organization_id = :oid AND id = :id LIMIT 1"
    ),
}


def _dumps(value: dict) -> str:
    return json.dumps(value or {}, default=str)


def _loads(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _record(row: Any) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        organization_id=row["organization_id"],
        visibility=MemoryVisibility(row["visibility"]),
        memory_type=MemoryType(row["memory_type"]),
        title=row["title"],
        description=row["description"] or "",
        pattern_key=row["pattern_key"],
        pattern_signature=row["pattern_signature"],
        status=MemoryStatus(row["status"]),
        confidence=float(row["confidence"] or 0),
        support_count=int(row["support_count"] or 0),
        contradiction_count=int(row["contradiction_count"] or 0),
        success_count=int(row["success_count"] or 0),
        first_observed_at=row["first_observed_at"],
        last_observed_at=row["last_observed_at"],
        validated_at=row["validated_at"],
        activated_at=row["activated_at"],
        created_from_conversation_id=row["created_from_conversation_id"],
        created_from_run_id=row["created_from_run_id"],
        intent_family=row["intent_family"] or "",
        source_type=row["source_type"] or "",
        retrieval_modality=row["retrieval_modality"] or "",
        tool_family=row["tool_family"] or "",
        failure_category=row["failure_category"] or "",
        success_signal=row["success_signal"] or "",
        source_component=row["source_component"] or "",
        agent_id=row["agent_id"],
        workflow_id=row["workflow_id"],
        metadata=_loads(row["metadata"]),
        version=int(row["version"] or 1),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _event(row: Any) -> MemoryEvent:
    return MemoryEvent(
        id=row["id"],
        organization_id=row["organization_id"],
        memory_id=row["memory_id"],
        conversation_id=row["conversation_id"],
        run_id=row["run_id"],
        request_id=row["request_id"],
        agent_id=row["agent_id"],
        workflow_id=row["workflow_id"],
        event_type=MemoryEventType(row["event_type"]),
        source_component=row["source_component"] or "",
        phase=row["phase"] or "",
        outcome=row["outcome"] or "",
        idempotency_key=row["idempotency_key"],
        metadata=_loads(row["metadata"]),
        created_at=row["created_at"],
    )


def _link(row: Any) -> MemoryEvidenceLink:
    return MemoryEvidenceLink(
        id=row["id"],
        organization_id=row["organization_id"],
        memory_id=row["memory_id"],
        kind=MemoryEvidenceKind(row["kind"]),
        ref_id=row["ref_id"],
        ref_label=row["ref_label"] or "",
        created_at=row["created_at"],
    )


class PostgresMemoryRepository(MemoryRepository):
    @asynccontextmanager
    async def exclusive(self):
        session = await get_async_session()
        token = _tx.set(session)
        try:
            yield
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            _tx.reset(token)
            await session.close()

    async def _run(self, sql: str, params: dict[str, Any], *, fetch: str = "all"):
        current = _tx.get()
        owns = current is None
        session = current if current is not None else await get_async_session()
        try:
            result = await session.execute(text(sql), params)
            if fetch == "one":
                row = result.mappings().first()
            elif fetch == "all":
                row = result.mappings().all()
            else:
                row = result.rowcount
            if owns:
                await session.commit()
            return row
        except Exception:
            if owns:
                await session.rollback()
            raise
        finally:
            if owns:
                await session.close()

    async def get(self, organization_id: UUID, memory_id: UUID) -> MemoryRecord | None:
        row = await self._run(
            """
            SELECT * FROM memory_records
            WHERE organization_id = :oid AND id = :id
            """,
            {"oid": organization_id, "id": memory_id},
            fetch="one",
        )
        return _record(row) if row else None

    async def find_live(
        self,
        organization_id: UUID,
        memory_type: MemoryType,
        pattern_signature: str,
    ) -> MemoryRecord | None:
        sql = """
            SELECT * FROM memory_records
            WHERE organization_id = :oid
              AND memory_type = :memory_type
              AND pattern_signature = :signature
              AND visibility = 'tenant'
              AND status NOT IN ('rejected', 'expired', 'superseded')
            ORDER BY updated_at DESC
            LIMIT 1
            """
        if _tx.get() is not None:
            sql = """
            SELECT * FROM memory_records
            WHERE organization_id = :oid
              AND memory_type = :memory_type
              AND pattern_signature = :signature
              AND visibility = 'tenant'
              AND status NOT IN ('rejected', 'expired', 'superseded')
            ORDER BY updated_at DESC
            LIMIT 1
            FOR UPDATE
            """
        row = await self._run(
            sql,
            {
                "oid": organization_id,
                "memory_type": memory_type.value,
                "signature": pattern_signature,
            },
            fetch="one",
        )
        return _record(row) if row else None

    async def insert(self, record: MemoryRecord) -> MemoryRecord:
        if record.visibility != MemoryVisibility.TENANT:
            raise ValueError("product-scope memory is not enabled")
        await self._run(
            """
            INSERT INTO memory_records (
                id, organization_id, visibility, memory_type, title, description,
                pattern_key, pattern_signature, status, confidence, support_count,
                contradiction_count, success_count, first_observed_at, last_observed_at,
                validated_at, activated_at, created_from_conversation_id, created_from_run_id,
                intent_family, source_type, retrieval_modality, tool_family, failure_category,
                success_signal, source_component, agent_id, workflow_id, metadata, version,
                created_at, updated_at
            ) VALUES (
                :id, :organization_id, :visibility, :memory_type, :title, :description,
                :pattern_key, :pattern_signature, :status, :confidence, :support_count,
                :contradiction_count, :success_count, :first_observed_at, :last_observed_at,
                :validated_at, :activated_at, :created_from_conversation_id, :created_from_run_id,
                :intent_family, :source_type, :retrieval_modality, :tool_family, :failure_category,
                :success_signal, :source_component, :agent_id, :workflow_id,
                CAST(:metadata AS jsonb), :version, :created_at, :updated_at
            )
            """,
            _record_params(record),
            fetch="none",
        )
        return record

    async def save(self, record: MemoryRecord) -> MemoryRecord:
        expected = record.version
        record.version = expected + 1
        record.updated_at = record.updated_at
        rowcount = await self._run(
            """
            UPDATE memory_records SET
                title = :title,
                description = :description,
                pattern_key = :pattern_key,
                status = :status,
                confidence = :confidence,
                support_count = :support_count,
                contradiction_count = :contradiction_count,
                success_count = :success_count,
                last_observed_at = :last_observed_at,
                validated_at = :validated_at,
                activated_at = :activated_at,
                success_signal = :success_signal,
                metadata = CAST(:metadata AS jsonb),
                version = :version,
                updated_at = :updated_at
            WHERE id = :id
              AND organization_id = :organization_id
              AND version = :expected_version
            """,
            {**_record_params(record), "expected_version": expected},
            fetch="none",
        )
        if not rowcount:
            record.version = expected
            raise KeyError("memory not found for organization")
        return record

    async def find_event_idempotency(
        self, organization_id: UUID, idempotency_key: str
    ) -> MemoryEvent | None:
        if not idempotency_key:
            return None
        row = await self._run(
            """
            SELECT * FROM memory_events
            WHERE organization_id = :oid AND idempotency_key = :key
            LIMIT 1
            """,
            {"oid": organization_id, "key": idempotency_key},
            fetch="one",
        )
        return _event(row) if row else None

    async def append_event(self, event: MemoryEvent) -> MemoryEvent:
        if event.idempotency_key:
            prior = await self.find_event_idempotency(event.organization_id, event.idempotency_key)
            if prior is not None:
                return prior
        await self._run(
            """
            INSERT INTO memory_events (
                id, organization_id, memory_id, conversation_id, run_id, request_id,
                agent_id, workflow_id, event_type, source_component, phase, outcome,
                idempotency_key, metadata, created_at
            ) VALUES (
                :id, :organization_id, :memory_id, :conversation_id, :run_id, :request_id,
                :agent_id, :workflow_id, :event_type, :source_component, :phase, :outcome,
                :idempotency_key, CAST(:metadata AS jsonb), :created_at
            )
            """,
            {
                "id": event.id,
                "organization_id": event.organization_id,
                "memory_id": event.memory_id,
                "conversation_id": event.conversation_id,
                "run_id": event.run_id,
                "request_id": event.request_id,
                "agent_id": event.agent_id,
                "workflow_id": event.workflow_id,
                "event_type": event.event_type.value,
                "source_component": event.source_component,
                "phase": event.phase,
                "outcome": event.outcome,
                "idempotency_key": event.idempotency_key,
                "metadata": _dumps(dict(event.metadata)),
                "created_at": event.created_at,
            },
            fetch="none",
        )
        return event

    async def add_evidence(self, link: MemoryEvidenceLink) -> MemoryEvidenceLink:
        owner = await self.get(link.organization_id, link.memory_id)
        if owner is None:
            raise KeyError("memory not found for organization")
        await self._run(
            """
            INSERT INTO memory_evidence (
                id, organization_id, memory_id, kind, ref_id, ref_label, created_at
            ) VALUES (
                :id, :organization_id, :memory_id, :kind, :ref_id, :ref_label, :created_at
            )
            """,
            {
                "id": link.id,
                "organization_id": link.organization_id,
                "memory_id": link.memory_id,
                "kind": link.kind.value,
                "ref_id": link.ref_id,
                "ref_label": link.ref_label,
                "created_at": link.created_at,
            },
            fetch="none",
        )
        return link

    async def list_records(
        self,
        organization_id: UUID,
        *,
        memory_type: str | None = None,
        status: str | None = None,
        agent_id: UUID | None = None,
        source_component: str | None = None,
        pattern: str | None = None,
        confidence_min: float | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        params: dict[str, Any] = {
            "oid": organization_id,
            "memory_type": memory_type,
            "status": status,
            "agent_id": agent_id,
            "source_component": source_component,
            "pattern": f"%{pattern[:80]}%" if pattern else None,
            "confidence_min": confidence_min,
            "updated_from": updated_from,
            "updated_to": updated_to,
            "limit": min(limit, 100),
            "offset": max(offset, 0),
        }
        rows = await self._run(
            """
            SELECT * FROM memory_records
            WHERE organization_id = :oid
              AND visibility = 'tenant'
              AND (:memory_type IS NULL OR memory_type = :memory_type)
              AND (:status IS NULL OR status = :status)
              AND (:agent_id IS NULL OR agent_id = :agent_id)
              AND (:source_component IS NULL OR source_component = :source_component)
              AND (
                    :pattern IS NULL
                    OR pattern_key ILIKE :pattern
                    OR pattern_signature ILIKE :pattern
              )
              AND (:confidence_min IS NULL OR confidence >= :confidence_min)
              AND (:updated_from IS NULL OR updated_at >= :updated_from)
              AND (:updated_to IS NULL OR updated_at <= :updated_to)
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
            fetch="all",
        )
        return [_record(row) for row in rows]

    async def list_events(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEvent]:
        rows = await self._run(
            """
            SELECT e.* FROM memory_events e
            JOIN memory_records m
              ON m.id = e.memory_id AND m.organization_id = e.organization_id
            WHERE e.organization_id = :oid AND e.memory_id = :mid
            ORDER BY e.created_at ASC
            LIMIT :limit OFFSET :offset
            """,
            {
                "oid": organization_id,
                "mid": memory_id,
                "limit": min(limit, 500),
                "offset": max(offset, 0),
            },
            fetch="all",
        )
        return [_event(row) for row in rows]

    async def list_evidence(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEvidenceLink]:
        rows = await self._run(
            """
            SELECT ev.* FROM memory_evidence ev
            JOIN memory_records m
              ON m.id = ev.memory_id AND m.organization_id = ev.organization_id
            WHERE ev.organization_id = :oid AND ev.memory_id = :mid
            ORDER BY ev.created_at ASC
            LIMIT :limit OFFSET :offset
            """,
            {
                "oid": organization_id,
                "mid": memory_id,
                "limit": min(limit, 100),
                "offset": max(offset, 0),
            },
            fetch="all",
        )
        return [_link(row) for row in rows]

    async def list_conversations(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = await self._run(
            """
            SELECT DISTINCT conversation_id, run_id
            FROM memory_events
            WHERE organization_id = :oid
              AND memory_id = :mid
              AND conversation_id IS NOT NULL
            ORDER BY conversation_id
            LIMIT :limit OFFSET :offset
            """,
            {
                "oid": organization_id,
                "mid": memory_id,
                "limit": min(limit, 100),
                "offset": max(offset, 0),
            },
            fetch="all",
        )
        return [
            {
                "conversation_id": str(row["conversation_id"]),
                "run_id": str(row["run_id"]) if row["run_id"] else None,
            }
            for row in rows
        ]

    async def events_for_scope(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> list[MemoryEvent]:
        if run_id is None and conversation_id is None:
            return []
        rows = await self._run(
            """
            SELECT * FROM memory_events
            WHERE organization_id = :oid
              AND (
                    (:run_id IS NOT NULL AND run_id = :run_id)
                 OR (:conversation_id IS NOT NULL AND conversation_id = :conversation_id)
              )
            ORDER BY created_at ASC
            """,
            {"oid": organization_id, "run_id": run_id, "conversation_id": conversation_id},
            fetch="all",
        )
        return [_event(row) for row in rows]

    async def events_for_request(
        self,
        organization_id: UUID,
        request_id: UUID,
        *,
        limit: int = 101,
    ) -> list[MemoryEvent]:
        rows = await self._run(
            """
            SELECT * FROM memory_events
            WHERE organization_id = :oid
              AND request_id = :request_id
            ORDER BY created_at ASC
            LIMIT :limit
            """,
            {"oid": organization_id, "request_id": request_id, "limit": limit},
            fetch="all",
        )
        return [_event(row) for row in rows]

    async def recall_candidates(
        self,
        organization_id: UUID,
        *,
        signature: str,
        intent_family: str,
        source_type: str,
        retrieval_modality: str,
        tool_family: str,
        failure_category: str,
        memory_types: tuple[str, ...],
        limit: int,
    ) -> list[MemoryRecord]:
        params = {
            "oid": organization_id,
            "signature": signature,
            "intent_family": intent_family,
            "tool_family": tool_family,
            "failure_category": failure_category,
            "use_intent": _usable(intent_family, {"unknown_intent"}),
            "use_tool": _usable(tool_family, {"none"}),
            "use_failure": _usable(failure_category, {"none"}),
            "memory_types": list(memory_types),
            "limit": min(max(limit, 1) * 5, 40),
        }
        if not (
            signature
            or params["use_intent"]
            or params["use_tool"]
            or params["use_failure"]
        ):
            return []
        rows = await self._run(
            """
            SELECT * FROM memory_records
            WHERE organization_id = :oid
              AND visibility = 'tenant'
              AND status = 'active'
              AND memory_type = ANY(CAST(:memory_types AS text[]))
              AND (
                    pattern_signature = :signature
                    OR (:use_intent AND intent_family = :intent_family)
                    OR (:use_tool AND tool_family = :tool_family)
                    OR (:use_failure AND failure_category = :failure_category)
              )
            ORDER BY confidence DESC, support_count DESC
            LIMIT :limit
            """,
            params,
            fetch="all",
        )
        ranked = [
            (
                _match_score(
                    record,
                    signature=signature,
                    intent_family=intent_family,
                    source_type=source_type,
                    retrieval_modality=retrieval_modality,
                    tool_family=tool_family,
                    failure_category=failure_category,
                ),
                record,
            )
            for record in (_record(row) for row in rows)
        ]
        ranked = [item for item in ranked if item[0] > 0]
        ranked.sort(key=lambda item: (item[0], item[1].confidence, item[1].support_count), reverse=True)
        return [record for _, record in ranked[:limit]]


class LedgerKnowledgeChecker:
    """Confirma que el ref vive en claim_ledger o evidence_ledger del mismo tenant."""

    async def has_backing(self, organization_id: UUID, links: list[MemoryEvidenceLink]) -> bool:
        session = await get_async_session()
        try:
            for link in links:
                if link.ref_id is None:
                    continue
                sql = _LEDGER_EXISTS.get(link.kind)
                if sql is None:
                    continue
                row = (
                    await session.execute(
                        text(sql),
                        {"oid": organization_id, "id": link.ref_id},
                    )
                ).first()
                if row is not None:
                    return True
            return False
        finally:
            await session.close()


def _usable(value: str, blanks: set[str]) -> bool:
    return bool(value) and value not in blanks and value != "unclassified"


def _record_params(record: MemoryRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "organization_id": record.organization_id,
        "visibility": record.visibility.value,
        "memory_type": record.memory_type.value,
        "title": record.title,
        "description": record.description,
        "pattern_key": record.pattern_key,
        "pattern_signature": record.pattern_signature,
        "status": record.status.value,
        "confidence": record.confidence,
        "support_count": record.support_count,
        "contradiction_count": record.contradiction_count,
        "success_count": record.success_count,
        "first_observed_at": record.first_observed_at,
        "last_observed_at": record.last_observed_at,
        "validated_at": record.validated_at,
        "activated_at": record.activated_at,
        "created_from_conversation_id": record.created_from_conversation_id,
        "created_from_run_id": record.created_from_run_id,
        "intent_family": record.intent_family,
        "source_type": record.source_type,
        "retrieval_modality": record.retrieval_modality,
        "tool_family": record.tool_family,
        "failure_category": record.failure_category,
        "success_signal": record.success_signal,
        "source_component": record.source_component,
        "agent_id": record.agent_id,
        "workflow_id": record.workflow_id,
        "metadata": _dumps(record.metadata),
        "version": record.version,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
