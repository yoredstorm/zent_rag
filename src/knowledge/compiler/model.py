# =============================================================================
# Knowledge Compiler — tipos canónicos
# =============================================================================
# El compilador convierte una FUENTE en conocimiento canónico verificable:
#
#   raw source -> parsed source -> structural model -> semantic units
#              -> entities -> facts -> relationships -> rules -> temporal facts
#              -> knowledge objects -> evidence links -> canonical knowledge
#
# Leyes:
#   - EVIDENCE FIRST: ningún candidate existe sin evidencia localizable.
#   - Nada se fusiona sin evidencia: el merge de entidades guarda razón y
#     confianza, y nunca une dos entidades por parecido superficial solo.
#   - La procedencia es un dato, no un comentario: cada candidato lleva el
#     locator exacto (documento, página, sección, bloque, tabla, fila, celda).
#   - Sin I/O: tipos puros, reutilizables por pipeline, API y tests.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


def normalize_term(value: str) -> str:
    """Normaliza un término para identidad canónica y comparación.

    No inventa equivalencias: colapsa espacios, unifica mayúsculas y quita
    puntuación de borde. "Record 4." ≡ "RECORD 4" ≡ " record   4 ".
    """
    text = (value or "").strip().strip(".,;:()[]\"'`«»").strip()
    return " ".join(text.lower().split())


# -----------------------------------------------------------------------------
# Unidades semánticas
# -----------------------------------------------------------------------------


class SemanticUnitKind(StrEnum):
    """Tipos de unidad semántica que el compilador reconoce."""

    DEFINITION = "definition"
    FIELD = "field"
    TABLE = "table"
    COLUMN = "column"
    LITERAL = "literal"
    PROCEDURE_STEP = "procedure_step"
    NOTE = "note"
    WARNING = "warning"
    EXAMPLE = "example"
    REFERENCE = "reference"
    SECTION = "section"


class EvidenceType(StrEnum):
    """Origen físico de la evidencia (fuerza explicable, no inventada)."""

    DETERMINISTIC = "deterministic"
    SCHEMA = "schema"
    STRUCTURAL = "structural"
    STATISTICAL = "statistical"
    DOCUMENT = "document"
    HUMAN = "human"
    LLM = "llm"


EVIDENCE_STRENGTH: dict[str, float] = {
    EvidenceType.DETERMINISTIC.value: 1.00,
    EvidenceType.SCHEMA.value: 0.95,
    EvidenceType.STRUCTURAL.value: 0.85,
    EvidenceType.STATISTICAL.value: 0.80,
    EvidenceType.DOCUMENT.value: 0.70,
    EvidenceType.HUMAN.value: 0.90,
    EvidenceType.LLM.value: 0.50,
}


@dataclass(kw_only=True)
class SourceLocator:
    """Dónde vive exactamente la evidencia.

    Es el contrato de provenance del Knowledge OS: cualquier afirmación debe
    poder volver hasta aquí, y desde aquí hasta la fuente original.
    """

    source_id: UUID | None = None
    document_id: UUID | None = None
    document_title: str = ""
    block_id: UUID | None = None
    page: int | None = None
    section_path: tuple[str, ...] = ()
    table_reference: str | None = None
    row_reference: str | None = None
    cell_reference: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    database_reference: str | None = None
    content_hash: str | None = None

    def locator_uri(self) -> str:
        """URI estable y legible del locator (para el evidence ledger)."""
        parts: list[str] = []
        if self.document_id is not None:
            parts.append(f"document/{self.document_id}")
        if self.section_path:
            parts.append("section/" + "/".join(self.section_path))
        if self.page is not None:
            parts.append(f"page/{self.page}")
        if self.block_id is not None:
            parts.append(f"block/{self.block_id}")
        if self.table_reference:
            parts.append(f"table/{self.table_reference}")
        if self.row_reference:
            parts.append(f"row/{self.row_reference}")
        if self.cell_reference:
            parts.append(f"cell/{self.cell_reference}")
        if self.database_reference:
            parts.append(f"db/{self.database_reference}")
        return "//".join(parts) if parts else "source/unknown"

    def to_dict(self) -> dict:
        return {
            "source_id": str(self.source_id) if self.source_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "document_title": self.document_title,
            "block_id": str(self.block_id) if self.block_id else None,
            "page": self.page,
            "section_path": list(self.section_path),
            "table_reference": self.table_reference,
            "row_reference": self.row_reference,
            "cell_reference": self.cell_reference,
            "database_reference": self.database_reference,
            "locator": self.locator_uri(),
        }


