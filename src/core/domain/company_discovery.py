# =============================================================================
# Domain Layer — Company Discovery Engine (Fase 5B)
# =============================================================================
# Ley fundamental:
#   DISCOVER -> SUPPORT -> SUGGEST -> VALIDATE -> CONFIRM
# Nunca: "LLM dice X" -> "X es verdad de la compañía".
#
#   - Los candidatos se ACUMULAN con evidencia; nada se confirma sin validación
#     humana o verificación estructural determinista (Fase 5A).
#   - El LLM/JEV solo desambigua cuando la resolución determinista queda
#     ambigua, y su salida sigue siendo SUGERENCIA: nunca fusión automática.
#   - La evidencia es referencias localizables, jamás chain-of-thought.
#   - Un candidato no es una entidad: proponer != afirmar.
#
# Tipos puros, sin I/O. Persistencia: migración 130. Adapter en
# infrastructure/postgres/company_discovery.py. Motor en src/company/discovery.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.company_graph import (
    SourceAuthorityLevel,
    company_entity_uuid,
    normalize_entity_type,
    normalize_relationship_type,
)

_MAX_KEY = 600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Etapas y tipos
# ---------------------------------------------------------------------------


class DiscoveryStage(StrEnum):
    """Ciclo de vida de un candidato. Progresión, no salto."""

    DISCOVERED = "discovered"
    SUPPORTED = "supported"
    SUGGESTED = "suggested"
    VALIDATED = "validated"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class CandidateKind(StrEnum):
    ENTITY = "entity"
    RELATIONSHIP = "relationship"
    MAPPING = "mapping"
    PROCESS = "process"
    SOURCE_AUTHORITY = "source_authority"
    KNOWLEDGE_GAP = "knowledge_gap"
    TERM = "term"
    TEMPORAL = "temporal"


class DiscoverySourceKind(StrEnum):
    """Fuentes consumibles. Structured/determinista primero (§2)."""

    DATABASE_SCHEMA = "database_schema"
    DATABASE_METADATA = "database_metadata"
    CATALOG = "catalog"
    TABULAR = "tabular"
    DOCUMENT = "document"
    SQL_QUERY = "sql_query"
    VERIFIED_QUERY = "verified_query"
    AGENT_CONFIG = "agent_config"
    WORKFLOW_CONFIG = "workflow_config"
    TOOL_CONFIG = "tool_config"
    EVENT = "event"
    CONVERSATION = "conversation"
    MEMORY = "memory"
    FINDING = "finding"
    CLAIM = "claim"
    EVIDENCE_LEDGER = "evidence_ledger"
    API_METADATA = "api_metadata"


# Fuentes cuya evidencia es determinista (no interpretación).
STRUCTURAL_SOURCES = frozenset(
    {
        DiscoverySourceKind.DATABASE_SCHEMA,
        DiscoverySourceKind.DATABASE_METADATA,
        DiscoverySourceKind.TOOL_CONFIG,
        DiscoverySourceKind.WORKFLOW_CONFIG,
        DiscoverySourceKind.AGENT_CONFIG,
        DiscoverySourceKind.API_METADATA,
    }
)

# Fuentes que requieren soporte acumulado o revisión, nunca confianza alta sola.
INTERPRETIVE_SOURCES = frozenset(
    {
        DiscoverySourceKind.DOCUMENT,
        DiscoverySourceKind.CONVERSATION,
        DiscoverySourceKind.SQL_QUERY,
        DiscoverySourceKind.VERIFIED_QUERY,
        DiscoverySourceKind.EVENT,
        DiscoverySourceKind.MEMORY,
        DiscoverySourceKind.FINDING,
        DiscoverySourceKind.CLAIM,
        DiscoverySourceKind.EVIDENCE_LEDGER,
    }
)


class DiscoveryTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    EVENT = "event"
    INGESTION = "ingestion"


class ProcessMode(StrEnum):
    """DESIGNED = documentado/definido en workflow. OBSERVED = ejecución real."""

    DESIGNED = "designed"
    OBSERVED = "observed"


class GapKind(StrEnum):
    UNDOCUMENTED_STEP = "undocumented_step"
    DOCUMENTED_BUT_UNOBSERVED = "documented_but_unobserved"
    NO_AUTHORITATIVE_DEFINITION = "no_authoritative_definition"
    MISSING_TECHNICAL_MAPPING = "missing_technical_mapping"
    CONTRADICTORY_DEFINITION = "contradictory_definition"
    AMBIGUOUS_ENTITY = "ambiguous_entity"


