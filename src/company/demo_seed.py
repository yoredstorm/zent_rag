# =============================================================================
# Company Intelligence Studio — Escenario demo "Fare Audit" (§26)
# =============================================================================
# Siembra un dominio completo y verificable: ATPCO provee Record2, Record2
# contiene Carrier Code, A1672 pertenece a PXSAUDIT, el proceso Fare Audit lee
# A1672, el Audit Agent asiste al proceso y Reconciliation Workflow automatiza
# el proceso de reconciliación. Además: memoria operativa, un Finding de
# retrieval de Excel y un experimento de structured exact.
#
# Idempotente: las entidades tienen id determinista, así que correrlo dos veces
# no duplica nada. Pensado para demos, e2e y tests.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.company.service import AuthorityRule, CompanyGraphService
from src.company.wiring import (
    company_authority_service,
    company_discovery_repository,
    company_graph_service,
)
from src.core.domain.company_graph import (
    CompanyEntity,
    EntityStatus,
    ProvenanceKind,
    ProvenanceRef,
    SourceAuthorityLevel,
)
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

DEMO_DOMAIN = "fare-audit"

#: (from_type, from_name, relationship_type, to_type, to_name)
DEMO_RELATIONSHIPS: tuple[tuple[str, str, str, str, str], ...] = (
    ("knowledge_source", "ATPCO", "PROVIDES", "dataset", "Record2"),
    ("dataset", "Record2", "CONTAINS", "field", "Carrier Code"),
    ("table", "A1672", "BELONGS_TO", "system", "PXSAUDIT"),
    ("process", "Fare Audit", "READS_FROM", "table", "A1672"),
    ("agent", "Audit Agent", "ASSISTS", "process", "Fare Audit"),
    (
        "workflow",
        "Reconciliation Workflow",
        "AUTOMATES",
        "process",
        "Reconciliation Process",
    ),
    ("process", "Reconciliation Process", "USES", "system", "PXSAUDIT"),
    ("concept", "Pending Transaction", "MAPS_TO", "field", "A1672STO0"),
    ("concept", "Pending Transaction", "USES", "table", "A1672"),
    ("table", "A1672", "CONTAINS", "field", "A1672STO0"),
    ("rule", "Fare Audit Rule", "GOVERNED_BY", "knowledge_source", "ATPCO"),
    ("team", "Audit Team", "OWNS", "process", "Reconciliation Process"),
)

#: (entity_type, canonical_name, display_name, aliases, domain)
DEMO_ENTITIES: tuple[tuple[str, str, str, tuple[str, ...], str], ...] = (
    ("knowledge_source", "ATPCO", "ATPCO", ("atpco", "airline tariff publishing"), DEMO_DOMAIN),
    ("dataset", "Record2", "Record2", ("record 2", "atpco record2"), DEMO_DOMAIN),
    ("field", "Carrier Code", "Carrier Code", ("carrier", "carrier code"), DEMO_DOMAIN),
    ("field", "A1672STO0", "A1672STO0", ("status", "sto0"), DEMO_DOMAIN),
    ("table", "A1672", "A1672", ("a1672", "transaction audit"), DEMO_DOMAIN),
    ("system", "PXSAUDIT", "PXSAUDIT", ("pxsaudit", "audit system"), DEMO_DOMAIN),
    ("process", "Fare Audit", "Fare Audit", ("fare audit", "auditoría de tarifas"), DEMO_DOMAIN),
    ("process", "Reconciliation Process", "Reconciliation", ("reconciliation", "reconciliación"), DEMO_DOMAIN),
    ("agent", "Audit Agent", "Audit Agent", ("audit agent",), DEMO_DOMAIN),
    ("workflow", "Reconciliation Workflow", "Reconciliation Workflow", ("reconciliation workflow",), DEMO_DOMAIN),
    ("concept", "Pending Transaction", "Pending Transaction", ("pending", "pendiente", "sin procesar"), DEMO_DOMAIN),
    ("rule", "Fare Audit Rule", "Fare Audit Rule", ("fare audit rule", "regla de auditoría"), DEMO_DOMAIN),
    ("team", "Audit Team", "Audit Team", ("audit team",), DEMO_DOMAIN),
)

#: Autoridad demo: el sistema de producción manda sobre el estado de ticket.
DEMO_AUTHORITY: tuple[tuple[str, str, str, str, SourceAuthorityLevel], ...] = (
    ("data", "pending transaction", "PXSAUDIT", "database", SourceAuthorityLevel.AUTHORITATIVE),
    ("data", "pending transaction", "documentation", "document", SourceAuthorityLevel.SECONDARY),
    ("fare-audit", "fare audit rule", "ATPCO", "document", SourceAuthorityLevel.PRIMARY),
    ("fare-audit", "fare audit rule", "email", "manual", SourceAuthorityLevel.INFORMATIONAL),
)


