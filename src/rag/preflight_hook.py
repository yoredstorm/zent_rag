# =============================================================================
# Preflight hook — frontera fina entre el RAG path y el juicio JEV previo.
# =============================================================================
# El orquestador no importa JEV: llama a este hook, que arma el estado acotado,
# ejecuta UN pack por fase, y devuelve la decisión COMPUESTA EN CÓDIGO.
#
# Principio: el objetivo no es hacer más llamadas a JEV, es hacer las preguntas
# correctas, en batch, en el momento correcto, antes de pagar generación cara.
#
# Fases:
#   PRE_REASONING        antes de retrieval/LLM caro   (forma y necesidades)
#   POST_RECONSTRUCTION  después de escenario/estados  (¿el análisis se sostiene?)
#   PRE_GENERATION       antes del generador           (¿puedo responder? ¿con qué?)
#   POST_GENERATION      verificación de la respuesta  (pack existente, §22)
#
# Rollout `RAG_JEV_PREFLIGHT_MODE`: off | shadow | on | canary.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID

from src.core.domain.decision import RiskLevel
from src.decision.confidence import JudgmentConfidencePolicy, default_policy
from src.decision.judgment import (
    PHASE_POST_RECONSTRUCTION,
    PHASE_PRE_GENERATION,
    PHASE_PRE_REASONING,
    JudgmentContext,
)
from src.decision.preflight import (
    ACTION_GENERATE,
    DECIDED_BY_LEGACY,
    MODE_CANARY,
    MODE_OFF,
    MODE_ON,
    TIER_DETERMINISTIC,
    TIER_REASONING,
    TIER_SMALL,
    TIER_STANDARD,
    DeterministicSignals,
    EscalationDecision,
    JudgmentPack,
    LLMEscalationPolicy,
    PreflightTrace,
    PreLLMReadiness,
    PreReasoningDecision,
    ReconstructionJudgment,
    build_readiness,
    clip,
    compose_post_reconstruction,
    compose_pre_reasoning,
    decision_influenced,
    normalize_preflight_mode,
    preflight_active,
    preview,
    run_pack,
)
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreflightSettings:
    """Configuración del juicio previo. Todo configurable, nada hardcodeado."""

    mode: str = MODE_OFF
    canary_percentage: int = 0
    enforce: bool = True
    strict_thresholds: float = 0.75
    next_action_choice: float = 0.80
    allow_deterministic_answer: bool = False
    allow_small_tier: bool = True
    extra_retrieval: bool = True
    reasoning_first: bool = True
    small_model: str = ""
    reasoning_model: str = ""

    @property
    def active(self) -> bool:
        return normalize_preflight_mode(self.mode) != MODE_OFF

    def controls_request(self, request_id: UUID | None) -> bool:
        """on controla siempre; canary sólo su porcentaje estable."""
        mode = normalize_preflight_mode(self.mode)
        if mode == MODE_ON:
            return True
        if mode == MODE_CANARY:
            if request_id is None:
                return False
            from src.decision.routing import in_canary

            return in_canary(request_id, int(self.canary_percentage or 0))
        return False


def settings_from_app() -> PreflightSettings:
    from src.core.config import get_settings

    s = get_settings()
    return PreflightSettings(
        mode=s.RAG_JEV_PREFLIGHT_MODE,
        canary_percentage=int(s.RAG_JEV_PREFLIGHT_CANARY_PERCENTAGE or 0),
        enforce=bool(s.RAG_JEV_PREFLIGHT_ENFORCE),
        strict_thresholds=float(s.RAG_JEV_PREFLIGHT_STRICT_THRESHOLDS),
        next_action_choice=float(s.RAG_JEV_PREFLIGHT_NEXT_ACTION_CHOICE),
        allow_deterministic_answer=bool(s.RAG_JEV_PREFLIGHT_ALLOW_DETERMINISTIC_ANSWER),
        allow_small_tier=bool(s.RAG_JEV_PREFLIGHT_ALLOW_SMALL_TIER),
        extra_retrieval=bool(s.RAG_JEV_PREFLIGHT_EXTRA_RETRIEVAL),
        reasoning_first=bool(s.RAG_JEV_PREFLIGHT_REASONING_FIRST),
        small_model=str(s.DECISION_FALLBACK_MODEL or s.GATEWAY_CHEAP_MODEL or ""),
        reasoning_model=str(s.DECISION_COMPLEX_MODEL or s.GATEWAY_QUALITY_MODEL or ""),
    )


