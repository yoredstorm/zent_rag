# =============================================================================
# JEV Preflight — juicio barato ANTES de pagar generación/razonamiento caro.
# =============================================================================
# Principio (docs/architecture/jev-preflight.md):
#
#   DETERMINISTIC FACTS → COMPANY CONTEXT → EVIDENCE → JEV JUDGMENT
#   → CODE COMPOSES DECISION → ONLY IF NECESSARY → EXPENSIVE LLM
#   → JEV / DETERMINISTIC VERIFICATION → ANSWER
#
# Lo que este módulo NO hace:
#   - no es fuente de hechos (los hechos vienen de evidence, SQL, knowledge,
#     Company Intelligence, reglas y memoria validada);
#   - no autoriza ni ejecuta acciones;
#   - no genera SQL ni respuestas;
#   - no pide a otro LLM que interprete las respuestas de JEV.
#
# Lo que sí hace: hacer las preguntas correctas, en batch, en el momento
# correcto, y COMPONER EN CÓDIGO la decisión que habilita (o no) la generación.
#
# Rollout: `RAG_JEV_PREFLIGHT_MODE` ∈ off | shadow | on | canary.
#   off     no se llama a JEV (comportamiento previo)
#   shadow  JEV decide qué HARÍA; la ejecución legacy manda
#   on      la decisión compuesta controla la generación
#   canary  igual que on para un porcentaje estable de requests
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.core.domain.decision import RiskLevel
from src.decision.confidence import (
    VERDICT_NO,
    VERDICT_UNCERTAIN,
    VERDICT_YES,
    JudgmentConfidencePolicy,
    JudgmentThresholds,
    default_policy,
)
from src.decision.distributions import (
    ChoiceReading,
    NoulReading,
    ScoreReading,
    read_choice,
    read_noul,
    read_score,
)
from src.decision.judgment import (
    PHASE_POST_GENERATION,
    PHASE_POST_RECONSTRUCTION,
    PHASE_PRE_GENERATION,
    PHASE_PRE_REASONING,
)
from src.decision.registry import get_definition

# -----------------------------------------------------------------------------
# Acciones y tiers (§17, §19)
# -----------------------------------------------------------------------------

ACTION_GENERATE = "generate_answer"
ACTION_RETRIEVE = "retrieve_more"
ACTION_RECONSTRUCT = "reconstruct_more"
ACTION_ASK_USER = "ask_user"
ACTION_ABSTAIN = "abstain"
ACTION_DETERMINISTIC = "deterministic_answer"
ACTIONS = (
    ACTION_GENERATE,
    ACTION_RETRIEVE,
    ACTION_RECONSTRUCT,
    ACTION_ASK_USER,
    ACTION_ABSTAIN,
    ACTION_DETERMINISTIC,
)

TIER_DETERMINISTIC = "deterministic"
TIER_SMALL = "small"
TIER_STANDARD = "standard"
TIER_REASONING = "reasoning"
TIERS = (TIER_DETERMINISTIC, TIER_SMALL, TIER_STANDARD, TIER_REASONING)

#: Tier que exige un modelo caro. `small`/`deterministic` no.
EXPENSIVE_TIERS = (TIER_STANDARD, TIER_REASONING)

DECIDED_BY_JEV = "jev"
DECIDED_BY_DETERMINISTIC = "deterministic"
DECIDED_BY_LEGACY = "legacy"

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"
MODE_CANARY = "canary"
PREFLIGHT_MODES = (MODE_OFF, MODE_SHADOW, MODE_ON, MODE_CANARY)


def normalize_preflight_mode(value: Any) -> str:
    mode = str(value or MODE_OFF).strip().lower()
    return mode if mode in PREFLIGHT_MODES else MODE_OFF


def preflight_controls_answer(mode: str) -> bool:
    """shadow/off observan o no hacen nada; on/canary controlan la ejecución."""
    return normalize_preflight_mode(mode) in (MODE_ON, MODE_CANARY)


def preflight_active(mode: str) -> bool:
    return normalize_preflight_mode(mode) != MODE_OFF


# -----------------------------------------------------------------------------
# Estado compartido por pack (acotado: cada pregunta cuesta tokens, §47)
# -----------------------------------------------------------------------------

MAX_QUESTIONS_PER_PACK = 16
MAX_STATE_CHARS = 240
MAX_STATE_ITEMS = 8


def clip(text: Any, limit: int = MAX_STATE_CHARS) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


def preview(items: Iterable[Any] | None, limit: int = MAX_STATE_ITEMS) -> list[str]:
    out: list[str] = []
    for item in list(items or [])[:limit]:
        out.append(clip(item))
    return out


def counts(values: Mapping[str, Any] | None) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in list((values or {}).items())[:12]
        if isinstance(value, (int, float))
    }


# -----------------------------------------------------------------------------
# Juicios: lectura + decisión + efecto
# -----------------------------------------------------------------------------


@dataclass
class QuestionJudgment:
    """Un juicio con su efecto. El efecto vive en el backend, traducido en UI."""

    id: str
    phase: str
    type: str
    version: int = 0
    risk: str = RiskLevel.LOW.value
    decision: str = ""
    confidence: float | None = None
    value: float | None = None
    certainty: float | None = None
    ambiguous: bool = False
    effect: str | None = None
    distribution: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "version": self.version,
            "decision": self.decision,
        }
        if self.confidence is not None:
            payload["confidence"] = round(float(self.confidence), 4)
        if self.value is not None:
            payload["value"] = round(float(self.value), 4)
        if self.certainty is not None:
            payload["certainty"] = round(float(self.certainty), 4)
        if self.ambiguous:
            payload["ambiguous"] = True
        if self.effect:
            payload["effect"] = self.effect
        if self.distribution:
            payload["distribution"] = self.distribution
        return payload


def _definition_meta(question_id: str, phase: str) -> dict[str, Any]:
    definition = get_definition(question_id, phase=phase)
    if definition is None:
        return {"version": 0, "risk": RiskLevel.LOW.value}
    return {"version": definition.version, "risk": definition.risk}


def _judgment(
    *,
    phase: str,
    question_id: str,
    answer: Mapping[str, Any] | None,
    thresholds: JudgmentThresholds,
) -> QuestionJudgment | None:
    raw = answer if isinstance(answer, Mapping) else None
    if raw is None:
        return None
    meta = _definition_meta(question_id, phase)
    kind = str(raw.get("type") or "").strip().lower()
    if not kind:
        if "choice" in raw:
            kind = "choice"
        elif "score" in raw:
            kind = "score"
        elif "noul" in raw:
            kind = "noul"

    if kind == "choice":
        reading: ChoiceReading | None = read_choice(
            raw,
            ambiguity_margin=thresholds.ambiguity_margin,
            high_confidence=thresholds.choice,
        )
        if reading is None:
            return None
        return QuestionJudgment(
            id=question_id,
            phase=phase,
            type="choice",
            decision=reading.choice,
            confidence=reading.confidence,
            ambiguous=reading.ambiguous,
            effect=choice_effect(phase, question_id, reading.choice, certain=reading.certain),
            distribution=reading.to_public_dict(),
            **meta,
        )

    if kind == "score":
        score_reading: ScoreReading | None = read_score(
            raw, high_confidence=thresholds.score
        )
        if score_reading is None:
            return None
        return QuestionJudgment(
            id=question_id,
            phase=phase,
            type="score",
            decision=str(score_reading.level or ""),
            value=score_reading.score,
            confidence=score_reading.confidence,
            effect=score_effect(phase, question_id, score_reading),
            distribution=score_reading.to_public_dict(),
            **meta,
        )

    reading_noul: NoulReading | None = read_noul(raw, default=None)
    if reading_noul is None:
        return None
    verdict = thresholds.verdict(reading_noul)
    return QuestionJudgment(
        id=question_id,
        phase=phase,
        type="noul",
        decision=verdict,
        value=reading_noul.value,
        certainty=reading_noul.certainty,
        effect=noul_effect(phase, question_id, verdict),
        distribution=reading_noul.to_public_dict(),
        **meta,
    )


