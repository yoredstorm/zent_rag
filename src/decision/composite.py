# =============================================================================
# CompositeDecisionProvider — Rules → JEV → small LLM → reasoning LLM.
# =============================================================================
from __future__ import annotations

import time

from src.core.domain.decision import (
    DecisionContext,
    DecisionProviderName,
    RoutingDecision,
    RoutingMode,
)
from src.core.ports.decision import DecisionProvider
from src.decision.policy import authorize_decision
from src.decision.providers.jev import JevTransportError
from src.decision.settings import DecisionEngineSettings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


class CompositeDecisionProvider(DecisionProvider):
    name = DecisionProviderName.COMPOSITE.value

    def __init__(
        self,
        *,
        settings: DecisionEngineSettings,
        rules: DecisionProvider,
        jev: DecisionProvider | None = None,
        llm: DecisionProvider | None = None,
        reasoning: DecisionProvider | None = None,
        registry=None,
    ) -> None:
        self._settings = settings
        self._rules = rules
        self._jev = jev
        self._llm = llm
        self._reasoning = reasoning
        self._registry = registry

    async def decide(self, context: DecisionContext) -> RoutingDecision:
        started = time.perf_counter()
        mode = self._settings.effective_mode
        act = self._settings.acts(context.request_id)
        observe = self._settings.observes(context.request_id) or act

        rules = await self._rules.decide(context)
        explicit_intent = rules.resolved and bool(rules.metadata.get("explicit"))
        if rules.resolved and (act or explicit_intent):
            rules.metadata = {
                **rules.metadata,
                "acting": True,
                "mode": mode,
                "explicit_act": bool(explicit_intent and not act),
            }
            return _finish(authorize_decision(rules, context, self._registry), started)
        # Shadow/sampled traffic stays in charge: rules are a candidate only.
        shadow_rules = rules if rules.resolved else None

        blocked = (
            context.budget.get("on_limit") == "block"
            and context.budget.get("remaining_ok") is False
        )
        if blocked:
            unresolved = RoutingDecision(
                provider=DecisionProviderName.RULES.value,
                resolved=False,
                fallback_used=True,
                capability="respond_directly",
                metadata={"reason": "budget_block", "acting": False, "mode": mode},
            )
            return _finish(unresolved, started)

        canary = act and mode == RoutingMode.HYBRID.value

        jev_decision: RoutingDecision | None = None
        if self._jev is not None and observe:
            jev_decision = await self._try_jev(context)

        if not act:
            unresolved = RoutingDecision(
                provider=DecisionProviderName.LEGACY.value,
                resolved=False,
                capability="knowledge.answer",
                confidence=0.0,
                metadata={
                    "shadow_candidate": jev_decision.to_public_dict() if jev_decision else None,
                    "rules_candidate": shadow_rules.to_public_dict() if shadow_rules else None,
                    "canary": canary,
                    "mode": mode,
                    "acting": False,
                    "observed": bool(jev_decision or shadow_rules),
                },
            )
            if jev_decision is not None:
                unresolved.raw_answers = {"jev": jev_decision.to_public_dict()}
                unresolved.estimated_cost = jev_decision.estimated_cost
                unresolved.prompt_tokens = jev_decision.prompt_tokens
                unresolved.completion_tokens = jev_decision.completion_tokens
                unresolved.latency_ms = jev_decision.latency_ms
            if shadow_rules is not None:
                unresolved.raw_answers = {
                    **unresolved.raw_answers,
                    "rules": shadow_rules.to_public_dict(),
                }
            return _finish(unresolved, started)

        if jev_decision is not None:
            gated = await self._gate(jev_decision, context)
            gated.metadata["canary"] = canary
            gated.metadata["mode"] = mode
            gated.metadata["acting"] = True
            return _finish(authorize_decision(gated, context, self._registry), started)

        llm_decision = await self._fallback_llm(context)
        llm_decision.fallback_used = True
        llm_decision.metadata["reason"] = "jev_unavailable"
        llm_decision.metadata["canary"] = canary
        llm_decision.metadata["mode"] = mode
        llm_decision.metadata["acting"] = True
        return _finish(authorize_decision(llm_decision, context, self._registry), started)

    async def _try_jev(self, context: DecisionContext) -> RoutingDecision | None:
        if self._jev is None:
            return None
        try:
            return await self._jev.decide(context)
        except JevTransportError as exc:
            logger.warning("JEV provider unavailable", error=str(exc)[:200])
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("JEV provider failed", error=str(exc)[:200])
            return None

    # Public accessors for the Control Center / Experiment Lab. Callers must
    # not rely on private attributes; providers stay behind the composite.
    @property
    def rules(self) -> DecisionProvider:
        return self._rules

    @property
    def jev(self) -> DecisionProvider | None:
        return self._jev

    @property
    def llm(self) -> DecisionProvider | None:
        return self._llm

    @property
    def reasoning(self) -> DecisionProvider | None:
        return self._reasoning

    async def _gate(
        self,
        jev_decision: RoutingDecision,
        context: DecisionContext,
    ) -> RoutingDecision:
        high = self._settings.high_confidence
        low = self._settings.low_confidence
        if jev_decision.confidence >= high:
            return jev_decision
        if jev_decision.confidence >= low:
            if context.budget.get("prefer_cheap"):
                return jev_decision
            secondary = await self._fallback_llm(context)
            if secondary.resolved and secondary.capability == jev_decision.capability:
                jev_decision.metadata["secondary_agreed"] = True
                return jev_decision
            secondary.fallback_used = True
            secondary.metadata["reason"] = "confidence_mid_disagreement"
            secondary.metadata["jev"] = jev_decision.to_public_dict()
            return secondary
        use_reasoning = jev_decision.needs_reasoning and not context.budget.get("prefer_cheap")
        fallback = await self._fallback_llm(context, reasoning=use_reasoning)
        fallback.fallback_used = True
        fallback.metadata["reason"] = "confidence_low"
        fallback.metadata["jev"] = jev_decision.to_public_dict()
        return fallback

    async def _fallback_llm(
        self,
        context: DecisionContext,
        *,
        reasoning: bool = False,
    ) -> RoutingDecision:
        provider = self._reasoning if reasoning and self._reasoning is not None else self._llm
        if provider is None:
            return RoutingDecision(
                provider=DecisionProviderName.LEGACY.value,
                resolved=False,
                fallback_used=True,
                capability="knowledge.answer",
                metadata={"reason": "llm_unavailable"},
            )
        return await provider.decide(context)


def _finish(decision: RoutingDecision, started: float) -> RoutingDecision:
    if decision.latency_ms <= 0:
        decision.latency_ms = (time.perf_counter() - started) * 1000
    return decision
