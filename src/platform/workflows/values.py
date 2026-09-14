# =============================================================================
# Workflow Values — tipado estándar de valores transportados entre nodos
# (Workflow Semantic Core, Fase 1-2).
#
# Envoltorio inmutable (WorkflowValue) + provenance para las contribuciones de
# contexto. No reemplaza los outputs crudos de los nodos: los adapta.
# Sin I/O, sin acceso a DB.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

# Tipos conceptuales del brief §4. "json" es el fallback interno.
VALUE_TYPES: tuple[str, ...] = (
    "string",
    "number",
    "boolean",
    "money",
    "percentage",
    "date",
    "datetime",
    "duration",
    "entity",
    "entity_list",
    "record",
    "record_list",
    "metric",
    "document",
    "document_list",
    "evidence",
    "evidence_list",
    "claim",
    "claim_list",
    "knowledge_answer",
    "agent_finding",
    "decision",
    "artifact",
    "error",
    "json",
)

# Tipos de puerto IR (y variantes de negocio) → tipo de valor de workflow.
RAW_TO_VALUE_TYPE: dict[str, str] = {
    "string": "string",
    "text": "string",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "money": "money",
    "percentage": "percentage",
    "duration": "duration",
    "entity": "entity",
    "entity_list": "entity_list",
    "record": "record",
    "record_list": "record_list",
    "metric": "metric",
    "document": "document",
    "document_list": "document_list",
    "evidence": "evidence",
    "evidence_list": "evidence_list",
    "claim": "claim",
    "claim_list": "claim_list",
    "knowledge_answer": "knowledge_answer",
    "agent_finding": "agent_finding",
    "decision": "decision",
    "artifact": "artifact",
    "error": "error",
    "json": "json",
}


def jsonable(raw: Any) -> Any:
    """Convierte un valor arbitrario a estructura serializable en JSON."""
    if raw is None or isinstance(raw, (str, int, float, bool)):
        return raw
    if isinstance(raw, (datetime, date, time)):
        return raw.isoformat()
    if isinstance(raw, UUID):
        return str(raw)
    if isinstance(raw, dict):
        return {str(k): jsonable(v) for k, v in raw.items()}
    if isinstance(raw, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in raw]
    return str(raw)


def infer_value_type(raw: Any) -> str:
    """Inferencia conservadora cuando el nodo no declara el tipo."""
    if isinstance(raw, bool):
        return "boolean"
    if isinstance(raw, (int, float)):
        return "number"
    if isinstance(raw, str):
        return "string"
    if isinstance(raw, dict):
        return "record"
    if isinstance(raw, (list, tuple)):
        return "record_list" if raw and all(isinstance(item, dict) for item in raw) else "json"
    return "json"


@dataclass(frozen=True, kw_only=True)
class Provenance:
    """Origen de un valor: permite decisiones auditables (brief §14)."""

    origin_kind: str = "node"  # node | trigger | knowledge | agent | datasource | system
    node_id: str | None = None
    node_type: str | None = None
    source_id: str | None = None
    document_id: UUID | None = None
    evidence_id: UUID | None = None
    page: int | None = None
    workspace_id: UUID | None = None
    timestamp: datetime | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(
            {
                "origin_kind": self.origin_kind,
                "node_id": self.node_id,
                "node_type": self.node_type,
                "source_id": self.source_id,
                "document_id": self.document_id,
                "evidence_id": self.evidence_id,
                "page": self.page,
                "workspace_id": self.workspace_id,
                "timestamp": self.timestamp,
                "confidence": self.confidence,
            }
        )


@dataclass(frozen=True, kw_only=True)
class WorkflowValue:
    """Valor tipado con etiqueta de negocio y provenance.

    El output crudo del nodo sigue siendo la verdad; este envoltorio describe
    qué significa el valor para el contexto compartido y el catálogo de datos.
    """

    value: Any = None
    value_type: str = "json"
    label: str | None = None
    unit: str | None = None
    provenance: Provenance | None = None
    redacted: bool = False

    def __post_init__(self) -> None:
        if self.value_type not in VALUE_TYPES:
            raise ValueError(f"value_type inválido: {self.value_type}")

    def json_value(self) -> Any:
        return jsonable(self.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.json_value(),
            "value_type": self.value_type,
            "label": self.label,
            "unit": self.unit,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "redacted": self.redacted,
        }

    @classmethod
    def from_raw(
        cls,
        raw: Any,
        *,
        value_type: str | None = None,
        label: str | None = None,
        unit: str | None = None,
        provenance: Provenance | None = None,
        redacted: bool = False,
    ) -> "WorkflowValue":
        return cls(
            value=raw,
            value_type=value_type or infer_value_type(raw),
            label=label,
            unit=unit,
            provenance=provenance,
            redacted=redacted,
        )


__all__ = [
    "Provenance",
    "RAW_TO_VALUE_TYPE",
    "VALUE_TYPES",
    "WorkflowValue",
    "infer_value_type",
    "jsonable",
]
