# =============================================================================
# JEV Decision Value — cuánto aportó cada juicio JEV (medición, no decisión).
# =============================================================================
# Clasifica los juicios JEV ya emitidos en los `steps` del run:
#   CONFIRMED   el veredicto coincide con la señal determinista canónica
#   CHANGED     el veredicto difiere (JEV movió la decisión)
#   PREVENTED   JEV fue más estricto que la señal determinista (evitó pasar)
#   SKIPPED     la fase no llamó JEV (passthrough / sin JEV)
#   UNCLASSIFIED no hay señal determinista comparable en el run
#
# No cambia ninguna decisión: es el insumo del reporte «¿dónde aporta JEV?».
# =============================================================================
from __future__ import annotations

from typing import Any, Iterable

JEV_VALUE_VERSION = "jev-value-1"

#: Fases con llamada JEV reconocibles en los steps del run.
_PHASE_BY_STEP = {
    "answer_gate": "answer_gate",
    "termination_gate": "termination",
    "tool_routing": "tool_routing",
    "agent_step": "agent_step",
    "conversation_intent": "turn_intent",
}

#: Acción de suficiencia determinista -> veredicto de gate esperado.
_SUFFICIENCY_TO_VERDICT = {
    "generate": "approve",
    "answer_with_limits": "answer_with_limits",
    "retrieve_more": "retrieve_more",
    "abstain": "abstain",
}

#: Cuanto más alto, más restrictivo (evita responder).
_STRICTNESS = {
    "approve": 0,
    "answer_with_limits": 1,
    "revise": 2,
    "retrieve_more": 2,
    "abstain": 3,
}

_SKIPPED_MODES = {"passthrough", "jev_no_tools", "off"}


def classify_gate_value(verdict: str, expected: str) -> str:
    """Valor del gate JEV contra la señal determinista del run."""
    verdict = str(verdict or "")
    expected = str(expected or "")
    if not verdict or not expected:
        return "UNCLASSIFIED"
    if verdict == expected:
        return "CONFIRMED"
    if _STRICTNESS.get(verdict, 1) > _STRICTNESS.get(expected, 1):
        return "PREVENTED"
    return "CHANGED"


def summarize_jev_value(steps: Iterable[Any]) -> dict:
    """Resumen agregado: llamadas por fase + valor por juicio comparable."""
    rows = [step for step in (steps or ()) if isinstance(step, dict)]
    by_phase: dict[str, int] = {}
    values: dict[str, int] = {key: 0 for key in ("CONFIRMED", "CHANGED", "PREVENTED", "SKIPPED", "UNCLASSIFIED")}
    calls = 0
    last_sufficiency_action = ""
    for step in rows:
        step_type = str(step.get("type") or "")
        if step_type == "evidence_sufficiency":
            last_sufficiency_action = str(step.get("recommended_action") or step.get("action") or "")
            continue
        phase = _PHASE_BY_STEP.get(step_type)
        if phase is None:
            continue
        mode = str(step.get("mode") or "")
        if mode in _SKIPPED_MODES or str(step.get("provider") or "") == "skip":
            values["SKIPPED"] += 1
            by_phase[phase] = by_phase.get(phase, 0) + 1
            continue
        calls += 1
        by_phase[phase] = by_phase.get(phase, 0) + 1
        if step_type == "answer_gate":
            expected = _SUFFICIENCY_TO_VERDICT.get(last_sufficiency_action, "")
            values[classify_gate_value(str(step.get("verdict") or ""), expected)] += 1
        else:
            values["UNCLASSIFIED"] += 1
    comparable = (
        values["CONFIRMED"] + values["CHANGED"] + values["PREVENTED"]
    )
    return {
        "version": JEV_VALUE_VERSION,
        "calls": calls,
        "by_phase": dict(sorted(by_phase.items())),
        "values": dict(values),
        "comparable": comparable,
        "redundant_rate": round(values["CONFIRMED"] / comparable, 4) if comparable else None,
    }


def skip_phases_from_settings(settings: Any) -> frozenset[str]:
    """Fases JEV que ops decide saltar (se habilitan con datos de redundant_rate).

    `RUNTIME_JEV_SKIP_PHASES` = lista separada por comas: `answer_gate`,
    `agent_step`, `termination`. Default vacío: JEV corre como siempre.
    """
    raw = str(getattr(settings, "RUNTIME_JEV_SKIP_PHASES", "") or "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def skip_shadow_enabled(settings: Any) -> bool:
    """`RUNTIME_JEV_SKIP_SHADOW=on`: no se llama al juez en fases shadow.

    Un veredicto shadow NO decide (solo se registra): no pagar la llamada es
    ahorro puro sin cambio de comportamiento. En fase on/canary no aplica.
    """
    raw = str(getattr(settings, "RUNTIME_JEV_SKIP_SHADOW", "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


def phase_skipped(phase: str) -> bool:
    """¿Ops pidió saltar esta fase JEV? Fail-open: sin settings, no se saltea."""
    try:
        from src.core.config import get_settings

        return str(phase or "").strip().lower() in skip_phases_from_settings(
            get_settings()
        )
    except Exception:  # noqa: BLE001 — la calibración nunca rompe el run
        return False


__all__ = [
    "JEV_VALUE_VERSION",
    "classify_gate_value",
    "phase_skipped",
    "skip_phases_from_settings",
    "skip_shadow_enabled",
    "summarize_jev_value",
]
