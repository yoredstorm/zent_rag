# =============================================================================
# Independent termination gate — Noul: is the original request satisfied?
# Hard max_steps remains the orchestrator guardrail.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.decision.judgment import PHASE_TERMINATION, JudgmentContext, call_judge
from src.decision.questions import noul_from_answer, noul_is_yes
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
    payload = await call_judge(
        engine,
        state=state,
        questions=termination_questions(),
        context=context or JudgmentContext(phase=PHASE_TERMINATION),
    )
    if not isinstance(payload, dict):
        return result
    noul = noul_from_answer((payload.get("answers") or {}).get("satisfied"), 0.0)
    return {
        "stop": noul_is_yes(noul, noul_yes),
        "confidence": round(abs(noul - 0.5) * 2.0, 4),
        "provider": "jev",
        "noul": noul,
    }
