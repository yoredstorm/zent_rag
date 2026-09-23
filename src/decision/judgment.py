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
PHASE_TARGET_SELECTION = "target_selection"

# Fases de batching (una llamada por estado compatible). Ver
# `src/decision/batch.py` y el ADR decision-engine-batching.md.
PHASE_POST_RETRIEVAL = "post_retrieval"
PHASE_POST_GENERATION = "post_generation"
PHASE_AGENT_STEP = "agent_step"

# Fases del JEV Preflight: juicio barato ANTES de pagar generación/razonamiento
# caro. Ver `src/decision/preflight.py` y docs/architecture/jev-preflight.md.
PHASE_PRE_REASONING = "pre_reasoning"
PHASE_POST_RECONSTRUCTION = "post_reconstruction"
PHASE_PRE_GENERATION = "pre_generation"

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
        PHASE_POST_RETRIEVAL,
        PHASE_POST_GENERATION,
        PHASE_AGENT_STEP,
        PHASE_PRE_REASONING,
        PHASE_POST_RECONSTRUCTION,
        PHASE_PRE_GENERATION,
        PHASE_TARGET_SELECTION,
    }
)

# Alias de etiqueta para métricas/usage: las fases de batching se reportan con
# la etiqueta legacy de su módulo principal para que los dashboards sigan
# comparables antes/después del batching.
_USAGE_PHASE_LABELS = {
    PHASE_POST_RETRIEVAL: PHASE_EVIDENCE,
    PHASE_POST_GENERATION: PHASE_GROUNDING,
    PHASE_AGENT_STEP: PHASE_TOOL_ROUTING,
}


def usage_phase_label(phase: str | None) -> str:
    """Etiqueta estable de fase para métricas y usage events."""
    value = str(phase or "unknown")
    return _USAGE_PHASE_LABELS.get(value, value)


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


@lru_cache(maxsize=256)
def _phase_params(judge: Any) -> frozenset[str]:
    """Parámetros aceptados por `judge_phase`, o `*` si acepta **kwargs."""
    try:
        signature = inspect.signature(judge)
    except (TypeError, ValueError):
        return frozenset()
    params = signature.parameters.values()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return frozenset({"*"})
    return frozenset(signature.parameters)


async def call_phase_judge(
    judge: Any,
    *,
    phase: str,
    state: dict[str, Any],
    questions: dict[str, Any] | None = None,
    batch_questions: dict[str, Any] | None = None,
    context: JudgmentContext | None = None,
    cache: Any = None,
) -> dict[str, Any] | None:
    """Invoca una fase de juicio con una sola llamada por estado compatible.

    Con un `DecisionEngine` (o cualquier judge con `judge_phase`) usa el camino
    batcheado: cache request-scoped, dedupe y rollout off/shadow/on. Con un
    callable simple (fakes, providers legacy) mantiene exactamente el contrato
    de `call_judge`, así los tests y fallbacks previos siguen funcionando.

    `questions=None` sin `batch_questions` significa "reutilizá el payload de
    esta fase si ya existe": sólo el camino batcheado puede responder eso.
    """
    target = getattr(judge, "judge_phase", None)
    if not callable(target):
        if questions is None:
            return None
        return await call_judge(judge, state=state, questions=questions, context=context)
    accepted = _phase_params(target)
    kwargs: dict[str, Any] = {
        "phase": phase,
        "state": state,
        "questions": questions,
        "batch_questions": batch_questions,
        "context": context,
        "cache": cache,
    }
    if accepted and "*" not in accepted:
        kwargs = {key: value for key, value in kwargs.items() if key in accepted}
    return await target(**kwargs)