# -----------------------------------------------------------------------------
# Efectos (§40): sólo cuando el juicio cambió algo
# -----------------------------------------------------------------------------


def noul_effect(phase: str, question_id: str, verdict: str) -> str | None:
    yes = verdict == VERDICT_YES
    no = verdict == VERDICT_NO
    if phase == PHASE_PRE_REASONING:
        if question_id == "simple_lookup_sufficient" and yes:
            return "fast_path_selected"
        if question_id == "needs_multiple_evidence" and yes:
            return "multi_evidence_required"
        if question_id == "needs_timeline" and yes:
            return "timeline_required"
        if question_id == "needs_state_reconstruction" and yes:
            return "state_reconstruction_activated"
        if question_id == "needs_graph" and yes:
            return "graph_traversal_activated"
        if question_id == "needs_hypothesis_testing" and yes:
            return "hypothesis_testing_activated"
        if question_id == "needs_structured_data" and yes:
            return "structured_lookup_required"
        if question_id == "needs_private_knowledge" and yes:
            return "retrieval_required"
        return None
    if phase == PHASE_POST_RECONSTRUCTION:
        if question_id == "critical_transition_missing" and yes:
            return "state_chain_incomplete"
        if question_id == "timeline_coherent" and no:
            return "timeline_conflict"
        if question_id == "hypothesis_user_contradicted" and yes:
            return "user_hypothesis_rejected"
        if question_id == "hypothesis_user_supported" and yes:
            return "user_hypothesis_supported"
        if question_id == "alternative_hypothesis_supported" and yes:
            return "alternative_explanation_active"
        if question_id == "inference_possible" and no:
            return "inference_blocked"
        if question_id == "critical_unknown_remaining" and yes:
            return "unknown_blocks_conclusion"
        if question_id.endswith("_supported") and yes:
            return "hypothesis_supported"
        if question_id.endswith("_contradicted") and yes:
            return "hypothesis_rejected"
        return None
    if phase == PHASE_PRE_GENERATION:
        if question_id == "critical_fact_missing" and yes:
            return "critical_fact_missing"
        if question_id == "critical_conflict_unresolved" and yes:
            return "critical_conflict"
        if question_id == "analysis_complete" and no:
            return "analysis_incomplete"
        if question_id == "inference_supported" and no:
            return "inference_unsupported"
        if question_id == "expensive_llm_needed" and no:
            return "expensive_model_avoided"
        if question_id == "needs_complex_reasoning_model" and no:
            return "expensive_model_avoided"
        if question_id == "simple_deterministic_answer_possible" and yes:
            return "deterministic_answer_possible"
        return None
    if phase == PHASE_POST_GENERATION:
        if question_id == "answer_grounded" and no:
            return "ungrounded_answer"
        if question_id == "answer_contains_unsupported_conclusion" and yes:
            return "unsupported_conclusion"
        if question_id == "answer_overstates_uncertainty" and yes:
            return "overstated_certainty"
        if question_id == "answer_ignores_material_conflict" and yes:
            return "conflict_not_disclosed"
        if question_id == "answer_complete" and no:
            return "answer_incomplete"
        return None
    return None


def choice_effect(phase: str, question_id: str, choice: str, *, certain: bool) -> str | None:
    if not certain:
        return None
    if phase == PHASE_PRE_GENERATION:
        if question_id == "next_action":
            return {
                ACTION_GENERATE: "generation_allowed",
                ACTION_RETRIEVE: "retrieval_round_requested",
                ACTION_RECONSTRUCT: "reconstruction_requested",
                ACTION_ASK_USER: "user_input_requested",
                ACTION_ABSTAIN: "generation_blocked",
                ACTION_DETERMINISTIC: "generation_skipped",
            }.get(choice)
        if question_id == "generation_tier":
            return f"generation_tier_{choice}"
    if phase == PHASE_PRE_REASONING and question_id == "reasoning_shape":
        return "reasoning_shape_selected"
    if phase == PHASE_PRE_REASONING and question_id == "preferred_capability":
        return "source_family_selected"
    if phase == PHASE_POST_GENERATION and question_id == "final_action":
        return {
            "approve": "answer_approved",
            "revise": "revision_requested",
            "abstain": "answer_abstained",
        }.get(choice)
    return None


def score_effect(phase: str, question_id: str, reading: ScoreReading) -> str | None:
    if phase == PHASE_PRE_GENERATION:
        if question_id == "risk_of_wrong_answer" and reading.score <= 1.0:
            return "low_risk_of_wrong_answer"
        if question_id == "answer_readiness" and reading.score >= 2.0 and reading.certain:
            return "answer_ready"
    if phase == PHASE_POST_RECONSTRUCTION:
        if question_id == "scenario_completeness" and reading.score < 1.0:
            return "scenario_incomplete"
    return None


# -----------------------------------------------------------------------------
# Pack
# -----------------------------------------------------------------------------


@dataclass
class JudgmentPack:
    """Resultado de una fase: una llamada, N juicios, efectos y costo."""

    phase: str
    mode: str = MODE_OFF
    ok: bool = False
    skipped_reason: str = ""
    questions: list[QuestionJudgment] = field(default_factory=list)
    latency_ms: float = 0.0
    cached: bool = False
    error: bool = False
    model: str = ""
    tokens: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def question_count(self) -> int:
        return len(self.questions)

    def get(self, question_id: str) -> QuestionJudgment | None:
        for question in self.questions:
            if question.id == question_id:
                return question
        return None

    def answer(self, question_id: str) -> dict[str, Any] | None:
        value = self.raw.get(question_id)
        return dict(value) if isinstance(value, Mapping) else None

    def noul(self, question_id: str, thresholds: JudgmentThresholds | None = None) -> NoulReading | None:
        answer = self.answer(question_id)
        if answer is None:
            return None
        policy = thresholds
        if policy is None:
            definition = get_definition(question_id, phase=self.phase)
            policy = default_policy().for_question(
                question_id,
                phase=self.phase,
                risk=definition.risk if definition else RiskLevel.LOW.value,
                threshold_key=definition.threshold_key if definition else "",
            )
        return policy.read(answer)

    def choice(self, question_id: str) -> ChoiceReading | None:
        return read_choice(self.answer(question_id))

    def score(self, question_id: str) -> ScoreReading | None:
        return read_score(self.answer(question_id))

    def effects(self) -> list[str]:
        seen: list[str] = []
        for question in self.questions:
            if question.effect and question.effect not in seen:
                seen.append(question.effect)
        return seen

    def uncertain_ids(self) -> list[str]:
        """Juicios sin veredicto claro: incertidumbre es información (§26)."""
        return [
            question.id
            for question in self.questions
            if question.decision == VERDICT_UNCERTAIN or question.ambiguous
        ]

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "phase": self.phase,
            "mode": self.mode,
            "status": "skipped" if self.skipped_reason else ("error" if self.error else "ok"),
            "question_count": self.question_count,
            "questions": [question.to_public_dict() for question in self.questions],
        }
        if self.skipped_reason:
            payload["summary"] = self.skipped_reason
        if self.latency_ms:
            payload["latency_ms"] = round(float(self.latency_ms), 2)
        if self.cached:
            payload["cached"] = True
        if self.model:
            payload["model"] = self.model
        if self.tokens:
            payload["tokens"] = dict(self.tokens)
        if self.cost:
            payload["cost_usd"] = round(float(self.cost), 6)
        effects = self.effects()
        if effects:
            payload["effects"] = effects
        return payload


