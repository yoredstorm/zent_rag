# =============================================================================
# Domain — Enterprise Entity Resolution (Phase 27C)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class EntityMatchStatus(StrEnum):
    MATCHED_OBSERVED = "MATCHED_OBSERVED"
    SUGGESTED_MATCH = "SUGGESTED_MATCH"
    APPROVED_MATCH = "APPROVED_MATCH"
    REJECTED_MATCH = "REJECTED_MATCH"


@dataclass(kw_only=True)
class EntityAlias:
    """Identificador físico de una entidad en un sistema fuente."""

    source_system: str
    identifier_type: str
    identifier_value: str
    display_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "identifier_type": self.identifier_type,
            "identifier_value": self.identifier_value,
            "display_name": self.display_name,
            "metadata": dict(self.metadata),
        }


@dataclass(kw_only=True)
class EnterpriseEntity:
    """Entidad canónica con aliases cross-system."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID | None = None
    canonical_name: str = ""
    aliases: list[EntityAlias] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "canonical_name": self.canonical_name,
            "aliases": [a.to_dict() for a in self.aliases],
            "metadata": dict(self.metadata),
        }


@dataclass(kw_only=True)
class EntityMatch:
    """Propuesta o decisión de match entre dos registros / entidades."""

    id: UUID = field(default_factory=uuid4)
    left_entity_id: str
    right_entity_id: str
    status: EntityMatchStatus = EntityMatchStatus.SUGGESTED_MATCH
    score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    auto_approved: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "left_entity_id": self.left_entity_id,
            "right_entity_id": self.right_entity_id,
            "status": self.status.value,
            "score": self.score,
            "signals": dict(self.signals),
            "reason": self.reason,
            "auto_approved": self.auto_approved,
        }