_ALLOWED_STAGE_TRANSITIONS: dict[DiscoveryStage, frozenset[DiscoveryStage]] = {
    DiscoveryStage.DISCOVERED: frozenset(
        {
            DiscoveryStage.SUPPORTED,
            DiscoveryStage.SUGGESTED,
            DiscoveryStage.REJECTED,
        }
    ),
    DiscoveryStage.SUPPORTED: frozenset(
        {
            DiscoveryStage.SUGGESTED,
            DiscoveryStage.VALIDATED,
            DiscoveryStage.DISCOVERED,
            DiscoveryStage.REJECTED,
        }
    ),
    DiscoveryStage.SUGGESTED: frozenset(
        {DiscoveryStage.VALIDATED, DiscoveryStage.REJECTED}
    ),
    DiscoveryStage.VALIDATED: frozenset(
        {DiscoveryStage.CONFIRMED, DiscoveryStage.REJECTED}
    ),
    DiscoveryStage.CONFIRMED: frozenset({DiscoveryStage.REJECTED}),
    DiscoveryStage.REJECTED: frozenset(),
}


def assert_stage_transition(old: DiscoveryStage, new: DiscoveryStage) -> None:
    """Prohibido saltar etapas o revivir un rechazo."""
    if old is new:
        return
    if new not in _ALLOWED_STAGE_TRANSITIONS[old]:
        raise ValueError(
            f"discovery stage transition not allowed: {old.value} -> {new.value}"
        )


def requires_human_confirmation(
    kind: CandidateKind, *, structural: bool = False
) -> bool:
    """Confirmar es acto humano salvo verificación estructural determinista.

    Un candidato interpretativo (documento, conversación, LLM) nunca se
    confirma solo: el motor lo deja en SUGGESTED y exige validación.
    """
    if kind in (CandidateKind.KNOWLEDGE_GAP, CandidateKind.TEMPORAL):
        return False
    if kind is CandidateKind.SOURCE_AUTHORITY:
        return not structural
    return not structural


# ---------------------------------------------------------------------------
# Referencias y evidencia
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityRef:
    """Referencia lógica a una entidad del grafo (id determinista).

    El candidato puede existir antes que la entidad: el id se deriva igual que
    en Fase 5A, así el promote es idempotente y no duplica nodos.
    """

    entity_type: str
    canonical_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_type", normalize_entity_type(self.entity_type))
        if not self.canonical_name.strip():
            raise ValueError("EntityRef.canonical_name must not be empty")

    def entity_id(self, organization_id: UUID) -> UUID:
        return company_entity_uuid(
            organization_id, self.entity_type, self.canonical_name
        )

    def to_dict(self) -> dict:
        return {"entity_type": self.entity_type, "canonical_name": self.canonical_name}

    @classmethod
    def from_dict(cls, payload: dict) -> EntityRef:
        return cls(
            entity_type=str(payload["entity_type"]),
            canonical_name=str(payload["canonical_name"]),
        )


