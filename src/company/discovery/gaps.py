# =============================================================================
# Company Discovery — Knowledge Gaps (§11) y conflictos de compañía (§12)
# =============================================================================
# Un hueco de conocimiento es una discrepancia OBSERVADA, no una opinión:
#   - un paso ocurre en N% de las corridas y no está en la documentación
#   - un término frecuente no tiene definición autoritativa ni mapeo técnico
#   - dos fuentes definen lo mismo de forma distinta
#
# Los conflictos REUTILIZAN el Claim Ledger: no se crea un sistema paralelo.
# El hueco se emite como candidato y, al promoverse, se registra como Finding
# del Learning Engine (KNOWLEDGE_GAP), que es donde vive el ciclo de aprendizaje.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.company.discovery.source_base import DiscoverySource
from src.company.discovery.source_loaders import load_claim_conflicts
from src.company.discovery.sources_structured import _support
from src.core.domain.company_discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoverySourceKind,
    GapKind,
    KnowledgeGapPayload,
    ProcessCandidatePayload,
    ProcessDivergence,
    ProcessMode,
    compare_processes,
)

#: Un paso observado por debajo de esta frecuencia es ruido, no hueco.
MIN_STEP_FREQUENCY = 0.5


class KnowledgeGapSource(DiscoverySource):
    """Convierte divergencias y conflictos observados en candidatos de hueco."""

    source_kind = DiscoverySourceKind.FINDING
    name = "knowledge_gap"

    def __init__(
        self,
        *,
        loader_conflicts=load_claim_conflicts,
        min_frequency: float = MIN_STEP_FREQUENCY,
        max_items: int | None = None,
    ) -> None:
        super().__init__(max_items=max_items)
        self._load_conflicts = loader_conflicts
        self.min_frequency = min_frequency

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        """Conflictos ya registrados en el Claim Ledger (§12)."""
        rows = await self._load_conflicts(organization_id, self.max_items)
        candidates: list[DiscoveryCandidate] = []
        for row in rows:
            subject = str(row.get("normalized_subject") or "").strip()
            predicate = str(row.get("normalized_predicate") or "").strip()
            objects = [str(item) for item in (row.get("objects") or []) if item]
            claim_ids = [str(item) for item in (row.get("claim_ids") or [])]
            if not subject or len(objects) < 2:
                continue
            gap = KnowledgeGapPayload(
                gap_kind=GapKind.CONTRADICTORY_DEFINITION,
                subject=f"{subject} {predicate}".strip(),
                detail=(
                    f"{len(objects)} distinct values claimed for the same "
                    f"subject/predicate: {', '.join(objects[:4])}"
                ),
                evidence_summary=tuple(claim_ids[:5]),
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.KNOWLEDGE_GAP,
                    payload=gap.to_dict(),
                    title=f"Conflict: {subject} {predicate}",
                    summary=gap.detail,
                    support=_support(
                        structural=False,
                        observations=int(row.get("claims") or len(objects)),
                        distinct_sources=len(objects),
                        contradictions=len(objects) - 1,
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=DiscoverySourceKind.CLAIM,
                        ref=claim_ids[0] if claim_ids else subject,
                        detail={
                            "subject": subject,
                            "predicate": predicate,
                            "objects": objects[:6],
                            "claim_ids": claim_ids[:6],
                        },
                    ),
                    workspace_id=workspace_id,
                )
            )
        return candidates

    def from_divergence(
        self,
        organization_id: UUID,
        divergence: ProcessDivergence,
        *,
        workspace_id: UUID | None = None,
    ) -> list[DiscoveryCandidate]:
        """Pasos observados que la documentación no menciona (§11).

        Ejemplo del spec: "Step C occurs in 82% of observed runs but is absent
        from process documentation".
        """
        candidates: list[DiscoveryCandidate] = []
        for step in divergence.undocumented_steps:
            if step.frequency < self.min_frequency:
                continue
            gap = KnowledgeGapPayload(
                gap_kind=GapKind.UNDOCUMENTED_STEP,
                subject=f"{divergence.process_name}:{step.name}",
                detail=(
                    f"step '{step.name}' occurs in {step.frequency:.0%} of "
                    f"{divergence.observed_runs} observed runs but is absent "
                    "from process documentation"
                ),
                frequency=step.frequency,
                observed_runs=divergence.observed_runs,
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.KNOWLEDGE_GAP,
                    payload=gap.to_dict(),
                    title=f"Gap: undocumented step {step.name}",
                    summary=gap.summary(),
                    support=_support(
                        structural=False,
                        observations=step.runs or divergence.observed_runs,
                        distinct_sources=1,
                        successful_runs=divergence.observed_runs,
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=f"{divergence.process_name}:{step.name}",
                        detail={
                            "frequency": step.frequency,
                            "runs": step.runs,
                            "process": divergence.process_name,
                        },
                    ),
                    workspace_id=workspace_id,
                )
            )
        for step in divergence.unobserved_steps:
            gap = KnowledgeGapPayload(
                gap_kind=GapKind.DOCUMENTED_BUT_UNOBSERVED,
                subject=f"{divergence.process_name}:{step.name}",
                detail=(
                    f"documented step '{step.name}' never appeared in "
                    f"{divergence.observed_runs} observed runs"
                ),
                frequency=0.0,
                observed_runs=divergence.observed_runs,
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.KNOWLEDGE_GAP,
                    payload=gap.to_dict(),
                    title=f"Gap: documented step {step.name} never observed",
                    summary=gap.detail,
                    support=_support(
                        structural=False,
                        observations=divergence.observed_runs,
                        distinct_sources=1,
                        successful_runs=divergence.observed_runs,
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=f"{divergence.process_name}:{step.name}",
                    ),
                    workspace_id=workspace_id,
                )
            )
        return candidates


def _process_name_key(payload: ProcessCandidatePayload) -> str:
    return " ".join(payload.name.strip().lower().split())


def find_process_divergences(
    processes: list[ProcessCandidatePayload],
) -> list[ProcessDivergence]:
    """Empareja procesos DESIGNED y OBSERVED con el mismo nombre.

    Sólo compara por nombre normalizado: emparejar por similitud semántica
    sería inferencia, y aquí se reporta lo observado.
    """
    designed: dict[str, ProcessCandidatePayload] = {}
    observed: dict[str, ProcessCandidatePayload] = {}
    for payload in processes:
        key = _process_name_key(payload)
        if not key:
            continue
        if payload.mode is ProcessMode.DESIGNED:
            designed.setdefault(key, payload)
        else:
            observed.setdefault(key, payload)
    divergences: list[ProcessDivergence] = []
    for key, observed_payload in observed.items():
        designed_payload = designed.get(key)
        if designed_payload is None:
            continue
        divergences.append(compare_processes(designed_payload, observed_payload))
    return divergences


__all__ = [
    "KnowledgeGapSource",
    "MIN_STEP_FREQUENCY",
    "find_process_divergences",
]