def build_pack(
    *,
    phase: str,
    payload: Mapping[str, Any] | None,
    mode: str,
    policy: JudgmentConfidencePolicy | None = None,
    latency_ms: float = 0.0,
    cached: bool = False,
    error: bool = False,
) -> JudgmentPack:
    """Convierte el payload de JEV en juicios con decisión y efecto."""
    active_policy = policy or default_policy()
    pack = JudgmentPack(phase=phase, mode=mode)
    if not isinstance(payload, Mapping):
        pack.error = error or True
        return pack
    answers = payload.get("answers") if isinstance(payload.get("answers"), Mapping) else payload
    if not isinstance(answers, Mapping):
        pack.error = True
        return pack
    pack.ok = True
    pack.cached = bool(cached or payload.get("deduped"))
    pack.model = str(payload.get("model") or "")
    pack.latency_ms = float(payload.get("latency_ms") or latency_ms or 0.0)
    cost = payload.get("estimated_cost")
    if isinstance(cost, (int, float)):
        pack.cost = float(cost)
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        pack.tokens = {
            "input": int(usage.get("input_tokens") or 0),
            "output": int(usage.get("output_tokens") or 0),
        }
    ordered: list[str] = []
    definitions = _definitions_for_phase(phase)
    for definition in definitions:
        if definition.id not in answers or definition.id in ordered:
            continue
        ordered.append(definition.id)
    for key in answers:
        if str(key) not in ordered:
            ordered.append(str(key))
    for question_id in ordered[: MAX_QUESTIONS_PER_PACK * 2]:
        raw = answers.get(question_id)
        if not isinstance(raw, Mapping):
            continue
        definition = get_definition(question_id, phase=phase)
        thresholds = active_policy.for_question(
            question_id,
            phase=phase,
            risk=definition.risk if definition is not None else RiskLevel.LOW.value,
            threshold_key=definition.threshold_key if definition is not None else "",
        )
        judgment = _judgment(
            phase=phase, question_id=question_id, answer=raw, thresholds=thresholds
        )
        if judgment is not None:
            pack.questions.append(judgment)
        pack.raw[question_id] = dict(raw)
    return pack


def _definitions_for_phase(phase: str):
    from src.decision.registry import default_registry

    return default_registry().for_phase(phase)


def skipped_pack(*, phase: str, mode: str, reason: str) -> JudgmentPack:
    return JudgmentPack(phase=phase, mode=mode, ok=False, skipped_reason=reason)


# -----------------------------------------------------------------------------
# PreLLMReadiness (§27, §28)
# -----------------------------------------------------------------------------

READINESS_OK = "ok"
READINESS_WARN = "warn"
READINESS_BLOCKED = "blocked"
READINESS_UNKNOWN = "unknown"

ROW_EVIDENCE = "evidence"
ROW_SCENARIO = "scenario"
ROW_STATE = "state"
ROW_HYPOTHESIS = "hypothesis"
ROW_INFERENCE = "inference"
ROW_CONFLICTS = "conflicts"
ROW_ANSWERABILITY = "answerability"
ROW_LLM = "llm"
ROW_ORDER = (
    ROW_EVIDENCE,
    ROW_SCENARIO,
    ROW_STATE,
    ROW_HYPOTHESIS,
    ROW_INFERENCE,
    ROW_CONFLICTS,
    ROW_ANSWERABILITY,
    ROW_LLM,
)


@dataclass
class ReadinessRow:
    """Una fila de la matriz: no dice "verdad", dice preparación."""

    key: str
    state: str = READINESS_UNKNOWN
    confidence: float | None = None
    detail: str | None = None
    source: str = DECIDED_BY_DETERMINISTIC

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": self.key, "state": self.state, "source": self.source}
        if self.confidence is not None:
            payload["confidence"] = round(float(self.confidence), 4)
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class PreLLMReadiness:
    """Matriz de preparación previa al LLM. Calculada en código (§27)."""

    rows: list[ReadinessRow] = field(default_factory=list)

    def set(self, row: ReadinessRow) -> None:
        self.rows = [current for current in self.rows if current.key != row.key]
        self.rows.append(row)

    def get(self, key: str) -> ReadinessRow | None:
        for row in self.rows:
            if row.key == key:
                return row
        return None

    @property
    def blocked(self) -> bool:
        return any(row.state == READINESS_BLOCKED for row in self.rows)

    @property
    def complete(self) -> bool:
        return all(
            row.state in (READINESS_OK, READINESS_WARN)
            for row in self.rows
            if row.key in ROW_ORDER
        )

    def ordered(self) -> list[ReadinessRow]:
        position = {key: index for index, key in enumerate(ROW_ORDER)}
        return sorted(self.rows, key=lambda row: position.get(row.key, 99))

    def to_public_dict(self) -> dict[str, Any]:
        return {"rows": [row.to_public_dict() for row in self.ordered()]}


# -----------------------------------------------------------------------------
# Señales determinísticas (código, no JEV)
# -----------------------------------------------------------------------------


@dataclass
class DeterministicSignals:
    """Lo que el código ya sabe sin pedirle nada a JEV.

    Nunca se inventa: un campo `None` es "no disponible", no un `False`.
    """

    answerable: bool | None = None
    answerability_reasons: tuple[str, ...] = ()
    source_conflict: bool = False
    evidence_sufficient: bool | None = None
    evidence_score: float | None = None
    analysis_complete: bool | None = None
    analysis_blockers: tuple[str, ...] = ()
    hypothesis_unresolved: int | None = None
    inference_supported: bool | None = None
    critical_unknowns: int | None = None
    retrieval_rounds: int = 0
    retrieval_budget_left: int = 0
    reasoning_shape: str = ""
    cheap_path: bool = False
    prefer_small_model: bool = False
    legacy_tier: str = TIER_STANDARD

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key in (
            "answerable",
            "source_conflict",
            "evidence_sufficient",
            "evidence_score",
            "analysis_complete",
            "hypothesis_unresolved",
            "inference_supported",
            "critical_unknowns",
            "retrieval_rounds",
            "retrieval_budget_left",
            "reasoning_shape",
            "legacy_tier",
        ):
            value = getattr(self, key)
            if value not in (None, "", False):
                payload[key] = value
        if self.answerability_reasons:
            payload["answerability_reasons"] = list(self.answerability_reasons)
        if self.analysis_blockers:
            payload["analysis_blockers"] = list(self.analysis_blockers)
        return payload


# -----------------------------------------------------------------------------
# Decisión de escalado (§16, §17, §18, §19, §20)
# -----------------------------------------------------------------------------


@dataclass
class EscalationDecision:
    """El código compone la decisión. JEV no la toma sola (§8)."""

    action: str = ACTION_GENERATE
    tier: str = TIER_STANDARD
    allow_generation: bool = True
    expensive_model_allowed: bool = True
    reasons: list[str] = field(default_factory=list)
    uncertain_critical: list[str] = field(default_factory=list)
    unsatisfied: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    confidence: float = 0.0
    decided_by: str = DECIDED_BY_LEGACY
    mode: str = MODE_OFF
    applied: bool = False
    source: str = "preflight"

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": self.action,
            "tier": self.tier,
            "allow_generation": bool(self.allow_generation),
            "decided_by": self.decided_by,
            "mode": self.mode,
            "applied": bool(self.applied),
        }
        if self.reasons:
            payload["reasons"] = list(self.reasons)
        if self.unsatisfied:
            payload["unsatisfied"] = list(self.unsatisfied)
        if self.uncertain_critical:
            payload["uncertain_critical"] = list(self.uncertain_critical)
        if self.conflicts:
            payload["conflicts"] = list(self.conflicts)
        if self.confidence:
            payload["confidence"] = round(float(self.confidence), 4)
        payload["expensive_model_allowed"] = bool(self.expensive_model_allowed)
        return payload


