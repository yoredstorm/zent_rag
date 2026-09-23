# =============================================================================
# Agent Runtime — integración del razonamiento (§34/§35/§37/§38/§47)
# =============================================================================
# El runtime no razona por su cuenta: prepara el estado de razonamiento una vez
# por run, lo usa para (a) no responder antes de reconstruir el escenario,
# (b) inyectar Company Context de forma acotada y (c) entregar el workspace al
# finalizar. Todo falla suave: sin motor, el runtime se comporta como antes.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_COMPANY_CONTEXT_KEY = "company_context"

#: Regla por defecto del prompt: comportamiento actual para preguntas simples.
DEFAULT_ANSWER_RULE = (
    "8. After a tool observation that contains documents or facts, respond with\n"
    '   {{"answer": "..."}}. Do not call the same tool with the same arguments again.\n'
    "   Search again only if the observation is (no results) or an error."
)

#: Regla para razonamiento complejo: no se responde con evidencia parcial.
ANALYSIS_ANSWER_RULE = (
    "8. This request requires reconstructing a scenario before answering. A tool\n"
    "   observation alone is NOT enough to answer: after each observation, update\n"
    "   your analysis and check whether the required analysis is complete.\n"
    "   Valid answers are:\n"
    '   {{"tool": "<name>", "arguments": {{...}}}} to collect still-missing evidence, or\n'
    '   {{"answer": "..."}} ONLY when the analysis is complete OR when you must state\n'
    "   exactly which evidence is missing to conclude.\n"
    "   Never answer with a plausible conclusion built on partial evidence, and never\n"
    "   invent record layouts, field positions or rule semantics that no observation\n"
    "   provides."
)


@dataclass
class ReasoningRunState:
    """Estado por run. Acotado y sin razonamiento privado."""

    enabled: bool = False
    mode: str = "off"
    shape: str = "SIMPLE_LOOKUP"
    is_complex: bool = False
    outcome: Any | None = None
    analysis_complete: bool = False
    blocked_direct_answers: int = 0
    company_context_sections: tuple[str, ...] = ()
    company_context_used: bool = False
    company_context_chars: int = 0
    company_context_truncated: bool = False
    memory_hits: int = 0
    error: str = ""

    @property
    def blocks_early_answer(self) -> bool:
        """Sólo bloquea si el plan sigue incompleto en una forma compleja."""
        return self.enabled and self.is_complex and not self.analysis_complete

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "shape": self.shape,
            "is_complex": self.is_complex,
            "analysis_complete": self.analysis_complete,
            "company_context_used": self.company_context_used,
            "company_context_sections": list(self.company_context_sections),
            "blocked_direct_answers": self.blocked_direct_answers,
            "error": self.error,
        }


def answer_rule(state: ReasoningRunState | None) -> str:
    """Regla del prompt según la forma detectada."""
    if state is not None and state.enabled and state.is_complex:
        conditions = _completion_conditions(state)
        if conditions:
            return (
                ANALYSIS_ANSWER_RULE
                + "\n   Required before answering:\n"
                + "\n".join(f"   - {item}" for item in conditions[:6])
            )
        return ANALYSIS_ANSWER_RULE
    return DEFAULT_ANSWER_RULE


def _completion_conditions(state: ReasoningRunState) -> tuple[str, ...]:
    outcome = state.outcome
    plan = getattr(outcome, "plan", None)
    return tuple(getattr(plan, "completion_conditions", ()) or ())


def should_block_direct_answer(
    state: ReasoningRunState | None, *, step_index: int, max_steps: int
) -> bool:
    """¿Debe rechazarse una respuesta directa todavía?

    Con presupuesto agotado se permite responder: la abstención estructurada la
    produce el bloque de workspace, no un loop infinito.
    """
    if state is None or not state.blocks_early_answer:
        return False
    if step_index >= max_steps - 1:
        return False
    state.blocked_direct_answers += 1
    return True


