# =============================================================================
# Decision usage recording — reuses UsageEngine. Fail-silent.
# =============================================================================
from __future__ import annotations

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.decision.judgment import JudgmentContext
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# Prefijo del evento: `jev_judge:<phase>` (≤30 chars, columna event_type).
# La idempotencia de usage_events es (request_id, event_type): un retry del
# mismo request/fase no cobra dos veces, y fases distintas no se pisan.
JUDGE_EVENT_PREFIX = "jev_judge"


class DecisionUsageRecorder:
    async def record(self, context: DecisionContext, decision: RoutingDecision) -> None:
        if context.request_id is None or context.organization_id is None:
            return
        try:
            from src.platform.usage.usage_engine import UsageEvent, record_event

            await record_event(
                UsageEvent(
                    request_id=context.request_id,
                    organization_id=context.organization_id,
                    user_id=context.user_id,
                    event_type="decision",
                    model=str(decision.metadata.get("model") or decision.provider)[:120],
                    provider=decision.provider[:60],
                    prompt_tokens=decision.prompt_tokens,
                    completion_tokens=decision.completion_tokens,
                    total_tokens=decision.prompt_tokens + decision.completion_tokens,
                    latency_ms=decision.latency_ms,
                    estimated_cost=decision.estimated_cost,
                    status="completed" if decision.resolved else "shadow",
                    routing={
                        "capability": decision.capability,
                        "fallback": decision.fallback_used,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision usage record failed", error=str(exc)[:200])

    async def record_judge(
        self,
        context: JudgmentContext,
        payload: dict,
    ) -> None:
        """Usage event por juicio JEV. Sin tenant/request no hay evento."""
        if not isinstance(payload, dict):
            return
        request_id = context.effective_request_id
        if request_id is None or context.organization_id is None:
            return
        try:
            from src.platform.usage.usage_engine import UsageEvent, record_event

            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            prompt_tokens = max(0, int(usage.get("input_tokens") or 0))
            completion_tokens = max(0, int(usage.get("output_tokens") or 0))
            phase = str(context.phase or "unknown")[:17]
            routing: dict = {"phase": context.phase}
            if context.capability:
                routing["capability"] = context.capability
            if context.workflow_id is not None:
                routing["workflow_id"] = str(context.workflow_id)
            if context.run_id is not None:
                routing["run_id"] = str(context.run_id)
            await record_event(
                UsageEvent(
                    request_id=request_id,
                    organization_id=context.organization_id,
                    user_id=context.user_id,
                    agent_id=context.agent_id,
                    deployment_id=context.deployment_id,
                    event_type=f"{JUDGE_EVENT_PREFIX}:{phase}"[:30],
                    model=str(payload.get("model") or context.model or context.provider)[:120],
                    provider=str(payload.get("provider") or context.provider or "jev")[:60],
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    latency_ms=float(payload.get("latency_ms") or 0.0),
                    status="completed",
                    estimated_cost=float(payload.get("estimated_cost") or 0.0),
                    trace_id=context.trace_id,
                    routing=routing,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("judge usage record failed", error=str(exc)[:200])