@dataclass(frozen=True, kw_only=True)
class DemoSeedResult:
    organization_id: UUID
    entities: int
    relationships: int
    authority_rules: int
    memory_recorded: bool
    finding_recorded: bool
    experiment_recorded: bool

    def to_dict(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "entities": self.entities,
            "relationships": self.relationships,
            "authority_rules": self.authority_rules,
            "memory_recorded": self.memory_recorded,
            "finding_recorded": self.finding_recorded,
            "experiment_recorded": self.experiment_recorded,
        }


async def seed_fare_audit_demo(
    organization_id: UUID,
    *,
    graph: CompanyGraphService | None = None,
    with_learning: bool = True,
) -> DemoSeedResult:
    """Siembra el escenario demo completo para una organización."""
    graph = graph or company_graph_service()
    evidence = (
        ProvenanceRef(kind=ProvenanceKind.MANUAL, ref="company-demo-seed"),
    )

    entities: dict[tuple[str, str], CompanyEntity] = {}
    for entity_type, name, display, aliases, domain in DEMO_ENTITIES:
        entities[(entity_type, name)] = await graph.upsert_entity(
            CompanyEntity(
                organization_id=organization_id,
                entity_type=entity_type,
                canonical_name=name,
                display_name=display,
                domain=domain,
                aliases=aliases,
                status=EntityStatus.CONFIRMED,
                confidence=0.9,
                source="manual",
                source_ref="company-demo-seed",
                evidence=evidence,
                metadata={"domain": DEMO_DOMAIN, "demo": True},
            )
        )

    created = 0
    for from_type, from_name, relationship_type, to_type, to_name in DEMO_RELATIONSHIPS:
        source = entities.get((from_type, from_name))
        target = entities.get((to_type, to_name))
        if source is None or target is None:
            logger.warning(
                "company demo relationship skipped",
                source=f"{from_type}:{from_name}",
                target=f"{to_type}:{to_name}",
            )
            continue
        relationship = await graph.propose_relationship(
            organization_id,
            source.id,
            target.id,
            relationship_type,
            source="manual",
            source_ref="company-demo-seed",
            evidence=evidence,
            confidence=0.85,
            metadata={"demo": True},
        )
        if relationship.status is EntityStatus.DISCOVERED:
            await graph.confirm_relationship(
                organization_id, relationship.id, status=EntityStatus.CONFIRMED
            )
        created += 1

    authority = company_authority_service()
    rules = 0
    for domain, concept, source_name, source_type, level in DEMO_AUTHORITY:
        await authority.upsert_rule(
            AuthorityRule(
                organization_id=organization_id,
                domain=domain,
                concept=concept,
                source_name=source_name,
                source_type=source_type,
                authority_level=level,
                priority=1,
            )
        )
        rules += 1

    memory_recorded = await _seed_memory(organization_id)
    finding_recorded = await _seed_finding(organization_id) if with_learning else False
    experiment_recorded = (
        await _seed_experiment(organization_id) if with_learning else False
    )

    result = DemoSeedResult(
        organization_id=organization_id,
        entities=len(entities),
        relationships=created,
        authority_rules=rules,
        memory_recorded=memory_recorded,
        finding_recorded=finding_recorded,
        experiment_recorded=experiment_recorded,
    )
    logger.info("company demo seeded", **result.to_dict())
    return result


async def _seed_memory(organization_id: UUID) -> bool:
    """Memoria operativa: 'structured field lookup' para consultas de pending."""
    try:
        from src.core.domain.memory import MemoryType, ValidationPath
        from src.memory.service import MemoryObservation
        from src.memory.signature import PatternFeatures
        from src.memory.wiring import memory_foundation_service
    except Exception:  # noqa: BLE001
        return False
    try:
        service = memory_foundation_service()
        observation = MemoryObservation(
            organization_id=organization_id,
            memory_type=MemoryType.OPERATIONAL,
            title="Structured field lookup para Pending Transaction",
            description=(
                "Las consultas sobre transacciones pending resuelven mejor con "
                "búsqueda estructurada por campo (A1672STO0) que por texto libre."
            ),
            features=PatternFeatures(
                intent_family="sql",
                tool_family="query_database",
                retrieval_modality="structured",
            ),
            source_component="company_demo_seed",
            phase="retrieval",
            outcome="success",
            success=True,
            confidence=0.7,
            idempotency_key=f"company-demo-memory-{organization_id}",
        )
        record = await service.observe(observation)
        for _ in range(2):
            await service.record_success(observation, signal="structured_exact")
        await service.validate(
            organization_id,
            record.id,
            via=ValidationPath.ADMIN,
            source_component="company_demo_seed",
        )
        await service.activate(organization_id, record.id, actor_id=None)
        return True
    except Exception as exc:  # noqa: BLE001 - demo fail-soft
        logger.warning("company demo memory failed", error=str(exc)[:200])
        return False


