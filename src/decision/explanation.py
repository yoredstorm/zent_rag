# =============================================================================
# Decision explanation — explicación operacional, nunca chain-of-thought.
# =============================================================================
# Modo usuario: ruta + motivo + confianza + fuentes + fallback.
# Modo admin: agrega preguntas evaluadas, choice, fase, modelo, latencia,
# costo y resultado de la política. Sólo etiquetas y valores; nada de
# razonamiento interno del modelo.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.core.domain.decision import RoutingDecision

_ROUTE_LABELS = {
    "knowledge.search": "base de conocimiento",
    "knowledge.retrieve": "base de conocimiento",
    "knowledge.answer": "base de conocimiento",
    "document.read": "documento",
    "database.query": "base de datos",
    "database.schema": "esquema de datos",
    "agent.execute": "agente",
    "agent.reason": "agente",
    "agent.delegate": "agente",
    "workflow.start": "workflow",
    "workflow.execute": "workflow",
    "workflow.resume": "workflow",
    "tool.call_api": "herramienta de API",
    "tool.send_email": "herramienta de email",
    "tool.execute": "herramienta",
    "api.request": "herramienta de API",
    "email.send": "herramienta de email",
    "llm.reason": "razonamiento del modelo",
    "llm.generate": "generación del modelo",
    "respond_directly": "respuesta directa",
}

_REASON_LABELS = {
    "explicit_capability": "el pedido indicó el destino explícitamente",
    "explicit_tool": "el pedido indicó la herramienta explícitamente",
    "explicit_workflow": "el pedido indicó el workflow explícitamente",
    "explicit_agent": "el pedido indicó el agente explícitamente",
    "sql_heuristic": "la consulta pide datos estructurados",
    "authorization": "la ruta pedida no está permitida; se usó el fallback",
    "authorization_denied": "la ruta pedida no está permitida; se usó el fallback",
    "confidence_low": "la confianza no alcanzó el umbral",
    "confidence_mid_disagreement": "los verificadores no coincidieron",
    "jev_unavailable": "el juez no estaba disponible; fallback determinístico",
    "budget_block": "el presupuesto del tenant está agotado",
    "invalid_target": "el destino elegido no estaba entre los permitidos",
    "low_confidence": "la confianza no alcanzó el umbral",
    "action_not_warranted": "la acción no quedó justificada",
    "no_candidates": "no hay destinos autorizados para este pedido",
    "single_candidate": "sólo hay un destino autorizado",
    "default_target": "se usó el destino por defecto del tenant",
    "explicit_target": "el pedido indicó el destino explícitamente",
    "ok": "la evidencia y la política habilitan la ruta",
}


def confidence_band(confidence: float) -> str:
    value = float(confidence or 0.0)
    if value >= 0.85:
        return "alta"
    if value >= 0.65:
        return "media"
    return "baja"


def route_label(capability: str) -> str:
    return _ROUTE_LABELS.get(str(capability or ""), str(capability or "sin ruta"))


def reason_label(reason: str) -> str:
    return _REASON_LABELS.get(str(reason or ""), "la política resolvió la ruta")


def explain_decision(
    decision: RoutingDecision | None,
    *,
    mode: str = "user",
    selection: Any = None,
    policy: Any = None,
    evidence_count: int | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    """Explicación lista para UI. `mode="admin"` agrega detalle operativo."""
    if decision is None:
        return {
            "route": "sin ruta",
            "reason": "no hubo decisión para explicar",
            "confidence": "baja",
            "fallback": False,
        }
    reason = str(
        decision.metadata.get("reason")
        or getattr(selection, "reason", "")
        or "ok"
    )
    user_view: dict[str, Any] = {
        "route": route_label(decision.capability),
        "reason": reason_label(reason),
        "confidence": confidence_band(float(decision.confidence or 0.0)),
        "fallback": bool(decision.fallback_used),
    }
    if evidence_count is not None:
        user_view["sources_consulted"] = int(evidence_count)
    if selection is not None and getattr(selection, "target_id", None):
        user_view["target"] = str(selection.target_id)
    if policy is not None and getattr(policy, "requires_human", False):
        user_view["requires_human_review"] = True
    if str(mode) != "admin":
        return user_view
    admin = {
        **user_view,
        "capability": decision.capability,
        "provider": decision.provider,
        "questions_evaluated": _questions(decision, selection),
        "choice": getattr(selection, "choice", None) if selection is not None else None,
        "confidence_value": round(float(decision.confidence or 0.0), 4),
        "phase": phase or str(getattr(selection, "phase", "") or "") or None,
        "model": str(decision.metadata.get("model") or "") or None,
        "latency_ms": round(float(decision.latency_ms or 0.0), 2),
        "cost": round(float(decision.estimated_cost or 0.0), 6),
        "policy_result": (
            policy.to_public_dict() if policy is not None and hasattr(policy, "to_public_dict") else None
        ),
        "selection": (
            selection.to_public_dict()
            if selection is not None and hasattr(selection, "to_public_dict")
            else None
        ),
        "fallback_used": bool(decision.fallback_used),
    }
    return admin


def _questions(decision: RoutingDecision, selection: Any) -> list[str]:
    questions = decision.metadata.get("questions")
    if isinstance(questions, (list, tuple)):
        return [str(q) for q in questions][:32]
    if selection is not None:
        return [str(q) for q in (getattr(selection, "questions", ()) or ())][:32]
    return []