#: Condiciones del gate (§17): todas deben cumplirse para generar.
GATE_CONDITIONS = (
    "answerable_from_current_evidence",
    "analysis_complete",
    "critical_fact_missing",
    "critical_conflict_unresolved",
    "inference_supported",
)

#: Preguntas cuyo resultado incierto se registra como incertidumbre material.
CRITICAL_QUESTIONS = (
    "answerable_from_current_evidence",
    "analysis_complete",
    "critical_fact_missing",
    "critical_conflict_unresolved",
    "inference_supported",
    "next_action",
)


@dataclass(frozen=True)
class LLMEscalationPolicy:
    """Política central: cuándo se paga generación cara y de qué nivel (§17-§20).

    Dos señales, nunca una sola: una condición insatisfecha sólo BLOQUEA cuando
    el código también ve un problema (answerability, evidencia o análisis). Si
    JEV es el único que dice "no está listo", se registra el desacuerdo y no se
    cambia la ejecución.
    """

    policy: JudgmentConfidencePolicy = field(default_factory=default_policy)
    require_next_action: bool = True
    #: Respuesta compuesta en código sólo si la configuración lo habilita (§18).
    allow_deterministic: bool = False
    allow_small: bool = True
    min_signals: int = 1
    budget_may_downgrade: bool = True
    #: Sin ninguna señal del código, bloquear exige un juicio concluyente y
    #: múltiple: un solo cruce de umbral nunca detiene la generación (§26).
    no_signal_min_confidence: float = 0.70
    no_signal_min_unsatisfied: int = 2

    def thresholds_for(self, question_id: str, *, phase: str = PHASE_PRE_GENERATION) -> JudgmentThresholds:
        definition = get_definition(question_id, phase=phase)
        return self.policy.for_question(
            question_id,
            phase=phase,
            risk=definition.risk if definition is not None else RiskLevel.HIGH.value,
            threshold_key=definition.threshold_key if definition is not None else "",
        )

    def evaluate(
        self,
        *,
        pack: JudgmentPack | None,
        signals: DeterministicSignals,
        mode: str = MODE_ON,
    ) -> EscalationDecision:
        decision = EscalationDecision(
            mode=mode,
            decided_by=DECIDED_BY_DETERMINISTIC,
            allow_generation=True,
            tier=signals.legacy_tier or TIER_STANDARD,
        )
        if pack is None or not pack.ok:
            decision.reasons.append("jev_unavailable")
            return decision

        decision.decided_by = DECIDED_BY_JEV
        verdicts: dict[str, str] = {}
        for question_id in GATE_CONDITIONS:
            verdicts[question_id] = self._verdict(pack, question_id)
            if verdicts[question_id] == VERDICT_UNCERTAIN:
                decision.uncertain_critical.append(question_id)

        unsatisfied = [
            question_id
            for question_id, verdict in verdicts.items()
            if not self._satisfied(question_id, verdict)
        ]
        decision.unsatisfied = unsatisfied
        next_action = pack.choice("next_action")
        if next_action is not None and next_action.ambiguous:
            decision.conflicts.append("next_action_ambiguous")
            if "next_action" not in decision.uncertain_critical:
                decision.uncertain_critical.append("next_action")
        elif next_action is not None:
            tier_from_action = None
            if next_action.choice in ACTIONS:
                tier_from_action = next_action.choice
            if (
                tier_from_action
                and self.require_next_action
                and next_action.choice != ACTION_GENERATE
                and next_action.certain
            ):
                decision.action = tier_from_action

        gate_ok = not unsatisfied
        decision.confidence = self._confidence(pack, verdicts)
        if not gate_ok:
            decision.reasons.append("gate_not_satisfied")
            decision.reasons.extend(f"unsatisfied_{question}" for question in unsatisfied)

        # Segunda señal determinística: sólo bloquea si el código también duda.
        deterministic_verdict = self._deterministic_blocked(signals)
        if not gate_ok and deterministic_verdict is True:
            decision.allow_generation = False
            decision.action = self._fallback_action(decision, signals)
        elif not gate_ok and deterministic_verdict is False:
            decision.conflicts.append("jev_only_signal")
            decision.reasons.append("deterministic_signals_ok")
            gate_ok = True
            decision.action = ACTION_GENERATE
        elif not gate_ok:
            # El código no tiene señales para confirmar ni para desmentir. Sin
            # segunda señal, bloquear exige un juicio concluyente y múltiple.
            if (
                len(unsatisfied) >= int(self.no_signal_min_unsatisfied)
                and not decision.uncertain_critical
                and decision.confidence >= float(self.no_signal_min_confidence)
            ):
                decision.reasons.append("judgment_only_signal_decisive")
                decision.allow_generation = False
                decision.action = self._fallback_action(decision, signals)
            else:
                decision.conflicts.append("jev_only_signal")
                decision.reasons.append("no_second_signal")
                gate_ok = True
                decision.action = ACTION_GENERATE

        if gate_ok and decision.action == ACTION_GENERATE:
            decision.tier = self._tier(pack, signals, decision)
            if decision.tier == TIER_DETERMINISTIC:
                decision.action = ACTION_DETERMINISTIC
        elif gate_ok and decision.action == ACTION_DETERMINISTIC:
            decision.tier = TIER_DETERMINISTIC
        elif gate_ok and decision.action in (ACTION_RETRIEVE, ACTION_RECONSTRUCT):
            decision.reasons.append("more_analysis_requested")

        # Invariante: sólo la acción de generar habilita la generación.
        decision.allow_generation = decision.action == ACTION_GENERATE
        decision.expensive_model_allowed = (
            decision.allow_generation and decision.tier in EXPENSIVE_TIERS
        )
        if decision.tier == TIER_SMALL and signals.legacy_tier in EXPENSIVE_TIERS:
            decision.reasons.append("cheaper_tier_sufficient")
        if not decision.allow_generation:
            decision.reasons.append(f"action_{decision.action}")
        return decision

    # -- internos -------------------------------------------------------------

    def _verdict(self, pack: JudgmentPack, question_id: str) -> str:
        thresholds = self.thresholds_for(question_id)
        reading = pack.noul(question_id, thresholds)
        if reading is None:
            return VERDICT_UNCERTAIN
        return thresholds.verdict(reading)

    @staticmethod
    def _satisfied(question_id: str, verdict: str) -> bool:
        expected_yes = question_id not in (
            "critical_fact_missing",
            "critical_conflict_unresolved",
        )
        if expected_yes:
            return verdict == VERDICT_YES
        return verdict == VERDICT_NO

    def _deterministic_blocked(self, signals: DeterministicSignals) -> bool | None:
        """True bloquea, False confirma que está bien, None no hay señal.

        `None` es distinto de `False`: significa que el código no puede opinar, y
        en ese caso sólo un juicio concluyente y múltiple puede bloquear.
        """
        checks = 0
        if signals.answerable is not None:
            checks += 1
            if not signals.answerable:
                return True
        if signals.evidence_sufficient is not None:
            checks += 1
            if not signals.evidence_sufficient:
                return True
        if signals.analysis_complete is not None:
            checks += 1
            if not signals.analysis_complete:
                return True
        if signals.source_conflict:
            return True
        if checks < max(1, int(self.min_signals)):
            return None
        return False

    def _fallback_action(
        self, decision: EscalationDecision, signals: DeterministicSignals
    ) -> str:
        if decision.action in (
            ACTION_RETRIEVE,
            ACTION_RECONSTRUCT,
            ACTION_ASK_USER,
            ACTION_ABSTAIN,
            ACTION_DETERMINISTIC,
        ):
            return decision.action
        if "critical_fact_missing" in decision.unsatisfied:
            return ACTION_RETRIEVE if signals.retrieval_budget_left > 0 else ACTION_ABSTAIN
        if "analysis_complete" in decision.unsatisfied:
            return (
                ACTION_RECONSTRUCT
                if signals.retrieval_budget_left > 0
                else ACTION_ABSTAIN
            )
        if "critical_conflict_unresolved" in decision.unsatisfied:
            return ACTION_ABSTAIN
        if "inference_supported" in decision.unsatisfied:
            return ACTION_ABSTAIN
        if "answerable_from_current_evidence" in decision.unsatisfied:
            return ACTION_RETRIEVE if signals.retrieval_budget_left > 0 else ACTION_ABSTAIN
        # Sólo el código dudó: se resuelve con la señal determinística disponible.
        if signals.evidence_sufficient is False:
            return ACTION_RETRIEVE if signals.retrieval_budget_left > 0 else ACTION_ABSTAIN
        if signals.analysis_complete is False:
            return (
                ACTION_RECONSTRUCT if signals.retrieval_budget_left > 0 else ACTION_ABSTAIN
            )
        if signals.source_conflict or signals.answerable is False:
            return ACTION_RETRIEVE if signals.retrieval_budget_left > 0 else ACTION_ABSTAIN
        return ACTION_GENERATE

    def _tier(
        self,
        pack: JudgmentPack,
        signals: DeterministicSignals,
        decision: EscalationDecision,
    ) -> str:
        deterministic_possible = self._verdict(
            pack, "simple_deterministic_answer_possible"
        ) == VERDICT_YES
        if deterministic_possible and self.allow_deterministic:
            decision.reasons.append("deterministic_answer_possible")
            return TIER_DETERMINISTIC
        complex_model = self._verdict(pack, "needs_complex_reasoning_model") == VERDICT_YES
        expensive_needed = self._verdict(pack, "expensive_llm_needed")
        tier_choice = pack.choice("generation_tier")
        if complex_model or expensive_needed == VERDICT_YES:
            if tier_choice is not None and tier_choice.choice == TIER_REASONING:
                return TIER_REASONING
            return TIER_REASONING if complex_model else TIER_STANDARD
        if tier_choice is not None and tier_choice.certain and tier_choice.choice in TIERS:
            tier = tier_choice.choice
        elif self.allow_small:
            tier = TIER_SMALL
        else:
            tier = TIER_STANDARD
        if (
            self.budget_may_downgrade
            and signals.prefer_small_model
            and tier in EXPENSIVE_TIERS
        ):
            # El presupuesto sólo baja el tier cuando el juicio lo permite:
            # nunca se degrada seguridad para ahorrar (§20).
            decision.reasons.append("budget_prefers_small")
            tier = TIER_SMALL
        return tier

    def _confidence(self, pack: JudgmentPack, verdicts: Mapping[str, str]) -> float:
        values = [
            float(question.confidence)
            for question in pack.questions
            if question.confidence is not None and question.id in GATE_CONDITIONS
        ]
        values.extend(
            float(question.certainty)
            for question in pack.questions
            if question.certainty is not None and question.id in GATE_CONDITIONS
        )
        if not values:
            return 0.0
        return round(min(values), 4)


