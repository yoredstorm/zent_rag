# =============================================================================
# In-memory MemoryRepository — tests y doble del puerto.
# El lock cubre la sección exclusiva. Las lecturas filtran organization_id.
# =============================================================================
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.domain.memory import (
    TERMINAL_STATUSES,
    MemoryEvent,
    MemoryEvidenceLink,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
)
from src.core.ports.memory import MemoryRepository


class InMemoryMemoryRepository(MemoryRepository):
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.records: dict[UUID, MemoryRecord] = {}
        self.events: list[MemoryEvent] = []
        self.evidence: list[MemoryEvidenceLink] = []

    @asynccontextmanager
    async def exclusive(self):
        async with self._lock:
            yield

    async def get(self, organization_id: UUID, memory_id: UUID) -> MemoryRecord | None:
        record = self.records.get(memory_id)
        if record is None or record.organization_id != organization_id:
            return None
        return record

    async def find_live(
        self,
        organization_id: UUID,
        memory_type: MemoryType,
        pattern_signature: str,
    ) -> MemoryRecord | None:
        for record in self.records.values():
            if record.organization_id != organization_id:
                continue
            if record.memory_type != memory_type:
                continue
            if record.pattern_signature != pattern_signature:
                continue
            if record.status in TERMINAL_STATUSES:
                continue
            return record
        return None

    async def insert(self, record: MemoryRecord) -> MemoryRecord:
        if record.id in self.records:
            raise ValueError("memory id already exists")
        self.records[record.id] = record
        return record

    async def save(self, record: MemoryRecord) -> MemoryRecord:
        current = self.records.get(record.id)
        if current is None or current.organization_id != record.organization_id:
            raise KeyError("memory not found for organization")
        record.version = current.version + 1
        self.records[record.id] = record
        return record

    async def find_event_idempotency(
        self, organization_id: UUID, idempotency_key: str
    ) -> MemoryEvent | None:
        if not idempotency_key:
            return None
        for event in self.events:
            if (
                event.organization_id == organization_id
                and event.idempotency_key == idempotency_key
            ):
                return event
        return None

    async def append_event(self, event: MemoryEvent) -> MemoryEvent:
        if event.idempotency_key:
            prior = await self.find_event_idempotency(
                event.organization_id, event.idempotency_key
            )
            if prior is not None:
                return prior
        self.events.append(event)
        return event

    async def add_evidence(self, link: MemoryEvidenceLink) -> MemoryEvidenceLink:
        record = await self.get(link.organization_id, link.memory_id)
        if record is None:
            raise KeyError("memory not found for organization")
        self.evidence.append(link)
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
        rows = [row for row in self.records.values() if row.organization_id == organization_id]
        if memory_type:
            rows = [row for row in rows if row.memory_type.value == memory_type]
        if status:
            rows = [row for row in rows if row.status.value == status]
        if agent_id is not None:
            rows = [row for row in rows if row.agent_id == agent_id]
        if source_component:
            rows = [row for row in rows if row.source_component == source_component]
        if pattern:
            needle = pattern.lower()
            rows = [
                row
                for row in rows
                if needle in row.pattern_key.lower() or needle in row.pattern_signature.lower()
            ]
        if confidence_min is not None:
            rows = [row for row in rows if row.confidence >= confidence_min]
        if updated_from is not None:
            rows = [row for row in rows if row.updated_at >= updated_from]
        if updated_to is not None:
            rows = [row for row in rows if row.updated_at <= updated_to]
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows[offset : offset + limit]

    async def list_events(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEvent]:
        rows = [
            event
            for event in self.events
            if event.organization_id == organization_id and event.memory_id == memory_id
        ]
        rows.sort(key=lambda event: event.created_at)
        return rows[offset : offset + limit]

    async def list_evidence(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEvidenceLink]:
        rows = [
            link
            for link in self.evidence
            if link.organization_id == organization_id and link.memory_id == memory_id
        ]
        return rows[offset : offset + limit]

    async def list_conversations(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        known: set[str] = set()
        for event in self.events:
            if event.organization_id != organization_id or event.memory_id != memory_id:
                continue
            if event.conversation_id is None:
                continue
            key = str(event.conversation_id)
            if key in known:
                continue
            known.add(key)
            seen.append(
                {
                    "conversation_id": key,
                    "run_id": str(event.run_id) if event.run_id else None,
                }
            )
        return seen[offset : offset + limit]

    async def events_for_scope(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> list[MemoryEvent]:
        rows: list[MemoryEvent] = []
        for event in self.events:
            if event.organization_id != organization_id:
                continue
            if run_id is not None and event.run_id == run_id:
                rows.append(event)
                continue
            if conversation_id is not None and event.conversation_id == conversation_id:
                rows.append(event)
        return rows

    async def events_for_request(
        self,
        organization_id: UUID,
        request_id: UUID,
        *,
        limit: int = 101,
    ) -> list[MemoryEvent]:
        rows = [
            event
            for event in self.events
            if event.organization_id == organization_id and event.request_id == request_id
        ]
        rows.sort(key=lambda event: event.created_at)
        return rows[:limit]

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
        ranked: list[tuple[int, MemoryRecord]] = []
        for record in self.records.values():
            if record.organization_id != organization_id:
                continue
            if record.status != MemoryStatus.ACTIVE:
                continue
            if memory_types and record.memory_type.value not in memory_types:
                continue
            score = _match_score(
                record,
                signature=signature,
                intent_family=intent_family,
                source_type=source_type,
                retrieval_modality=retrieval_modality,
                tool_family=tool_family,
                failure_category=failure_category,
            )
            if score <= 0:
                continue
            ranked.append((score, record))
        ranked.sort(key=lambda item: (item[0], item[1].confidence, item[1].support_count), reverse=True)
        return [record for _, record in ranked[:limit]]


def _match_score(
    record: MemoryRecord,
    *,
    signature: str,
    intent_family: str,
    source_type: str,
    retrieval_modality: str,
    tool_family: str,
    failure_category: str,
) -> int:
    """Firma exacta, o coincidencia de intent/tool/fallo. Una modalidad sola no basta."""
    if signature and record.pattern_signature == signature:
        return 100
    intent_ok = _specific(intent_family, {"unknown_intent"}) and record.intent_family == intent_family
    tool_ok = _specific(tool_family, {"none"}) and record.tool_family == tool_family
    failure_ok = _specific(failure_category, {"none"}) and record.failure_category == failure_category
    if not (intent_ok or tool_ok or failure_ok):
        return 0
    score = 0
    if intent_ok:
        score += 40
    if tool_ok:
        score += 20
    if failure_ok:
        score += 30
    if _specific(source_type, {"unknown_source"}) and record.source_type == source_type:
        score += 15
    if _specific(retrieval_modality, {"unknown_retrieval"}) and record.retrieval_modality == retrieval_modality:
        score += 15
    return score


def _specific(value: str, extra_blanks: set[str]) -> bool:
    return bool(value) and value not in extra_blanks and value != "unclassified"