def workspace_block(state: ReasoningRunState | None) -> str:
    """§38: representación acotada del workspace para finalizar. Sin CoT."""
    if state is None or not state.enabled or state.outcome is None:
        return ""
    outcome = state.outcome
    lines: list[str] = ["## ANALYSIS WORKSPACE (hechos verificados, no razonamiento privado)"]
    trace = outcome.public_trace() if hasattr(outcome, "public_trace") else {}
    lines.append(
        "shape: {shape} | scenario_events: {events} | transitions: {confirmed}+{unresolved} "
        "| hypotheses: {tested} | analysis_complete: {complete}".format(
            shape=trace.get("shape", state.shape),
            events=trace.get("scenario_events", 0),
            confirmed=trace.get("transitions_confirmed", 0),
            unresolved=trace.get("transitions_unresolved", 0),
            tested=trace.get("hypotheses_tested", 0),
            complete=trace.get("analysis_complete", state.analysis_complete),
        )
    )
    workspace = getattr(outcome, "workspace", None)
    if workspace is not None:
        facts = getattr(workspace, "confirmed_facts", ())
        if facts:
            lines.append("CONFIRMED FACTS:")
            for fact in list(facts)[:6]:
                authority = f" [{fact.authority}]" if fact.authority else ""
                lines.append(f"- ({fact.status.value}{authority}) {fact.statement[:200]}")
        rules = getattr(workspace, "rules", ())
        if rules:
            lines.append("APPLICABLE RULES:")
            for rule in list(rules)[:4]:
                lines.append(f"- {rule.statement[:200]}")
        hypotheses = getattr(workspace, "hypotheses", None)
        if hypotheses is not None:
            lines.append("HYPOTHESES:")
            for hypothesis in getattr(hypotheses, "hypotheses", ())[:4]:
                lines.append(
                    f"- [{hypothesis.verdict.value}/{hypothesis.origin.value}] "
                    f"{hypothesis.statement[:160]}"
                )
        unknowns = getattr(workspace, "unknowns", ())
        if unknowns:
            lines.append("CRITICAL UNKNOWNS: " + "; ".join(str(u)[:120] for u in unknowns[:4]))
        authority = getattr(workspace, "source_authority", {})
        if authority:
            lines.append(
                "SOURCE AUTHORITY: "
                + "; ".join(f"{name}={level}" for name, level in list(authority.items())[:5])
            )
    completion = getattr(outcome, "completion", None)
    if completion is not None and not completion.complete:
        lines.append("INCOMPLETE ANALYSIS BLOCKERS: " + ", ".join(completion.blockers[:5]))
    blueprint = getattr(outcome, "blueprint", None)
    if blueprint is not None:
        lines.append(
            "Draft conclusion (verify against the evidence before using it): "
            + str(blueprint.conclusion)[:400]
        )
    return "\n".join(lines)[:4000]


def abstention_answer(state: ReasoningRunState | None) -> str:
    """Respuesta cuando el análisis quedó incompleto: abstención explícita."""
    if state is None or state.outcome is None:
        return ""
    outcome = state.outcome
    completion = getattr(outcome, "completion", None)
    lines = []
    blueprint = getattr(outcome, "blueprint", None)
    if blueprint is not None and blueprint.conclusion:
        lines.append(blueprint.conclusion)
    else:
        lines.append("No puedo determinarlo todavía con la evidencia disponible.")
    if completion is not None and completion.blockers:
        lines.append(
            "Falta verificar: " + ", ".join(completion.blockers[:5]) + "."
        )
    if blueprint is not None and blueprint.limitations:
        lines.append("Limitaciones: " + "; ".join(blueprint.limitations[:4]) + ".")
    return " ".join(lines)


def reasoning_steps(state: ReasoningRunState | None) -> list[dict]:
    """§47: pasos observables para "Ver flujo". Nunca razonamiento privado."""
    if state is None or not state.enabled:
        return []
    steps: list[dict] = [
        {
            "type": "reasoning_classification",
            "shape": state.shape,
            "is_complex": state.is_complex,
            "mode": state.mode,
        }
    ]
    if state.company_context_used:
        steps.append(
            {
                "type": "company_context",
                "sections": list(state.company_context_sections),
                "chars": state.company_context_chars,
                "truncated": state.company_context_truncated,
                "memory_hits": state.memory_hits,
            }
        )
    outcome = state.outcome
    if outcome is None:
        return steps
    plan = getattr(outcome, "plan", None)
    if plan is not None:
        steps.append(
            {
                "type": "reasoning_plan",
                "shape": plan.reasoning_shape.value,
                "operations": [step.operation for step in plan.steps],
                "status": plan.status.value,
            }
        )
    trace = outcome.public_trace() if hasattr(outcome, "public_trace") else {}
    if trace.get("activated"):
        for name, payload in (
            (
                "scenario_parse",
                {
                    "events": trace.get("scenario_events", 0),
                    "schemas_resolved": trace.get("schemas_resolved", 0),
                    "schemas_missing": trace.get("schemas_missing", 0),
                },
            ),
            (
                "state_reconstruction",
                {
                    "transitions_confirmed": trace.get("transitions_confirmed", 0),
                    "transitions_unresolved": trace.get("transitions_unresolved", 0),
                },
            ),
            (
                "hypothesis_test",
                {
                    "tested": trace.get("hypotheses_tested", 0),
                    "supported": trace.get("hypotheses_supported", 0),
                    "rejected": trace.get("hypotheses_rejected", 0),
                },
            ),
            (
                "analysis_completion",
                {"analysis_complete": trace.get("analysis_complete", False)},
            ),
        ):
            steps.append({"type": name, **payload})
    return steps


