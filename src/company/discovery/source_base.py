# =============================================================================
# Company Discovery — contrato de fuentes de descubrimiento (§1)
# =============================================================================
# Cada fuente declara qué evidencia produce y entrega candidatos. Las fuentes
# deterministas (schema, config) van primero y pueden elevar la confianza sin
# interpretación; las interpretativas acumulan soporte.
#
# Los loaders (acceso a datos) se INYECTAN: el extractor es puro y testeable
# sin Postgres, y una fuente nueva se agrega registrándose (sin tocar el motor).
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID

from src.core.domain.company_discovery import (
    STRUCTURAL_SOURCES,
    CandidateKind,
    CandidateSupport,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoverySourceKind,
    DiscoveryStage,
    candidate_key,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DiscoverySource(ABC):
    """Fuente de descubrimiento. No escribe en el grafo: solo propone."""

    source_kind: DiscoverySourceKind
    name: str = ""
    #: tope de elementos leídos por corrida (nunca consultas sin límite)
    max_items: int = 200

    def __init__(self, *, max_items: int | None = None) -> None:
        if max_items is not None:
            self.max_items = max_items

    @abstractmethod
    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        """Candidatos observados en esta corrida."""
        ...

    # -- helpers de construcción --------------------------------------
    def build_candidate(
        self,
        *,
        organization_id: UUID,
        kind: CandidateKind,
        payload: dict,
        title: str,
        summary: str = "",
        support: CandidateSupport,
        evidence: DiscoveryEvidence | None = None,
        workspace_id: UUID | None = None,
        discovered_by: str = "",
        confidence: float | None = None,
    ) -> DiscoveryCandidate:
        from src.company.discovery.confidence import next_stage_for, score_candidate

        structural = self.source_kind in STRUCTURAL_SOURCES
        if structural and not support.structural:
            support = CandidateSupport(
                observations=support.observations,
                distinct_sources=support.distinct_sources,
                distinct_actors=support.distinct_actors,
                successful_runs=support.successful_runs,
                contradictions=support.contradictions,
                authoritative_sources=support.authoritative_sources,
                structural=True,
            )
        breakdown = score_candidate(kind=kind, support=support)
        total = breakdown.total if confidence is None else confidence
        # La etapa inicial la dicta la evidencia: una fuente que ya observó
        # corroboración no nace en DISCOVERED. El motor sólo puede avanzarla.
        stage = DiscoveryStage(
            next_stage_for(
                kind=kind,
                support=support,
                confidence=total,
                structural=structural,
            )
        )
        return DiscoveryCandidate(
            organization_id=organization_id,
            kind=kind,
            natural_key=candidate_key(kind, payload),
            title=title[:320],
            summary=summary,
            payload=payload,
            source_kind=self.source_kind,
            source_ref=evidence.ref if evidence else "",
            discovered_by=discovered_by or self.name or self.source_kind.value,
            stage=stage,
            confidence=total,
            confidence_factors=breakdown.factors,
            support=support,
            evidence=(evidence,) if evidence else (),
            workspace_id=workspace_id,
            first_observed_at=_utcnow(),
            last_observed_at=_utcnow(),
        )


class DiscoverySourceRegistry:
    """Registro de fuentes. Extensible sin tocar el motor."""

    _sources: dict[str, DiscoverySource] = {}

    @classmethod
    def register(cls, source: DiscoverySource) -> None:
        cls._sources[source.source_kind.value] = source

    @classmethod
    def get(cls, source_kind: DiscoverySourceKind) -> DiscoverySource | None:
        return cls._sources.get(source_kind.value)

    @classmethod
    def all(cls) -> list[DiscoverySource]:
        return list(cls._sources.values())

    @classmethod
    def for_kinds(
        cls, kinds: tuple[DiscoverySourceKind, ...]
    ) -> list[DiscoverySource]:
        if not kinds:
            return cls.all()
        wanted = {kind.value for kind in kinds}
        return [s for s in cls._sources.values() if s.source_kind.value in wanted]

    @classmethod
    def clear(cls) -> None:
        cls._sources.clear()


def default_sources() -> list[DiscoverySource]:
    """Fuentes builtin en orden: estructurado/determinista primero (§2)."""
    from src.company.discovery.sources_config import (
        AgentConfigSource,
        WorkflowConfigSource,
    )
    from src.company.discovery.sources_documents import (
        DocumentConceptSource,
        TemporalVersionSource,
    )
    from src.company.discovery.sources_structured import (
        CatalogSemanticSource,
        DatabaseSchemaSource,
        TabularStructureSource,
    )
    from src.company.discovery.sources_usage import (
        AuthorityCandidateSource,
        ObservedProcessSource,
        SqlUsageSource,
    )

    return [
        DatabaseSchemaSource(),
        CatalogSemanticSource(),
        TabularStructureSource(),
        WorkflowConfigSource(),
        AgentConfigSource(),
        SqlUsageSource(),
        ObservedProcessSource(),
        AuthorityCandidateSource(),
        DocumentConceptSource(),
        TemporalVersionSource(),
    ]


def register_default_sources() -> None:
    for source in default_sources():
        DiscoverySourceRegistry.register(source)
