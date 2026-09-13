# =============================================================================
# Condition Tree — reglas de negocio AND/OR anidadas para nodos `condition` y
# `filter`. El runtime ya tiene un evaluador plano; este módulo agrega el árbol
# sin duplicar el motor de ejecución.
#
# Formato canónico (lo que la UI Simple edita y el Graph guarda en config.rules):
#   {"kind": "condition", "field": "trigger.stock", "operator": "<",
#    "value": 10, "label": "Stock disponible"}
#   {"kind": "group", "op": "and", "children": [ ... ]}
#
# Compatibilidad: un config con field/operator/value (legacy) se normaliza a un
# árbol de una sola condición.
# =============================================================================
from __future__ import annotations

from typing import Any, Callable

from src.platform.workflows.business_schema import BusinessOutputField

EvalOperator = Callable[[Any, str, Any], bool]
ResolveField = Callable[[str], Any]

_CONDITION_LABELS = {
    "==": "es",
    "!=": "no es",
    ">": "es mayor que",
    ">=": "es al menos",
    "<": "es menor que",
    "<=": "es como máximo",
    "contains": "contiene",
    "not_contains": "no contiene",
    "starts_with": "empieza con",
    "ends_with": "termina con",
    "is_empty": "está vacío",
    "not_empty": "no está vacío",
    "changed": "cambió",
}

VALUELESS_OPERATORS = frozenset({"is_empty", "not_empty"})


def is_condition_tree(rules: Any) -> bool:
    return isinstance(rules, dict) and rules.get("kind") in ("condition", "group")


def normalize_rules(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Devuelve el árbol de reglas de un config, migrando el formato legacy."""
    data = config if isinstance(config, dict) else {}
    if is_condition_tree(data.get("rules")):
        return dict(data["rules"])
    if data.get("field"):
        return {
            "kind": "condition",
            "field": str(data.get("field")),
            "operator": str(data.get("operator") or "=="),
            "value": data.get("value"),
        }
    return None


def evaluate_condition_tree(rules: dict[str, Any], resolve: ResolveField, eval_op: EvalOperator) -> bool:
    """Evalúa un árbol AND/OR. `resolve` obtiene el valor actual del campo y
    `eval_op` es el evaluador plano del motor (`engine._eval_condition`)."""
    if not isinstance(rules, dict):
        return False
    kind = rules.get("kind")
    if kind == "group":
        children = rules.get("children") or []
        outcomes = [evaluate_condition_tree(child, resolve, eval_op) for child in children if isinstance(child, dict)]
        if str(rules.get("op") or "and").lower() == "or":
            return any(outcomes)
        return all(outcomes)
    if kind != "condition":
        return False
    field = str(rules.get("field") or "")
    operator = str(rules.get("operator") or "==")
    value = rules.get("value")
    actual = resolve(field)
    return bool(eval_op(actual, operator, value))


def describe_condition_tree(rules: dict[str, Any]) -> str:
    """Texto humano para el resumen del workflow y los runs."""
    if not isinstance(rules, dict):
        return ""
    kind = rules.get("kind")
    if kind == "group":
        children = [c for c in (rules.get("children") or []) if isinstance(c, dict)]
        separator = " o " if str(rules.get("op") or "and").lower() == "or" else " y "
        parts: list[str] = []
        for child in children:
            text = describe_condition_tree(child)
            if not text:
                continue
            if child.get("kind") == "group":
                text = f"({text})"
            parts.append(text)
        return separator.join(parts)
    if kind != "condition":
        return ""
    field = str(rules.get("label") or rules.get("field") or "")
    operator = str(rules.get("operator") or "==")
    label = _CONDITION_LABELS.get(operator, operator)
    if operator in VALUELESS_OPERATORS:
        return f"{field} {label}"
    value = rules.get("value")
    if value is None:
        return f"{field} {label}"
    return f"{field} {label} {value}"


def condition_rules(field: str, operator: str, value: Any = None, label: str | None = None) -> dict[str, Any]:
    rule: dict[str, Any] = {"kind": "condition", "field": field, "operator": operator}
    if label:
        rule["label"] = label
    if value is not None:
        rule["value"] = value
    return rule


def group_rules(op: str = "and", children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"kind": "group", "op": "or" if str(op).lower() == "or" else "and", "children": list(children or [])}


def plan_node_to_rules(node: Any, resolve_ref: Callable[[Any], str] | None = None) -> dict[str, Any]:
    """Convierte un PlanCondition/ConditionGroup (intent.py) al formato del
    runtime. `resolve_ref` traduce el PlanFieldRef a la referencia técnica
    ({{nodes...}}, trigger.path, ...); por defecto usa `field.ref` o el nombre."""
    from src.platform.workflows.intent import VALUELESS_OPERATORS as _PLAN_VALUELESS
    from src.platform.workflows.intent import ConditionGroup, PlanCondition

    def _field_ref(field: Any) -> tuple[str, str | None, str | None]:
        ref = resolve_ref(field) if resolve_ref else (field.ref or "")
        label = field.label
        if not ref:
            ref = field.field
        return str(ref), str(field.field), label

    if isinstance(node, ConditionGroup):
        children = [plan_node_to_rules(child, resolve_ref) for child in node.children]
        return group_rules(node.op, children)
    if isinstance(node, PlanCondition):
        ref, _key, label = _field_ref(node.field)
        value = None if node.operator.value in _PLAN_VALUELESS else node.value
        return condition_rules(ref, _engine_operator(node.operator), value, label)
    return {}


def _engine_operator(operator: Any) -> str:
    from src.platform.workflows.intent import CANONICAL_TO_ENGINE, normalize_operator

    canonical = normalize_operator(operator)
    return CANONICAL_TO_ENGINE[canonical.value]


def output_field_keys(outputs: list[BusinessOutputField]) -> list[str]:
    """Atajo para el Data Picker: claves de salida declaradas."""
    return [field.key for field in outputs]


__all__ = [
    "VALUELESS_OPERATORS",
    "condition_rules",
    "describe_condition_tree",
    "evaluate_condition_tree",
    "group_rules",
    "is_condition_tree",
    "normalize_rules",
    "output_field_keys",
    "plan_node_to_rules",
]
