# =============================================================================
# Agent step batching — tool routing + termination en UNA llamada por paso.
# =============================================================================
# Ambos módulos juzgan el mismo estado incremental (user_request, tool_results,
# available_tools). Sólo se batchean cuando LOS DOS features están activos y
# RAG_DECISION_BATCH_MODE=on: si alguno está apagado, cada módulo conserva su
# llamada aislada y su comportamiento previo.
#
# El juicio combinado se pide al cerrar el paso (después del tool result): ahí
# el estado ya incluye lo que el paso produjo, así termination juzga el estado
# actual y routing prepara el paso siguiente sin segunda llamada.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.decision.batch import build_agent_step_questions, normalize_batch_mode
from src.decision.judgment import PHASE_AGENT_STEP, JudgmentContext, call_phase_judge
from src.runtime.termination import gate_enabled, satisfied_from_answers
from src.runtime.tool_routing import (
    _tool_meta,
    apply_tool_answers,
    build_agent_state,
    routing_enabled,
    tool_criteria,
)


def step_batch_enabled(settings, config: dict | None = None) -> bool:
    """True sólo si tool routing y termination están activos y el batch está on."""
    if not routing_enabled(settings, config):
        return False
    if not gate_enabled(settings, config):
        return False
    mode = normalize_batch_mode(getattr(settings, "DECISION_BATCH_MODE", "off"))
    return mode == "on"


@dataclass
class AgentStepJudgment:
    tools: list[Any] = field(default_factory=list)
    routing: dict[str, Any] = field(default_factory=dict)
    termination: dict[str, Any] = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)
    state_chars: int = 0
    jev_used: bool = False

    def to_step(self) -> dict[str, Any]:
        return {
            "type": "agent_step",
            "questions": self.questions,
            "state_chars": self.state_chars,
            "routing": self.routing,
            "termination": self.termination,
        }


async def judge_agent_step(
    *,
    engine,
    tools: list[Any],
    user_request: str,
    history: list[str],
    tool_calls: int,
    agent_instructions: str = "",
    noul_yes: float = 0.65,
    noul_no: float = 0.35,
    max_state_chars: int = 30000,
    confidence_threshold: float = 0.60,
    min_tools: int = 3,
    context: JudgmentContext | None = None,
) -> AgentStepJudgment | None:
    """Una llamada AGENT_STEP con tool routing + termination del mismo estado."""
    include_routing = len(tools) >= max(1, int(min_tools or 3))
    include_termination = tool_calls > 0
    if engine is None or (not include_routing and not include_termination):
        return None
    criteria = tool_criteria(tools) if include_routing else {}
    built = build_agent_state(
        user_request=user_request,
        history=history,
        criteria=criteria or {"none": "No tool. Answer or finish without a tool."},
        agent_instructions=agent_instructions,
        max_state_chars=max_state_chars,
    )
    phase = build_agent_step_questions(
        tool_criteria=criteria,
        include_tool_routing=include_routing,
        include_termination=include_termination,
    )
    payload = await call_phase_judge(
        engine,
        phase=PHASE_AGENT_STEP,
        state=built.state,
        questions=phase.to_jevy(),
        context=context or JudgmentContext(phase=PHASE_AGENT_STEP),
    )
    if not isinstance(payload, dict):
        return None
    answers = payload.get("answers") or {}
    if include_routing:
        selected, routing_meta = apply_tool_answers(
            tools,
            answers,
            noul_yes=noul_yes,
            noul_no=noul_no,
            confidence_threshold=confidence_threshold,
        )
        routing_meta = {
            **routing_meta,
            "state_chars": built.chars,
            "truncated": built.truncated,
            "truncated_sections": list(built.truncated),
        }
    else:
        selected = tools
        routing_meta = {**_tool_meta(), "skip_reason": "too_few_tools", "tools_count": len(tools)}
    termination = (
        satisfied_from_answers(answers, noul_yes=noul_yes)
        if include_termination
        else {"stop": False, "confidence": 0.0, "provider": "skip"}
    )
    return AgentStepJudgment(
        tools=selected,
        routing=routing_meta,
        termination=termination,
        questions=list(phase.ids()),
        state_chars=built.chars,
        jev_used=True,
    )