def _tier_rank(tier: str) -> int:
    try:
        return TIERS.index(tier)
    except ValueError:
        return len(TIERS)


def tier_index(tier: str) -> int:
    """Posición del tier en la escala (deterministic < small < standard < reasoning)."""
    return _tier_rank(tier)


# -----------------------------------------------------------------------------
# Composición de las otras fases (§8)
# -----------------------------------------------------------------------------


@dataclass
class PreReasoningDecision:
    """Lo que el código compone del pack PRE_REASONING (§8)."""

    shape: str = ""
    shape_confidence: float = 0.0
    shape_ambiguous: bool = False
    shape_runner_up: str = ""
    source_family: str = ""
    source_family_confidence: float = 0.0
    complexity: float = 0.0
    complexity_level: str = ""
    needs: dict[str, bool] = field(default_factory=dict)
    simple_fast_path: bool = False
    uncertain: list[str] = field(default_factory=list)
    decided_by: str = DECIDED_BY_LEGACY

    def requires(self, key: str) -> bool:
        return bool(self.needs.get(key))

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "shape": self.shape,
            "decided_by": self.decided_by,
            "simple_fast_path": bool(self.simple_fast_path),
        }
        if self.shape_confidence:
            payload["shape_confidence"] = round(self.shape_confidence, 4)
        if self.shape_ambiguous:
            payload["shape_ambiguous"] = True
        if self.shape_runner_up:
            payload["shape_runner_up"] = self.shape_runner_up
        if self.source_family:
            payload["source_family"] = self.source_family
        if self.complexity:
            payload["complexity"] = round(self.complexity, 4)
        if self.complexity_level:
            payload["complexity_level"] = self.complexity_level
        if self.needs:
            payload["needs"] = {key: value for key, value in self.needs.items() if value}
        if self.uncertain:
            payload["uncertain"] = list(self.uncertain)
        return payload


NEED_QUESTIONS: dict[str, str] = {
    "private_knowledge": "needs_private_knowledge",
    "multiple_evidence": "needs_multiple_evidence",
    "structured_data": "needs_structured_data",
    "graph": "needs_graph",
    "timeline": "needs_timeline",
    "state_reconstruction": "needs_state_reconstruction",
    "hypothesis_testing": "needs_hypothesis_testing",
}


def compose_pre_reasoning(
    pack: JudgmentPack | None,
    *,
    policy: JudgmentConfidencePolicy | None = None,
) -> PreReasoningDecision:
    """Compone la decisión de forma de análisis. Sin JEV, todo queda vacío."""
    decision = PreReasoningDecision()
    if pack is None or not pack.ok:
        return decision
    active = policy or default_policy()
    decision.decided_by = DECIDED_BY_JEV

    shape = pack.choice("reasoning_shape")
    if shape is not None:
        decision.shape = shape.choice
        decision.shape_confidence = shape.confidence
        decision.shape_ambiguous = shape.ambiguous
        decision.shape_runner_up = shape.runner_up or ""
        if shape.ambiguous:
            decision.uncertain.append("reasoning_shape")

    family = pack.choice("preferred_capability")
    if family is not None and not family.ambiguous:
        decision.source_family = family.choice
        decision.source_family_confidence = family.confidence

    score = pack.score("analysis_complexity")
    if score is not None:
        decision.complexity = score.score
        decision.complexity_level = str(score.level or "")

    for key, question_id in NEED_QUESTIONS.items():
        thresholds = active.for_question(question_id, phase=PHASE_PRE_REASONING)
        reading = pack.noul(question_id, thresholds)
        if reading is None:
            continue
        verdict = thresholds.verdict(reading)
        if verdict == VERDICT_YES:
            decision.needs[key] = True
        elif verdict == VERDICT_UNCERTAIN:
            decision.uncertain.append(question_id)

    fast_path = pack.noul(
        "simple_lookup_sufficient",
        active.for_question("simple_lookup_sufficient", phase=PHASE_PRE_REASONING),
    )
    if fast_path is not None:
        decision.simple_fast_path = active.for_question(
            "simple_lookup_sufficient", phase=PHASE_PRE_REASONING
        ).verdict(fast_path) == VERDICT_YES

    # Ambigüedad de forma (§10): dos formas con peso material ⇒ ninguna manda.
    if (
        decision.shape_ambiguous
        and decision.shape_runner_up == "temporal_sequence"
        and decision.shape == "state_transition"
    ):
        decision.needs.setdefault("timeline", True)
    return decision


