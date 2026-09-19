# =============================================================================
# Capability executor — maps capability ids onto existing handlers by name.
# Does not reimplement RAG/Agent/Workflow engines.
# =============================================================================
from __future__ import annotations

from src.core.domain.decision import CapabilitySpec, RoutingDecision
from src.core.domain.runtime import ExecutionState, RuntimeStep
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.decision.policy import authorize_decision


class CapabilityExecutor:
    """Authorize then name the existing handler. Orchestrator still owns I/O."""

    def __init__(self, registry: InMemoryCapabilityRegistry | None = None) -> None:
        self._registry = registry or InMemoryCapabilityRegistry()
        self._registry.sync_tools()

    def spec(self, capability_id: str) -> CapabilitySpec | None:
        return self._registry.get(capability_id)

    def handler_name(self, capability_id: str) -> str:
        spec = self.spec(capability_id)
        if spec is not None and getattr(spec, "handler", ""):
            return spec.handler
        return "unknown"

    def authorize(
        self,
        decision: RoutingDecision,
        state: ExecutionState,
        *,
        permissions: frozenset[str],
    ) -> RoutingDecision:
        from src.core.domain.decision import DecisionContext

        if state.organization_id is None:
            return decision
        context = DecisionContext(
            user_request=state.request,
            organization_id=state.organization_id,
            request_id=state.request_id,
            user_id=state.user_id,
            available_capabilities=state.available_capabilities or (decision.capability,),
            permissions=permissions,
            budget=dict(state.budget),
        )
        return authorize_decision(decision, context, self._registry)

    def plan_execution(
        self,
        decision: RoutingDecision,
        state: ExecutionState,
    ) -> ExecutionState:
        cap = decision.capability if decision.resolved else "knowledge.answer"
        state.selected_capability = cap
        state.decisions.append(
            {
                "capability": cap,
                "confidence": round(decision.confidence, 4),
                "provider": decision.provider,
                "handler": self.handler_name(cap),
            }
        )
        state.append_step(
            RuntimeStep(
                name="decide",
                status="ok" if decision.resolved else "skipped",
                confidence=decision.confidence,
                capability=cap,
                cost=float(decision.estimated_cost or 0.0),
                tokens=int(decision.prompt_tokens or 0) + int(decision.completion_tokens or 0),
                detail=decision.provider,
            )
        )
        return state
