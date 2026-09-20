# =============================================================================
# Experimental agent tool routing — JEV Choice then expose a subset.
# =============================================================================
# Score fusion: 0.6 * probabilidad de la opcion + 0.4 * certeza de needs_tool.
# Por debajo del umbral no se impone nada ("sin certeza, decide el LLM").
# Authorization still uses the full allowlist at execute time.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.decision.questions import noul_certainty, noul_is_no, noul_is_yes
from src.runtime.jev_state import StateSection, build_jev_state
from src.runtime.questions import tool_routing_questions

TOOL_WEIGHTS = {"choice": 0.6, "needs_tool": 0.4}


def routing_enabled(settings, config: dict | None = None) -> bool:
    """Flag del tenant; `config.runtime.tool_routing` del agente manda si existe."""
    runtime = (config or {}).get("runtime") if isinstance(config, dict) else None
    if isinstance(runtime, dict):
        override = runtime.get("tool_routing")
        if isinstance(override, bool):
            return override
    mode = str(getattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off") or "off").lower()
    return mode in {"experimental", "on", "true", "1"}


def _tool_meta() -> dict[str, Any]:
    return {
        "mode": "passthrough",
        "choice": None,
        "confidence": 0.0,
        "certainty": 0.0,
        "needs_tool": False,
        "score": 0.0,
        "certain": False,
        "alternatives": [],
        "state_chars": 0,
    }


async def select_relevant_tools(
    tools: list[Any],
    *,
    engine,
    user_request: str,
    history: list[str],
    noul_yes: float = 0.65,
    noul_no: float = 0.35,
    agent_instructions: str = "",
    max_state_chars: int = 30000,
    confidence_threshold: float = 0.60,
) -> tuple[list[Any], dict[str, Any]]:
    """Return a subset of tools. Empty judge payload keeps the full list."""
    meta = _tool_meta()
    if engine is None or len(tools) <= 2:
        return tools, meta
    criteria = {str(t.name): str(getattr(t, "description", "") or t.name)[:180] for t in tools[:16]}
    criteria["none"] = "No tool. Answer or finish without a tool."
    observations = "\n".join(line[:1200] for line in history[-8:])
    built = build_jev_state(
        [
            StateSection("user_request", 1, (user_request or "")[:4000]),
            StateSection("agent_instructions", 2, agent_instructions),
            StateSection("tool_results", 3, observations),
            StateSection("available_tools", 4, ", ".join(criteria.keys())),
        ],
        max_chars=max_state_chars,
    )
    state = built.state
    payload = await engine.judge(state=state, questions=tool_routing_questions(criteria))
    if not isinstance(payload, dict):
        return tools, meta
    answers = payload.get("answers") or {}
    needs = float((answers.get("needs_tool") or {}).get("noul") or 0.0)
    tool_ans = answers.get("tool") or {}
    choice = str(tool_ans.get("choice") or "none")
    probabilities = tool_ans.get("probabilities") or {}
    choice_prob = float(tool_ans.get("confidence") or 0.0)
    try:
        choice_prob = max(choice_prob, float(probabilities.get(choice) or 0.0))
    except (TypeError, ValueError):
        pass
    certainty = noul_certainty(needs)
    score = TOOL_WEIGHTS["choice"] * choice_prob + TOOL_WEIGHTS["needs_tool"] * certainty
    alternatives = [
        k
        for k, _ in sorted(
            ((str(k), float(v)) for k, v in probabilities.items() if str(k) != choice),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
    ]
    meta = {
        "mode": "jev",
        "choice": choice,
        "confidence": round(choice_prob, 4),
        "certainty": round(certainty, 4),
        "needs_tool": noul_is_yes(needs, noul_yes),
        "score": round(score, 4),
        "certain": score >= confidence_threshold,
        "alternatives": alternatives,
        "state_chars": built.chars,
        "truncated": built.truncated,
    }

    by_name = {str(t.name): t for t in tools}
    if choice == "none":
        # Solo se retiran las herramientas si JEV esta seguro de que no hacen falta.
        if noul_is_no(needs, noul_no) and score >= confidence_threshold:
            meta["mode"] = "jev_no_tools"
            return [], meta
        meta["certain"] = False
        return tools, meta
    if not meta["certain"] or choice not in by_name:
        meta["certain"] = False
        return tools, meta
    selected: list[Any] = [by_name[choice]]
    for alt in alternatives:
        if alt in by_name and by_name[alt] not in selected:
            selected.append(by_name[alt])
    return selected, meta