@dataclass(frozen=True, kw_only=True)
class DiscoveryEvidence:
    """Referencia localizable que sostiene un candidato. Sin chain-of-thought."""

    source_kind: DiscoverySourceKind
    ref: str
    detail: dict = field(default_factory=dict)
    excerpt: str = ""

    def __post_init__(self) -> None:
        if not self.ref.strip():
            raise ValueError("DiscoveryEvidence.ref must not be empty")

    def to_dict(self) -> dict:
        return {
            "source_kind": self.source_kind.value,
            "ref": self.ref,
            "detail": self.detail,
            "excerpt": self.excerpt[:400],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> DiscoveryEvidence:
        return cls(
            source_kind=DiscoverySourceKind(payload["source_kind"]),
            ref=str(payload["ref"]),
            detail=dict(payload.get("detail") or {}),
            excerpt=str(payload.get("excerpt") or ""),
        )


@dataclass(frozen=True, kw_only=True)
class CandidateSupport:
    """Soporte acumulado. Contar ocurrencias no basta (§8)."""

    observations: int = 0
    distinct_sources: int = 0
    distinct_actors: int = 0
    successful_runs: int = 0
    contradictions: int = 0
    authoritative_sources: int = 0
    structural: bool = False

    def merged(self, other: CandidateSupport) -> CandidateSupport:
        return CandidateSupport(
            observations=self.observations + other.observations,
            distinct_sources=max(self.distinct_sources, other.distinct_sources),
            distinct_actors=max(self.distinct_actors, other.distinct_actors),
            successful_runs=self.successful_runs + other.successful_runs,
            contradictions=max(self.contradictions, other.contradictions),
            authoritative_sources=max(
                self.authoritative_sources, other.authoritative_sources
            ),
            structural=self.structural or other.structural,
        )

    def to_dict(self) -> dict:
        return {
            "observations": self.observations,
            "distinct_sources": self.distinct_sources,
            "distinct_actors": self.distinct_actors,
            "successful_runs": self.successful_runs,
            "contradictions": self.contradictions,
            "authoritative_sources": self.authoritative_sources,
            "structural": self.structural,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> CandidateSupport:
        return cls(
            observations=int(payload.get("observations") or 0),
            distinct_sources=int(payload.get("distinct_sources") or 0),
            distinct_actors=int(payload.get("distinct_actors") or 0),
            successful_runs=int(payload.get("successful_runs") or 0),
            contradictions=int(payload.get("contradictions") or 0),
            authoritative_sources=int(payload.get("authoritative_sources") or 0),
            structural=bool(payload.get("structural")),
        )


@dataclass(frozen=True, kw_only=True)
class ConfidenceBreakdown:
    """Confianza trazable: cada factor explica el número final."""

    total: float
    factors: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.total <= 1.0:
            raise ValueError("ConfidenceBreakdown.total must be within [0, 1]")

    def to_dict(self) -> dict:
        return {"total": self.total, "factors": dict(self.factors)}


# ---------------------------------------------------------------------------
# Payloads tipados (lo que el candidato propone)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class EntityCandidatePayload:
    entity_type: str
    canonical_name: str
    display_name: str = ""
    description: str = ""
    domain: str = "general"
    aliases: tuple[str, ...] = ()
    technical_identifiers: tuple[str, ...] = ()
    abbreviation: str = ""
    keyword: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_type", normalize_entity_type(self.entity_type))
        if not self.canonical_name.strip():
            raise ValueError("EntityCandidatePayload.canonical_name must not be empty")

    @property
    def ref(self) -> EntityRef:
        return EntityRef(
            entity_type=self.entity_type, canonical_name=self.canonical_name
        )

    def to_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "display_name": self.display_name,
            "description": self.description,
            "domain": self.domain,
            "aliases": list(self.aliases),
            "technical_identifiers": list(self.technical_identifiers),
            "abbreviation": self.abbreviation,
            "keyword": self.keyword,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> EntityCandidatePayload:
        return cls(
            entity_type=str(payload["entity_type"]),
            canonical_name=str(payload["canonical_name"]),
            display_name=str(payload.get("display_name") or ""),
            description=str(payload.get("description") or ""),
            domain=str(payload.get("domain") or "general"),
            aliases=tuple(payload.get("aliases") or ()),
            technical_identifiers=tuple(payload.get("technical_identifiers") or ()),
            abbreviation=str(payload.get("abbreviation") or ""),
            keyword=str(payload.get("keyword") or ""),
        )


@dataclass(frozen=True, kw_only=True)
class RelationshipCandidatePayload:
    from_ref: EntityRef
    to_ref: EntityRef
    relationship_type: str
    observed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relationship_type",
            normalize_relationship_type(self.relationship_type),
        )
        if self.from_ref == self.to_ref:
            raise ValueError("relationship candidate must link two different entities")

    def to_dict(self) -> dict:
        return {
            "from_ref": self.from_ref.to_dict(),
            "to_ref": self.to_ref.to_dict(),
            "relationship_type": self.relationship_type,
            "observed": self.observed,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> RelationshipCandidatePayload:
        return cls(
            from_ref=EntityRef.from_dict(payload["from_ref"]),
            to_ref=EntityRef.from_dict(payload["to_ref"]),
            relationship_type=str(payload["relationship_type"]),
            observed=bool(payload.get("observed")),
        )


@dataclass(frozen=True, kw_only=True)
class MappingCandidatePayload:
    """Concepto de negocio propuesto -> objetivo técnico estructurado (§13)."""

    concept_ref: EntityRef
    target_ref: EntityRef
    values: tuple[str, ...] = ()
    predicate: str = ""
    mapping_type: str = "DIRECT"

    def to_dict(self) -> dict:
        return {
            "concept_ref": self.concept_ref.to_dict(),
            "target_ref": self.target_ref.to_dict(),
            "values": list(self.values),
            "predicate": self.predicate,
            "mapping_type": self.mapping_type,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> MappingCandidatePayload:
        return cls(
            concept_ref=EntityRef.from_dict(payload["concept_ref"]),
            target_ref=EntityRef.from_dict(payload["target_ref"]),
            values=tuple(payload.get("values") or ()),
            predicate=str(payload.get("predicate") or ""),
            mapping_type=str(payload.get("mapping_type") or "DIRECT"),
        )


@dataclass(frozen=True, kw_only=True)
class ProcessStep:
    name: str
    order: int
    frequency: float = 0.0
    runs: int = 0
    documented: bool = False
    system: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ProcessStep.name must not be empty")
        if self.order < 0:
            raise ValueError("ProcessStep.order must be >= 0")
        if not 0.0 <= self.frequency <= 1.0:
            raise ValueError("ProcessStep.frequency must be within [0, 1]")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "order": self.order,
            "frequency": self.frequency,
            "runs": self.runs,
            "documented": self.documented,
            "system": self.system,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ProcessStep:
        return cls(
            name=str(payload["name"]),
            order=int(payload.get("order") or 0),
            frequency=float(payload.get("frequency") or 0.0),
            runs=int(payload.get("runs") or 0),
            documented=bool(payload.get("documented")),
            system=str(payload.get("system") or ""),
        )


@dataclass(frozen=True, kw_only=True)
class ProcessCandidatePayload:
    name: str
    mode: ProcessMode
    steps: tuple[ProcessStep, ...] = ()
    runs_observed: int = 0
    systems: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    workflow_id: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ProcessCandidatePayload.name must not be empty")

    def step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in sorted(self.steps, key=lambda s: s.order))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mode": self.mode.value,
            "steps": [s.to_dict() for s in self.steps],
            "runs_observed": self.runs_observed,
            "systems": list(self.systems),
            "events": list(self.events),
            "rules": list(self.rules),
            "workflow_id": self.workflow_id,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ProcessCandidatePayload:
        return cls(
            name=str(payload["name"]),
            mode=ProcessMode(payload.get("mode") or ProcessMode.OBSERVED.value),
            steps=tuple(ProcessStep.from_dict(s) for s in payload.get("steps") or ()),
            runs_observed=int(payload.get("runs_observed") or 0),
            systems=tuple(payload.get("systems") or ()),
            events=tuple(payload.get("events") or ()),
            rules=tuple(payload.get("rules") or ()),
            workflow_id=str(payload.get("workflow_id") or ""),
        )


@dataclass(frozen=True, kw_only=True)
class DivergentStep:
    name: str
    frequency: float
    runs: int
    present_in: str  # designed | observed

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "frequency": self.frequency,
            "runs": self.runs,
            "present_in": self.present_in,
        }


@dataclass(frozen=True, kw_only=True)
class ProcessDivergence:
    """Diseñado vs observado: base de Knowledge Gap Discovery (§10/§11)."""

    process_name: str
    undocumented_steps: tuple[DivergentStep, ...] = ()
    unobserved_steps: tuple[DivergentStep, ...] = ()
    observed_runs: int = 0

    @property
    def has_divergence(self) -> bool:
        return bool(self.undocumented_steps or self.unobserved_steps)


def compare_processes(
    designed: ProcessCandidatePayload, observed: ProcessCandidatePayload
) -> ProcessDivergence:
    """Compara un proceso diseñado con su ejecución observada.

    Sólo compara nombres de paso normalizados: no infiere equivalencias
    semánticas (eso sería interpretación, no observación).
    """
    designed_names = {_norm_step(name) for name in designed.step_names()}
    observed_names = {_norm_step(name) for name in observed.step_names()}
    undocumented = tuple(
        DivergentStep(
            name=step.name,
            frequency=step.frequency,
            runs=step.runs,
            present_in=ProcessMode.OBSERVED.value,
        )
        for step in observed.steps
        if _norm_step(step.name) not in designed_names
    )
    unobserved = tuple(
        DivergentStep(
            name=step.name,
            frequency=step.frequency,
            runs=step.runs,
            present_in=ProcessMode.DESIGNED.value,
        )
        for step in designed.steps
        if _norm_step(step.name) not in observed_names
    )
    return ProcessDivergence(
        process_name=observed.name or designed.name,
        undocumented_steps=undocumented,
        unobserved_steps=unobserved,
        observed_runs=observed.runs_observed,
    )


def _norm_step(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


@dataclass(frozen=True, kw_only=True)
class AuthorityCandidatePayload:
    domain: str
    concept: str
    source_name: str
    proposed_level: SourceAuthorityLevel
    rationale: str = ""
    source_type: str = "database"

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "concept": self.concept,
            "source_name": self.source_name,
            "proposed_level": self.proposed_level.value,
            "rationale": self.rationale,
            "source_type": self.source_type,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> AuthorityCandidatePayload:
        return cls(
            domain=str(payload.get("domain") or "general"),
            concept=str(payload.get("concept") or ""),
            source_name=str(payload["source_name"]),
            proposed_level=SourceAuthorityLevel(
                payload.get("proposed_level") or SourceAuthorityLevel.PRIMARY.value
            ),
            rationale=str(payload.get("rationale") or ""),
            source_type=str(payload.get("source_type") or "database"),
        )


@dataclass(frozen=True, kw_only=True)
class KnowledgeGapPayload:
    gap_kind: GapKind
    subject: str
    detail: str = ""
    frequency: float = 0.0
    observed_runs: int = 0
    evidence_summary: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("KnowledgeGapPayload.subject must not be empty")

    def to_dict(self) -> dict:
        return {
            "gap_kind": self.gap_kind.value,
            "subject": self.subject,
            "detail": self.detail,
            "frequency": self.frequency,
            "observed_runs": self.observed_runs,
            "evidence_summary": list(self.evidence_summary),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> KnowledgeGapPayload:
        return cls(
            gap_kind=GapKind(payload["gap_kind"]),
            subject=str(payload["subject"]),
            detail=str(payload.get("detail") or ""),
            frequency=float(payload.get("frequency") or 0.0),
            observed_runs=int(payload.get("observed_runs") or 0),
            evidence_summary=tuple(payload.get("evidence_summary") or ()),
        )

    def summary(self) -> str:
        if self.frequency and self.observed_runs:
            return (
                f"{self.subject} occurs in {self.frequency:.0%} of "
                f"{self.observed_runs} observed runs"
            )
        return self.detail or self.subject


@dataclass(frozen=True, kw_only=True)
class TermCandidatePayload:
    """Business terminology observada -> concepto propuesto (§7)."""

    term: str
    aliases: tuple[str, ...] = ()
    proposed_concept: str = ""
    domain: str = "general"

    def __post_init__(self) -> None:
        if not self.term.strip():
            raise ValueError("TermCandidatePayload.term must not be empty")

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "aliases": list(self.aliases),
            "proposed_concept": self.proposed_concept,
            "domain": self.domain,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> TermCandidatePayload:
        return cls(
            term=str(payload["term"]),
            aliases=tuple(payload.get("aliases") or ()),
            proposed_concept=str(payload.get("proposed_concept") or ""),
            domain=str(payload.get("domain") or "general"),
        )


@dataclass(frozen=True, kw_only=True)
class TemporalCandidatePayload:
    """Vigencia descubierta + relación entre versiones (§14)."""

    subject_ref: EntityRef
    superseded_by_ref: EntityRef | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    version_label: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.effective_from and self.effective_to:
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to must be >= effective_from")

    def to_dict(self) -> dict:
        return {
            "subject_ref": self.subject_ref.to_dict(),
            "superseded_by_ref": (
                self.superseded_by_ref.to_dict() if self.superseded_by_ref else None
            ),
            "effective_from": self.effective_from.isoformat()
            if self.effective_from
            else None,
            "effective_to": self.effective_to.isoformat()
            if self.effective_to
            else None,
            "version_label": self.version_label,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> TemporalCandidatePayload:
        def _dt(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        superseded = payload.get("superseded_by_ref")
        return cls(
            subject_ref=EntityRef.from_dict(payload["subject_ref"]),
            superseded_by_ref=EntityRef.from_dict(superseded) if superseded else None,
            effective_from=_dt(payload.get("effective_from")),
            effective_to=_dt(payload.get("effective_to")),
            version_label=str(payload.get("version_label") or ""),
            note=str(payload.get("note") or ""),
        )


# ---------------------------------------------------------------------------
# Agregado: DiscoveryCandidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DiscoveryCandidate:
    """Propuesta estructurada. Nunca es verdad por sí misma."""

    organization_id: UUID
    kind: CandidateKind
    natural_key: str
    title: str
    payload: dict
    source_kind: DiscoverySourceKind
    source_ref: str = ""
    discovered_by: str = ""
    summary: str = ""
    stage: DiscoveryStage = DiscoveryStage.DISCOVERED
    confidence: float = 0.0
    confidence_factors: dict = field(default_factory=dict)
    support: CandidateSupport = field(default_factory=CandidateSupport)
    evidence: tuple[DiscoveryEvidence, ...] = ()
    resolution: dict = field(default_factory=dict)
    workspace_id: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    materialized_id: UUID | None = None
    first_observed_at: datetime = field(default_factory=_utcnow)
    last_observed_at: datetime = field(default_factory=_utcnow)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.natural_key.strip():
            raise ValueError("DiscoveryCandidate.natural_key must not be empty")
        if len(self.natural_key) > _MAX_KEY:
            raise ValueError(f"natural_key must be <= {_MAX_KEY} chars")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("DiscoveryCandidate.confidence must be within [0, 1]")

    @property
    def structural(self) -> bool:
        return self.source_kind in STRUCTURAL_SOURCES or self.support.structural

    def with_observation(
        self,
        *,
        support: CandidateSupport,
        evidence: DiscoveryEvidence | None,
        confidence: ConfidenceBreakdown,
        stage: DiscoveryStage | None = None,
    ) -> DiscoveryCandidate:
        """Acumula una nueva observación. Nunca degrada evidencia previa."""
        merged_evidence = self.evidence
        if evidence is not None and not any(
            item.ref == evidence.ref and item.source_kind is evidence.source_kind
            for item in self.evidence
        ):
            merged_evidence = self.evidence + (evidence,)
        return replace(
            self,
            support=self.support.merged(support),
            evidence=merged_evidence,
            confidence=confidence.total,
            confidence_factors=confidence.factors,
            stage=stage or self.stage,
            last_observed_at=_utcnow(),
            updated_at=_utcnow(),
        )

    def with_stage(self, stage: DiscoveryStage) -> DiscoveryCandidate:
        assert_stage_transition(self.stage, stage)
        return replace(self, stage=stage, updated_at=_utcnow())

    def resolved(self, resolution: dict) -> DiscoveryCandidate:
        return replace(self, resolution=resolution, updated_at=_utcnow())

    def materialized(self, entity_id: UUID) -> DiscoveryCandidate:
        return replace(
            self, materialized_id=entity_id, updated_at=_utcnow()
        )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "kind": self.kind.value,
            "natural_key": self.natural_key,
            "title": self.title,
            "summary": self.summary,
            "payload": self.payload,
            "source_kind": self.source_kind.value,
            "source_ref": self.source_ref,
            "discovered_by": self.discovered_by,
            "stage": self.stage.value,
            "confidence": self.confidence,
            "confidence_factors": self.confidence_factors,
            "support": self.support.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "resolution": self.resolution,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "materialized_id": (
                str(self.materialized_id) if self.materialized_id else None
            ),
            "first_observed_at": self.first_observed_at.isoformat(),
            "last_observed_at": self.last_observed_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Corrida de descubrimiento (job)
# ---------------------------------------------------------------------------


class DiscoveryRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class DiscoveryRun:
    """Corrida de descubrimiento. Sirve como job durable (§23)."""

    organization_id: UUID
    trigger: DiscoveryTrigger = DiscoveryTrigger.MANUAL
    status: DiscoveryRunStatus = DiscoveryRunStatus.PENDING
    source_kinds: tuple[DiscoverySourceKind, ...] = ()
    candidates_found: int = 0
    candidates_new: int = 0
    candidates_updated: int = 0
    promoted: int = 0
    conflicts: int = 0
    metrics: dict = field(default_factory=dict)
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime = field(default_factory=_utcnow)
    id: UUID = field(default_factory=uuid4)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "trigger": self.trigger.value,
            "status": self.status.value,
            "source_kinds": [kind.value for kind in self.source_kinds],
            "candidates_found": self.candidates_found,
            "candidates_new": self.candidates_new,
            "candidates_updated": self.candidates_updated,
            "promoted": self.promoted,
            "conflicts": self.conflicts,
            "metrics": self.metrics,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Candidate factory helpers (dedupe keys canónicas)
# ---------------------------------------------------------------------------


def entity_candidate_key(payload: EntityCandidatePayload) -> str:
    return f"entity:{payload.entity_type}:{payload.canonical_name.strip().lower()}"


def relationship_candidate_key(payload: RelationshipCandidatePayload) -> str:
    return (
        f"relationship:{payload.from_ref.entity_type}:"
        f"{payload.from_ref.canonical_name.strip().lower()}:"
        f"{payload.relationship_type}:"
        f"{payload.to_ref.entity_type}:{payload.to_ref.canonical_name.strip().lower()}"
    )


def mapping_candidate_key(payload: MappingCandidatePayload) -> str:
    return (
        f"mapping:{payload.concept_ref.canonical_name.strip().lower()}:"
        f"{payload.target_ref.entity_type}:"
        f"{payload.target_ref.canonical_name.strip().lower()}"
    )


def process_candidate_key(payload: ProcessCandidatePayload) -> str:
    return f"process:{payload.mode.value}:{payload.name.strip().lower()}"


def authority_candidate_key(payload: AuthorityCandidatePayload) -> str:
    return (
        f"authority:{payload.domain.strip().lower()}:"
        f"{payload.concept.strip().lower()}:{payload.source_name.strip().lower()}"
    )


def gap_candidate_key(payload: KnowledgeGapPayload) -> str:
    return f"gap:{payload.gap_kind.value}:{payload.subject.strip().lower()}"


def term_candidate_key(payload: TermCandidatePayload) -> str:
    return f"term:{payload.term.strip().lower()}"


def temporal_candidate_key(payload: TemporalCandidatePayload) -> str:
    version = payload.version_label or (
        payload.effective_from.date().isoformat() if payload.effective_from else "open"
    )
    return (
        f"temporal:{payload.subject_ref.canonical_name.strip().lower()}:{version}"
    )


def candidate_key(kind: CandidateKind, payload: dict) -> str:
    """Clave canónica de dedupe por tipo de candidato."""
    if kind is CandidateKind.ENTITY:
        return entity_candidate_key(EntityCandidatePayload.from_dict(payload))
    if kind is CandidateKind.RELATIONSHIP:
        return relationship_candidate_key(
            RelationshipCandidatePayload.from_dict(payload)
        )
    if kind is CandidateKind.MAPPING:
        return mapping_candidate_key(MappingCandidatePayload.from_dict(payload))
    if kind is CandidateKind.PROCESS:
        return process_candidate_key(ProcessCandidatePayload.from_dict(payload))
    if kind is CandidateKind.SOURCE_AUTHORITY:
        return authority_candidate_key(AuthorityCandidatePayload.from_dict(payload))
    if kind is CandidateKind.KNOWLEDGE_GAP:
        return gap_candidate_key(KnowledgeGapPayload.from_dict(payload))
    if kind is CandidateKind.TERM:
        return term_candidate_key(TermCandidatePayload.from_dict(payload))
    if kind is CandidateKind.TEMPORAL:
        return temporal_candidate_key(TemporalCandidatePayload.from_dict(payload))
    raise ValueError(f"unsupported candidate kind: {kind}")


__all__ = [
    "AuthorityCandidatePayload",
    "CandidateKind",
    "CandidateSupport",
    "ConfidenceBreakdown",
    "DiscoveryCandidate",
    "DiscoveryEvidence",
    "DiscoveryRun",
    "DiscoveryRunStatus",
    "DiscoverySourceKind",
    "DiscoveryStage",
    "DiscoveryTrigger",
    "DivergentStep",
    "EntityCandidatePayload",
    "EntityRef",
    "GapKind",
    "KnowledgeGapPayload",
    "MappingCandidatePayload",
    "ProcessCandidatePayload",
    "ProcessDivergence",
    "ProcessMode",
    "ProcessStep",
    "RelationshipCandidatePayload",
    "STRUCTURAL_SOURCES",
    "SourceAuthorityLevel",
    "TemporalCandidatePayload",
    "TermCandidatePayload",
    "assert_stage_transition",
    "candidate_key",
    "compare_processes",
    "requires_human_confirmation",
]