async def _seed_finding(organization_id: UUID) -> bool:
    """Finding: problema de recuperación de Excel en el proceso de auditoría."""
    try:
        from src.core.domain.learning_cycle import Finding, FindingSeverity
        from src.infrastructure.postgres.learning_cycle_store import (
            PostgresLearningCycleStore,
        )

        finding = Finding(
            organization_id=organization_id,
            category="RETRIEVAL",
            severity=FindingSeverity.MEDIUM,
            pattern_key="excel_retrieval_issue",
            observed="Excel lookup por celda falla cuando la fila tiene merged cells",
            alternative="preferir búsqueda estructurada por campo sobre lectura de celda",
            baseline_strategy="excel_cell_lookup",
            candidate_strategy="structured_field_lookup",
            sample_size=12,
            window="30d",
            confidence="medium",
            dedupe_key=f"company-demo-excel-{organization_id}",
            evidence=["demo-seed"],
            affected=["Record2", "Fare Audit"],
        )
        await PostgresLearningCycleStore().upsert_finding(finding)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("company demo finding failed", error=str(exc)[:200])
        return False


async def _seed_experiment(organization_id: UUID) -> bool:
    """Experimento: structured_exact para el mismo caso."""
    try:
        from uuid import NAMESPACE_URL, uuid5

        from src.core.domain.learning_cycle import (
            ExperimentKind,
            ExperimentMode,
            ExperimentRequest,
            ExperimentStatus,
            Finding,
            FindingSeverity,
        )
        from src.infrastructure.postgres.learning_cycle_store import (
            PostgresLearningCycleStore,
        )

        store = PostgresLearningCycleStore()
        finding = Finding(
            organization_id=organization_id,
            category="RETRIEVAL",
            severity=FindingSeverity.MEDIUM,
            pattern_key="excel_retrieval_issue",
            observed="Excel lookup por celda falla cuando la fila tiene merged cells",
            alternative="preferir búsqueda estructurada por campo",
            baseline_strategy="excel_cell_lookup",
            candidate_strategy="structured_field_lookup",
            sample_size=12,
            window="30d",
            confidence="medium",
            dedupe_key=f"company-demo-excel-{organization_id}",
        )
        saved_finding = await store.upsert_finding(finding)
        experiment = ExperimentRequest(
            organization_id=organization_id,
            finding_id=saved_finding.id,
            hypothesis_id=uuid5(
                NAMESPACE_URL, f"company-demo-hypothesis:{organization_id}"
            ),
            mode=ExperimentMode.SHADOW,
            kind=ExperimentKind.RETRIEVAL_STRATEGY,
            baseline="hybrid",
            candidate="structured_exact",
            status=ExperimentStatus.COMPLETED,
        )
        await store.save_experiment(experiment)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("company demo experiment failed", error=str(exc)[:200])
        return False


async def seed_demo_candidates(organization_id: UUID) -> int:
    """Candidatos de descubrimiento demo: un hueco y una relación observada.

    Se usa en tests y demos para que las vistas de gaps y de descubrimiento
    tengan contenido real sin ejecutar el motor completo.
    """
    from src.core.domain.company_discovery import (
        CandidateKind,
        CandidateSupport,
        DiscoveryCandidate,
        DiscoveryEvidence,
        DiscoverySourceKind,
        DiscoveryStage,
        GapKind,
        KnowledgeGapPayload,
        candidate_key,
    )

    store = company_discovery_repository()
    gap = KnowledgeGapPayload(
        gap_kind=GapKind.UNDOCUMENTED_STEP,
        subject="Reconciliation Process:manual-review",
        detail=(
            "step 'manual-review' occurs in 27% of observed runs but is absent "
            "from process documentation"
        ),
        frequency=0.27,
        observed_runs=100,
    )
    candidate = DiscoveryCandidate(
        organization_id=organization_id,
        kind=CandidateKind.KNOWLEDGE_GAP,
        natural_key=candidate_key(CandidateKind.KNOWLEDGE_GAP, gap.to_dict()),
        title="Gap: undocumented step manual-review",
        summary=gap.summary(),
        payload=gap.to_dict(),
        source_kind=DiscoverySourceKind.EVENT,
        source_ref="demo-seed",
        discovered_by="company_demo_seed",
        stage=DiscoveryStage.SUGGESTED,
        confidence=0.6,
        support=CandidateSupport(
            observations=100, successful_runs=100, distinct_sources=1
        ),
        evidence=(DiscoveryEvidence(source_kind=DiscoverySourceKind.EVENT, ref="demo-seed"),),
    )
    await store.upsert_candidate(candidate)
    return 1


__all__ = [
    "DEMO_AUTHORITY",
    "DEMO_DOMAIN",
    "DEMO_ENTITIES",
    "DEMO_RELATIONSHIPS",
    "DemoSeedResult",
    "seed_demo_candidates",
    "seed_fare_audit_demo",
]
