# =============================================================================
# Authorization after Decision — JEV cannot grant capabilities.
# =============================================================================
from __future__ import annotations

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.core.ports.decision import CapabilityRegistry
from src.decision.capabilities import InMemoryCapabilityRegistry

_SAFE_FALLBACK = "knowledge.answer"


def authorize_decision(
    decision: RoutingDecision,
    context: DecisionContext,
    registry: CapabilityRegistry | None = None,
    *,
    tenant_allowlist: frozenset[str] | None = None,
) -> RoutingDecision:
    """Strip unauthorized capabilities. Never elevates permissions."""
    registry = registry or InMemoryCapabilityRegistry()
    allowlist = tenant_allowlist
    if allowlist is None:
        raw = context.tenant_policy.get("capability_allowlist")
        if isinstance(raw, (list, tuple, set, frozenset)):
            allowlist = frozenset(str(x) for x in raw)
    requested = decision.capability
    allowed = registry.is_allowed(
        requested,
        permissions=context.permissions,
        tenant_allowlist=allowlist,
    )
    if allowed and requested in context.available_capabilities:
        return decision
    fallback = _SAFE_FALLBACK
    if fallback not in context.available_capabilities:
        fallback = "respond_directly"
    decision.capability = fallback
    decision.fallback_used = True
    decision.metadata = {
        **decision.metadata,
        "authorization_denied": True,
        "denied_capability": requested,
        "reason": "authorization",
    }
    decision.needs_tool = False
    decision.needs_agent = False
    decision.needs_workflow = False
    decision.needs_knowledge = fallback.startswith("knowledge.")
    return decision
