# =============================================================================
# Semantic Reconstruction Layer — contratos canónicos (IR)
# =============================================================================
# Tipos puros, sin I/O. Una fuente heterogénea (PDF, DOCX, TXT, Markdown, HTML,
# Excel, CSV, JSON, XML, base de datos, API, eventos, ...) converge aquí al
# mismo modelo semántico. `SEMANTIC RECONSTRUCTION` no es un parche de PDF: es
# una capa universal.
#
# Leyes:
#   - No inventar: reconstruir solo con evidencia estructural/contextual.
#   - La procedencia es inmutable y viaja con cada elemento.
#   - Nunca un número mágico: la confianza se registra por dimensiones.
#   - Un fragmento sospechoso no se convierte en conocimiento canónico.
# =============================================================================
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

SCHEMA_VERSION = "1.0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_term(value: str) -> str:
    """Normaliza un término para comparación (no crea equivalencias)."""
    text = (value or "").strip().strip(".,;:()[]\"'`«»").strip()
    return " ".join(text.lower().split())


class SourceKind(StrEnum):
    """Formato/fuente física de la que se extrajo la representación."""

    PDF = "pdf"
    DOCX = "docx"
    TEXT = "text"
    MARKDOWN = "markdown"
    HTML = "html"
    SPREADSHEET = "spreadsheet"
    CSV = "csv"
    JSON = "json"
    XML = "xml"
    DATABASE = "database"
    API = "api"
    EVENT = "event"
    EMAIL = "email"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


class ReconstructionStatus(StrEnum):
    """Veredicto de la Semantic Quality Gate sobre una unidad/elemento."""

    VALID = "VALID"
    RECONSTRUCTED = "RECONSTRUCTED"
    AMBIGUOUS = "AMBIGUOUS"
    INCOMPLETE = "INCOMPLETE"
    LOW_QUALITY = "LOW_QUALITY"
    STRUCTURAL_ARTIFACT = "STRUCTURAL_ARTIFACT"
    DUPLICATE = "DUPLICATE"
    REQUIRES_REPAIR = "REQUIRES_REPAIR"
    REJECTED = "REJECTED"


#: Estados que pueden convertirse en conocimiento normalmente.
KNOWLEDGE_STATUSES: frozenset[str] = frozenset(
    {ReconstructionStatus.VALID.value, ReconstructionStatus.RECONSTRUCTED.value}
)

#: Estados que nunca deben alimentar al Knowledge Compiler como conocimiento.
NON_KNOWLEDGE_STATUSES: frozenset[str] = frozenset(
    {
        ReconstructionStatus.AMBIGUOUS.value,
        ReconstructionStatus.INCOMPLETE.value,
        ReconstructionStatus.LOW_QUALITY.value,
        ReconstructionStatus.STRUCTURAL_ARTIFACT.value,
        ReconstructionStatus.DUPLICATE.value,
        ReconstructionStatus.REQUIRES_REPAIR.value,
        ReconstructionStatus.REJECTED.value,
    }
)


class ElementKind(StrEnum):
    """Tipo estructural de un elemento crudo, independiente del formato."""

    DOCUMENT = "document"
    WORKBOOK = "workbook"
    SHEET = "sheet"
    SECTION = "section"
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_ROW = "table_row"
    RECORD = "record"
    FIELD = "field"
    COLUMN = "column"
    FORMULA = "formula"
    CODE = "code"
    QUOTE = "quote"
    CAPTION = "caption"
    FIGURE = "figure"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    REFERENCE = "reference"
    METADATA = "metadata"
    OBJECT = "object"
    ARRAY = "array"
    PROPERTY = "property"
    SCHEMA = "schema"
    ENDPOINT = "endpoint"
    PARAMETER = "parameter"
    RESPONSE = "response"
    EVENT = "event"
    MESSAGE = "message"
    NOTE = "note"
    WARNING = "warning"
    EXAMPLE = "example"
    PROCEDURE = "procedure"
    DEFINITION = "definition"
    UNKNOWN = "unknown"


class ContinuityKind(StrEnum):
    """Por qué dos elementos separados pertenecen a la misma unidad lógica."""

    NONE = "NONE"
    LINE_WRAP = "LINE_WRAP"
    DEHYPHENATION = "DEHYPHENATION"
    WORD_FRAGMENT = "WORD_FRAGMENT"
    SENTENCE = "SENTENCE"
    PAGE_CONTINUATION = "PAGE_CONTINUATION"
    TABLE_CONTINUATION = "TABLE_CONTINUATION"
    REPEATED_HEADER = "REPEATED_HEADER"
    LIST_CONTINUATION = "LIST_CONTINUATION"
    JSON_SPLIT = "JSON_SPLIT"
    XML_SPLIT = "XML_SPLIT"


