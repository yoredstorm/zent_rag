# =============================================================================
# Agent steps -> flow timeline (mismo mapeo que el portal, lado servidor).
# =============================================================================
from __future__ import annotations

from typing import Any

STEP_LABEL: dict[str, str] = {
    "llm": "LLM (razonamiento)",
    "tool_call": "Herramienta",
    "tool_routing": "JEV elige herramienta",
    "termination_gate": "JEV verifica cierre",
    "answer_gate": "JEV verifica respuesta",
    "answer_revision": "Revisión con feedback de JEV",
    "final": "Respuesta final",
    "guardrail": "Límite",
    "error": "Error",
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


def step_to_flow(step: dict[str, Any]) -> dict[str, Any]:
    step_type = str(step.get("type") or "")
    detail = ""
    if step_type == "tool_routing":
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
    status = "warn" if step.get("error") or step.get("verdict") == "abstain" else "ok"
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
        if step_type in {"tool_routing", "termination_gate", "answer_gate"}:
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