@dataclass(kw_only=True)
class EvidenceRef:
    """Evidencia concreta que respalda un candidato."""

    locator: SourceLocator
    evidence_type: str = EvidenceType.DOCUMENT.value
    excerpt: str = ""
    method: str = "deterministic"
    confidence: float = 0.7

    @property
    def strength(self) -> float:
        base = EVIDENCE_STRENGTH.get(self.evidence_type, 0.5)
        return max(0.05, min(1.0, base * max(0.0, min(1.0, self.confidence))))

    def to_dict(self) -> dict:
        return {
            "locator": self.locator.to_dict(),
            "evidence_type": self.evidence_type,
            "strength": round(self.strength, 4),
            "excerpt": self.excerpt[:400],
            "method": self.method,
        }


@dataclass(kw_only=True)
class TemporalScope:
    """Vigencia del conocimiento. Vacío = vigente y sin ventana declarada."""

    effective_from: date | None = None
    effective_to: date | None = None
    observed_at: datetime | None = None
    version_label: str | None = None
    scope: str | None = None

    @property
    def is_bounded(self) -> bool:
        return self.effective_from is not None or self.effective_to is not None

    def to_dict(self) -> dict:
        return {
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "version_label": self.version_label,
            "scope": self.scope,
        }


@dataclass(kw_only=True)
class SemanticUnit:
    """Unidad mínima de significado extraída de una fuente."""

    kind: str
    key: str
    label: str
    text: str = ""
    confidence: float = 0.7
    attributes: dict = field(default_factory=dict)
    evidence: EvidenceRef

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "key": self.key,
            "label": self.label,
            "text": self.text[:600],
            "confidence": round(self.confidence, 4),
            "attributes": self.attributes,
            "evidence": self.evidence.to_dict(),
        }


# -----------------------------------------------------------------------------
# Entidades e identidad canónica
# -----------------------------------------------------------------------------


class EntityType(StrEnum):
    """Tipo lógico de entidad. Se deriva de la evidencia, no se asume."""

    CONCEPT = "concept"
    TERM = "term"
    RECORD = "record"
    CATEGORY = "category"
    FIELD = "field"
    CODE = "code"
    TABLE = "table"
    COLUMN = "column"
    SOURCE = "source"
    DOCUMENT = "document"
    ORGANIZATION = "organization"
    PROCESS = "process"
    UNKNOWN = "unknown"


class AliasType(StrEnum):
    """Por qué dos nombres apuntan a la misma entidad."""

    SYNONYM = "synonym"
    ABBREVIATION = "abbreviation"
    ACRONYM = "acronym"
    ALTERNATE_SPELLING = "alternate_spelling"
    CONTEXTUAL_NAME = "contextual_name"
    CODE = "code"
    TRANSLATION = "translation"


@dataclass(kw_only=True)
class EntityAlias:
    alias: str
    alias_type: str = AliasType.SYNONYM.value
    confidence: float = 0.6
    reason: str = ""
    evidence: EvidenceRef | None = None

    @property
    def normalized(self) -> str:
        return normalize_term(self.alias)

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "normalized": self.normalized,
            "alias_type": self.alias_type,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(kw_only=True)
class EntityCandidate:
    """Entidad descubierta, con su identidad canónica propuesta."""

    name: str
    entity_type: str = EntityType.CONCEPT.value
    description: str | None = None
    domain: str | None = None
    confidence: float = 0.7
    aliases: list[EntityAlias] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)

    @property
    def normalized(self) -> str:
        return normalize_term(self.name)

    @property
    def natural_key(self) -> str:
        """Identidad por NOMBRE normalizado, no por dónde apareció.

        "Record 4" es el mismo objeto de conocimiento si lo define un PDF o si
        es la cabecera de una columna en Excel: la procedencia cambia, la
        identidad no. El tipo lógico viaja como atributo, no como identidad.
        """
        return f"entity:{self.normalized}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "normalized": self.normalized,
            "entity_type": self.entity_type,
            "description": self.description,
            "domain": self.domain,
            "natural_key": self.natural_key,
            "confidence": round(self.confidence, 4),
            "aliases": [a.to_dict() for a in self.aliases],
            "evidence_count": len(self.evidence),
        }


@dataclass(kw_only=True)
class EntityMerge:
    """Resultado de resolver dos nombres al mismo canónico. Siempre con razón."""

    canonical_name: str
    merged_alias: str
    alias_type: str
    reason: str
    confidence: float


# -----------------------------------------------------------------------------
# Hechos, relaciones, reglas
# -----------------------------------------------------------------------------


class FactKind(StrEnum):
    DEFINITION = "definition"
    FIELD_MEANING = "field_meaning"
    STRUCTURAL = "structural"
    RULE = "rule"
    CONSTRAINT = "constraint"
    PROCESS_STEP = "process_step"
    METRIC = "metric"
    REFERENCE = "reference"
    OTHER = "other"


