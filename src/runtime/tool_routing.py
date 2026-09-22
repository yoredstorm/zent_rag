# =============================================================================
# Experimental agent tool routing — JEV Choice then expose a subset.
# =============================================================================
# Score fusion: 0.6 * probabilidad de la opcion + 0.4 * certeza de needs_tool.
# Por debajo del umbral no se impone nada ("sin certeza, decide el LLM").
# Authorization still uses the full allowlist at execute time.
#
# Batching (AGENT_STEP): cuando termination gate también está activo y
# RAG_DECISION_BATCH_MODE=on, `src/runtime/agent_step.py` compone las preguntas
# de ambos módulos en una sola llamada y reutiliza `apply_tool_answers`.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.decision.batch import (
    answer_for,
    build_agent_step_questions,
    noul_for,
)
from src.decision.judgment import PHASE_AGENT_STEP, JudgmentContext, call_phase_judge
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
        "skip_reason": None,
        "choice": None,
        "confidence": 0.0,
        "certainty": 0.0,
        "needs_tool": False,
        "score": 0.0,
        "certain": False,
        "alternatives": [],
        "state_chars": 0,
    }


def tool_criteria(tools: list[Any]) -> dict[str, str]:
    criteria = {
        str(t.name): str(getattr(t, "description", "") or t.name)[:180]
        for t in tools[:16]
    }
    criteria["none"] = "No tool. Answer or finish without a tool."
    return criteria


def build_agent_state(
    *,
    user_request: str,
    history: list[str],
    criteria: dict[str, str],
    agent_instructions: str = "",
    max_state_chars: int = 30000,
):
    """Prioridad del state: request → tool results → instrucciones → choices.

    Nunca se manda la KB completa: el builder recorta por presupuesto y reporta
    `chars` + `truncated` (secciones recortadas).
    """
    observations = "\n".join(line[:1200] for line in history[-8:])
    return build_jev_state(
        [
            StateSection("user_request", 1, (user_request or "")[:4000]),
            StateSection("tool_results", 2, observations),
            StateSection("agent_instructions", 3, agent_instructions),
            StateSection("available_tools", 4, ", ".join(criteria.keys())),
        ],
        max_chars=max_state_chars,
    )


def apply_tool_answers(
    tools: list[Any],
    answers: dict[str, Any],
    *,
    noul_yes: float = 0.65,
    noul_no: float = 0.35,
    confidence_threshold: float = 0.60,
) -> tuple[list[Any], dict[str, Any]]:
    """Compone el subset de tools desde las respuestas atómicas. Nunca ejecuta."""
    needs = noul_for(answers, "needs_tool", default=0.0) or 0.0
    tool_ans = answer_for(answers, "tool") or {}
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
    min_tools: int = 3,
    context: JudgmentContext | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Return a subset of tools. Empty judge payload keeps the full list.

    `skip_reason` en el meta explica por que JEV no fue consultado:
    `no_engine` (no configurado), `too_few_tools` (menos de `min_tools`
    herramientas) o `no_payload` (JEV no respondio).
    """
    meta = _tool_meta()
    if engine is None:
        meta["skip_reason"] = "no_engine"
        return tools, meta
    if len(tools) < max(1, int(min_tools or 3)):
        meta["skip_reason"] = "too_few_tools"
        meta["tools_count"] = len(tools)
        return tools, meta
    criteria = tool_criteria(tools)
    built = build_agent_state(
        user_request=user_request,
        history=history,
        criteria=criteria,
        agent_instructions=agent_instructions,
        max_state_chars=max_state_chars,
    )
    payload = await call_phase_judge(
        engine,
        phase=PHASE_AGENT_STEP,
        state=built.state,
        questions=tool_routing_questions(criteria),
        batch_questions=build_agent_step_questions(
            tool_criteria=criteria, include_termination=False
        ).to_jevy(),
        context=context or JudgmentContext(phase=PHASE_AGENT_STEP),
    )
    if not isinstance(payload, dict):
        meta["skip_reason"] = "no_payload"
        return tools, meta
    answers = payload.get("answers") or {}
    selected, selected_meta = apply_tool_answers(
        tools,
        answers,
        noul_yes=noul_yes,
        noul_no=noul_no,
        confidence_threshold=confidence_threshold,
    )
    meta = {
        **meta,
        **selected_meta,
        "state_chars": built.chars,
        "truncated": built.truncated,
        "truncated_sections": list(built.truncated),
    }
    return selected, meta
