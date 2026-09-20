# =============================================================================
# Experimental agent tool routing — JEV Choice then expose a subset.
# Authorization still uses the full allowlist at execute time.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.decision.questions import noul_is_yes
from src.runtime.questions import tool_routing_questions


def routing_enabled(settings, config: dict | None = None) -> bool:
    """Flag del tenant; `config.runtime.tool_routing` del agente manda si existe."""
    runtime = (config or {}).get("runtime") if isinstance(config, dict) else None
    if isinstance(runtime, dict):
        override = runtime.get("tool_routing")
        if isinstance(override, bool):
            return override
    mode = str(getattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off") or "off").lower()
    return mode in {"experimental", "on", "true", "1"}


async def select_relevant_tools(
    tools: list[Any],
    *,
    engine,
    user_request: str,
    history: list[str],
    noul_yes: float = 0.65,
) -> tuple[list[Any], dict[str, Any]]:
    """Return a subset of tools. Empty judge payload keeps the full list."""
    meta: dict[str, Any] = {"mode": "passthrough", "confidence": 0.0, "alternatives": []}
    if engine is None or len(tools) <= 2:
        return tools, meta
    criteria = {str(t.name): str(getattr(t, "description", "") or t.name)[:180] for t in tools[:16]}
    criteria["none"] = "No tool. Answer or finish without a tool."
    state = {
        "user_request": (user_request or "")[:2000],
        "available_tools": list(criteria.keys()),
        "tool_results": [line[:180] for line in history[-6:] if line.startswith("OBSERVATION")],
    }
    payload = await engine.judge(state=state, questions=tool_routing_questions(criteria))
    if not isinstance(payload, dict):
        return tools, meta
    answers = payload.get("answers") or {}
    needs = float((answers.get("needs_tool") or {}).get("noul") or 0.0)
    tool_ans = answers.get("tool") or {}
    choice = str(tool_ans.get("choice") or "none")
    confidence = float(tool_ans.get("confidence") or 0.0)
    probs = tool_ans.get("probabilities") or {}
    alternatives = [
        k
        for k, _ in sorted(
            ((str(k), float(v)) for k, v in probs.items() if str(k) != choice),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
    ]
    meta = {
        "mode": "jev",
        "choice": choice,
        "confidence": round(confidence, 4),
        "needs_tool": noul_is_yes(needs, noul_yes),
        "alternatives": alternatives,
    }
    by_name = {str(t.name): t for t in tools}
    selected: list[Any] = []
    if choice in by_name:
        selected.append(by_name[choice])
    for alt in alternatives:
        if alt in by_name and by_name[alt] not in selected:
            selected.append(by_name[alt])
    if not selected:
        return tools, meta
    return selected, meta
