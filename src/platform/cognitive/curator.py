# =============================================================================
# Knowledge Curator — Phase 7
# =============================================================================
# Convierte observaciones de un cognitive run (conflictos, debates, cobertura)
# en KnowledgeSuggestion PROPOSED. Nunca aprueba: la promoción es humana.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.curator import (
    KnowledgeSuggestion,
    SuggestionKind,
    SuggestionStatus,
)
from src.core.ports.cognitive import CognitiveRepository
from src.core.ports.curator import CuratorRepository


class KnowledgeCurator:
    def __init__(
        self,
        repository: CuratorRepository,
        cognitive_repo: CognitiveRepository,
    ) -> None:
        self._repo = repository
        self._cognitive = cognitive_repo

    async def propose_from_run(
        self,
        organization_id: UUID,
        run_id: UUID,
        *,
        created_by: UUID | None = None,
    ) -> list[KnowledgeSuggestion]:
        run = await self._cognitive.get_run(organization_id, run_id)
        if run is None:
            raise ValueError("cognitive run not found")
        plan = run.get("plan") or {}
        workspace_id = _uuid_or_none(run.get("workspace_id"))
        suggestions: list[KnowledgeSuggestion] = []

        for conflict in plan.get("conflicts") or []:
            claim_ids = tuple(
                _uuid_or_none(claim_id)
                for claim_id in (conflict.get("claims") or [])
            )
            suggestions.append(
                KnowledgeSuggestion(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    kind=SuggestionKind.CONCEPT_REVIEW,
                    title=(
                        "Conflicto sin resolver: "
                        f"{conflict.get('conflict_type', 'direct_conflict')}"
                    ),
                    reasoning=str(conflict.get("reason") or ""),
                    claim_ids=tuple(c for c in claim_ids if c is not None),
                    payload={
                        "conflict_type": conflict.get("conflict_type"),
                        "resolution": conflict.get("resolution"),
                    },
                    provenance=CatalogProvenance.INFERRED,
                    status=SuggestionStatus.PROPOSED,
                    confidence=0.4,
                    created_by=created_by,
                )
            )

        for outcome in plan.get("debate") or []:
            claim_id = _uuid_or_none(outcome.get("claim_id"))
            kind = str(outcome.get("kind") or "")
            challenge = outcome.get("challenge") or {}
            detail = str(challenge.get("detail") or "")[:200]
            if kind == "upheld":
                suggestions.append(
                    KnowledgeSuggestion(
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        kind=SuggestionKind.CONCEPT_REVIEW,
                        title=f"Claim sin respaldo: {detail[:120]}",
                        reasoning=str(outcome.get("resolution_note") or ""),
                        claim_ids=(claim_id,) if claim_id else (),
                        payload={
                            "debate_kind": "upheld",
                            "evidence_check_ratio": outcome.get(
                                "evidence_check_ratio"
                            ),
                        },
                        confidence=0.35,
                        created_by=created_by,
                    )
                )
            elif kind == "defended":
                suggestions.append(
                    KnowledgeSuggestion(
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        kind=SuggestionKind.FACT_CANDIDATE,
                        title="Candidato a hecho verificado (defendido)",
                        reasoning=str(outcome.get("resolution_note") or ""),
                        claim_ids=(claim_id,) if claim_id else (),
                        payload={
                            "debate_kind": "defended",
                            "evidence_check_ratio": outcome.get(
                                "evidence_check_ratio"
                            ),
                        },
                        confidence=0.55,
                        created_by=created_by,
                    )
                )

        critique = plan.get("critique") or {}
        if int(critique.get("missing_evidence") or 0) >= 3:
            suggestions.append(
                KnowledgeSuggestion(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    kind=SuggestionKind.CONCEPT_REVIEW,
                    title="Cobertura de fuentes insuficiente",
                    reasoning=str(critique.get("summary") or ""),
                    payload={"missing_evidence": critique.get("missing_evidence")},
                    confidence=0.3,
                    created_by=created_by,
                )
            )

        persisted: list[KnowledgeSuggestion] = []
        for suggestion in suggestions:
            persisted.append(await self._repo.propose(suggestion))
        return persisted


def _uuid_or_none(value) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None
