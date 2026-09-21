# =============================================================================
# Agent steps -> flow timeline (mismo mapeo que el portal, lado servidor).
# =============================================================================
from __future__ import annotations

from typing import Any

STEP_LABEL: dict[str, str] = {
    "llm": "LLM (razonamiento)",
    "tool_call": "Herramienta",
    "tool_routing": "JEV elige herramienta",
    "tool_filter": "Herramientas omitidas",
    "termination_gate": "JEV verifica cierre",
    "answer_gate": "JEV verifica respuesta",
    "answer_revision": "Revisión con feedback de JEV",
    "final": "Respuesta final",
    "guardrail": "Límite",
    "error": "Error",
}

OMIT_REASON_LABEL: dict[str, str] = {
    "no_data_sources": "el agente no tiene fuentes de datos",
    "no_tabular_sources": "el agente no tiene CSV/Excel",
    "no_api_allowlist": "no hay APIs permitidas configuradas",
}

VERDICT_LABEL: dict[str, str] = {
    "approve": "aprobada",
    "revise": "revisar",
    "revise_exhausted": "aprobada (revisión ya usada)",
    "abstain": "abstención",
}


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


SKIP_REASON_LABEL: dict[str, str] = {
    "no_engine": "JEV no configurado",
    "no_payload": "JEV sin respuesta",
}


def _skip_detail(step: dict[str, Any]) -> str:
    """Detalle honesto cuando el router no consulto a JEV."""
    reason = str(step.get("skip_reason") or "")
    if reason in SKIP_REASON_LABEL:
        return SKIP_REASON_LABEL[reason]
    if reason == "too_few_tools":
        count = int(_num(step.get("tools_count")))
        plural = "herramientas activas" if count != 1 else "herramienta activa"
        return f"JEV no consultado · {count} {plural}"
    return "JEV no consultado"


def step_to_flow(step: dict[str, Any]) -> dict[str, Any]:
    step_type = str(step.get("type") or "")
    detail = ""
    if step_type == "tool_routing":
        if str(step.get("mode") or "") == "passthrough":
            detail = _skip_detail(step)
        else:
            choice = str(step.get("choice") or "—")
            confidence = _num(step.get("confidence"))
            score = _num(step.get("score"))
            parts = [choice]
            if confidence > 0:
                parts.append(f"confianza {confidence:.2f}")
            if score > 0:
                parts.append(f"score {score:.2f}")
            if step.get("certain") is False:
                parts.append("sin certeza (decide el LLM)")
            detail = " · ".join(parts)
    elif step_type == "answer_gate":
        verdict = VERDICT_LABEL.get(str(step.get("verdict") or ""), str(step.get("verdict") or ""))
        parts = []
        if step.get("grounded") is True:
            parts.append("respaldada")
        elif step.get("grounded") is False:
            parts.append("sin respaldo")
        if step.get("complete") is True:
            parts.append("completa")
        elif step.get("complete") is False:
            parts.append("incompleta")
        quality = _num(step.get("quality"))
        if quality > 0:
            parts.append(f"calidad {quality:g}/3")
        if verdict:
            parts.append(f"→ {verdict}")
        score = _num(step.get("score"))
        if score > 0:
            parts.append(f"score {score:.2f}")
        detail = " · ".join(parts)
    elif step_type == "termination_gate":
        detail = "cerró el run" if step.get("stop") else "continuó"
    elif step_type == "answer_revision":
        detail = str(step.get("feedback") or "corrección pedida por JEV")[:200]
    elif step_type == "tool_call":
        if step.get("error"):
            detail = str(step["error"])[:160]
        elif step.get("output"):
            detail = str(step["output"])[:120]
        else:
            detail = "herramienta"
    elif step_type == "tool_filter":
        omitted = step.get("omitted") if isinstance(step.get("omitted"), list) else []
        parts = []
        for item in omitted:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "herramienta")
            reason = OMIT_REASON_LABEL.get(
                str(item.get("reason") or ""), str(item.get("reason") or "")
            )
            parts.append(f"{tool} ({reason})" if reason else tool)
        detail = " · ".join(parts) or "sin cambios"
    elif step_type == "llm":
        detail = " · ".join(
            part
            for part in (
                str(step.get("model") or ""),
                f"{int(_num(step.get('tokens')))} tokens" if _num(step.get("tokens")) > 0 else "",
                ", ".join(str(k) for k in step["action"]) if isinstance(step.get("action"), dict) else "",
            )
            if part
        )
    else:
        detail = str(step.get("detail") or step.get("status") or "")[:160]

    name = (
        str(step.get("tool") or "herramienta")
        if step_type == "tool_call"
        else STEP_LABEL.get(step_type, step_type or "paso")
    )
    status = (
        "warn"
        if step.get("error") or step.get("verdict") == "abstain" or step_type == "tool_filter"
        else "ok"
    )
    return {
        "name": name,
        "status": status,
        "ms": round(_num(step.get("latency_ms")), 2),
        "detail": detail[:200],
    }


def steps_to_flow(steps: Any) -> dict[str, Any]:
    """Timeline + bloque JEV (used/score/verdict) para el flujo persistido."""
    rows = [step for step in (steps or []) if isinstance(step, dict)] if isinstance(steps, list) else []
    timeline: list[dict[str, Any]] = []
    jev_used = False
    jev_score: float | None = None
    jev_verdict: str | None = None
    jev_grounded: bool | None = None
    jev_complete: bool | None = None
    for step in rows:
        step_type = str(step.get("type") or "")
        if step_type == "tool_routing":
            # Un paso `passthrough` solo se mostro: JEV no fue consultado.
            if str(step.get("mode") or "") != "passthrough":
                jev_used = True
        elif step_type in {"termination_gate", "answer_gate"}:
            # `provider=skip` = el gate no llego a juzgar (JEV no disponible).
            if str(step.get("provider") or "jev") != "skip":
                jev_used = True
        if step_type == "answer_gate":
            score = _num(step.get("score"))
            if score > 0:
                jev_score = round(score, 4)
            if step.get("verdict"):
                jev_verdict = str(step.get("verdict"))
            if isinstance(step.get("grounded"), bool):
                jev_grounded = bool(step.get("grounded"))
            if isinstance(step.get("complete"), bool):
                jev_complete = bool(step.get("complete"))
        timeline.append(step_to_flow(step))
    return {
        "steps": timeline,
        "jev": {
            "used": jev_used,
            "score": jev_score,
            "verdict": jev_verdict,
            "grounded": jev_grounded,
            "complete": jev_complete,
        },
    }
