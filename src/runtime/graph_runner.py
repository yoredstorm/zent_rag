# =============================================================================
# Graph runner — vecindario canónico de las entidades resueltas (S5, C2).
# =============================================================================
# Lee conocimiento canónico (knowledge_edges), no Qdrant: son hechos ya
# compilados con refs. No alimenta la respuesta todavía; se traza.
# =============================================================================
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.runtime.representation_runners import (
    MAX_ITEMS_PER_RUNNER,
    RunnerContext,
    RunnerItem,
    RunnerResult,
)


class GraphLookup(Protocol):
    async def object_edges(
        self, organization_id: UUID, object_id: UUID, *, limit: int = 200
    ) -> dict: ...


class GraphRunner:
    representation = "graph"

    def __init__(self, lookup: GraphLookup, *, max_edges: int = 24) -> None:
        self._lookup = lookup
        self._max_edges = max(1, int(max_edges))

    async def run(self, ctx: RunnerContext) -> RunnerResult:
        if ctx.entities is None or not ctx.entities.mentions:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="sin_entidades_resueltas",
            )
        items: list[RunnerItem] = []
        resolved = [
            item
            for item in ctx.entities.mentions
            if item.status == "resolved" and item.matches
        ]
        if not resolved:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="menciones_sin_resolver",
            )
        for mention in resolved:
            match = mention.matches[0]
            data = await self._lookup.object_edges(
                ctx.organization_id,
                UUID(match.canonical_id),
                limit=self._max_edges,
            )
            for edge in list(data.get("edges") or ())[: self._max_edges]:
                subject = str(edge.get("subject_name") or "")
                predicate = str(edge.get("predicate") or "")
                obj = str(edge.get("object_name") or "")
                items.append(
                    RunnerItem(
                        title=f"{subject} {predicate} {obj}".strip(),
                        summary=str(edge.get("relationship_type") or predicate),
                        refs={
                            "edge_id": str(edge.get("id") or ""),
                            "canonical_id": match.canonical_id,
                            "subject_id": str(edge.get("subject_id") or ""),
                            "object_id": str(edge.get("object_id") or ""),
                        },
                        score=edge.get("confidence"),
                    )
                )
                if len(items) >= MAX_ITEMS_PER_RUNNER:
                    break
            if len(items) >= MAX_ITEMS_PER_RUNNER:
                break
        status = "ok" if items else "empty"
        return RunnerResult(
            representation=self.representation, status=status, items=tuple(items)
        )
