# =============================================================================
# Response Intelligence — wiring (una llamada, fail-soft, observable).
# =============================================================================
# Frontera fina: los llamadores (AgentRuntime, RAG orchestrator) no conocen JEV
# ni el catálogo de blueprints; piden el contrato y lo inyectan en el prompt.
#
# Rollout `RAG_RESPONSE_INTELLIGENCE_MODE`:
#   off     sin contrato (comportamiento previo)
#   rules   contrato determinista (forma elegida por reglas) — default
#   on      rules + pack JEV cuando dos formas quedan empatadas de verdad
#   canary  on para un porcentaje estable de requests
#
# El contrato NUNCA aporta hechos: sólo dice cómo explicarlos.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from uuid import UUID

from src.core.domain.response import ResponseContract, ResponseProfile
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.response.contract import compose_contract
from src.intelligence.response.presentation import PresentationPolicy
from src.intelligence.response.profile import profile_from_config
from src.intelligence.response.questions import (
    CompositionAnswers,
    read_composition_answers,
)
from src.intelligence.response.selector import (
    BlueprintSelection,
    select_blueprint,
    selection_from_jev,
)

logger = get_logger(__name__)

MODE_OFF = "off"
MODE_RULES = "rules"
MODE_ON = "on"
MODE_CANARY = "canary"
MODES = (MODE_OFF, MODE_RULES, MODE_ON, MODE_CANARY)

SOURCE_OFF = "off"
SOURCE_RULES = "rules"
SOURCE_JEV = "jev"


def normalize_mode(value: Any) -> str:
    mode = str(value or MODE_RULES).strip().lower()
    return mode if mode in MODES else MODE_RULES


def mode_from_settings() -> str:
    try:
        from src.core.config import get_settings

        return normalize_mode(getattr(get_settings(), "RAG_RESPONSE_INTELLIGENCE_MODE", MODE_RULES))
    except Exception:  # noqa: BLE001 — sin settings, determinista
        return MODE_RULES


def canary_allows(mode: str, request_id: UUID | None) -> bool:
    """En canary sólo una fracción estable usa JEV; el resto queda en rules."""
    if normalize_mode(mode) != MODE_CANARY:
        return True
    if request_id is None:
        return False
    try:
        from src.core.config import get_settings
        from src.decision.routing import in_canary

        percent = int(getattr(get_settings(), "RAG_RESPONSE_INTELLIGENCE_CANARY_PERCENTAGE", 0) or 0)
        return in_canary(request_id, percent)
    except Exception:  # noqa: BLE001
        return False


@dataclass
class ResponsePlan:
    """Contrato + cómo se decidió + qué preguntó JEV (si preguntó)."""

    contract: ResponseContract | None = None
    pack: Any = None
    mode: str = MODE_RULES
    source: str = SOURCE_RULES
    selection: BlueprintSelection | None = None
    answers: CompositionAnswers | None = None
    error: str = ""
    uncertain: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.contract is not None and self.source != SOURCE_OFF

    def facts(self) -> dict[str, Any]:
        contract = self.contract
        if contract is None:
            return {}
        return {
            "blueprint": contract.blueprint,
            "detail": contract.detail,
            "needs_example": "example" in contract.sections,
            "needs_table": bool(contract.formatting.get("table")),
            "needs_step_by_step": bool(contract.formatting.get("numbered_steps")),
            "citations_required": bool(contract.evidence.get("citations_required")),
            "hedging_required": contract.hedging_required,
            "decided_by": contract.decided_by,
        }

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "source": self.source,
        }
        if self.contract is not None:
            payload["contract"] = self.contract.to_public_dict()
        if self.selection is not None:
            payload["selection"] = self.selection.to_public_dict()
        if self.answers is not None and self.answers.answered:
            payload["jev_answers"] = self.answers.to_public_dict()
        if self.pack is not None:
            payload["jev"] = {
                "questions": self.pack.question_count,
                "latency_ms": round(float(getattr(self.pack, "latency_ms", 0.0)), 2),
                "model": getattr(self.pack, "model", ""),
                "cached": bool(getattr(self.pack, "cached", False)),
            }
        if self.uncertain:
            payload["uncertain"] = list(self.uncertain)[:6]
        if self.error:
            payload["error"] = self.error[:120]
        return payload


def signals_from_truth(
    *,
    reasoning: object | None = None,
    answerability: object | None = None,
    contradictions: Iterable[str] = (),
    source_conflict: bool = False,
    conflict_note: str = "",
) -> dict[str, Any]:
    """Señales de verdad que el contrato debe respetar (§19-§22).

    Nunca inventa: si no hay dato, devuelve vacío.
    """
    unresolved: list[str] = []
    missing: list[str] = []
    completion = getattr(reasoning, "completion", None)
    if completion is not None:
        if getattr(completion, "complete", None) is False:
            unresolved.extend(str(item) for item in getattr(completion, "reason_codes", ()) or ())
            missing.extend(str(item) for item in getattr(completion, "blockers", ()) or ())
    outcome = getattr(reasoning, "outcome", None)
    workspace = getattr(outcome, "workspace", None)
    if workspace is not None:
        missing.extend(str(item) for item in list(getattr(workspace, "unknowns", ()) or ())[:4])
    reasons = [str(item) for item in (getattr(answerability, "reason_codes", ()) or ())]
    for code in reasons:
        if code in {
            "ANALYSIS_INCOMPLETE",
            "STATE_UNRESOLVED",
            "HYPOTHESIS_UNRESOLVED",
            "INFERENCE_UNSUPPORTED",
            "TIMELINE_INCOMPLETE",
            "GRAPH_RELATION_UNCONFIRMED",
            "SCHEMA_REQUIRED",
        }:
            unresolved.append(code)
    if not source_conflict and "SOURCE_CONFLICT" in reasons:
        source_conflict = True
    contradictions_list = [str(item) for item in contradictions if str(item)][:4]
    if contradictions_list and not unresolved:
        unresolved.append("contradictions_open")
    return {
        "unresolved": tuple(dict.fromkeys(unresolved))[:6],
        "missing_information": tuple(dict.fromkeys([*missing, *contradictions_list]))[:6],
        "source_conflict": bool(source_conflict),
        "conflict_note": conflict_note[:200],
    }


