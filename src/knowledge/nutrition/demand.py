# =============================================================================
# Knowledge Nutrition — query demand profile
# =============================================================================
# Estadística de demanda por organización/workspace a partir de señales REALES
# (probes evaluados + feedback). No guarda PII innecesaria: la query se agrupa
# por tipo y por concepto, y el texto completo solo viaja si ya lo pidió el
# caller (queda en probes/feedback, no acá).
# =============================================================================
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from src.knowledge.acceptance.contracts import AcceptanceReport
from src.knowledge.enrichment.contracts import SemanticEnrichmentResult


@dataclass(frozen=True, kw_only=True)
class DemandItem:
    key: str
    kind: str  # query_type | concept | identifier
    frequency: int
    success_rate: float | None
    gap_frequency: int
    retrievability: float | None


@dataclass(frozen=True, kw_only=True)
class QueryDemandProfile:
    organization_id: str
    workspace_id: str | None = None
    document_id: str | None = None
    total_queries: int = 0
    items: tuple[DemandItem, ...] = ()
    demand_coverage: float | None = None
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    policy_version: str = "demand-policy-1"

    def to_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "document_id": self.document_id,
            "total_queries": self.total_queries,
            "items": [asdict(item) for item in self.items],
            "demand_coverage": self.demand_coverage,
            "computed_at": self.computed_at.isoformat(),
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class QueryDemandModel:
    """Agregado de demanda (probes + feedback) sin conservar texto sensible.

    Métricas §10: questions_total, success_rate, retrieval_failure_rate,
    negative_feedback_rate, coverage. Alimenta `demand_coverage` del score.
    """

    organization_id: str
    document_id: str | None = None
    workspace_id: str | None = None
    questions_total: int = 0
    probes_passed: int = 0
    probes_failed: int = 0
    success_rate: float | None = None
    retrieval_failure_rate: float | None = None
    negative_feedback_rate: float | None = None
    coverage: float | None = None
    intents: tuple[DemandItem, ...] = ()
    concepts: tuple[DemandItem, ...] = ()
    evaluations_considered: int = 0
    actions_considered: int = 0
    policy_version: str = "demand-policy-2"

    def to_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "document_id": self.document_id,
            "workspace_id": self.workspace_id,
            "questions_total": self.questions_total,
            "probes_passed": self.probes_passed,
            "probes_failed": self.probes_failed,
            "success_rate": self.success_rate,
            "retrieval_failure_rate": self.retrieval_failure_rate,
            "negative_feedback_rate": self.negative_feedback_rate,
            "coverage": self.coverage,
            "intents": [asdict(item) for item in self.intents],
            "concepts": [asdict(item) for item in self.concepts],
            "evaluations_considered": self.evaluations_considered,
            "actions_considered": self.actions_considered,
            "policy_version": self.policy_version,
        }


_RETRIEVAL_FAILURE_TYPES = frozenset(
    {
        "RETRIEVAL_MISS",
        "BAD_RANK",
        "MISSING_KNOWLEDGE",
        "INSUFFICIENT_EVIDENCE",
        "STALE_KNOWLEDGE",
    }
)


