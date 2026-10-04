# =============================================================================
# Enrichment — contratos
# =============================================================================
# Todos los items comparten la ley de procedencia:
#   derived=True, canonical=False, source_unit_ids no vacío, derivation_method,
#   confidence en [0,1], policy_version.
#
# Un item sin provenance no existe: el guard de calidad lo elimina antes de
# tocar el índice. Nunca se convierte en evidencia ni en conocimiento canónico.
# =============================================================================
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from .versioning import (
    ENRICHMENT_SCHEMA_VERSION,
    ENRICHMENT_VERSION,
    POLICY_VERSION,
)

DERIVATIONS = ("deterministic", "structural", "statistical", "domain_heuristic", "model")

QUERY_TYPES = (
    "exact_identifier",
    "alias",
    "semantic_paraphrase",
    "section_question",
    "relation_question",
    "table_lookup",
    "temporal_question",
    "definition",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _dedupe(values) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or ():
        cleaned = _clean(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


@dataclass(frozen=True, kw_only=True)
class EnrichmentItem:
    """Base lógica: todo lo derivado es trazable a unidades fuente."""

    source_unit_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    derivation_method: str = "deterministic"
    derived: bool = True
    canonical: bool = False
    policy_version: str = POLICY_VERSION
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("EnrichmentItem.confidence must be within [0, 1]")
        if self.derivation_method not in DERIVATIONS:
            raise ValueError(
                f"EnrichmentItem.derivation_method must be one of {DERIVATIONS}"
            )


@dataclass(frozen=True, kw_only=True)
class SemanticConcept(EnrichmentItem):
    """Concepto derivado (término de dominio, campo, columna, categoría)."""

    concept_id: str
    canonical_name: str
    semantic_type: str = "concept"
    aliases: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.canonical_name.strip():
            raise ValueError("SemanticConcept.canonical_name must not be empty")
        if not self.concept_id:
            raise ValueError("SemanticConcept.concept_id must not be empty")

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "canonical_name": self.canonical_name,
            "semantic_type": self.semantic_type,
            "aliases": list(self.aliases),
            "identifiers": list(self.identifiers),
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
            **({"metadata": dict(self.metadata)} if self.metadata else {}),
        }


@dataclass(frozen=True, kw_only=True)
class RetrievalAlias(EnrichmentItem):
    """Alias para retrieval: NO es un alias canónico de entidad."""

    value: str
    kind: str = "surface"  # surface | acronym | separator | case | code | unit
    target_concept_id: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.value.strip():
            raise ValueError("RetrievalAlias.value must not be empty")

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "kind": self.kind,
            "target_concept_id": self.target_concept_id,
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class EnrichmentIdentifier(EnrichmentItem):
    """Identificador exacto (código, byte, máscara, hex). Se guarda verbatim."""

    value: str
    identifier_type: str = "code"  # code | byte | mask | hex | numeric_id | literal

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.value.strip():
            raise ValueError("EnrichmentIdentifier.value must not be empty")

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "identifier_type": self.identifier_type,
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class DomainTerm(EnrichmentItem):
    """Término de dominio/industria (incluye unidades y qualifiers léxicos)."""

    term: str
    semantic_type: str = "domain_term"
    canonical_hint: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.term.strip():
            raise ValueError("DomainTerm.term must not be empty")

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "semantic_type": self.semantic_type,
            "canonical_hint": self.canonical_hint,
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class TemporalQualifier(EnrichmentItem):
    """Fecha/rango/vigencia detectada. No crea temporal assertions canónicas."""

    value: str
    qualifier_type: str = "date"  # date | range | validity | format
    normalized_value: str | None = None
    ambiguous: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.value.strip():
            raise ValueError("TemporalQualifier.value must not be empty")

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "qualifier_type": self.qualifier_type,
            "normalized_value": self.normalized_value,
            "ambiguous": bool(self.ambiguous),
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class SemanticReference(EnrichmentItem):
    """Referencia cruzada detectada (ver tabla X, sección Y, nota Z)."""

    reference_text: str
    target_kind: str = "section"
    target_candidate: str = ""
    resolved_target: str | None = None
    source_unit_id: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.reference_text.strip():
            raise ValueError("SemanticReference.reference_text must not be empty")

    def to_dict(self) -> dict:
        return {
            "reference_text": self.reference_text,
            "target_kind": self.target_kind,
            "target_candidate": self.target_candidate,
            "resolved_target": self.resolved_target,
            "source_unit_id": self.source_unit_id,
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class PossibleRule(EnrichmentItem):
    """Candidato a regla (if/then/must/shall/required). NO se compila aquí."""

    rule_key: str
    statement: str
    condition: str = ""
    consequence: str = ""
    language: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.statement.strip():
            raise ValueError("PossibleRule.statement must not be empty")

    def to_dict(self) -> dict:
        return {
            "rule_key": self.rule_key,
            "statement": self.statement,
            "condition": self.condition,
            "consequence": self.consequence,
            "language": self.language,
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class SyntheticQuestion(EnrichmentItem):
    """Pregunta de retrieval. NO es evidencia, NO es fact, NO se compila."""

    question: str
    query_type: str = "semantic_paraphrase"
    source_unit_id: str = ""
    target_concept_id: str | None = None
    expected_document_id: str | None = None
    expected_section_id: str | None = None
    generator_version: str = ENRICHMENT_VERSION
    synthetic: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.question.strip():
            raise ValueError("SyntheticQuestion.question must not be empty")
        if self.query_type not in QUERY_TYPES:
            raise ValueError(
                f"SyntheticQuestion.query_type must be one of {QUERY_TYPES}"
            )

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "query_type": self.query_type,
            "source_unit_id": self.source_unit_id,
            "target_concept_id": self.target_concept_id,
            "expected_document_id": self.expected_document_id,
            "expected_section_id": self.expected_section_id,
            "generator_version": self.generator_version,
            "synthetic": True,
            "canonical": False,
            "derived": True,
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class SemanticTypeTag(EnrichmentItem):
    """Asignación de semantic type a un término/unidad."""

    name: str
    semantic_type: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.name.strip():
            raise ValueError("SemanticTypeTag.name must not be empty")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "semantic_type": self.semantic_type,
            "source_unit_ids": list(self.source_unit_ids),
            "confidence": round(float(self.confidence), 4),
            "derivation_method": self.derivation_method,
            "derived": True,
            "canonical": False,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, kw_only=True)
class EnrichmentStatistics:
    """Contadores medibles (nunca texto fuente)."""

    units_total: int = 0
    concepts: int = 0
    aliases: int = 0
    identifiers: int = 0
    domain_terms: int = 0
    temporal_qualifiers: int = 0
    references: int = 0
    possible_rules: int = 0
    retrieval_aliases: int = 0
    synthetic_questions: int = 0
    semantic_types: int = 0
    deterministic_items: int = 0
    model_items: int = 0
    rejected_items: int = 0
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items()}


@dataclass(frozen=True, kw_only=True)
class EnrichmentQuality:
    """Señales de confianza del enrichment (evidence-first)."""

    items_total: int = 0
    items_with_provenance: int = 0
    orphan_items: int = 0
    unknown_source_units: int = 0
    average_confidence: float = 0.0
    min_confidence: float = 0.0
    max_confidence: float = 0.0
    prohibited_items: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def source_coverage(self) -> float:
        if self.items_total <= 0:
            return 1.0
        return round(self.items_with_provenance / self.items_total, 4)

    def to_dict(self) -> dict:
        return {
            "items_total": self.items_total,
            "items_with_provenance": self.items_with_provenance,
            "orphan_items": self.orphan_items,
            "unknown_source_units": self.unknown_source_units,
            "prohibited_items": self.prohibited_items,
            "source_coverage": self.source_coverage,
            "average_confidence": round(self.average_confidence, 4),
            "min_confidence": round(self.min_confidence, 4),
            "max_confidence": round(self.max_confidence, 4),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, kw_only=True)
class SemanticEnrichmentResult:
    """Resultado completo del enrichment de un documento."""

    organization_id: UUID
    document_id: UUID
    enrichment_version: str = ENRICHMENT_VERSION
    schema_version: str = ENRICHMENT_SCHEMA_VERSION
    policy_version: str = POLICY_VERSION
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    generated_at: datetime = field(default_factory=_utcnow)
    language: str | None = None
    concepts: tuple[SemanticConcept, ...] = ()
    aliases: tuple[RetrievalAlias, ...] = ()
    identifiers: tuple[EnrichmentIdentifier, ...] = ()
    domain_terms: tuple[DomainTerm, ...] = ()
    temporal_qualifiers: tuple[TemporalQualifier, ...] = ()
    references: tuple[SemanticReference, ...] = ()
    possible_rules: tuple[PossibleRule, ...] = ()
    retrieval_aliases: tuple[RetrievalAlias, ...] = ()
    synthetic_questions: tuple[SyntheticQuestion, ...] = ()
    semantic_types: tuple[SemanticTypeTag, ...] = ()
    statistics: EnrichmentStatistics = field(default_factory=EnrichmentStatistics)
    quality: EnrichmentQuality = field(default_factory=EnrichmentQuality)
    source_provenance: dict = field(default_factory=dict)
    derived: bool = True
    canonical: bool = False

    def items(self) -> tuple[EnrichmentItem, ...]:
        return (
            *self.concepts,
            *self.aliases,
            *self.identifiers,
            *self.domain_terms,
            *self.temporal_qualifiers,
            *self.references,
            *self.possible_rules,
            *self.retrieval_aliases,
            *self.synthetic_questions,
            *self.semantic_types,
        )

    def concepts_by_id(self) -> dict[str, SemanticConcept]:
        return {concept.concept_id: concept for concept in self.concepts}

    def payload(self, *, max_concepts: int = 24, max_questions: int = 12, max_identifiers: int = 24) -> dict:
        """Vista compacta para metadata del documento e índice (sin texto crudo)."""
        return {
            "enrichment_version": self.enrichment_version,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "generated_at": self.generated_at.isoformat(),
            "derived": True,
            "canonical": False,
            "language": self.language,
            "concepts": [item.to_dict() for item in self.concepts[:max_concepts]],
            "identifiers": [item.to_dict() for item in self.identifiers[:max_identifiers]],
            "domain_terms": [item.to_dict() for item in self.domain_terms[:max_concepts]],
            "temporal_qualifiers": [item.to_dict() for item in self.temporal_qualifiers[:12]],
            "possible_rules": [item.to_dict() for item in self.possible_rules[:12]],
            "synthetic_questions": [
                item.to_dict() for item in self.synthetic_questions[:max_questions]
            ],
            "retrieval_aliases": [item.to_dict() for item in self.retrieval_aliases[:max_concepts * 2]],
            "statistics": self.statistics.to_dict(),
            "quality": self.quality.to_dict(),
        }

    def index_fields(self, *, limit: int = 32) -> dict:
        """Campos para el payload de cada punto: ids/aliases acotados."""
        concept_ids = [item.concept_id for item in self.concepts[:limit]]
        aliases = _dedupe(
            [alias.value for alias in self.retrieval_aliases]
            + [alias for concept in self.concepts for alias in concept.aliases]
        )[:limit]
        questions = _dedupe(
            [item.question for item in self.synthetic_questions]
        )[:limit]
        identifiers = _dedupe(
            [item.value for item in self.identifiers]
            + [value for concept in self.concepts for value in concept.identifiers]
        )[:limit]
        semantic_types = _dedupe(
            [item.semantic_type for item in self.semantic_types]
            + [concept.semantic_type for concept in self.concepts]
        )[:limit]
        return {
            "enrichment_version": self.enrichment_version,
            "enrichment_derived": "true",
            "enrichment_canonical": "false",
            "concept_ids": concept_ids,
            "semantic_types": semantic_types,
            "retrieval_aliases": aliases,
            "retrieval_questions": questions,
            "enrichment_identifiers": identifiers,
        }