@dataclass
class ReconstructionJudgment:
    """Veredictos compuestos de POST_RECONSTRUCTION."""

    scenario_completeness: float = 0.0
    reconstruction_quality: float = 0.0
    rule_coverage: float = 0.0
    timeline_coherent: str = VERDICT_UNCERTAIN
    critical_transition_missing: str = VERDICT_UNCERTAIN
    inference_possible: str = VERDICT_UNCERTAIN
    critical_unknown_remaining: str = VERDICT_UNCERTAIN
    user_hypothesis_supported: str = VERDICT_UNCERTAIN
    user_hypothesis_contradicted: str = VERDICT_UNCERTAIN
    alternative_explanation: str = VERDICT_UNCERTAIN
    hypothesis_verdicts: list[dict[str, Any]] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    decided_by: str = DECIDED_BY_LEGACY

    @property
    def analysis_complete(self) -> bool:
        return (
            self.timeline_coherent == VERDICT_YES
            and self.critical_transition_missing == VERDICT_NO
            and self.critical_unknown_remaining == VERDICT_NO
            and self.inference_possible == VERDICT_YES
        )

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decided_by": self.decided_by,
            "analysis_complete": bool(self.analysis_complete),
            "timeline_coherent": self.timeline_coherent,
            "critical_transition_missing": self.critical_transition_missing,
            "inference_possible": self.inference_possible,
            "critical_unknown_remaining": self.critical_unknown_remaining,
            "user_hypothesis": {
                "supported": self.user_hypothesis_supported,
                "contradicted": self.user_hypothesis_contradicted,
            },
        }
        if self.scenario_completeness:
            payload["scenario_completeness"] = round(self.scenario_completeness, 4)
        if self.reconstruction_quality:
            payload["reconstruction_quality"] = round(self.reconstruction_quality, 4)
        if self.rule_coverage:
            payload["rule_coverage"] = round(self.rule_coverage, 4)
        if self.hypothesis_verdicts:
            payload["hypotheses"] = list(self.hypothesis_verdicts)
        if self.uncertain:
            payload["uncertain"] = list(self.uncertain)
        return payload


def compose_post_reconstruction(
    pack: JudgmentPack | None,
    *,
    hypothesis_count: int = 0,
    policy: JudgmentConfidencePolicy | None = None,
) -> ReconstructionJudgment:
    judgment = ReconstructionJudgment()
    if pack is None or not pack.ok:
        return judgment
    active = policy or default_policy()
    judgment.decided_by = DECIDED_BY_JEV
    definition_phase = PHASE_POST_RECONSTRUCTION

    def _noul(question_id: str) -> str:
        thresholds = active.for_question(question_id, phase=definition_phase)
        reading = pack.noul(question_id, thresholds)
        verdict = thresholds.verdict(reading)
        if verdict == VERDICT_UNCERTAIN and reading is not None:
            judgment.uncertain.append(question_id)
        return verdict

    score = pack.score("scenario_completeness")
    if score is not None:
        judgment.scenario_completeness = score.score
    quality = pack.score("state_reconstruction_quality")
    if quality is not None:
        judgment.reconstruction_quality = quality.score
    coverage = pack.score("rule_coverage")
    if coverage is not None:
        judgment.rule_coverage = coverage.score

    judgment.timeline_coherent = _noul("timeline_coherent")
    judgment.critical_transition_missing = _noul("critical_transition_missing")
    judgment.inference_possible = _noul("inference_possible")
    judgment.critical_unknown_remaining = _noul("critical_unknown_remaining")
    judgment.user_hypothesis_supported = _noul("hypothesis_user_supported")
    judgment.user_hypothesis_contradicted = _noul("hypothesis_user_contradicted")
    judgment.alternative_explanation = _noul("alternative_hypothesis_supported")

    for index in range(max(0, int(hypothesis_count))):
        supported = _noul(f"hypothesis_{index}_supported")
        contradicted = _noul(f"hypothesis_{index}_contradicted")
        judgment.hypothesis_verdicts.append(
            {
                "index": index,
                "verdict": _hypothesis_verdict(supported, contradicted),
                "supported": supported,
                "contradicted": contradicted,
            }
        )
    return judgment


def _hypothesis_verdict(supported: str, contradicted: str) -> str:
    """Código compone el veredicto; la evidencia contraria manda (§15)."""
    if contradicted == VERDICT_YES and supported != VERDICT_YES:
        return "rejected"
    if supported == VERDICT_YES and contradicted != VERDICT_YES:
        return "supported"
    if supported == VERDICT_YES and contradicted == VERDICT_YES:
        return "unresolved"
    return "unresolved"


def compose_final_action(
    pack: JudgmentPack | None,
    *,
    policy: JudgmentConfidencePolicy | None = None,
) -> dict[str, Any]:
    """Compone approve/revise/abstain + motivo de revisión (§22, §23).

    El motivo se COMPONE de los juicios ya emitidos: no se pide otro LLM ni una
    segunda llamada (§45).
    """
    active = policy or default_policy()
    result: dict[str, Any] = {"action": "approve", "reasons": [], "decided_by": DECIDED_BY_LEGACY}
    if pack is None or not pack.ok:
        return result
    result["decided_by"] = DECIDED_BY_JEV
    revision_reasons: list[str] = []

    def _verdict(question_id: str) -> str:
        thresholds = active.for_question(question_id, phase=PHASE_POST_GENERATION)
        return thresholds.verdict(pack.noul(question_id, thresholds))

    if _verdict("answer_grounded") == VERDICT_NO:
        revision_reasons.append("missing_evidence")
        result["action"] = "abstain"
    if _verdict("answer_contains_unsupported_conclusion") == VERDICT_YES:
        revision_reasons.append("unsupported_claim")
    if _verdict("answer_ignores_material_conflict") == VERDICT_YES:
        revision_reasons.append("conflict_not_disclosed")
    if _verdict("answer_overstates_uncertainty") == VERDICT_YES:
        revision_reasons.append("too_uncertain")
    if _verdict("answer_complete") == VERDICT_NO:
        revision_reasons.append("incomplete_answer")
    choice = pack.choice("final_action")
    if choice is not None and choice.certain and choice.choice in ("approve", "revise", "abstain"):
        if choice.choice == "abstain":
            result["action"] = "abstain"
        elif choice.choice == "revise" and result["action"] != "abstain":
            result["action"] = "revise"
    elif choice is not None and choice.ambiguous:
        revision_reasons.append("uncertain_verdict")
    if revision_reasons and result["action"] == "approve":
        result["action"] = "revise"
    result["reasons"] = revision_reasons
    result["revision_reason"] = revision_reasons[0] if revision_reasons else ""
    return result


# -----------------------------------------------------------------------------
# Matriz de preparación (§27) — calculada en código, siempre
# -----------------------------------------------------------------------------


def _row_state_from_verdict(verdict: str, *, blocked_on_no: bool = True) -> str:
    if verdict == VERDICT_YES:
        return READINESS_OK
    if verdict == VERDICT_NO:
        return READINESS_BLOCKED if blocked_on_no else READINESS_WARN
    return READINESS_UNKNOWN


