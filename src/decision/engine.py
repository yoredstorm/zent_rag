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
        cache=None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._registry = registry
        self._tracer = tracer
        self._usage = usage
        self._jev = jev
        from src.decision.batch import default_cache

        self._cache = cache if cache is not None else default_cache()

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

    # -------------------------------------------------------------------------
    # Batched phases — ONE call per compatible state (ADR batching)
    # -------------------------------------------------------------------------

    async def judge_phase(
        self,
        *,
        phase: str,
        state: dict[str, Any],
        questions: dict[str, Any] | None = None,
        batch_questions: dict[str, Any] | None = None,
        context: JudgmentContext | None = None,
        cache: Any = None,
    ) -> dict[str, Any] | None:
        """Ejecuta (o reutiliza) el juicio de una fase.

        - `questions`: preguntas legacy del módulo (comportamiento off/shadow).
        - `batch_questions`: preguntas de la fase completa (on/shadow).
        - `questions=None` + `batch_questions=None`: reutiliza el payload de la
          fase para el mismo request/estado; None si no hay nada cacheado.

        Nunca lanza: un JEV caído devuelve None y el llamador conserva su
        fallback determinístico.
        """
        from src.decision.batch import (
            MODE_OFF,
            MODE_ON,
            MODE_SHADOW,
            JudgmentCache,
            PhaseJudgment,
            compare_payloads,
            questions_fingerprint,
            record_phase_metrics,
            record_shadow_diffs,
            request_key,
            state_fingerprint,
        )

        mode = self._settings.effective_batch_mode
        ctx = context or JudgmentContext()
        if ctx.phase != phase:
            import dataclasses

            ctx = dataclasses.replace(ctx, phase=phase)
        store: JudgmentCache = cache if cache is not None else self._cache

        # Reuse-only call: el estado ya fue juzgado en esta fase para este request.
        if questions is None and batch_questions is None:
            if self._jev is None or mode != MODE_ON:
                return None
            entry = store.get(
                request=request_key(ctx.effective_request_id),
                phase=str(phase),
                state_fp=state_fingerprint(phase, state),
            )
            if entry is None:
                return None
            record_phase_metrics(
                PhaseJudgment(
                    phase=str(phase),
                    payload=entry.payload,
                    questions=entry.question_ids,
                    cached=True,
                    mode=mode,
                    question_count=len(entry.question_ids),
                )
            )
            return _reused_payload(entry.payload, phase)

        if mode == MODE_OFF:
            legacy = questions if questions is not None else (batch_questions or {})
            return await self.judge(state=state, questions=legacy, context=ctx)

        batch = batch_questions or questions or {}
        if mode == MODE_SHADOW:
            legacy_questions = questions if questions is not None else batch
            legacy = await self.judge(state=state, questions=legacy_questions, context=ctx)
            if batch_questions and self._jev is not None:
                legacy_fp = questions_fingerprint(legacy_questions)
                batch_fp = questions_fingerprint(batch_questions)
                if batch_fp != legacy_fp:
                    shadow = await self.judge(state=state, questions=batch_questions, context=ctx)
                    if shadow is not None:
                        record_shadow_diffs(
                            compare_payloads(
                                phase=str(phase),
                                legacy_answers=legacy,
                                batch_answers=shadow,
                                question_ids=list(
                                    dict.fromkeys([*legacy_questions, *batch_questions])
                                ),
                                request_id=ctx.effective_request_id,
                            )
                        )
            return legacy

        # mode == on
        if self._jev is None:
            return None
        req = request_key(ctx.effective_request_id)
        state_fp = state_fingerprint(phase, state)
        q_fp = questions_fingerprint(batch)
        entry = store.get(request=req, phase=str(phase), state_fp=state_fp, questions_fp=q_fp)
        if entry is not None:
            record_phase_metrics(
                PhaseJudgment(
                    phase=str(phase),
                    payload=entry.payload,
                    questions=entry.question_ids,
                    cached=True,
                    mode=mode,
                    question_count=len(entry.question_ids),
                )
            )
            return _reused_payload(entry.payload, phase)
        started = time.perf_counter()
        payload = await self.judge(state=state, questions=batch, context=ctx)
        judgment = PhaseJudgment(
            phase=str(phase),
            payload=payload,
            questions=tuple(str(q) for q in batch),
            cached=False,
            error=payload is None,
            mode=mode,
            latency_ms=(time.perf_counter() - started) * 1000,
            question_count=len(batch),
        )
        record_phase_metrics(judgment)
        if isinstance(payload, dict) and req:
            store.put(
                request=req,
                phase=str(phase),
                state_fp=state_fp,
                questions_fp=q_fp,
                payload=payload,
                question_ids=batch.keys(),
            )
        return payload

    def batch_shadow_diffs(self) -> list[dict[str, Any]]:
        from src.decision.batch import shadow_diffs

        return shadow_diffs()

    def clear_batch_cache(self) -> None:
        self._cache.clear()

    @property
    def batch_cache(self):
        return self._cache


def _reused_payload(payload: dict[str, Any], phase: str) -> dict[str, Any]:
    """Copia marcada como reutilizada: sin doble costo en usage/observabilidad."""
    data = dict(payload)
    data["deduped"] = True
    data["phase"] = phase
    data["deduped_cost"] = data.get("estimated_cost", 0.0)
    data["estimated_cost"] = 0.0
    data["usage"] = {"input_tokens": 0, "output_tokens": 0}
    return data


def _memory_ids(context: DecisionContext) -> list[str]:
    ids: list[str] = []
    for item in context.operational_patterns:
        if isinstance(item, dict) and item.get("memory_id"):
            ids.append(str(item["memory_id"]))
    return ids


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
        memory_ids=_memory_ids(context),
        jev_capability=(
            (decision.metadata.get("jev") or {}).get("capability")
            if isinstance(decision.metadata.get("jev"), dict)
            else (decision.raw_answers.get("jev") or {}).get("capability")
            if isinstance(decision.raw_answers.get("jev"), dict)
            else None
        ),
    )