@dataclass(kw_only=True)
class FactCandidate:
    """Afirmación atómica: (sujeto, predicado, objeto) con evidencia."""

    subject: str
    predicate: str
    object_value: str | None = None
    subject_type: str = EntityType.CONCEPT.value
    object_type: str | None = None
    fact_kind: str = FactKind.OTHER.value
    method: str = "deterministic"
    confidence: float = 0.7
    temporal: TemporalScope = field(default_factory=TemporalScope)
    attributes: dict = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)

    @property
    def subject_key(self) -> str:
        return normalize_term(self.subject)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object_value": self.object_value,
            "fact_kind": self.fact_kind,
            "method": self.method,
            "confidence": round(self.confidence, 4),
            "temporal": self.temporal.to_dict(),
            "attributes": self.attributes,
            "evidence_count": len(self.evidence),
        }


class RelationshipKind(StrEnum):
    CONTAINS = "contains"
    PART_OF = "part_of"
    MODIFIES = "modifies"
    APPLIES_TO = "applies_to"
    REQUIRES = "requires"
    REFERENCES = "references"
    HAS_PATTERN = "has_pattern"
    HAS_NOTE = "has_note"
    HAS_EXAMPLE = "has_example"
    HAS_WARNING = "has_warning"
    DERIVED_FROM = "derived_from"
    RELATES_TO = "relates_to"


@dataclass(kw_only=True)
class RelationshipCandidate:
    """Arista tipada del grafo de conocimiento."""

    subject: str
    predicate: str
    object_name: str
    subject_type: str = EntityType.CONCEPT.value
    object_type: str = EntityType.CONCEPT.value
    relationship_type: str = "semantic"
    confidence: float = 0.7
    attributes: dict = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object_name,
            "relationship_type": self.relationship_type,
            "confidence": round(self.confidence, 4),
            "evidence_count": len(self.evidence),
        }


@dataclass(kw_only=True)
class RuleCandidate:
    """Regla o restricción de negocio detectable en una fuente."""

    subject: str
    statement: str
    rule_key: str
    rule_type: str = "business_rule"
    modality: str = "must"
    confidence: float = 0.7
    temporal: TemporalScope = field(default_factory=TemporalScope)
    evidence: list[EvidenceRef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "statement": self.statement[:600],
            "rule_key": self.rule_key,
            "rule_type": self.rule_type,
            "modality": self.modality,
            "confidence": round(self.confidence, 4),
            "temporal": self.temporal.to_dict(),
            "evidence_count": len(self.evidence),
        }


# -----------------------------------------------------------------------------
# Conflictos
# -----------------------------------------------------------------------------


class ConflictType(StrEnum):
    """Causa probable del conflicto. No se decide "quién está mal"."""

    VERSION_CHANGE = "VERSION_CHANGE"
    TEMPORAL_CHANGE = "TEMPORAL_CHANGE"
    SCOPE_DIFFERENCE = "SCOPE_DIFFERENCE"
    EXCEPTION = "EXCEPTION"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(kw_only=True)
class ConflictCandidate:
    """Dos afirmaciones incompatibles sobre el mismo sujeto y predicado."""

    subject: str
    predicate: str
    value_a: str
    value_b: str
    conflict_type: str
    confidence: float
    reason: str
    source_a: str | None = None
    source_b: str | None = None
    values_equivalent: bool = False
    evidence: list[EvidenceRef] = field(default_factory=list)
    evidence_ids: list[UUID] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "value_a": self.value_a[:300],
            "value_b": self.value_b[:300],
            "conflict_type": self.conflict_type,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "values_equivalent": self.values_equivalent,
        }


# -----------------------------------------------------------------------------
# Resultado de compilación
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class CompilationResult:
    """Todo lo que el compilador produjo a partir de una fuente."""

    organization_id: UUID
    source_id: UUID | None = None
    document_id: UUID | None = None
    document_title: str = ""
    compilation_kind: str = "document"
    units: list[SemanticUnit] = field(default_factory=list)
    entities: list[EntityCandidate] = field(default_factory=list)
    facts: list[FactCandidate] = field(default_factory=list)
    relationships: list[RelationshipCandidate] = field(default_factory=list)
    rules: list[RuleCandidate] = field(default_factory=list)
    conflicts: list[ConflictCandidate] = field(default_factory=list)
    merges: list[EntityMerge] = field(default_factory=list)
    evidence_count: int = 0
    persisted: dict = field(default_factory=dict)

    @property
    def objects_total(self) -> int:
        return len(self.entities) + len(self.facts) + len(self.rules)

    def to_dict(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "document_title": self.document_title,
            "compilation_kind": self.compilation_kind,
            "counts": {
                "units": len(self.units),
                "entities": len(self.entities),
                "entities_merged": len(self.merges),
                "facts": len(self.facts),
                "relationships": len(self.relationships),
                "rules": len(self.rules),
                "conflicts": len(self.conflicts),
                "evidence": self.evidence_count,
            },
            "persisted": self.persisted,
        }
