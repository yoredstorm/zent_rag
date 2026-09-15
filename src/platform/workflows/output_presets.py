# =============================================================================
# Output Presets — resultados estructurados canónicos para el nodo agent
# (Cognitive Workflows, Fase 4).
#
# El backend genera el JSON Schema; el portal solo muestra la opción. Los
# campos quedan en la raíz del output (para referencias `{{nodes.x.output.Y}}`)
# y el contexto recibe un `decision_result` tipado.
# =============================================================================
from __future__ import annotations

from typing import Any

OUTPUT_TYPES: tuple[str, ...] = (
    "text",
    "decision",
    "classification",
    "business_assessment",
    "json_schema",
)

OUTPUT_TYPE_LABELS: dict[str, str] = {
    "text": "Texto libre",
    "decision": "Decisión",
    "classification": "Clasificación",
    "business_assessment": "Evaluación de negocio",
    "json_schema": "JSON personalizado",
}

_TEXT_SCHEMA: dict[str, Any] = {}

_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "title": "Decisión"},
        "reason": {"type": "string", "title": "Motivo"},
        "confidence": {"type": "number", "title": "Confianza"},
        "requires_review": {"type": "boolean", "title": "Requiere revisión"},
    },
    "required": ["decision"],
}

_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "title": "Clasificación"},
        "confidence": {"type": "number", "title": "Confianza"},
        "reason": {"type": "string", "title": "Motivo"},
    },
    "required": ["label"],
}

_BUSINESS_ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "risk": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH"],
            "title": "Riesgo",
        },
        "reason": {"type": "string", "title": "Motivo"},
        "recommendation": {"type": "string", "title": "Recomendación"},
        "confidence": {"type": "number", "title": "Confianza"},
        "requires_review": {"type": "boolean", "title": "Requiere revisión"},
    },
    "required": ["risk"],
}

OUTPUT_PRESETS: dict[str, dict[str, Any]] = {
    "text": _TEXT_SCHEMA,
    "decision": _DECISION_SCHEMA,
    "classification": _CLASSIFICATION_SCHEMA,
    "business_assessment": _BUSINESS_ASSESSMENT_SCHEMA,
}


def resolve_output_schema(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Schema del nodo: `output_schema` explícito gana; si no, el preset."""
    cfg = config or {}
    declared = cfg.get("output_schema")
    if isinstance(declared, dict) and declared:
        return declared
    preset = str(cfg.get("output_type") or "").strip().lower()
    if preset and preset != "text":
        return OUTPUT_PRESETS.get(preset)
    return None


__all__ = [
    "OUTPUT_PRESETS",
    "OUTPUT_TYPE_LABELS",
    "OUTPUT_TYPES",
    "resolve_output_schema",
]
