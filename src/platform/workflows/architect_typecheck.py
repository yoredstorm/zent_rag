# =============================================================================
# Workflow Architect — referencias y tipos reales (Prompt 04, actividad F).
#
# No asume que cualquier JSON alimenta cualquier JSON. Resuelve el schema del
# paso de origen y del input del paso destino, incluyendo paths anidados y
# arrays; produce issues estructurados para reparación determinista.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.platform.workflows.architect_models import PlanStep

_INDEX_RE = re.compile(r"\[(\d+|\*)\]")
_JSON_TYPE_MAP: dict[str, str] = {
    "text": "string",
    "string": "string",
    "uuid": "string",
    "date": "string",
    "datetime": "string",
    "enum": "string",
    "number": "number",
    "money": "number",
    "integer": "integer",
    "boolean": "boolean",
    "json": "object",
    "record": "object",
    "document": "object",
    "evidence": "object",
    "record_list": "array",
    "binary": "string",
}


@dataclass(frozen=True)
class ContractIssue:
    code: str
    step_id: str | None
    field: str
    expected: str
    received: str
    message: str
    alternatives: tuple[str, ...] = ()
    action_required: str = ""


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    current: Any = root
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, dict) else None


def resolve_schema_path(
    schema: dict[str, Any] | None, path: str
) -> dict[str, Any] | None:
    """Resuelve `producto.id`, `items[0].sku` o `items[].sku` en JSON Schema."""
    if not isinstance(schema, dict) or not path:
        return None
    root = schema
    current: dict[str, Any] | None = schema
    cleaned = path.removeprefix("output.")
    for part in [p for p in cleaned.split(".") if p]:
        if current is None:
            return None
        current = _deref(root, current)
        if current is None:
            return None
        # Soporta arrays: nombre[0] / nombre[] / nombre[*].
        name = _INDEX_RE.sub("", part)
        if name:
            properties = current.get("properties") or {}
            current = properties.get(name) if isinstance(properties, dict) else None
            if current is None:
                return None
        if _INDEX_RE.search(part):
            current = current.get("items") if isinstance(current, dict) else None
    return _deref(root, current) if isinstance(current, dict) else None


def _deref(root: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(root, ref)
        return resolved
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        merged: dict[str, Any] = {}
        for item in all_of:
            resolved = _deref(root, item if isinstance(item, dict) else None)
            if resolved:
                merged.update(resolved)
        return merged or schema
    return schema


def schema_types(schema: dict[str, Any] | None) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    raw_type = schema.get("type")
    types: set[str] = set()
    if isinstance(raw_type, str):
        types.add(raw_type)
    elif isinstance(raw_type, list):
        types.update(str(item) for item in raw_type)
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list):
            for option in options:
                types |= schema_types(option if isinstance(option, dict) else None)
    if not types and any(k in schema for k in ("properties", "required", "additionalProperties")):
        types.add("object")
    if not types and "items" in schema:
        types.add("array")
    return {item for item in types if item}


def _normalize_type(value: str) -> str:
    return _JSON_TYPE_MAP.get(value, value)


def deref_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    return schema


def type_compatible(
    source: dict[str, Any] | None,
    target: dict[str, Any] | None,
) -> tuple[bool, str, str]:
    """Compatibilidad conservadora. Unknown no bloquea; mismatch sí."""
    source_types = {_normalize_type(item) for item in schema_types(source)}
    target_types = {_normalize_type(item) for item in schema_types(target)}
    if not source_types or not target_types:
        return True, ", ".join(sorted(source_types)) or "unknown", ", ".join(sorted(target_types)) or "unknown"
    if "object" in target_types and "object" in source_types:
        return True, "object", "object"
    if "array" in target_types and "array" in source_types:
        source_items = (source or {}).get("items")
        target_items = (target or {}).get("items")
        if isinstance(source_items, dict) and isinstance(target_items, dict):
            return type_compatible(source_items, target_items)
        return True, "array", "array"
    if source_types == {"integer"} and "number" in target_types:
        return True, "integer", "number"
    if source_types & target_types:
        source_format = str((source or {}).get("format") or "")
        target_format = str((target or {}).get("format") or "")
        if target_format == "uuid" and source_format and source_format != "uuid":
            return (
                False,
                f"{', '.join(sorted(source_types))} ({source_format})",
                f"{', '.join(sorted(target_types))} ({target_format})",
            )
        return True, ", ".join(sorted(source_types)), ", ".join(sorted(target_types))
    if "null" in source_types and source_types - {"null"}:
        source_types -= {"null"}
        if source_types & target_types:
            return True, ", ".join(sorted(source_types)), ", ".join(sorted(target_types))
    return (
        False,
        ", ".join(sorted(source_types)),
        ", ".join(sorted(target_types)),
    )