# -----------------------------------------------------------------------------
# Estado por fase (acotado: cada pregunta cuesta tokens)
# -----------------------------------------------------------------------------


def pre_reasoning_state(
    *,
    query: str,
    company_context: Mapping[str, Any] | None = None,
    memory_patterns: list[Any] | None = None,
    available_sources: tuple[str, ...] | list[str] = (),
    sql_enabled: bool = False,
    classification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(company_context or {})
    return {
        "user_request": clip(query, 2000),
        "company_context_summary": clip(context.get("summary"), 600),
        "company_context_counts": {
            key: value
            for key, value in list(context.items())[:8]
            if isinstance(value, (int, float))
        },
        "memory_patterns": preview(memory_patterns, 5),
        "available_sources": list(available_sources)[:12],
        "sql_enabled": bool(sql_enabled),
        "classification": dict(classification or {}),
    }


def post_reconstruction_state(
    *,
    query: str,
    scenario: Mapping[str, Any] | None = None,
    transitions: Mapping[str, Any] | None = None,
    facts: list[Any] | None = None,
    rules: list[Any] | None = None,
    timeline: Mapping[str, Any] | None = None,
    hypotheses: list[Any] | None = None,
    user_hypothesis: str = "",
    alternative_hypotheses: list[Any] | None = None,
    unknowns: list[Any] | None = None,
    contradictions: list[Any] | None = None,
    missing_requirements: list[Any] | None = None,
    unparsed_items: list[Any] | None = None,
) -> dict[str, Any]:
    scenario_payload = dict(scenario or {})
    transitions_payload = dict(transitions or {})
    return {
        "question": clip(query, 600),
        "scenario": clip(scenario_payload.get("summary"), 800),
        "scenario_events": int(scenario_payload.get("events") or 0),
        "scenario_fingerprint": str(scenario_payload.get("fingerprint") or ""),
        "record_types": preview(scenario_payload.get("record_types"), 6),
        "transitions": clip(transitions_payload.get("chain_text"), 800),
        "transitions_confirmed": int(transitions_payload.get("confirmed") or 0),
        "transitions_unresolved": int(transitions_payload.get("unresolved") or 0),
        "transitions_fingerprint": str(transitions_payload.get("fingerprint") or ""),
        "gaps": preview(transitions_payload.get("gaps"), 6),
        "facts": preview(facts, 8),
        "rules": preview(rules, 8),
        "timeline": clip((timeline or {}).get("summary"), 500),
        "timeline_orders": preview((timeline or {}).get("orders"), 3),
        "hypothesis_candidates": preview(hypotheses, 4),
        "user_hypothesis": clip(user_hypothesis, 240),
        "alternative_hypotheses": preview(alternative_hypotheses, 3),
        "unresolved_items": preview(unknowns, 8),
        "contradictions": preview(contradictions, 6),
        "missing_requirements": preview(missing_requirements, 6),
        "unparsed_items": preview(unparsed_items, 6),
    }


def pre_generation_state(
    *,
    query: str,
    evidence: str = "",
    confirmed_facts: list[Any] | None = None,
    rules: list[Any] | None = None,
    analysis: Mapping[str, Any] | None = None,
    unknowns: list[Any] | None = None,
    conclusion: str = "",
    budget: Mapping[str, Any] | None = None,
    evidence_fingerprint: str = "",
    analysis_fingerprint: str = "",
) -> dict[str, Any]:
    return {
        "question": clip(query, 600),
        "evidence": clip(evidence, 1600),
        "confirmed_facts": preview(confirmed_facts, 8),
        "rules": preview(rules, 6),
        "analysis": dict(analysis or {}),
        "unknowns": preview(unknowns, 8),
        "candidate_conclusion": clip(conclusion, 600),
        "budget": dict(budget or {}),
        "evidence_fingerprint": str(evidence_fingerprint),
        "analysis_fingerprint": str(analysis_fingerprint),
    }


@dataclass
class PreGenerationResult:
    """Pack + decisión compuesta + matriz. Todo lo que el orquestador necesita."""

    pack: JudgmentPack | None = None
    decision: EscalationDecision = field(default_factory=EscalationDecision)
    readiness: PreLLMReadiness = field(default_factory=PreLLMReadiness)
    pre_reasoning: PreReasoningDecision = field(default_factory=PreReasoningDecision)
    reconstruction: ReconstructionJudgment = field(default_factory=ReconstructionJudgment)
    #: Conclusión ya establecida por el análisis (blueprint). Vacía = no hay
    #: respuesta determinística posible: se genera.
    conclusion: str = ""
    observed_flow: str = ""
    limitations: tuple[str, ...] = ()

    @property
    def allow_generation(self) -> bool:
        return bool(self.decision.allow_generation)

    @property
    def tier(self) -> str:
        return self.decision.tier

    @property
    def action(self) -> str:
        return self.decision.action

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision": self.decision.to_public_dict(),
            "readiness": self.readiness.to_public_dict(),
        }
        if self.reconstruction.decided_by != DECIDED_BY_LEGACY:
            payload["reconstruction"] = self.reconstruction.to_public_dict()
        return payload


