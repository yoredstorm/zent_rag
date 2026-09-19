# =============================================================================
# Independent termination gate — Noul: is the original request satisfied?
# Hard max_steps remains the orchestrator guardrail.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.decision.questions import noul_is_yes
from src.runtime.questions import termination_questions


def gate_enabled(settings) -> bool:
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
) -> dict[str, Any]:
    """Return {stop, confidence, provider}. Never bypasses max_steps."""
    result = {"stop": False, "confidence": 0.0, "provider": "skip"}
    if engine is None or tool_calls <= 0:
        return result
    state = {
        "user_request": (user_request or "")[:2000],
        "tool_results": [line[:180] for line in history[-8:]],
    }
    payload = await engine.judge(state=state, questions=termination_questions())
    if not isinstance(payload, dict):
        return result
    noul = float(((payload.get("answers") or {}).get("satisfied") or {}).get("noul") or 0.0)
    return {
        "stop": noul_is_yes(noul, noul_yes),
        "confidence": round(abs(noul - 0.5) * 2.0, 4),
        "provider": "jev",
        "noul": noul,
    }