def literal_matches(schema: dict[str, Any] | None, value: Any) -> bool:
    if not isinstance(schema, dict) or not schema:
        return True
    types = schema_types(schema)
    if not types:
        return True
    if value is None:
        return "null" in types
    if isinstance(value, bool):
        return bool(types & {"boolean"})
    if isinstance(value, int):
        return bool(types & {"integer", "number"})
    if isinstance(value, float):
        return "number" in types
    if isinstance(value, str):
        return bool(types & {"string"})
    if isinstance(value, list):
        return "array" in types
    if isinstance(value, dict):
        return bool(types & {"object"})
    return True


def _capability_index(capabilities: dict[str, Any]) -> dict[str, Any]:
    raw = capabilities.get("capability_index") or {}
    return raw if isinstance(raw, dict) else {}


def _step_ref(step: PlanStep) -> str:
    if step.type == "capability_call":
        return str(step.params.get("capability") or "").strip()
    if step.type == "integration_action":
        return str(step.params.get("action_id") or "").strip()
    if step.type == "agent_analysis":
        agent_id = str(step.params.get("agent_id") or "").strip()
        return f"agent.{agent_id}" if agent_id else ""
    return ""


def descriptor_for(step: PlanStep, capabilities: dict[str, Any]) -> dict[str, Any] | None:
    ref = _step_ref(step)
    if not ref:
        return None
    descriptor = _capability_index(capabilities).get(ref)
    return descriptor if isinstance(descriptor, dict) else None


def step_output_schema(
    step: PlanStep, capabilities: dict[str, Any]
) -> dict[str, Any] | None:
    descriptor = descriptor_for(step, capabilities)
    if descriptor:
        schema = descriptor.get("output_schema")
        return schema if isinstance(schema, dict) else None
    if step.type == "wait":
        expected = step.params.get("expected_payload_schema")
        if isinstance(expected, dict):
            schema = dict(expected)
            properties = dict(schema.get("properties") or {})
            properties.setdefault("event_type", {"type": "string"})
            properties.setdefault("port", {"type": "string"})
            schema["properties"] = properties
            return schema
        return None
    mapping = {
        "business_query": "query_business_data",
        "knowledge_query": "kb_query",
        "decision": "condition",
        "filter": "filter",
        "notify": "notify",
        "business_result": "business_result",
        "human_approval": "human_approval",
    }
    node_type = mapping.get(step.type)
    if not node_type:
        return None
    try:
        from src.platform.workflows.parameters import node_business_schema

        schema = node_business_schema(node_type)
    except Exception:  # noqa: BLE001
        return None
    if schema is None:
        return None
    properties: dict[str, Any] = {}
    for output in schema.outputs:
        properties[str(output.key)] = {
            "type": _normalize_type(str(output.type)),
        }
    return {"type": "object", "properties": properties} if properties else None


def step_input_schema(
    step: PlanStep, field: str, capabilities: dict[str, Any]
) -> dict[str, Any] | None:
    descriptor = descriptor_for(step, capabilities)
    if not descriptor:
        return None
    schema = descriptor.get("input_schema")
    if not isinstance(schema, dict):
        return None
    return resolve_schema_path(schema, field)


