# =============================================================================
# ZentRuntime — understand / decide / authorize / execute / observe / finish.
# Delegates; never embeds capability-specific logic.
# =============================================================================
from __future__ import annotations

import time
from uuid import UUID

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.core.domain.runtime import ExecutionState, RuntimeStep
from src.decision.capabilities import default_capability_ids
from src.runtime.executor import CapabilityExecutor
from src.runtime.wallet import snapshot_budget


class ZentRuntime:
    def __init__(
        self,
        *,
        engine=None,
        executor: CapabilityExecutor | None = None,
        dispatcher=None,
    ) -> None:
        self._engine = engine
        self._executor = executor or CapabilityExecutor()
        self._dispatcher = dispatcher

    def new_state(
        self,
        *,
        request: str,
        organization_id: UUID,
        user_id: UUID | None = None,
        conversation_id: UUID | None = None,
        sql_enabled: bool = False,
        knowledge_enabled: bool = True,
        include_advisory: bool = False,
        goal: str = "",
    ) -> ExecutionState:
        caps = default_capability_ids(
            sql_enabled=sql_enabled,
            knowledge_enabled=knowledge_enabled,
            include_advisory=include_advisory,
        )
        state = ExecutionState(
            request=request,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            goal=goal or request[:200],
            available_capabilities=caps,
        )
        state.append_step(RuntimeStep(name="understand", status="ok", detail="capabilities loaded"))
        return state

    async def decide(
        self,
        state: ExecutionState,
        *,
        permissions: frozenset[str] = frozenset(),
    ) -> RoutingDecision:
        if self._engine is None:
            from src.decision.service import get_decision_engine

            self._engine = get_decision_engine()
        if state.organization_id is None:
            raise ValueError("organization_id required")
        budget = await snapshot_budget(state.organization_id)
        state.budget = budget
        started = time.perf_counter()
        context = DecisionContext(
            user_request=state.request,
            organization_id=state.organization_id,
            request_id=state.request_id,
            user_id=state.user_id,
            available_capabilities=state.available_capabilities,
            permissions=permissions,
            sql_enabled="database.query" in state.available_capabilities,
            knowledge_enabled="knowledge.answer" in state.available_capabilities,
            budget=budget,
            conversation_state=state.sanitized_for_model(),
        )
        decision = await self._engine.decide(context)
        decision.latency_ms = (time.perf_counter() - started) * 1000
        authorized = self._executor.authorize(decision, state, permissions=permissions)
        self._executor.plan_execution(authorized, state)
        if not authorized.resolved:
            state.append_step(
                RuntimeStep(name="fallback", status="ok", detail="unresolved; legacy handlers remain")
            )
        return authorized

    async def execute(
        self,
        state: ExecutionState,
        decision: RoutingDecision,
        request,
    ):
        """Dispatch an authorized decision and record the execution step."""
        if self._dispatcher is None:
            raise RuntimeError("CapabilityDispatcher not configured")
        result = await self._dispatcher.dispatch(decision, request)
        state.append_step(
            RuntimeStep(
                name="execute",
                status="ok" if result.completed else "error",
                duration_ms=round(result.latency_ms, 2),
                tokens=result.tokens,
                cost=result.cost,
                capability=result.capability,
                detail=result.handler if result.completed else (result.error or result.handler),
            )
        )
        return result

    def finish(self, state: ExecutionState, *, status: str = "ok") -> ExecutionState:
        state.append_step(RuntimeStep(name="finish", status=status))
        return state
