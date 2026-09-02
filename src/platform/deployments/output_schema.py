# =============================================================================
# Output Schema — validación de respuestas estructuradas (ERP/CRM/WMS)
# =============================================================================
# Mini-validador de JSON Schema (subset suficiente para outputs de agentes):
#   type: string | integer | number | boolean | object | array | null
#   required: [..]  properties: {..}  items: {..}
# =============================================================================
from __future__ import annotations

from typing import Any

_JSON_TYPES = {"string", "integer", "number", "boolean", "object", "array", "null"}


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "null":
        return value is None
    return True


def validate_against_schema(
    data: Any, schema: dict, path: str = "$"
) -> list[str]:
    """Valida `data` contra un JSON Schema (subset). Devuelve lista de errores."""
    if not isinstance(schema, dict):
        return []

    errors: list[str] = []
    type_names = schema.get("type")
    types = [type_names] if isinstance(type_names, str) else (
        list(type_names) if isinstance(type_names, list) else []
    )
    if types:
        ok = any(_matches_type(data, t) for t in types if t in _JSON_TYPES)
        if not ok:
            errors.append(f"{path}: se esperaba tipo {types}, se obtuvo {type(data).__name__}")
            return errors

    if "object" in types or (not types and isinstance(data, dict)):
        for required in schema.get("required") or []:
            if required not in data:
                errors.append(f"{path}: falta la propiedad requerida '{required}'")
        for prop_name, prop_schema in (schema.get("properties") or {}).items():
            if prop_name in data:
                errors.extend(
                    validate_against_schema(
                        data[prop_name], prop_schema, f"{path}.{prop_name}"
                    )
                )
    elif "array" in types and isinstance(data, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(data):
                errors.extend(
                    validate_against_schema(item, items_schema, f"{path}[{i}]")
                )
    return errors


def validate_json_answer(
    answer: str, schema: dict
) -> tuple[dict | list | None, list[str]]:
    """Parsea la respuesta del agente y la valida contra el schema.

    Devuelve (data, errores): data = objeto/array parseado si el JSON es válido.
    """
    import json

    try:
        data = json.loads(answer)
    except json.JSONDecodeError:
        return None, ["La respuesta no es JSON válido"]
    errors = validate_against_schema(data, schema)
    return data, errors
