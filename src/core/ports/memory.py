# =============================================================================
# Port — Memory repository. Toda operación exige organization_id.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.domain.memory import MemoryEvent, MemoryEvidenceLink, MemoryRecord, MemoryType


class MemoryRepository(ABC):
    @abstractmethod
    def exclusive(self) -> AbstractAsyncContextManager[None]:
        """Sección crítica tenant-safe para crear o reforzar."""

    @abstractmethod
    async def get(self, organization_id: UUID, memory_id: UUID) -> MemoryRecord | None:
        ...

    @abstractmethod
    async def find_live(
        self,
        organization_id: UUID,
        memory_type: MemoryType,
        pattern_signature: str,
    ) -> MemoryRecord | None:
        ...

    @abstractmethod
    async def insert(self, record: MemoryRecord) -> MemoryRecord:
        ...

    @abstractmethod
    async def save(self, record: MemoryRecord) -> MemoryRecord:
        ...

    @abstractmethod
    async def find_event_idempotency(
        self, organization_id: UUID, idempotency_key: str
    ) -> MemoryEvent | None:
        ...

    @abstractmethod
    async def append_event(self, event: MemoryEvent) -> MemoryEvent:
        ...

    @abstractmethod
    async def add_evidence(self, link: MemoryEvidenceLink) -> MemoryEvidenceLink:
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def list_events(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEvent]:
        ...

    @abstractmethod
    async def list_evidence(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEvidenceLink]:
        ...

    @abstractmethod
    async def list_conversations(
        self,
        organization_id: UUID,
        memory_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def events_for_scope(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> list[MemoryEvent]:
        ...

    @abstractmethod
    async def events_for_request(
        self,
        organization_id: UUID,
        request_id: UUID,
        *,
        limit: int = 101,
    ) -> list[MemoryEvent]:
        ...

    @abstractmethod
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
        ...
