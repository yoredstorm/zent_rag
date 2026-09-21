# =============================================================================
# JudgmentContext — identidad y fase de cada llamada a engine.judge().
# =============================================================================
# `judge` responde preguntas atómicas fuera del routing de capabilities
# (adaptive RAG, evidence, grounding, tool routing, termination, answer gate,
# workflow AI decision). Sin contexto, esas llamadas no pueden contabilizarse
# por tenant ni atribuirse a una fase.
#
# Compatibilidad: el contexto es opcional. `call_judge` solo lo pasa a
# callables que declaran el parámetro `context` (o **kwargs), así los fakes y
# callers existentes siguen funcionando.
# =============================================================================
from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Awaitable, Callable
from uuid import UUID

PHASE_ROUTING = "routing"
PHASE_PRE_RETRIEVAL = "pre_retrieval"
PHASE_EVIDENCE = "evidence"
PHASE_GROUNDING = "grounding"
PHASE_TOOL_ROUTING = "tool_routing"
PHASE_TERMINATION = "termination"
PHASE_ANSWER_GATE = "answer_gate"
PHASE_WORKFLOW_DECISION = "workflow_decision"

JUDGE_PHASES = frozenset(
    {
        PHASE_ROUTING,
        PHASE_PRE_RETRIEVAL,
        PHASE_EVIDENCE,
        PHASE_GROUNDING,
        PHASE_TOOL_ROUTING,
        PHASE_TERMINATION,
        PHASE_ANSWER_GATE,
        PHASE_WORKFLOW_DECISION,
    }
)


@dataclass(frozen=True, kw_only=True)
class JudgmentContext:
    """Qué fase llamó a JEV y a quién pertenece el juicio.

    Solo `phase` es obligatorio conceptualmente; organización y request son
    opcionales para no romper callers sin tenant (tests, workflows sueltos).
    """

    phase: str = "unknown"
    organization_id: UUID | None = None
    request_id: UUID | None = None
    user_id: UUID | None = None
    provider: str = "jev"
    model: str | None = None
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    capability: str | None = None
    run_id: UUID | None = None
    deployment_id: UUID | None = None
    trace_id: str | None = None

    @property
    def effective_request_id(self) -> UUID | None:
        """request_id del request; run_id como correlación de agentes/workflows."""
        return self.request_id or self.run_id


@lru_cache(maxsize=256)
def _accepts_context(judge: Any) -> bool:
    try:
        signature = inspect.signature(judge)
    except (TypeError, ValueError):
        return False
    params = signature.parameters.values()
    if "context" in signature.parameters:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def _judge_callable(judge: Any) -> Any:
    """Acepta un callable o un engine con `.judge` (DecisionEngine)."""
    if callable(judge):
        return judge
    method = getattr(judge, "judge", None)
    return method if callable(method) else judge


async def call_judge(
    judge: Callable[..., Awaitable[dict[str, Any] | None]],
    *,
    state: dict[str, Any],
    questions: dict[str, Any],
    context: JudgmentContext | None = None,
) -> dict[str, Any] | None:
    """Invoca un judge con contexto cuando el callable lo soporta."""
    target = _judge_callable(judge)
    if context is None or not _accepts_context(target):
        return await target(state=state, questions=questions)
    return await target(state=state, questions=questions, context=context)