def build_readiness(
    *,
    pack: JudgmentPack | None,
    signals: DeterministicSignals,
    decision: EscalationDecision | None = None,
    reconstruction: ReconstructionJudgment | None = None,
    policy: JudgmentConfidencePolicy | None = None,
) -> PreLLMReadiness:
    """Compone la matriz de preparación previa al LLM (§27).

    Cada fila declara de dónde viene (`source`): JEV o determinístico. Una fila
    `unknown` no bloquea; una `blocked` sí. No se habla de verdad absoluta:
    se habla de preparación, soporte y confianza (§28).
    """
    active = policy or default_policy()
    readiness = PreLLMReadiness()

    def _verdict(question_id: str, phase: str = PHASE_PRE_GENERATION) -> str:
        if pack is None or not pack.ok:
            return VERDICT_UNCERTAIN
        thresholds = active.for_question(question_id, phase=phase)
        return thresholds.verdict(pack.noul(question_id, thresholds))

    def _score(question_id: str) -> ScoreReading | None:
        if pack is None or not pack.ok:
            return None
        return pack.score(question_id)

    # Evidencia
    strength = _score("evidence_strength")
    evidence_sufficient = signals.evidence_sufficient
    if strength is not None:
        state = READINESS_OK if strength.score >= 2.0 else (
            READINESS_WARN if strength.score >= 1.0 else READINESS_BLOCKED
        )
        readiness.set(
            ReadinessRow(
                key=ROW_EVIDENCE,
                state=state,
                confidence=strength.confidence or None,
                detail=str(strength.level or ""),
                source=DECIDED_BY_JEV,
            )
        )
    elif evidence_sufficient is not None:
        readiness.set(
            ReadinessRow(
                key=ROW_EVIDENCE,
                state=READINESS_OK if evidence_sufficient else READINESS_BLOCKED,
                confidence=signals.evidence_score,
                detail="sufficient" if evidence_sufficient else "insufficient",
                source=DECIDED_BY_DETERMINISTIC,
            )
        )

    # Escenario y estado: la reconstrucción sólo existe si el análisis corrió.
    if reconstruction is not None and reconstruction.decided_by == DECIDED_BY_JEV:
        scenario = reconstruction.scenario_completeness
        readiness.set(
            ReadinessRow(
                key=ROW_SCENARIO,
                state=(
                    READINESS_OK
                    if scenario >= 2.0
                    else READINESS_WARN
                    if scenario >= 1.0
                    else READINESS_BLOCKED
                ),
                confidence=min(1.0, scenario / 3.0) if scenario else None,
                detail="complete" if scenario >= 3.0 else "partial",
                source=DECIDED_BY_JEV,
            )
        )
        quality = reconstruction.reconstruction_quality
        readiness.set(
            ReadinessRow(
                key=ROW_STATE,
                state=(
                    READINESS_OK
                    if reconstruction.timeline_coherent == VERDICT_YES
                    and reconstruction.critical_transition_missing == VERDICT_NO
                    else READINESS_BLOCKED
                    if reconstruction.critical_transition_missing == VERDICT_YES
                    else READINESS_WARN
                ),
                confidence=min(1.0, quality / 3.0) if quality else None,
                detail="chain_confirmed"
                if reconstruction.critical_transition_missing == VERDICT_NO
                else "chain_incomplete",
                source=DECIDED_BY_JEV,
            )
        )
        hypothesis_state = READINESS_UNKNOWN
        if reconstruction.user_hypothesis_contradicted == VERDICT_YES:
            hypothesis_state = READINESS_OK
        elif reconstruction.user_hypothesis_supported == VERDICT_YES:
            hypothesis_state = READINESS_OK
        elif reconstruction.alternative_explanation == VERDICT_YES:
            hypothesis_state = READINESS_OK
        elif reconstruction.uncertain:
            hypothesis_state = READINESS_UNKNOWN
        readiness.set(
            ReadinessRow(
                key=ROW_HYPOTHESIS,
                state=hypothesis_state,
                detail=(
                    "rejected"
                    if reconstruction.user_hypothesis_contradicted == VERDICT_YES
                    else "supported"
                    if reconstruction.user_hypothesis_supported == VERDICT_YES
                    else "alternative"
                    if reconstruction.alternative_explanation == VERDICT_YES
                    else "unresolved"
                ),
                source=DECIDED_BY_JEV,
            )
        )

    # Inferencia
    inference_verdict = _verdict("inference_supported")
    if inference_verdict != VERDICT_UNCERTAIN:
        readiness.set(
            ReadinessRow(
                key=ROW_INFERENCE,
                state=_row_state_from_verdict(inference_verdict),
                detail="supported" if inference_verdict == VERDICT_YES else "unsupported",
                source=DECIDED_BY_JEV,
            )
        )
    elif signals.inference_supported is not None:
        readiness.set(
            ReadinessRow(
                key=ROW_INFERENCE,
                state=READINESS_OK if signals.inference_supported else READINESS_BLOCKED,
                source=DECIDED_BY_DETERMINISTIC,
            )
        )

    # Conflictos
    conflict_verdict = _verdict("critical_conflict_unresolved")
    if conflict_verdict != VERDICT_UNCERTAIN or signals.source_conflict:
        blocked = conflict_verdict == VERDICT_YES or signals.source_conflict
        readiness.set(
            ReadinessRow(
                key=ROW_CONFLICTS,
                state=READINESS_BLOCKED if blocked else READINESS_OK,
                detail="unresolved" if blocked else "none_critical",
                source=DECIDED_BY_JEV if conflict_verdict != VERDICT_UNCERTAIN else DECIDED_BY_DETERMINISTIC,
            )
        )

    # Answerability
    if signals.answerable is not None:
        readiness.set(
            ReadinessRow(
                key=ROW_ANSWERABILITY,
                state=READINESS_OK if signals.answerable else READINESS_BLOCKED,
                detail=",".join(list(signals.answerability_reasons)[:3]) or None,
                source=DECIDED_BY_DETERMINISTIC,
            )
        )

    # LLM
    if decision is not None and decision.decided_by == DECIDED_BY_JEV:
        if not decision.allow_generation:
            state = READINESS_BLOCKED
        elif decision.uncertain_critical:
            # Un juicio crítico incierto no bloquea por sí solo, pero se declara.
            state = READINESS_WARN
        else:
            state = READINESS_OK
        readiness.set(
            ReadinessRow(
                key=ROW_LLM,
                state=state,
                confidence=decision.confidence or None,
                detail=decision.tier,
                source=DECIDED_BY_JEV,
            )
        )
    return readiness


# -----------------------------------------------------------------------------
# Runner — una llamada por fase
# -----------------------------------------------------------------------------


async def run_pack(
    *,
    judge: Any,
    phase: str,
    state: Mapping[str, Any],
    mode: str = MODE_ON,
    context: Any = None,
    cache: Any = None,
    policy: JudgmentConfidencePolicy | None = None,
    hypotheses: list[Any] | None = None,
    available: set[str] | None = None,
) -> JudgmentPack:
    """Ejecuta (o reutiliza) el pack de una fase. Nunca lanza.

    Sin judge o con el modo en off no hay llamada: el llamador conserva su
    fallback determinístico. Un JEV caído degrada a "sin juicio", jamás a error.
    """
    import time

    active_mode = normalize_preflight_mode(mode)
    if not preflight_active(active_mode):
        return skipped_pack(phase=phase, mode=active_mode, reason="mode_off")
    if judge is None:
        return skipped_pack(phase=phase, mode=active_mode, reason="judge_unavailable")

    from src.decision.batch import build_phase_questions
    from src.decision.judgment import JudgmentContext, call_phase_judge

    kwargs: dict[str, Any] = {}
    if phase == PHASE_PRE_REASONING and available is not None:
        kwargs["available"] = available
    elif phase == PHASE_POST_RECONSTRUCTION and hypotheses is not None:
        kwargs["hypotheses"] = hypotheses
    try:
        questions = build_phase_questions(phase, **kwargs).to_jevy()
    except Exception:  # noqa: BLE001 — un builder roto no rompe el request
        return skipped_pack(phase=phase, mode=active_mode, reason="questions_unavailable")

    if not questions:
        return skipped_pack(phase=phase, mode=active_mode, reason="no_questions")

    ctx = context if context is not None else JudgmentContext(phase=phase)
    if getattr(ctx, "phase", phase) != phase:
        import dataclasses

        ctx = dataclasses.replace(ctx, phase=phase)
    started = time.perf_counter()
    try:
        payload = await call_phase_judge(
            judge, phase=phase, state=dict(state), questions=questions, context=ctx, cache=cache
        )
    except Exception:  # noqa: BLE001
        pack = JudgmentPack(phase=phase, mode=active_mode, error=True)
        pack.latency_ms = (time.perf_counter() - started) * 1000
        return _measured(pack)
    latency_ms = (time.perf_counter() - started) * 1000
    if not isinstance(payload, Mapping):
        pack = JudgmentPack(phase=phase, mode=active_mode, error=True)
        pack.latency_ms = latency_ms
        return _measured(pack)
    return _measured(
        build_pack(
            phase=phase,
            payload=payload,
            mode=active_mode,
            policy=policy,
            latency_ms=latency_ms,
        )
    )


