# =============================================================================
# KnowledgeSystemEvent — eventos de dominio del conocimiento (C8, W5).
# =============================================================================
# Puro: sin I/O, sin bus, sin persistencia. `event_name` es el nombre que viaja
# al bus existente (`knowledge.<tipo>`). Los cambios de reglas, conflictos,
# supersesiones, gaps y cambios de alto impacto exigen revisión humana por
# default; NEW_ENTITY/NEW_RULE son informativos. El payload nunca rompe la
# construcción: None → {}.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class KnowledgeEventType(StrEnum):
    """Tipos exactos de evento de conocimiento (W5)."""

    NEW_ENTITY = "new_entity"
    NEW_RULE = "new_rule"
    RULE_CHANGED = "rule_changed"
    CONFLICT_DETECTED = "conflict_detected"
    SOURCE_SUPERSEDED = "source_superseded"
    KNOWLEDGE_GAP_DETECTED = "knowledge_gap_detected"
    HIGH_IMPACT_CHANGE = "high_impact_change"
    # Knowledge Nutrition (§25): el enrichment y la aceptación de retrieval son
    # eventos informativos; las acciones de nutrición informan revisión.
    SEMANTIC_ENRICHED = "semantic_enriched"
    RETRIEVAL_ACCEPTANCE_FAILED = "retrieval_acceptance_failed"
    RETRIEVAL_REPRESENTATION_UPDATED = "retrieval_representation_updated"
    KNOWLEDGE_REINDEXED = "knowledge_reindexed"
    KNOWLEDGE_NUTRITION_REQUIRED = "knowledge_nutrition_required"


_SIN_REVISION = frozenset(
    {
        KnowledgeEventType.NEW_ENTITY,
        KnowledgeEventType.NEW_RULE,
        KnowledgeEventType.SEMANTIC_ENRICHED,
        KnowledgeEventType.RETRIEVAL_REPRESENTATION_UPDATED,
        KnowledgeEventType.KNOWLEDGE_REINDEXED,
    }
)


def default_requires_review(event_type: KnowledgeEventType) -> bool:
    """True salvo para eventos informativos; desconocidos exigen revisión."""
    return event_type not in _SIN_REVISION


@dataclass(frozen=True)
class KnowledgeSystemEvent:
    """Evento de conocimiento listo para publicar en `rag:events`."""

    type: KnowledgeEventType
    organization_id: UUID
    payload: dict | None = None
    confidence: float | None = None
    requires_review: bool | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    object_id: UUID | None = None
    rule_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.type, KnowledgeEventType):
            object.__setattr__(self, "type", KnowledgeEventType(self.type))
        if self.payload is None:
            object.__setattr__(self, "payload", {})
        if self.requires_review is None:
            object.__setattr__(
                self, "requires_review", default_requires_review(self.type)
            )
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("KnowledgeSystemEvent.confidence must be within [0, 1]")

    @property
    def event_name(self) -> str:
        return f"knowledge.{self.type.value}"

    def to_public_dict(self) -> dict[str, Any]:
        """Vista serializable: ids no nulos + payload + confianza + revisión."""
        data: dict[str, Any] = {
            "type": self.type.value,
            "event": self.event_name,
            "organization_id": str(self.organization_id),
            "payload": dict(self.payload),
            "confidence": self.confidence,
            "requires_review": bool(self.requires_review),
        }
        for key in ("source_id", "document_id", "object_id"):
            value = getattr(self, key)
            if value is not None:
                data[key] = str(value)
        if self.rule_key is not None:
            data["rule_key"] = self.rule_key
        return data
