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
    from src.runtime.knowledge_strategy import KnowledgeStrategy

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
    notes: list[dict] = field(default_factory=list)

    def add_note(self, stage: str, detail: str) -> None:
        self.notes.append({"stage": stage, "detail": detail[:240]})

    def to_public_dict(self) -> dict:
        payload: dict = {"mode": cognitive_runtime_mode(), "notes": list(self.notes)}
        if self.plan is not None:
            payload["plan"] = self.plan.to_public_dict()
        if self.strategy is not None:
            payload["strategy"] = self.strategy.to_public_dict()
        return payload