def build_demand_model(
    evaluations: list[dict],
    actions: list[dict] | None = None,
    *,
    organization_id: str,
    document_id: str | None = None,
    workspace_id: str | None = None,
    enrichment: SemanticEnrichmentResult | None = None,
) -> QueryDemandModel:
    """Agrega evaluaciones persistidas + acciones de nutrition (sin texto crudo).

    `evaluations` son filas de `knowledge_retrieval_evaluations` (o reportes).
    Nunca conserva la query completa: agrupa por tipo de intent y por concepto.
    """
    questions_total = 0
    passed = 0
    failed = 0
    intent_counts: dict[str, list[int]] = {}
    for evaluation in evaluations or ():
        total = int(evaluation.get("probes_total") or 0)
        if total <= 0:
            continue
        questions_total += total
        passed += int(evaluation.get("probes_passed") or 0)
        failed += int(evaluation.get("probes_failed") or 0)
        for probe in evaluation.get("failed_probes") or ():
            query_type = str(probe.get("query_type") or "unknown")
            counts = intent_counts.setdefault(query_type, [0, 0])
            counts[0] += 1
            counts[1] += 1
        metrics = evaluation.get("metrics") or {}
        if not intent_counts and metrics.get("state"):
            intent_counts.setdefault("evaluation", [0, 0])

    actions = list(actions or ())
    negative = [
        action
        for action in actions
        if str(action.get("failure_type") or "") in _RETRIEVAL_FAILURE_TYPES
    ]
    success_rate = round(passed / questions_total, 4) if questions_total else None
    retrieval_failure_rate = (
        round(failed / questions_total, 4) if questions_total else None
    )
    negative_feedback_rate = (
        round(len(negative) / questions_total, 4) if questions_total else None
    )

    intents = tuple(
        DemandItem(
            key=query_type,
            kind="query_type",
            frequency=counts[0],
            success_rate=(
                round((counts[0] - counts[1]) / counts[0], 4) if counts[0] else None
            ),
            gap_frequency=counts[1],
            retrievability=success_rate,
        )
        for query_type, counts in sorted(intent_counts.items())
    )

    concepts: list[DemandItem] = []
    if enrichment is not None:
        failed_queries = {
            str(probe.get("query") or "").casefold()
            for evaluation in evaluations or ()
            for probe in evaluation.get("failed_probes") or ()
        }
        for concept in enrichment.concepts[:50]:
            frequency = 0
            gaps = 0
            for question in enrichment.synthetic_questions:
                if question.target_concept_id != concept.concept_id:
                    continue
                frequency += 1
                if question.question.casefold() in failed_queries:
                    gaps += 1
            if frequency == 0:
                continue
            concepts.append(
                DemandItem(
                    key=concept.canonical_name,
                    kind="concept",
                    frequency=frequency,
                    success_rate=round((frequency - gaps) / frequency, 4),
                    gap_frequency=gaps,
                    retrievability=success_rate,
                )
            )
    concepts.sort(key=lambda item: -item.frequency)

    return QueryDemandModel(
        organization_id=organization_id,
        document_id=document_id,
        workspace_id=workspace_id,
        questions_total=questions_total,
        probes_passed=passed,
        probes_failed=failed,
        success_rate=success_rate,
        retrieval_failure_rate=retrieval_failure_rate,
        negative_feedback_rate=negative_feedback_rate,
        coverage=success_rate,
        intents=intents[:30],
        concepts=tuple(concepts[:30]),
        evaluations_considered=len(evaluations or ()),
        actions_considered=len(actions),
    )


def demand_profile_from_acceptance(
    report: AcceptanceReport,
    *,
    enrichment: SemanticEnrichmentResult | None = None,
) -> QueryDemandProfile:
    """Perfil de demanda a partir de los probes evaluados (por tipo/concepto)."""
    by_type: dict[str, list[bool]] = {}
    for outcome in report.outcomes:
        by_type.setdefault(outcome.query_type, []).append(bool(outcome.passed))

    items: list[DemandItem] = []
    for query_type, results in sorted(by_type.items()):
        total = len(results)
        passed = sum(1 for value in results if value)
        items.append(
            DemandItem(
                key=query_type,
                kind="query_type",
                frequency=total,
                success_rate=round(passed / total, 4) if total else None,
                gap_frequency=total - passed,
                retrievability=report.recall_at_5,
            )
        )

    # Conceptos: frecuencia = cobertura de probes que los tocan (proxy de demanda
    # cuando no hay log de queries; se reemplaza cuando el caller pase queries).
    concept_items: list[DemandItem] = []
    if enrichment is not None:
        failed_keys = {
            (outcome.query or "").casefold() for outcome in report.failed_probes
        }
        for concept in enrichment.concepts[:50]:
            frequency = 0
            gaps = 0
            for question in enrichment.synthetic_questions:
                if question.target_concept_id != concept.concept_id:
                    continue
                frequency += 1
                if question.question.casefold() in failed_keys:
                    gaps += 1
            if frequency == 0:
                continue
            concept_items.append(
                DemandItem(
                    key=concept.canonical_name,
                    kind="concept",
                    frequency=frequency,
                    success_rate=round((frequency - gaps) / frequency, 4),
                    gap_frequency=gaps,
                    retrievability=report.recall_at_5,
                )
            )
    items.extend(sorted(concept_items, key=lambda item: -item.frequency)[:30])

    total = report.probes_total
    coverage = None
    if total:
        coverage = round(report.probes_passed / total, 4)
    return QueryDemandProfile(
        organization_id=str(report.organization_id),
        workspace_id=str(report.workspace_id) if report.workspace_id else None,
        document_id=str(report.document_id) if report.document_id else None,
        total_queries=total,
        items=tuple(items[:60]),
        demand_coverage=coverage,
    )