# ---------------------------------------------------------------------------
# Preparación por run
# ---------------------------------------------------------------------------


async def prepare_reasoning_state(
    *,
    organization_id: UUID | None,
    message: str,
    request_context: dict | None,
    agent_id: UUID | None = None,
) -> ReasoningRunState:
    """Compila contexto y razona una vez por run. Fail-soft total."""
    try:
        from src.intelligence.reasoning import wiring
    except Exception:  # noqa: BLE001 - sin paquete, runtime legacy
        return ReasoningRunState()

    try:
        settings = None
        try:
            from src.core.config import get_settings

            settings = get_settings()
        except Exception:  # noqa: BLE001
            settings = None
        mode = wiring.reasoning_mode(settings)
        if mode.value == "off" or not wiring.reasoning_active(settings):
            return ReasoningRunState(mode=mode.value)
        engine = wiring.evidence_reasoning_engine(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reasoning wiring unavailable", error=str(exc)[:150])
        return ReasoningRunState()

    state = ReasoningRunState(enabled=True, mode=mode.value)
    try:
        classification = await engine.classifier.classify(message)
        state.shape = classification.shape.value
        state.is_complex = classification.is_complex
        if not classification.is_complex:
            # Fast path: no se compila contexto ni se razona (§10).
            return state
        compiled = None
        existing = (request_context or {}).get(_COMPANY_CONTEXT_KEY)
        if existing:
            # El contexto explícito del workflow tiene prioridad: no se compila dos veces.
            compiled = existing
        elif organization_id is not None and engine.company_context_provider is not None:
            compiled = await engine._compile_company_context(  # noqa: SLF001
                organization_id, message, agent_id=agent_id, as_of=None
            )
        compiled_dict = compiled if isinstance(compiled, dict) else _dict_of(compiled)
        if compiled_dict:
            state.company_context_used = True
            state.company_context_sections = tuple(sorted(str(k) for k in compiled_dict))
            state.company_context_chars = len(str(compiled_dict))
            state.company_context_truncated = state.company_context_chars > 6000
            state.memory_hits = len(compiled_dict.get("memories") or ())
        outcome = await engine.reason(
            message,
            organization_id=organization_id,
            intent=getattr(classification, "intent", "general"),
            company_context=compiled_dict or None,
            scenario_text=message,
            mode=mode,
            agent_id=agent_id,
        )
        state.outcome = outcome
        trace = outcome.public_trace() if hasattr(outcome, "public_trace") else {}
        state.analysis_complete = bool(trace.get("analysis_complete"))
    except Exception as exc:  # noqa: BLE001
        state.error = str(exc)[:200]
        logger.warning("reasoning run state failed", error=state.error)
    return state


def _dict_of(value: object) -> dict:
    if value is None:
        return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def record_termination_skipped(
    state: ReasoningRunState | None, *, reason: str
) -> dict | None:
    """§37: el gate de terminación no puede parar con análisis incompleto."""
    if state is None or not state.blocks_early_answer:
        return None
    return {
        "type": "reasoning_incomplete",
        "detail": (
            "termination gate held: analysis incomplete "
            f"({reason}); shape={state.shape}"
        ),
        "shape": state.shape,
    }


__all__ = [
    "ANALYSIS_ANSWER_RULE",
    "DEFAULT_ANSWER_RULE",
    "ReasoningRunState",
    "abstention_answer",
    "answer_rule",
    "prepare_reasoning_state",
    "reasoning_steps",
    "record_termination_skipped",
    "should_block_direct_answer",
    "workspace_block",
]
