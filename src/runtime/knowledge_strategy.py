# =============================================================================
# Knowledge Strategy — representaciones + razones + scope (brief §5).
# =============================================================================
# Determinista y sin I/O. En C1 se deriva del retrieval planner existente y se
# traza; las fases siguientes agregan entity resolution canónica y enforcement
# de scope pre-retrieval.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.rag.retrieval.planner import RetrievalPlan, build_retrieval_plan

#: Orden de presentación de las representaciones (el planner decide cuáles).
_REPRESENTATION_ORDER = ("structured", "exact", "temporal", "graph", "vector")


@dataclass(frozen=True)
class StrategyRepresentation:
    representation: str
    reason: str

    def to_public_dict(self) -> dict:
        return {"representation": self.representation, "reason": self.reason}


@dataclass(frozen=True)
class KnowledgeStrategy:
    query: str
    primary: str
    representations: tuple[StrategyRepresentation, ...]
    exact_needles: tuple[str, ...] = ()
    entity_mentions: tuple[str, ...] = ()
    temporal_intent: str | None = None
    structured_intent: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    role: str = ""

    def includes(self, representation: str) -> bool:
        return any(item.representation == representation for item in self.representations)

    def to_public_dict(self) -> dict:
        return {
            "primary": self.primary,
            "representations": [item.to_public_dict() for item in self.representations],
            "exact_needles": list(self.exact_needles),
            "entity_mentions": list(self.entity_mentions),
            "temporal_intent": self.temporal_intent,
            "structured_intent": self.structured_intent,
            "scope": {
                "organization_id": self.organization_id,
                "workspace_id": self.workspace_id,
                "role": self.role,
            },
        }


def build_knowledge_strategy(
    retrieval_plan: RetrievalPlan | None = None,
    *,
    query: str = "",
    organization_id: str | None = None,
    workspace_id: str | None = None,
    role: str = "",
) -> KnowledgeStrategy:
    """Estrategia declarada: qué representaciones consultar y con qué scope."""
    plan = retrieval_plan if retrieval_plan is not None else build_retrieval_plan(query)
    representations = tuple(
        StrategyRepresentation(
            representation=representation,
            reason=plan.reasons.get(representation, "representación base"),
        )
        for representation in _REPRESENTATION_ORDER
        if plan.includes(representation)
    )
    return KnowledgeStrategy(
        query=plan.query,
        primary=plan.primary,
        representations=representations,
        exact_needles=tuple(plan.exact_needles),
        entity_mentions=tuple(plan.entity_mentions),
        temporal_intent=plan.temporal_intent,
        structured_intent=plan.structured_intent,
        organization_id=organization_id,
        workspace_id=workspace_id,
        role=role,
    )
