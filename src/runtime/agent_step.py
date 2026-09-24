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

from src.decision.batch import build_agent_step_questions, normalize_batch_mode, noul_for
from src.decision.judgment import PHASE_AGENT_STEP, JudgmentContext, call_phase_judge
from src.decision.questions import noul_is_yes
from src.runtime.termination import gate_enabled, satisfied_from_answers
from src.runtime.tool_routing import (
    _tool_meta,
    apply_tool_answers,
    build_agent_state,
    routing_enabled,
    tool_criteria,
)

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"
MODE_CANARY = "canary"
LOOP_MODES = (MODE_OFF, MODE_SHADOW, MODE_ON, MODE_CANARY)

#: Veredicto del paso (mismo vocabulario que el preflight del RAG).
ACTION_GENERATE = "generate_answer"
ACTION_RETRIEVE = "retrieve_more"
ACTION_ASK_USER = "ask_user"
ACTION_ABSTAIN = "abstain"


def loop_mode(settings, config: dict | None = None) -> str:
    """Modo del loop JEV del agente, con override por agente.

    `config_json.runtime.jev_loop` (off|shadow|on|canary) manda; si no, el flag
    del sistema. Los overrides legacy (tool_routing/termination_gate en off)
    siguen apagando su parte.
    """
    raw = (config or {}).get("runtime") if isinstance(config, dict) else None
    override = str((raw or {}).get("jev_loop") or "").strip().lower() if isinstance(raw, dict) else ""
    if override in LOOP_MODES:
        return override
    mode = str(getattr(settings, "RUNTIME_AGENT_JEV_LOOP", MODE_ON) or MODE_ON).strip().lower()
    return mode if mode in LOOP_MODES else MODE_ON


def loop_enabled(settings, config: dict | None = None) -> bool:
    """True si hay que juzgar cada paso (shadow también juzga: sólo no actúa)."""
    return loop_mode(settings, config) != MODE_OFF


def step_batch_enabled(settings, config: dict | None = None) -> bool:
    """True sólo si tool routing y termination están activos y el batch está on.

    Se mantiene por compatibilidad: el loop JEV ya no depende de estos flags.
    """
    if not routing_enabled(settings, config):
        return False
    if not gate_enabled(settings, config):
        return False
    mode = normalize_batch_mode(getattr(settings, "DECISION_BATCH_MODE", "off"))
    return mode == "on"


def compose_next_action(
    *,
    routing: dict[str, Any],
    termination: dict[str, Any],
    retrieval_rounds_left: int,
    has_uncovered_entities: bool,
    has_usable_evidence: bool,
) -> tuple[str, str]:
    """Veredicto del paso, compuesto en código (nunca lo interpreta un LLM).

    Devuelve `(action, reason)`.
    """
    stop = bool(termination.get("stop"))
    needs_more = routing.get("needs_more_evidence")
    needs_tool = bool(routing.get("needs_tool"))
    if stop and has_usable_evidence:
        return ACTION_GENERATE, "termination_satisfied"
    if retrieval_rounds_left > 0 and (needs_more is True or has_uncovered_entities):
        return ACTION_RETRIEVE, "evidence_gap"
    if not has_usable_evidence and retrieval_rounds_left <= 0:
        return ACTION_ABSTAIN, "no_usable_evidence"
    if needs_tool:
        return ACTION_GENERATE, "tool_choice_pending"
    if stop:
        return ACTION_GENERATE, "termination_satisfied"
    return ACTION_GENERATE, "default"


@dataclass
class AgentStepJudgment:
    tools: list[Any] = field(default_factory=list)
    routing: dict[str, Any] = field(default_factory=dict)
    termination: dict[str, Any] = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)
    state_chars: int = 0
    jev_used: bool = False
    #: Respuestas crudas del pack (para publicar el juicio completo en el flujo).
    answers: dict[str, Any] = field(default_factory=dict)
    #: Veredicto del paso (compuesto en código).
    next_action: str = ""
    action_reason: str = ""
    #: Entidades de la pregunta que la evidencia todavía no menciona.
    uncovered_entities: list[str] = field(default_factory=list)
    mode: str = MODE_OFF

    def to_step(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "agent_step",
            "questions": self.questions,
            "state_chars": self.state_chars,
            "routing": self.routing,
            "termination": self.termination,
            "mode": self.mode,
        }
        if self.next_action:
            payload["next_action"] = self.next_action
            payload["action_reason"] = self.action_reason
        if self.uncovered_entities:
            payload["uncovered_entities"] = list(self.uncovered_entities)[:4]
        return payload


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
    retrieval_rounds_left: int = 0,
    uncovered_entities: list[str] | None = None,
    has_usable_evidence: bool = True,
    include_evidence_gap: bool = False,
    mode: str = MODE_ON,
) -> AgentStepJudgment | None:
    """Una llamada AGENT_STEP con tool routing + termination del mismo estado.

    Con `retrieval_rounds_left`/`uncovered_entities` también compone el veredicto
    del paso (`next_action`), que es lo que el runtime ejecuta.
    """
    include_routing = len(tools) >= max(1, int(min_tools or 3))
    include_termination = tool_calls > 0
    if engine is None or (not include_routing and not include_termination and not include_evidence_gap):
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
        include_evidence_gap=include_evidence_gap,
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
    needs_more_reading = noul_for(answers, "needs_more_evidence")
    if needs_more_reading is not None:
        routing_meta = {**routing_meta, "needs_more_evidence": noul_is_yes(
            needs_more_reading, noul_yes
        )}
    gap = [str(item) for item in (uncovered_entities or []) if str(item)][:4]
    action, reason = compose_next_action(
        routing=routing_meta,
        termination=termination,
        retrieval_rounds_left=max(0, int(retrieval_rounds_left or 0)),
        has_uncovered_entities=bool(gap),
        has_usable_evidence=bool(has_usable_evidence),
    )
    return AgentStepJudgment(
        tools=selected,
        routing=routing_meta,
        termination=termination,
        questions=list(phase.ids()),
        state_chars=built.chars,
        jev_used=True,
        answers={str(key): value for key, value in answers.items() if isinstance(value, dict)},
        next_action=action,
        action_reason=reason,
        uncovered_entities=gap,
        mode=mode,
    )


def step_verdict_note(judgment: AgentStepJudgment, *, refined_query: str = "") -> str:
    """Veredicto del paso para el historial. Es un dato, no razonamiento privado."""
    lines = [f"## JEV · paso ({len(judgment.questions)} preguntas, 1 llamada)"]
    if judgment.uncovered_entities:
        lines.append(f"- la evidencia no menciona: {', '.join(judgment.uncovered_entities)}")
    if judgment.next_action == ACTION_RETRIEVE:
        target = refined_query or "la(s) entidad(es) sin cubrir"
        lines.append(f"- acción: buscar de nuevo con «{target}»")
        lines.append("- no respondas de memoria lo que todavía no está en la evidencia")
    elif judgment.next_action == ACTION_ABSTAIN:
        lines.append("- acción: no hay evidencia suficiente; declaralo en la respuesta")
    elif judgment.termination.get("stop"):
        lines.append("- acción: la evidencia alcanza; respondé con lo consultado")
    else:
        lines.append("- acción: seguí con lo que la evidencia sostenga")
    return "\n".join(lines)