class OrchestratorPreflightHook:
    """Juicio previo del RAG path. Nunca lanza: sin JEV, camino legacy."""

    def __init__(
        self,
        settings: PreflightSettings | None = None,
        *,
        judge: Any = None,
        cache: Any = None,
        policy: JudgmentConfidencePolicy | None = None,
    ) -> None:
        self._settings = settings or settings_from_app()
        self._judge = judge
        self._cache = cache
        self._policy = policy or default_policy()
        self._escalation = LLMEscalationPolicy(
            policy=self._policy,
            allow_deterministic=self._settings.allow_deterministic_answer,
            allow_small=self._settings.allow_small_tier,
        )

    @property
    def settings(self) -> PreflightSettings:
        return self._settings

    @property
    def policy(self) -> JudgmentConfidencePolicy:
        return self._policy

    def enabled(self) -> bool:
        return self._settings.active and self._judge is not None

    def controls_request(self, request_id: UUID | None) -> bool:
        """¿La decisión compuesta manda, o sólo se registra (shadow)?"""
        return self.enabled() and self._settings.enforce and self._settings.controls_request(request_id)

    def new_trace(self, *, request_id: UUID | None = None) -> PreflightTrace:
        mode = normalize_preflight_mode(self._settings.mode)
        if self.enabled() and mode == MODE_CANARY and not self._settings.controls_request(request_id):
            mode = "shadow"
        return PreflightTrace(mode=mode if self.enabled() else MODE_OFF)

    def _context(
        self,
        phase: str,
        *,
        organization_id: UUID | None,
        request_id: UUID | None,
    ) -> JudgmentContext:
        return JudgmentContext(
            phase=phase,
            organization_id=organization_id,
            request_id=request_id,
        )

    def model_hint(self, tier: str) -> str:
        """Modelo sugerido dentro de los candidatos permitidos por settings."""
        if tier == TIER_SMALL:
            return self._settings.small_model
        if tier == TIER_REASONING:
            return self._settings.reasoning_model
        return ""

    # -- fases ---------------------------------------------------------------

    async def judge_pre_reasoning(
        self,
        *,
        trace: PreflightTrace | None,
        query: str,
        organization_id: UUID | None = None,
        request_id: UUID | None = None,
        company_context: Mapping[str, Any] | None = None,
        memory_patterns: list[Any] | None = None,
        available_sources: tuple[str, ...] | list[str] = (),
        sql_enabled: bool = False,
        classification: Mapping[str, Any] | None = None,
        skip: bool = False,
    ) -> PreReasoningDecision:
        """§57: una consulta simple no paga packs complejos."""
        if skip or not preflight_active(self._settings.mode):
            return PreReasoningDecision()
        available = {"sql_enabled"} if sql_enabled else set()
        state = pre_reasoning_state(
            query=query,
            company_context=company_context,
            memory_patterns=memory_patterns,
            available_sources=available_sources,
            sql_enabled=sql_enabled,
            classification=classification,
        )
        pack = await run_pack(
            judge=self._judge,
            phase=PHASE_PRE_REASONING,
            state=state,
            mode=self._settings.mode,
            context=self._context(
                PHASE_PRE_REASONING,
                organization_id=organization_id,
                request_id=request_id,
            ),
            cache=self._cache,
            policy=self._policy,
            available=available,
        )
        if trace is not None:
            trace.add_pack(pack)
        decision = compose_pre_reasoning(pack, policy=self._policy)
        if trace is not None and (decision.needs or decision.uncertain):
            trace.add_decision(
                PHASE_PRE_REASONING,
                {
                    "action": ACTION_GENERATE,
                    "tier": TIER_STANDARD,
                    "allow_generation": True,
                    "reasons": sorted(decision.needs),
                    "uncertain_critical": list(decision.uncertain),
                    "decided_by": decision.decided_by,
                    "mode": self._settings.mode,
                    "applied": False,
                },
            )
        return decision

    async def judge_post_reconstruction(
        self,
        *,
        trace: PreflightTrace | None,
        query: str,
        organization_id: UUID | None = None,
        request_id: UUID | None = None,
        hypothesis_count: int = 0,
        **state_kwargs: Any,
    ) -> ReconstructionJudgment:
        if not preflight_active(self._settings.mode):
            return ReconstructionJudgment()
        state = post_reconstruction_state(query=query, **state_kwargs)
        pack = await run_pack(
            judge=self._judge,
            phase=PHASE_POST_RECONSTRUCTION,
            state=state,
            mode=self._settings.mode,
            context=self._context(
                PHASE_POST_RECONSTRUCTION,
                organization_id=organization_id,
                request_id=request_id,
            ),
            cache=self._cache,
            policy=self._policy,
            hypotheses=[{"index": index} for index in range(max(0, int(hypothesis_count)))],
        )
        if trace is not None:
            trace.add_pack(pack)
        return compose_post_reconstruction(
            pack,
            hypothesis_count=hypothesis_count,
            policy=self._policy,
        )

    async def judge_pre_generation(
        self,
        *,
        trace: PreflightTrace | None,
        query: str,
        signals: DeterministicSignals,
        organization_id: UUID | None = None,
        request_id: UUID | None = None,
        pre_reasoning: PreReasoningDecision | None = None,
        reconstruction: ReconstructionJudgment | None = None,
        evidence: str = "",
        confirmed_facts: list[Any] | None = None,
        rules: list[Any] | None = None,
        analysis: Mapping[str, Any] | None = None,
        unknowns: list[Any] | None = None,
        conclusion: str = "",
        observed_flow: str = "",
        limitations: tuple[str, ...] = (),
        budget: Mapping[str, Any] | None = None,
        evidence_fingerprint: str = "",
        analysis_fingerprint: str = "",
    ) -> PreGenerationResult:
        """El gate: compone la decisión de escalado antes del generador (§17)."""
        mode = self._settings.mode
        pre = pre_reasoning or PreReasoningDecision()
        reconstructed = reconstruction or ReconstructionJudgment()
        state = pre_generation_state(
            query=query,
            evidence=evidence,
            confirmed_facts=confirmed_facts,
            rules=rules,
            analysis=analysis,
            unknowns=unknowns,
            conclusion=conclusion,
            budget=budget,
            evidence_fingerprint=evidence_fingerprint,
            analysis_fingerprint=analysis_fingerprint,
        )
        pack: JudgmentPack | None = None
        if preflight_active(mode):
            pack = await run_pack(
                judge=self._judge,
                phase=PHASE_PRE_GENERATION,
                state=state,
                mode=mode,
                context=self._context(
                    PHASE_PRE_GENERATION,
                    organization_id=organization_id,
                    request_id=request_id,
                ),
                cache=self._cache,
                policy=self._policy,
            )
            if trace is not None:
                trace.add_pack(pack)
        decision = self._escalation.evaluate(pack=pack, signals=signals, mode=mode)
        applied = self.controls_request(request_id)
        decision.applied = bool(applied and pack is not None and pack.ok)
        if decision.applied is False and pack is not None and pack.ok:
            decision.reasons.append("observed_only")
        self._record_escalation(decision)
        readiness = build_readiness(
            pack=pack,
            signals=signals,
            decision=decision,
            reconstruction=reconstructed,
            policy=self._policy,
        )
        result = PreGenerationResult(
            pack=pack,
            decision=decision,
            readiness=readiness,
            pre_reasoning=pre,
            reconstruction=reconstructed,
            conclusion=clip(conclusion, 1200),
            observed_flow=clip(observed_flow, 800),
            limitations=tuple(str(item)[:200] for item in limitations),
        )
        if trace is not None:
            trace.add_decision(
                PHASE_PRE_GENERATION,
                {
                    **decision.to_public_dict(),
                    "legacy_tier": signals.legacy_tier,
                    "unsatisfied": list(decision.unsatisfied),
                    "uncertain_critical": list(decision.uncertain_critical),
                    "readiness": readiness.to_public_dict(),
                    "influer": bool(
                        decision.applied and decision_influenced(decision)
                    ),
                },
            )
            self._record_observation(
                trace=trace,
                decision=decision,
                readiness=readiness,
                legacy_tier=signals.legacy_tier,
            )
        return result

    # -- flujo ---------------------------------------------------------------

    def _record_escalation(self, decision: EscalationDecision) -> None:
        """Métricas de la decisión compuesta. Fail-soft: nunca rompe el request."""
        try:
            from src.decision.metrics import record_escalation

            record_escalation(decision)
        except Exception:  # noqa: BLE001
            pass

    def _record_observation(
        self,
        *,
        trace: PreflightTrace,
        decision: EscalationDecision,
        readiness: PreLLMReadiness,
        legacy_tier: str,
    ) -> None:
        """Una observación por request para el reporte de efectividad (§54)."""
        try:
            from src.decision.preflight_report import (
                observation_from_trace,
                record_observation,
            )

            record_observation(
                observation_from_trace(
                    trace=trace,
                    decision=decision,
                    mode=self._settings.mode,
                    readiness=readiness,
                    legacy_tier=legacy_tier,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    def attach(self, flow: dict, trace: PreflightTrace | None) -> dict:
        """Suma el bloque `jev_preflight` al flow. Aditivo y fail-soft."""
        if trace is None or not trace.packs:
            return flow
        try:
            payload = trace.to_public_dict()
        except Exception as exc:  # noqa: BLE001
            logger.warning("preflight trace failed", error=str(exc)[:160])
            return flow
        return {**flow, "jev_preflight": payload}


def risk_for_decision(decision: EscalationDecision) -> str:
    """Riesgo declarado de la decisión: alto cuando bloquea o baja el tier."""
    if not decision.allow_generation:
        return RiskLevel.HIGH.value
    if decision.tier in (TIER_SMALL, TIER_DETERMINISTIC):
        return RiskLevel.MEDIUM.value
    return RiskLevel.LOW.value


__all__ = [
    "OrchestratorPreflightHook",
    "PreflightSettings",
    "PreGenerationResult",
    "post_reconstruction_state",
    "pre_generation_state",
    "pre_reasoning_state",
    "risk_for_decision",
    "settings_from_app",
]
