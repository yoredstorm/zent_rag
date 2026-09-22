# =============================================================================
# Domain — Memory Foundation (observación, no auto-optimización)
# =============================================================================
# Cuatro tipos: conversation, knowledge, operational, learning.
# La conversación produce MemoryEvent. MemoryRecord es el agregado.
# ACTIVE significa "elegible para recall dentro de políticas", nunca
# permiso para mutar prompts, thresholds, modelos ni configuración.
#
# Knowledge Memory apunta a Evidence Ledger / Claim Ledger. No es un hecho
# por haber salido de un LLM.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryType(StrEnum):
    CONVERSATION = "conversation"
    KNOWLEDGE = "knowledge"
    OPERATIONAL = "operational"
    LEARNING = "learning"


class MemoryStatus(StrEnum):
    OBSERVED = "observed"
    REINFORCED = "reinforced"
    PATTERN = "pattern"
    VALIDATED = "validated"
    ACTIVE = "active"
    CONTRADICTED = "contradicted"
    STALE = "stale"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class MemoryVisibility(StrEnum):
    """tenant: privada del organization_id. product: reservada, no se escribe."""

    TENANT = "tenant"
    PRODUCT = "product"


class MemoryEventType(StrEnum):
    OBSERVED = "memory.observed"
    CREATED = "memory.created"
    USED = "memory.used"
    REINFORCED = "memory.reinforced"
    CONTRADICTED = "memory.contradicted"
    VALIDATED = "memory.validated"
    ACTIVATED = "memory.activated"
    DEACTIVATED = "memory.deactivated"
    REJECTED = "memory.rejected"
    EXPIRED = "memory.expired"
    SUPERSEDED = "memory.superseded"
    RESTORED = "memory.restored"
    STALED = "memory.staled"


class MemoryEvidenceKind(StrEnum):
    CONVERSATION = "conversation"
    RUN = "run"
    DECISION_TRACE = "decision_trace"
    RETRIEVAL = "retrieval"
    AGENT_RESULT = "agent_result"
    TOOL_RESULT = "tool_result"
    EXPERIMENT = "experiment"
    CLAIM = "claim"
    EVIDENCE_LEDGER = "evidence_ledger"


class ValidationPath(StrEnum):
    EXPERIMENT = "experiment"
    GOLDEN_SET = "golden_set"
    STATISTICAL = "statistical"
    ADMIN = "admin"


KNOWLEDGE_EVIDENCE_KINDS = frozenset(
    {MemoryEvidenceKind.CLAIM, MemoryEvidenceKind.EVIDENCE_LEDGER}
)

RECALL_STATUS = frozenset({MemoryStatus.ACTIVE})