async def compose_for_request(
    *,
    question: str,
    profile: ResponseProfile | None = None,
    config_json: Mapping[str, Any] | None = None,
    judge: Any = None,
    mode: str | None = None,
    request_id: UUID | None = None,
    organization_id: UUID | None = None,
    shape: str = "",
    intent: str = "",
    has_records: bool = False,
    has_data_rows: bool = False,
    is_followup: bool = False,
    unresolved: Iterable[str] = (),
    missing_information: Iterable[str] = (),
    source_conflict: bool = False,
    conflict_note: str = "",
    presentation: PresentationPolicy | None = None,
) -> ResponsePlan:
    """Compone el contrato de respuesta del request. Nunca lanza.

    `presentation` es el ritmo de lectura medido del caso (conceptos, capas,
    enumeraciones, cuánta evidencia se explica). Si no se pasa, se deriva de la
    pregunta: el comportamiento por defecto ya es legible sin configurar nada.
    """
    active_mode = normalize_mode(mode if mode is not None else mode_from_settings())
    if active_mode == MODE_OFF:
        return ResponsePlan(mode=active_mode, source=SOURCE_OFF)
    resolved_profile = profile or profile_from_config(config_json)
    selection = select_blueprint(
        question=question,
        intent=intent,
        shape=shape,
        has_records=has_records,
        has_data_rows=has_data_rows,
        is_followup=is_followup,
        preferred_blueprints=resolved_profile.preferred_blueprints,
    )
    plan = ResponsePlan(mode=active_mode, source=SOURCE_RULES, selection=selection)
    should_ask_jev = active_mode in (MODE_ON, MODE_CANARY) and canary_allows(active_mode, request_id)
    if should_ask_jev and judge is not None and selection.needs_jev:
        answers, pack = await _judge_composition(
            judge=judge,
            question=question,
            selection=selection,
            profile=resolved_profile,
            shape=shape,
            organization_id=organization_id,
            request_id=request_id,
        )
        if answers is not None:
            plan.answers = answers
            plan.pack = pack
            if answers.blueprint:
                plan.source = SOURCE_JEV
                selection = selection_from_jev(
                    choice=answers.blueprint,
                    confidence=answers.blueprint_confidence,
                    ambiguous=answers.blueprint_ambiguous,
                    runner_up=answers.blueprint_runner_up,
                    detail=answers.detail,
                    deterministic=selection,
                )
                plan.selection = selection
            plan.uncertain = list(answers.uncertain)
    plan.contract = compose_contract(
        question=question,
        profile=resolved_profile,
        selection=selection,
        answers=plan.answers,
        shape=shape,
        intent=intent,
        has_records=has_records,
        has_data_rows=has_data_rows,
        unresolved=unresolved,
        missing_information=missing_information,
        source_conflict=source_conflict,
        conflict_note=conflict_note,
        presentation=presentation,
    )
    return plan


async def _judge_composition(
    *,
    judge: Any,
    question: str,
    selection: BlueprintSelection,
    profile: ResponseProfile,
    shape: str,
    organization_id: UUID | None,
    request_id: UUID | None,
) -> tuple[CompositionAnswers | None, Any]:
    """UNA llamada batched para la forma de respuesta (§5). Fail-soft."""
    from src.decision.batch import build_response_composition_questions
    from src.decision.judgment import (
        PHASE_RESPONSE_COMPOSITION,
        JudgmentContext,
        call_phase_judge,
    )

    try:
        questions = build_response_composition_questions().to_jevy()
    except Exception as exc:  # noqa: BLE001
        logger.warning("response composition questions failed", error=str(exc)[:160])
        return None, None
    state: dict[str, Any] = {
        "user_request": (question or "")[:2000],
        "blueprint_options": [selection.blueprint, *selection.candidates][:6],
        "deterministic_candidates": list(selection.candidates)[:6],
        "audience": profile.audience,
        "technical_level": profile.technical_level,
        "reasoning_shape": shape,
        "conclusions_fingerprint": f"{selection.blueprint}:{shape}",
    }
    try:
        payload = await call_phase_judge(
            judge,
            phase=PHASE_RESPONSE_COMPOSITION,
            state=state,
            questions=questions,
            context=JudgmentContext(
                phase=PHASE_RESPONSE_COMPOSITION,
                organization_id=organization_id,
                request_id=request_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — el contrato determinista sigue
        logger.warning("response composition judge failed", error=str(exc)[:160])
        return None, None
    if not isinstance(payload, Mapping):
        return None, None
    return read_composition_answers(payload), _pack_of(payload)


def _pack_of(payload: Mapping[str, Any]) -> Any:
    try:
        from src.decision.preflight import build_pack, normalize_preflight_mode

        return build_pack(
            phase="response_composition",
            payload=payload,
            mode=normalize_preflight_mode(mode_from_settings()),
        )
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "MODE_CANARY",
    "MODE_OFF",
    "MODE_ON",
    "MODE_RULES",
    "MODES",
    "ResponsePlan",
    "SOURCE_JEV",
    "SOURCE_OFF",
    "SOURCE_RULES",
    "canary_allows",
    "compose_for_request",
    "mode_from_settings",
    "normalize_mode",
    "signals_from_truth",
]