class FragmentKind(StrEnum):
    """Razones específicas del Fragment Detector."""

    MID_WORD_START = "MID_WORD_START"
    MID_WORD_END = "MID_WORD_END"
    ABRUPT_SENTENCE = "ABRUPT_SENTENCE"
    TINY_ISOLATED_TEXT = "TINY_ISOLATED_TEXT"
    REPEATED_FRAGMENT = "REPEATED_FRAGMENT"
    OVERLAPPING_CHUNK = "OVERLAPPING_CHUNK"
    TABLE_FRAGMENT = "TABLE_FRAGMENT"
    HEADER_FOOTER_ARTIFACT = "HEADER_FOOTER_ARTIFACT"
    PARTIAL_ENTITY = "PARTIAL_ENTITY"
    CONTINUATION_FRAGMENT = "CONTINUATION_FRAGMENT"
    TRUNCATED_WORD = "TRUNCATED_WORD"
    LAYOUT_ARTIFACT = "LAYOUT_ARTIFACT"


@dataclass(frozen=True, kw_only=True)
class ConfidenceSignals:
    """Confianza multidimensional: nunca un único número mágico.

    `reconstruction_confidence` es la composición ponderada de las dimensiones
    medidas; las dimensiones quedan registradas para que el Knowledge Compiler
    decida con señales, no con un escalar opaco.
    """

    structure_confidence: float = 0.0
    continuity_confidence: float = 0.0
    semantic_completeness: float = 0.0
    schema_confidence: float = 0.0
    source_quality: float = 0.0
    reconstruction_confidence: float = 0.0

    _WEIGHTS: tuple[tuple[str, float], ...] = (
        ("structure_confidence", 0.25),
        ("continuity_confidence", 0.20),
        ("semantic_completeness", 0.25),
        ("schema_confidence", 0.10),
        ("source_quality", 0.20),
    )

    def __post_init__(self) -> None:
        for name in (
            "structure_confidence",
            "continuity_confidence",
            "semantic_completeness",
            "schema_confidence",
            "source_quality",
            "reconstruction_confidence",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"ConfidenceSignals.{name} must be within [0, 1]")

    @classmethod
    def compute(
        cls,
        *,
        structure_confidence: float,
        continuity_confidence: float = 0.0,
        semantic_completeness: float = 0.0,
        schema_confidence: float = 0.0,
        source_quality: float = 0.0,
    ) -> ConfidenceSignals:
        """Compone la confianza sobre las dimensiones realmente medidas > 0."""
        provided = {
            "structure_confidence": structure_confidence,
            "continuity_confidence": continuity_confidence,
            "semantic_completeness": semantic_completeness,
            "schema_confidence": schema_confidence,
            "source_quality": source_quality,
        }
        weighted = 0.0
        weight_total = 0.0
        for name, weight in cls._WEIGHTS:
            value = float(provided.get(name) or 0.0)
            if value <= 0.0:
                continue
            weighted += weight * math.log(max(value, 1e-6))
            weight_total += weight
        composite = math.exp(weighted / weight_total) if weight_total else 0.0
        return cls(
            structure_confidence=structure_confidence,
            continuity_confidence=continuity_confidence,
            semantic_completeness=semantic_completeness,
            schema_confidence=schema_confidence,
            source_quality=source_quality,
            reconstruction_confidence=round(min(1.0, max(0.0, composite)), 4),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "structure_confidence": round(self.structure_confidence, 4),
            "continuity_confidence": round(self.continuity_confidence, 4),
            "semantic_completeness": round(self.semantic_completeness, 4),
            "schema_confidence": round(self.schema_confidence, 4),
            "source_quality": round(self.source_quality, 4),
            "reconstruction_confidence": round(self.reconstruction_confidence, 4),
        }


