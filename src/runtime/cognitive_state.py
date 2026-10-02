# =============================================================================
# Cognitive Turn State — estado compartido de las etapas cognitivas (W1).
# =============================================================================
# C1: plan + strategy + notas. Las fases siguientes agregan evidence, brief,
# claims, verification, budget y loop. Sin I/O.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.core.config import get_settings

if TYPE_CHECKING:  # solo anotaciones: con `off` no se importa plan/strategy
    from src.runtime.cognitive_plan import CognitivePlan
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.evidence_assembly import EvidencePackage
    from src.runtime.knowledge_brief import KnowledgeBrief
    from src.runtime.knowledge_strategy import KnowledgeStrategy
    from src.runtime.representation_runners import RunnerResult

COGNITIVE_MODES = ("off", "shadow", "limited", "active")


def cognitive_runtime_mode() -> str:
    """Modo del runtime cognitivo; cualquier valor desconocido cae a 'off'."""
    mode = str(getattr(get_settings(), "COGNITIVE_OS_ENABLED", "off") or "off")
    mode = mode.strip().lower()
    return mode if mode in COGNITIVE_MODES else "off"


@dataclass
class CognitiveTurn:
    query: str
    plan: CognitivePlan | None = None
    strategy: KnowledgeStrategy | None = None
    entities: "EntityResolution | None" = None
    runners: tuple["RunnerResult", ...] = ()
    evidence: "EvidencePackage | None" = None
    brief: "KnowledgeBrief | None" = None
    notes: list[dict] = field(default_factory=list)

    def add_note(self, stage: str, detail: str) -> None:
        self.notes.append({"stage": stage, "detail": detail[:240]})

    def jev_signals(self) -> dict:
        """Señales determinísticas para el preflight JEV (C2: se exponen, no deciden)."""
        from src.runtime.cognitive_plan import KnowledgeNeed

        exact = bool(self.plan and KnowledgeNeed.EXACT_LOOKUP in self.plan.needs)
        entity_resolved: bool | None = None
        if self.entities is not None and self.entities.mentions:
            entity_resolved = all(
                item.status == "resolved" for item in self.entities.mentions
            )
        return {
            "exact_lookup_declared": exact,
            "entity_resolved": entity_resolved,
        }

    def to_public_dict(self) -> dict:
        payload: dict = {
            "mode": cognitive_runtime_mode(),
            "notes": list(self.notes),
            "signals": self.jev_signals(),
        }
        if self.plan is not None:
            payload["plan"] = self.plan.to_public_dict()
        if self.strategy is not None:
            payload["strategy"] = self.strategy.to_public_dict()
        payload["entities"] = (
            self.entities.to_public_dict() if self.entities is not None else None
        )
        payload["runners"] = [
            runner.to_public_dict() for runner in self.runners
        ]
        payload["evidence"] = (
            self.evidence.to_public_dict() if self.evidence is not None else None
        )
        payload["brief"] = (
            self.brief.to_public_dict() if self.brief is not None else None
        )
        return payload
