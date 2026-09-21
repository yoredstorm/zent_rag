# =============================================================================
# DecisionEngine — facade used by the Orchestrator.
# =============================================================================
from __future__ import annotations

import time
from typing import Any

from src.core.domain.decision import DecisionContext, DecisionTrace, RoutingDecision
from src.core.ports.decision import DecisionProvider
from src.decision.judgment import JudgmentContext
from src.decision.metrics import record_judge, record_trace_written
from src.decision.policy import authorize_decision
from src.decision.settings import DecisionEngineSettings
from src.infrastructure.observability.tracing import trace_span


class DecisionEngine:
    """Orchestrator-facing API. Providers stay behind this facade."""

    def __init__(
        self,
        provider: DecisionProvider,
        settings: DecisionEngineSettings,
        *,
        registry=None,
        tracer=None,
        usage=None,
        jev=None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._registry = registry
        self._tracer = tracer
        self._usage = usage
        self._jev = jev

    @property
    def settings(self) -> DecisionEngineSettings:
        return self._settings

    @property
    def provider(self) -> DecisionProvider:
        return self._provider

    async def decide(self, context: DecisionContext) -> RoutingDecision:
        async with trace_span(
            "decision.evaluate",
            provider=self._provider.name,
            mode=self._settings.effective_mode,
        ):
            decision = await self._provider.decide(context)
        authorized = authorize_decision(decision, context, self._registry)
        if self._tracer is not None and (
            authorized.resolved
            or self._settings.tracked(context.request_id)
            or authorized.prompt_tokens > 0
        ):
            try:
                trace = _trace_from(context, authorized, self._settings)
                await self._tracer.record(trace)
                if authorized.metadata.get("trace_id") is None:
                    authorized.metadata["trace_id"] = str(trace.decision_id)
                record_trace_written(authorized)
            except Exception:  # noqa: BLE001
                pass
        if self._usage is not None and (
            authorized.resolved or authorized.prompt_tokens > 0 or authorized.completion_tokens > 0
        ):
            try:
                await self._usage.record(context, authorized)
            except Exception:  # noqa: BLE001
                pass
        return authorized

    async def judge(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        context: JudgmentContext | None = None,
    ) -> dict[str, Any] | None:
        """Atomic questions (adaptive/agent/workflow). None if JEV unavailable.

        `context` es opcional y backward-compatible: sin él el juicio corre
        igual pero no produce usage event por tenant.
        """
        if self._jev is None:
            return None
        ctx = context or JudgmentContext()
        phase = ctx.phase or "unknown"
        started = time.perf_counter()
        async with trace_span("decision.judge", phase=phase):
            try:
                payload = await self._jev.judge(state=state, questions=questions)
            except Exception:  # noqa: BLE001 — el juicio nunca rompe el request
                record_judge(
                    None,
                    error=True,
                    phase=phase,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
                return None
        latency_ms = (time.perf_counter() - started) * 1000
        if not isinstance(payload, dict):
            record_judge(None, error=True, phase=phase, latency_ms=latency_ms)
            return None
        enriched = self._enrich_judge_payload(payload, ctx, latency_ms)
        record_judge(enriched, phase=phase, latency_ms=latency_ms)
        if self._usage is not None:
            try:
                await self._usage.record_judge(ctx, enriched)
            except Exception:  # noqa: BLE001
                pass
        return enriched

    def _enrich_judge_payload(
        self,
        payload: dict[str, Any],
        context: JudgmentContext,
        latency_ms: float,
    ) -> dict[str, Any]:
        """Provider/model/usage/costo observables aunque el provider no los traiga."""
        data = dict(payload)
        data.setdefault("provider", context.provider or "jev")
        data.setdefault("phase", context.phase)
        model = str(data.get("model") or context.model or getattr(self._jev, "model", "") or "")
        if model:
            data["model"] = model
        data.setdefault("latency_ms", round(latency_ms, 2))
        data.setdefault("estimated_cost", 0.0)
        return data


def _trace_from(
    context: DecisionContext,
    decision: RoutingDecision,
    settings: DecisionEngineSettings,
) -> DecisionTrace:
    from src.decision.questions import build_routing_questions

    questions = [
        {"id": key, "type": spec.get("type")}
        for key, spec in build_routing_questions(context.available_capabilities).items()
    ]
    return DecisionTrace(
        organization_id=context.organization_id,
        request_id=context.request_id,
        user_id=context.user_id,
        provider=decision.provider,
        questions=questions,
        results=[decision.to_public_dict()],
        selected_capability=decision.capability,
        confidence=decision.confidence,
        fallback_used=decision.fallback_used,
        latency_ms=decision.latency_ms,
        estimated_cost=decision.estimated_cost,
        routing_mode=settings.effective_mode,
        model=str(decision.metadata.get("model") or "") or None,
        shadow=settings.observes(context.request_id)
        and not settings.acts(context.request_id)
        and not decision.resolved,
        canary=bool(decision.metadata.get("canary")),
        jev_capability=(
            (decision.metadata.get("jev") or {}).get("capability")
            if isinstance(decision.metadata.get("jev"), dict)
            else (decision.raw_answers.get("jev") or {}).get("capability")
            if isinstance(decision.raw_answers.get("jev"), dict)
            else None
        ),
    )
