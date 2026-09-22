# =============================================================================
# Independent termination gate — Noul: is the original request satisfied?
# Hard max_steps remains the orchestrator guardrail.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.decision.batch import build_agent_step_questions, noul_for
from src.decision.judgment import PHASE_AGENT_STEP, JudgmentContext, call_phase_judge
from src.decision.questions import noul_is_yes
from src.runtime.questions import termination_questions


def gate_enabled(settings, config: dict | None = None) -> bool:
    """Flag del tenant; `config.runtime.termination_gate` del agente manda si existe."""
    runtime = (config or {}).get("runtime") if isinstance(config, dict) else None
    if isinstance(runtime, dict):
        override = runtime.get("termination_gate")
        if isinstance(override, bool):
            return override
    flag = getattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    if isinstance(flag, bool):
        return flag
    return str(flag or "off").lower() in {"on", "true", "1", "experimental"}


def satisfied_from_answers(
    answers: dict[str, Any],
    *,
    noul_yes: float = 0.65,
) -> dict[str, Any]:
    """Compone el veredicto de termination desde las respuestas atómicas."""
    noul = noul_for(answers, "satisfied", default=0.0) or 0.0
    return {
        "stop": noul_is_yes(noul, noul_yes),
        "confidence": round(abs(noul - 0.5) * 2.0, 4),
        "provider": "jev",
        "noul": noul,
    }


async def original_request_satisfied(
    *,
    engine,
    user_request: str,
    history: list[str],
    tool_calls: int,
    noul_yes: float = 0.65,
    context: JudgmentContext | None = None,
) -> dict[str, Any]:
    """Return {stop, confidence, provider}. Never bypasses max_steps."""
    result = {"stop": False, "confidence": 0.0, "provider": "skip"}
    if engine is None or tool_calls <= 0:
        return result
    state = {
        "user_request": (user_request or "")[:2000],
        "tool_results": [line[:180] for line in history[-8:]],
    }
    context = context or JudgmentContext(phase=PHASE_AGENT_STEP)
    # 1) Reutilizar el juicio AGENT_STEP del mismo estado (tool routing + termination
    #    batcheados). 2) Si no hay payload, preguntar sólo termination.
    payload = await call_phase_judge(
        engine,
        phase=PHASE_AGENT_STEP,
        state=state,
        questions=None,
        context=context,
    )
    if payload is None:
        payload = await call_phase_judge(
            engine,
            phase=PHASE_AGENT_STEP,
            state=state,
            questions=termination_questions(),
            batch_questions=build_agent_step_questions(
                include_tool_routing=False, include_termination=True
            ).to_jevy(),
            context=context,
        )
    if not isinstance(payload, dict):
        return result
    answers = payload.get("answers") or {}
    return satisfied_from_answers(answers, noul_yes=noul_yes)
