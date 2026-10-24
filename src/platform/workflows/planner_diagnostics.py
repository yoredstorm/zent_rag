# =============================================================================
# Planner diagnostics — código técnico a mensaje humano con CTA.
# =============================================================================
from __future__ import annotations

from typing import Any

_CATALOG: dict[str, dict[str, Any]] = {
    "planner.budget_insufficient": {
        "title": "El presupuesto no alcanza",
        "message": "No hay presupuesto suficiente para entender, planificar y verificar este proceso.",
        "action": "Sube el presupuesto, elige un modelo más económico o usa una plantilla.",
        "retryable": True,
    },
    "planner.invalid_llm_output": {
        "title": "El modelo no devolvió un plan válido",
        "message": "La respuesta no respetó el contrato del planificador. No se creó ningún workflow.",
        "action": "Reintenta o reformula el pedido; revisa el modelo configurado.",
        "retryable": True,
    },
    "planner.llm_unavailable": {
        "title": "El proveedor no está disponible",
        "message": "No se pudo contactar al modelo. No se inventó un plan alternativo.",
        "action": "Revisa la credencial/proveedor y vuelve a intentar.",
        "retryable": True,
    },
    "planner.tool_budget_exhausted": {
        "title": "Demasiadas búsquedas",
        "message": "El planner agotó el límite de consultas al catálogo antes de proponer un plan.",
        "action": "Usa una misión más concreta o una plantilla, o sube el límite de herramientas.",
        "retryable": True,
    },
    "planner.no_plan": {
        "title": "No se pudo cerrar un plan",
        "message": "No hay un plan válido dentro del presupuesto. No se publicó nada.",
        "action": "Reformula la misión con el resultado y los datos concretos.",
        "retryable": True,
    },
    "planner.capability_not_inspected": {
        "title": "Falta revisar una dependencia",
        "message": "El plan usa una capacidad que no fue inspeccionada antes de proponerla.",
        "action": "Revisa el catálogo y vuelve a generar el plan.",
        "retryable": True,
    },
    "planner.unexpected_error": {
        "title": "El planner falló",
        "message": "Ocurrió un error inesperado. No se creó un workflow falso.",
        "action": "Reintenta; si persiste, revisa los diagnósticos técnicos.",
        "retryable": True,
    },
}

_BUDGET_ACTIONS = {
    "tokens": "Sube el máximo de tokens o reduce el catálogo/misión.",
    "cost": "Sube el presupuesto en USD o elige un modelo más económico.",
    "llm_calls": "Sube el máximo de llamadas o usa una plantilla.",
    "tool_calls": "Sube el máximo de herramientas o concreta la misión.",
    "duration": "Sube el tiempo máximo o simplifica el proceso.",
}


def budget_diagnostic(reason: str | None) -> dict[str, Any]:
    key = str(reason or "budget")
    return {
        "code": f"planner.budget_exceeded.{key}",
        "title": "Se agotó el presupuesto",
        "message": f"El planner alcanzó el límite de {key} antes de terminar.",
        "action": _BUDGET_ACTIONS.get(key, "Ajusta el presupuesto y vuelve a intentar."),
        "retryable": True,
        "reason": key,
    }


def user_diagnostic(code: str, *, reason: str | None = None) -> dict[str, Any]:
    if str(code).startswith("planner.budget_exceeded"):
        return budget_diagnostic(reason or str(code).rsplit(".", 1)[-1])
    item = _CATALOG.get(str(code))
    if item is not None:
        return {"code": str(code), **item}
    return {
        "code": str(code),
        "title": "No se pudo completar el diseño",
        "message": "El planner no produjo un resultado publicable. No se creó nada.",
        "action": "Revisa el mensaje y vuelve a intentar; no se publicó nada.",
        "retryable": True,
    }


__all__ = ["budget_diagnostic", "user_diagnostic"]
