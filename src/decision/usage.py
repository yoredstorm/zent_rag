# =============================================================================
# Decision usage recording — reuses UsageEngine. Fail-silent.
# =============================================================================
from __future__ import annotations

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


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