@dataclass(frozen=True, kw_only=True)
class SourceProvenance:
    """Conexión inmutable con la fuente original.

    PDF: página + región (bbox) + texto crudo. Spreadsheet: hoja/fila/columna/
    celda. Database: schema/tabla/fila/clave/columna. JSON: ruta. XML: XPath.
    API: endpoint + ruta de request/response. Nunca se pierde al reconstruir.
    """

    source_kind: str = SourceKind.UNKNOWN.value
    adapter: str = ""
    source_id: UUID | None = None
    document_id: UUID | None = None
    document_title: str = ""
    block_id: UUID | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1
    section_path: tuple[str, ...] = ()
    char_start: int | None = None
    char_end: int | None = None
    sheet: str | None = None
    table: str | None = None
    row: int | None = None
    column: str | None = None
    cell: str | None = None
    json_path: str | None = None
    xpath: str | None = None
    database: str | None = None
    schema: str | None = None
    endpoint: str | None = None
    method: str | None = None
    response_path: str | None = None
    content_hash: str | None = None
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source_kind": self.source_kind,
            "adapter": self.adapter,
            "source_id": str(self.source_id) if self.source_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "document_title": self.document_title,
            "block_id": str(self.block_id) if self.block_id else None,
            "page": self.page,
            "bbox": list(self.bbox) if self.bbox else None,
            "section_path": list(self.section_path),
            "sheet": self.sheet,
            "table": self.table,
            "row": self.row,
            "column": self.column,
            "cell": self.cell,
            "json_path": self.json_path,
            "xpath": self.xpath,
            "database": self.database,
            "schema": self.schema,
            "endpoint": self.endpoint,
            "method": self.method,
            "response_path": self.response_path,
            "content_hash": self.content_hash,
            "excerpt": self.excerpt[:400],
        }
        return {key: value for key, value in data.items() if value not in (None, "", [], ())}

    def locator(self) -> str:
        """URI estable y legible de procedencia para auditoría."""
        parts: list[str] = []
        if self.document_id is not None:
            parts.append(f"document/{self.document_id}")
        if self.page is not None:
            parts.append(f"page/{self.page}")
        if self.block_id is not None:
            parts.append(f"block/{self.block_id}")
        if self.sheet:
            parts.append(f"sheet/{self.sheet}")
        if self.table:
            parts.append(f"table/{self.table}")
        if self.row is not None:
            parts.append(f"row/{self.row}")
        if self.column:
            parts.append(f"column/{self.column}")
        if self.cell:
            parts.append(f"cell/{self.cell}")
        if self.json_path:
            parts.append(f"json/{self.json_path}")
        if self.xpath:
            parts.append(f"xml/{self.xpath}")
        if self.schema:
            parts.append(f"schema/{self.schema}")
        if self.endpoint:
            parts.append(f"api/{self.method or 'GET'}:{self.endpoint}")
        return "//".join(parts) if parts else "source/unknown"


def element_uuid(document_id: UUID | None, index: int, text: str) -> UUID:
    """Identidad determinista de un elemento crudo (reingesta idempotente)."""
    import hashlib

    digest = hashlib.sha256(f"{document_id}|{index}|{text[:200]}".encode("utf-8")).hexdigest()
    return UUID(bytes=bytes.fromhex(digest[:32]))