def contract_issues(
    step: PlanStep,
    capabilities: dict[str, Any],
    sources: dict[str, PlanStep] | None = None,
) -> list[ContractIssue]:
    """Valida inputs declarativos, salidas esperadas y tipos entre pasos."""
    issues: list[ContractIssue] = []
    descriptor = descriptor_for(step, capabilities)
    ref = _step_ref(step)

    if descriptor is not None:
        version = descriptor.get("version")
        declared = step.contract_version
        if declared is not None and version is not None and int(declared) != int(version):
            issues.append(
                ContractIssue(
                    code="contract.version_mismatch",
                    step_id=step.id,
                    field="contract_version",
                    expected=str(version),
                    received=str(declared),
                    message=(
                        f"«{step.goal}» declara v{declared} de {ref}, pero el catálogo "
                        f"tiene v{version}."
                    ),
                    action_required="Actualiza el contrato o vuelve a descubrir la capacidad.",
                )
            )
        if step.outputs_expected:
            output_schema = descriptor.get("output_schema") or {}
            properties = output_schema.get("properties") if isinstance(output_schema, dict) else {}
            properties = properties if isinstance(properties, dict) else {}
            missing = [item for item in step.outputs_expected if item not in properties]
            if missing and properties:
                issues.append(
                    ContractIssue(
                        code="contract.outputs_missing",
                        step_id=step.id,
                        field="outputs_expected",
                        expected=", ".join(sorted(str(key) for key in properties)[:12]),
                        received=", ".join(missing[:8]),
                        message=(
                            f"«{step.goal}» espera salidas que el contrato no declara: "
                            + ", ".join(missing[:5])
                        ),
                        alternatives=tuple(sorted(str(key) for key in properties)[:8]),
                        action_required="Usa campos reales del output_schema inspeccionado.",
                    )
                )
        if step.idempotency == "none" and (
            "financial" in (descriptor.get("side_effects") or [])
            or descriptor.get("risk_level") == "critical"
        ):
            issues.append(
                ContractIssue(
                    code="contract.idempotency_required",
                    step_id=step.id,
                    field="idempotency",
                    expected="required",
                    received="none",
                    message=(
                        f"«{step.goal}» es una acción financiera/crítica sin idempotencia "
                        "declarada."
                    ),
                    action_required="Declara idempotency=required; el runtime usa instance+node.",
                )
            )

    # Inputs literales contra el schema del destino.
    raw_inputs = step.params.get("inputs")
    if descriptor is not None and isinstance(raw_inputs, dict):
        input_schema = descriptor.get("input_schema") or {}
        properties = input_schema.get("properties") if isinstance(input_schema, dict) else {}
        properties = properties if isinstance(properties, dict) else {}
        for key, value in list(raw_inputs.items())[:40]:
            target_schema = properties.get(str(key))
            if properties and target_schema is None:
                issues.append(
                    ContractIssue(
                        code="contract.input_unknown",
                        step_id=step.id,
                        field=f"params.inputs.{key}",
                        expected=", ".join(sorted(str(item) for item in properties)[:12]),
                        received=str(key),
                        message=f"«{step.goal}» envía el input desconocido «{key}».",
                        alternatives=tuple(sorted(str(item) for item in properties)[:8]),
                        action_required="Usa un campo del input_schema inspeccionado.",
                    )
                )
                continue
            if isinstance(target_schema, dict) and not literal_matches(target_schema, value):
                issues.append(
                    ContractIssue(
                        code="contract.literal_type",
                        step_id=step.id,
                        field=f"params.inputs.{key}",
                        expected=", ".join(sorted(schema_types(target_schema))) or "json",
                        received=type(value).__name__,
                        message=(
                            f"«{step.goal}» envía «{key}» con un tipo incompatible."
                        ),
                        action_required="Convierte el literal al tipo del contrato.",
                    )
                )

    for input_ref in step.inputs:
        target_schema = step_input_schema(
            step, str(input_ref.to or input_ref.field), capabilities
        )
        if descriptor is not None and target_schema is None:
            input_schema = descriptor.get("input_schema") or {}
            properties = input_schema.get("properties") if isinstance(input_schema, dict) else {}
            if isinstance(properties, dict) and properties:
                field_name = str(input_ref.to or input_ref.field)
                issues.append(
                    ContractIssue(
                        code="contract.input_unknown",
                        step_id=step.id,
                        field="inputs.to",
                        expected=", ".join(sorted(str(item) for item in properties)[:12]),
                        received=field_name,
                        message=(
                            f"«{step.goal}» intenta llenar «{field_name}», que no existe "
                            "en el contrato de entrada."
                        ),
                        alternatives=tuple(sorted(str(item) for item in properties)[:8]),
                        action_required="Elige un campo de entrada permitido.",
                    )
                )
        source = (sources or {}).get(input_ref.step)
        if source is None:
            continue
        output_schema = step_output_schema(source, capabilities)
        source_field = input_ref.field
        source_schema = (
            output_schema
            if source_field == "output" and output_schema
            else (
                resolve_schema_path(output_schema, source_field)
                if output_schema
                else None
            )
        )
        if output_schema is not None and source_schema is None:
            properties = output_schema.get("properties") if isinstance(output_schema, dict) else {}
            properties = properties if isinstance(properties, dict) else {}
            issues.append(
                ContractIssue(
                    code="contract.output_unknown",
                    step_id=step.id,
                    field="inputs.field",
                    expected=", ".join(sorted(str(item) for item in properties)[:12])
                    or "campo existente",
                    received=source_field,
                    message=(
                        f"«{step.goal}» usa «{source_field}» de «{source.goal}», "
                        "pero ese campo no existe en su salida."
                    ),
                    alternatives=tuple(sorted(str(item) for item in properties)[:8]),
                    action_required="Elige un campo de salida del contrato.",
                )
            )
        elif source_schema is not None and target_schema is not None:
            compatible, source_type, target_type = type_compatible(
                source_schema, target_schema
            )
            if not compatible:
                issues.append(
                    ContractIssue(
                        code="contract.type_mismatch",
                        step_id=step.id,
                        field="inputs.field",
                        expected=target_type,
                        received=source_type,
                        message=(
                            f"«{step.goal}» conecta {source_field} ({source_type}) "
                            f"a un input que espera {target_type}."
                        ),
                        action_required=(
                            "Usa un campo del tipo correcto o transforma el dato en un "
                            "paso intermedio."
                        ),
                    )
                )
    return issues


__all__ = [
    "ContractIssue",
    "contract_issues",
    "descriptor_for",
    "literal_matches",
    "resolve_schema_path",
    "schema_types",
    "step_input_schema",
    "step_output_schema",
    "type_compatible",
]