TERMINAL_STATUSES = frozenset(
    {
        MemoryStatus.REJECTED,
        MemoryStatus.EXPIRED,
        MemoryStatus.SUPERSEDED,
    }
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


@dataclass(kw_only=True)
class MemoryRecord:
    """Agregado de memoria. Multi-tenant. Sin chain-of-thought."""

    organization_id: UUID
    memory_type: MemoryType
    title: str
    description: str
    pattern_key: str
    pattern_signature: str
    id: UUID = field(default_factory=uuid4)
    visibility: MemoryVisibility = MemoryVisibility.TENANT
    status: MemoryStatus = MemoryStatus.OBSERVED
    confidence: float = 0.0
    support_count: int = 0
    contradiction_count: int = 0
    success_count: int = 0
    first_observed_at: datetime = field(default_factory=_utcnow)
    last_observed_at: datetime = field(default_factory=_utcnow)
    validated_at: datetime | None = None
    activated_at: datetime | None = None
    created_from_conversation_id: UUID | None = None
    created_from_run_id: UUID | None = None
    intent_family: str = ""
    source_type: str = ""
    retrieval_modality: str = ""
    tool_family: str = ""
    failure_category: str = ""
    success_signal: str = ""
    source_component: str = ""
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.memory_type, str):
            self.memory_type = MemoryType(self.memory_type)
        if isinstance(self.status, str):
            self.status = MemoryStatus(self.status)
        if isinstance(self.visibility, str):
            self.visibility = MemoryVisibility(self.visibility)
        if not self.title.strip():
            raise ValueError("MemoryRecord.title must not be empty")
        if not self.pattern_signature.strip():
            raise ValueError("MemoryRecord.pattern_signature must not be empty")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("MemoryRecord.confidence must be within [0, 1]")
        if self.visibility != MemoryVisibility.TENANT:
            raise ValueError("product-scope memory is not enabled")

    @property
    def success_rate(self) -> float:
        if self.support_count <= 0:
            return 0.0
        return self.success_count / self.support_count

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "memory_type": self.memory_type.value,
            "title": self.title,
            "description": self.description,
            "pattern_key": self.pattern_key,
            "pattern_signature": self.pattern_signature,
            "status": self.status.value,
            "visibility": self.visibility.value,
            "confidence": round(float(self.confidence), 4),
            "support_count": self.support_count,
            "contradiction_count": self.contradiction_count,
            "success_count": self.success_count,
            "success_rate": round(self.success_rate, 4),
            "first_observed_at": _iso(self.first_observed_at),
            "last_observed_at": _iso(self.last_observed_at),
            "validated_at": _iso(self.validated_at),
            "activated_at": _iso(self.activated_at),
            "created_from_conversation_id": (
                str(self.created_from_conversation_id)
                if self.created_from_conversation_id
                else None
            ),
            "created_from_run_id": (
                str(self.created_from_run_id) if self.created_from_run_id else None
            ),
            "intent_family": self.intent_family,
            "source_type": self.source_type,
            "retrieval_modality": self.retrieval_modality,
            "tool_family": self.tool_family,
            "failure_category": self.failure_category,
            "success_signal": self.success_signal,
            "source_component": self.source_component,
            "agent_id": str(self.agent_id) if self.agent_id else None,
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "metadata": dict(self.metadata),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


@dataclass(frozen=True, kw_only=True)
class MemoryEvent:
    """Ledger append-only. Sin chain-of-thought, secretos ni documentos."""

    organization_id: UUID
    memory_id: UUID
    event_type: MemoryEventType
    source_component: str
    phase: str
    outcome: str
    id: UUID = field(default_factory=uuid4)
    conversation_id: UUID | None = None
    run_id: UUID | None = None
    request_id: UUID | None = None
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.event_type, str):
            object.__setattr__(self, "event_type", MemoryEventType(self.event_type))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.id),
            "organization_id": str(self.organization_id),
            "memory_id": str(self.memory_id),
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "run_id": str(self.run_id) if self.run_id else None,
            "request_id": str(self.request_id) if self.request_id else None,
            "agent_id": str(self.agent_id) if self.agent_id else None,
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "event_type": self.event_type.value,
            "source_component": self.source_component,
            "phase": self.phase,
            "outcome": self.outcome,
            "metadata": dict(self.metadata),
            "timestamp": _iso(self.created_at),
        }


@dataclass(frozen=True, kw_only=True)
class MemoryEvidenceLink:
    organization_id: UUID
    memory_id: UUID
    kind: MemoryEvidenceKind
    id: UUID = field(default_factory=uuid4)
    ref_id: UUID | None = None
    ref_label: str = ""
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", MemoryEvidenceKind(self.kind))
        label = (self.ref_label or "")[:240]
        object.__setattr__(self, "ref_label", label)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "memory_id": str(self.memory_id),
            "kind": self.kind.value,
            "ref_id": str(self.ref_id) if self.ref_id else None,
            "ref_label": self.ref_label,
            "created_at": _iso(self.created_at),
        }


@dataclass(frozen=True, kw_only=True)
class EvidenceRef:
    kind: MemoryEvidenceKind
    ref_id: UUID | None = None
    ref_label: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", MemoryEvidenceKind(self.kind))