@dataclass(frozen=True, kw_only=True)
class RawElement:
    """Elemento crudo extraído por un Source Adapter, aún sin reconstruir."""

    id: UUID
    kind: str
    text: str
    order: int
    provenance: SourceProvenance
    depth: int = 0
    parent_id: UUID | None = None
    heading_path: tuple[str, ...] = ()
    confidence: float = 0.8
    attributes: dict[str, Any] = field(default_factory=dict)
    children: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if self.order < 0:
            raise ValueError(f"RawElement.order must be >= 0, got {self.order}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("RawElement.confidence must be within [0, 1]")

    @property
    def is_chrome(self) -> bool:
        return self.kind in {
            ElementKind.HEADER.value,
            ElementKind.FOOTER.value,
            ElementKind.PAGE_NUMBER.value,
        }


@dataclass(frozen=True, kw_only=True)
class RawTable:
    """Tabla extraída sin aplanar: headers + filas + rango físico."""

    id: str
    name: str
    provenance: SourceProvenance
    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    header_depth: int = 1
    merged_cells: tuple[dict[str, Any], ...] = ()
    formulas: tuple[dict[str, Any], ...] = ()
    title: str = ""
    confidence: float = 0.8
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawExtraction:
    """Salida de un Source Adapter: estructura física común a todo formato."""

    source_kind: str
    adapter: str
    title: str = ""
    elements: list[RawElement] = field(default_factory=list)
    tables: list[RawTable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class Continuation:
    """Dos elementos separados que forman una misma unidad lógica."""

    id: str
    kind: str
    left_id: UUID
    right_id: UUID
    merged_text: str
    confidence: float
    reason: str
    method: str = "deterministic"
    ambiguity: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "left_id": str(self.left_id),
            "right_id": str(self.right_id),
            "merged_text": self.merged_text[:400],
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "method": self.method,
            "ambiguity": self.ambiguity,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, kw_only=True)
class SemanticUnitIR:
    """Unidad semántica reconstruida, independiente del formato original."""

    id: UUID
    key: str
    kind: str
    label: str
    text: str
    status: str
    provenance: SourceProvenance
    confidence: ConfidenceSignals
    method: str = "deterministic"
    source_element_ids: tuple[UUID, ...] = ()
    continuation_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def compact(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "key": self.key,
            "kind": self.kind,
            "label": self.label[:200],
            "text": self.text[:600],
            "status": self.status,
            "method": self.method,
            "confidence": self.confidence.to_dict(),
            "provenance": self.provenance.to_dict(),
            "source_element_ids": [str(value) for value in self.source_element_ids],
            "continuation_id": self.continuation_id,
            "attributes": {
                key: value
                for key, value in self.attributes.items()
                if key not in {"raw_text"}
            },
        }


@dataclass(frozen=True, kw_only=True)
class StructuralNode:
    """Nodo del árbol estructural (sección, objeto, array, hoja...)."""

    id: UUID
    kind: str
    text: str = ""
    order: int = 0
    depth: int = 0
    parent_id: UUID | None = None
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
    confidence: float = 0.8
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SemanticRecord:
    """Registro de una tabla/hoja: valores por columna, nunca filas a texto."""

    id: str
    table_id: str
    values: dict[str, str]
    physical_row: int | None = None
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SemanticField:
    """Columna/campo con tipo físico y semántico."""

    id: str
    name: str
    normalized_name: str = ""
    inferred_type: str = "unknown"
    semantic_type: str = "unknown"
    description: str = ""
    nullable: bool = True
    position: int | None = None
    header_path: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    sample_values: tuple[str, ...] = ()
    status: str = ReconstructionStatus.VALID.value
    confidence: ConfidenceSignals = field(default_factory=ConfidenceSignals)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SemanticTable:
    """Tabla reconstruida conservando headers, filas, merged cells y formulas."""

    id: str
    name: str
    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    records: tuple[SemanticRecord, ...] = ()
    fields: tuple[SemanticField, ...] = ()
    header_depth: int = 1
    merged_cells: tuple[dict[str, Any], ...] = ()
    formulas: tuple[dict[str, Any], ...] = ()
    status: str = ReconstructionStatus.VALID.value
    confidence: ConfidenceSignals = field(default_factory=ConfidenceSignals)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
    metadata: dict[str, Any] = field(default_factory=dict)

    def compact(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "headers": list(self.headers[:60]),
            "rows": [list(row[:60]) for row in self.rows[:50]],
            "row_count": len(self.rows),
            "column_count": len(self.headers),
            "header_depth": self.header_depth,
            "merged_cells": list(self.merged_cells[:50]),
            "formulas": list(self.formulas[:50]),
            "status": self.status,
            "confidence": self.confidence.to_dict(),
            "provenance": self.provenance.to_dict(),
            "fields": [
                {
                    "id": field.id,
                    "name": field.name,
                    "inferred_type": field.inferred_type,
                    "semantic_type": field.semantic_type,
                    "nullable": field.nullable,
                    "position": field.position,
                    "header_path": list(field.header_path[:8]),
                    "status": field.status,
                }
                for field in self.fields[:120]
            ],
            "metadata": self.metadata,
        }


@dataclass
class SemanticRepresentation:
    """Semantic Intermediate Representation (IR) de una fuente.

    Independiente del formato. Conceptualmente contiene Source, StructuralNode,
    SemanticBlock/Unit, Section, Table, Record, Field, Continuation, Reference,
    Hierarchy, Context y Provenance sin una tabla SQL por concepto.
    """

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    source_kind: str = SourceKind.UNKNOWN.value
    adapter: str = ""
    title: str = ""
    status: str = ReconstructionStatus.VALID.value
    nodes: list[StructuralNode] = field(default_factory=list)
    units: list[SemanticUnitIR] = field(default_factory=list)
    tables: list[SemanticTable] = field(default_factory=list)
    continuations: list[Continuation] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    @property
    def knowledge_units(self) -> list[SemanticUnitIR]:
        return [unit for unit in self.units if unit.status in KNOWLEDGE_STATUSES]

    def status_distribution(self) -> dict[str, int]:
        distribution: dict[str, int] = {}
        for unit in self.units:
            distribution[unit.status] = distribution.get(unit.status, 0) + 1
        return distribution