def _measured(pack: JudgmentPack) -> JudgmentPack:
    """Registra el pack (métricas fail-soft) y lo devuelve intacto."""
    try:
        from src.decision.metrics import record_preflight_pack

        record_preflight_pack(pack)
    except Exception:  # noqa: BLE001 — la observabilidad nunca rompe el juicio
        pass
    return pack


# -----------------------------------------------------------------------------
# Traza del preflight — la historia y las KPIs salen del mismo dato
# -----------------------------------------------------------------------------


@dataclass
class PreflightTrace:
    """Acumula packs y decisiones de un request. Sin CoT: sólo juicios y efectos."""

    mode: str = MODE_OFF
    packs: list[JudgmentPack] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def add_pack(self, pack: JudgmentPack | None) -> PreflightTrace:
        if pack is not None:
            self.packs.append(pack)
        return self

    def add_decision(self, phase: str, decision: Mapping[str, Any] | None) -> PreflightTrace:
        if decision:
            self.decisions.append({"phase": phase, **dict(decision)})
        return self

    def pack_for(self, phase: str) -> JudgmentPack | None:
        for pack in self.packs:
            if pack.phase == phase and pack.ok:
                return pack
        return None

    def summary(self) -> dict[str, Any]:
        executed = [pack for pack in self.packs if pack.ok]
        questions = sum(pack.question_count for pack in executed)
        latency = sum(float(pack.latency_ms) for pack in executed)
        cost = sum(float(pack.cost) for pack in executed)
        tokens = {
            "input": sum(int(pack.tokens.get("input") or 0) for pack in executed),
            "output": sum(int(pack.tokens.get("output") or 0) for pack in executed),
        }
        influenced = 0
        avoided = 0
        blocked = 0
        uncertain = 0
        tiers: dict[str, int] = {}
        for decision in self.decisions:
            if decision.get("influer") or _influenced(decision):
                influenced += 1
            if decision.get("tier"):
                tiers[str(decision["tier"])] = tiers.get(str(decision["tier"]), 0) + 1
            if decision.get("action") in (ACTION_ABSTAIN, ACTION_DETERMINISTIC) and decision.get(
                "applied"
            ):
                blocked += 1
                avoided += 1
            elif (
                decision.get("tier") in (TIER_SMALL, TIER_DETERMINISTIC)
                and decision.get("legacy_tier") in EXPENSIVE_TIERS
                and decision.get("applied")
            ):
                avoided += 1
            uncertain += len(list(decision.get("uncertain_critical") or []))
        payload: dict[str, Any] = {
            "mode": self.mode,
            "calls": len(executed),
            "judgments": questions,
            "skipped_calls": len([pack for pack in self.packs if pack.skipped_reason]),
            "failed_calls": len([pack for pack in self.packs if pack.error]),
            "cached_calls": len([pack for pack in executed if pack.cached]),
            "decisions": len(self.decisions),
            "decisions_influenced": influenced,
            "uncertain_critical_judgments": uncertain,
            "generation_blocked": blocked,
            "llm_escalations_avoided": avoided,
            "latency_ms": round(latency, 2),
            "cost_usd": round(cost, 6),
            "tokens": tokens,
        }
        if tiers:
            payload["tiers"] = tiers
        if executed:
            payload["questions_per_call"] = round(questions / len(executed), 2)
        return payload

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "summary": self.summary(),
            "packs": [pack.to_public_dict() for pack in self.packs],
            "decisions": list(self.decisions),
        }


def _influenced(decision: Mapping[str, Any]) -> bool:
    """Un juicio influyó si cambió la acción, el tier o bloqueó la generación."""
    if decision.get("influer") is not None:
        return bool(decision.get("influer"))
    if not decision.get("applied"):
        return False
    if not decision.get("allow_generation", True):
        return True
    tier = str(decision.get("tier") or "")
    legacy = str(decision.get("legacy_tier") or TIER_STANDARD)
    if tier in (TIER_SMALL, TIER_DETERMINISTIC) and legacy in EXPENSIVE_TIERS:
        return True
    if tier == TIER_REASONING and legacy != TIER_REASONING:
        return True
    return False


def decision_influenced(decision: Mapping[str, Any] | Any) -> bool:
    """Versión pública: la usan el hook y la traza del story."""
    if isinstance(decision, Mapping):
        return _influenced(decision)
    payload = {
        "applied": bool(getattr(decision, "applied", False)),
        "allow_generation": bool(getattr(decision, "allow_generation", True)),
        "tier": str(getattr(decision, "tier", "") or ""),
        "legacy_tier": str(getattr(decision, "legacy_tier", TIER_STANDARD) or TIER_STANDARD),
    }
    return _influenced(payload)


__all__ = [
    "ACTIONS",
    "ACTION_ABSTAIN",
    "ACTION_ASK_USER",
    "ACTION_DETERMINISTIC",
    "ACTION_GENERATE",
    "ACTION_RECONSTRUCT",
    "ACTION_RETRIEVE",
    "CRITICAL_QUESTIONS",
    "DECIDED_BY_DETERMINISTIC",
    "DECIDED_BY_JEV",
    "DECIDED_BY_LEGACY",
    "DeterministicSignals",
    "EXPENSIVE_TIERS",
    "EscalationDecision",
    "GATE_CONDITIONS",
    "JudgmentPack",
    "LLMEscalationPolicy",
    "MAX_QUESTIONS_PER_PACK",
    "MODE_CANARY",
    "MODE_OFF",
    "MODE_ON",
    "MODE_SHADOW",
    "NEED_QUESTIONS",
    "PREFLIGHT_MODES",
    "PreLLMReadiness",
    "PreReasoningDecision",
    "PreflightTrace",
    "QuestionJudgment",
    "READINESS_BLOCKED",
    "READINESS_OK",
    "READINESS_UNKNOWN",
    "READINESS_WARN",
    "ROW_ANSWERABILITY",
    "ROW_CONFLICTS",
    "ROW_EVIDENCE",
    "ROW_HYPOTHESIS",
    "ROW_INFERENCE",
    "ROW_LLM",
    "ROW_ORDER",
    "ROW_SCENARIO",
    "ROW_STATE",
    "ReadinessRow",
    "ReconstructionJudgment",
    "TIERS",
    "TIER_DETERMINISTIC",
    "TIER_REASONING",
    "TIER_SMALL",
    "TIER_STANDARD",
    "build_pack",
    "build_readiness",
    "choice_effect",
    "clip",
    "compose_final_action",
    "compose_post_reconstruction",
    "compose_pre_reasoning",
    "counts",
    "decision_influenced",
    "normalize_preflight_mode",
    "noul_effect",
    "preflight_active",
    "preflight_controls_answer",
    "preview",
    "run_pack",
    "score_effect",
    "skipped_pack",
    "tier_index",
]
