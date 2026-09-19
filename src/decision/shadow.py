# =============================================================================
# Shadow comparison — current path stays in charge; JEV is observational.
# =============================================================================
from __future__ import annotations

from src.core.domain.decision import DecisionContext, DecisionTrace, RoutingDecision
from src.decision.routing import capability_from_legacy_method
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


def compare_shadow(
    *,
    actual_method: str,
    engine_decision: RoutingDecision,
    context: DecisionContext,
) -> DecisionTrace:
    actual = capability_from_legacy_method(actual_method)
    raw_jev = engine_decision.raw_answers.get("jev")
    shadow = raw_jev if isinstance(raw_jev, dict) else None
    jev_cap = None
    jev_conf = None
    if shadow:
        jev_cap = shadow.get("capability")
        jev_conf = shadow.get("confidence")
    elif engine_decision.provider == "jev":
        jev_cap = engine_decision.capability
        jev_conf = engine_decision.confidence
    agreement = jev_cap == actual if jev_cap else None
    return DecisionTrace(
        organization_id=context.organization_id,
        request_id=context.request_id,
        user_id=context.user_id,
        provider=engine_decision.provider,
        selected_capability=actual,
        actual_capability=actual,
        jev_capability=str(jev_cap) if jev_cap else None,
        confidence=float(jev_conf or engine_decision.confidence or 0.0),
        fallback_used=engine_decision.fallback_used,
        latency_ms=engine_decision.latency_ms,
        estimated_cost=engine_decision.estimated_cost,
        agreement=agreement,
        shadow=True,
        results=[
            {
                "actual_decision": actual,
                "jev_decision": jev_cap,
                "jev_confidence": jev_conf,
                "agreement": agreement,
                "latency_ms": engine_decision.latency_ms,
                "cost": engine_decision.estimated_cost,
                "fallback": engine_decision.fallback_used,
            }
        ],
    )
