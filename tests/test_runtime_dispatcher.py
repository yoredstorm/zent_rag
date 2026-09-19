# =============================================================================
# Capability dispatcher + ZentRuntime execution — unit tests (no DB, no JEV).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.decision import (
    DecisionContext,
    RoutingDecision,
)
from src.decision.capabilities import InMemoryCapabilityRegistry, default_capability_ids
from src.decision.composite import CompositeDecisionProvider
from src.decision.engine import DecisionEngine
from src.decision.rules import RulesDecisionProvider
from src.decision.settings import DecisionEngineSettings
from src.runtime.dispatcher import (
    CapabilityDispatcher,
    DispatchRequest,
    DispatchResult,
    denied,
)
from src.runtime.engine import ZentRuntime


def _decision(
    capability: str = "agent.execute",
    *,
    resolved: bool = True,
    acting: bool = True,
    metadata: dict | None = None,
) -> RoutingDecision:
    return RoutingDecision(
        capability=capability,
        resolved=resolved,
        provider="rules",
        confidence=1.0,
        metadata={"acting": acting, **(metadata or {})},
    )


def _request(**kwargs) -> DispatchRequest:
    base = dict(organization_id=uuid4(), user_id=uuid4(), query="hola")
    base.update(kwargs)
    return DispatchRequest(**base)


# ---------------------------------------------------------------------------
# Dispatcher core
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_runs_registered_handler() -> None:
    dispatcher = CapabilityDispatcher()
    seen: dict = {}

    async def handler(request, decision):
        seen["agent_id"] = request.agent_id
        return DispatchResult(capability=decision.capability, answer="ok")

    dispatcher.register("agent_runtime", handler)
    agent_id = uuid4()
    result = await dispatcher.dispatch(
        _decision(), _request(agent_id=agent_id)
    )
    assert result.completed is True
    assert result.answer == "ok"
    assert result.handler == "agent_runtime"
    assert seen["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_dispatch_needs_target() -> None:
    dispatcher = CapabilityDispatcher()
    dispatcher.register("agent_runtime", _unused_handler)
    result = await dispatcher.dispatch(_decision(), _request())
    assert result.status == "needs_target"
    assert result.error == "missing_target:agent_id"


@pytest.mark.asyncio
async def test_dispatch_rejects_observational_decision() -> None:
    dispatcher = CapabilityDispatcher()
    dispatcher.register("agent_runtime", _unused_handler)
    result = await dispatcher.dispatch(
        _decision(acting=False), _request(agent_id=uuid4())
    )
    assert result.status == "unavailable"
    assert result.error == "decision_is_observational"


@pytest.mark.asyncio
async def test_dispatch_unknown_handler_is_unavailable() -> None:
    dispatcher = CapabilityDispatcher()
    result = await dispatcher.dispatch(
        _decision("workflow.execute"), _request(workflow_id=uuid4())
    )
    assert result.status == "unavailable"
    assert result.error == "handler_not_registered:workflow_engine"


@pytest.mark.asyncio
async def test_dispatch_wraps_handler_exception() -> None:
    dispatcher = CapabilityDispatcher()

    async def boom(request, decision):
        raise RuntimeError("kaboom")

    dispatcher.register("tool_registry", boom)
    result = await dispatcher.dispatch(
        _decision("tool.execute"), _request(tool="query_database")
    )
    assert result.status == "failed"
    assert "kaboom" in (result.error or "")


def test_denied_helper() -> None:
    result = denied("tool.call_api", handler="tool_registry")
    assert result.status == "denied"
    assert result.completed is False


def test_can_dispatch_only_for_registered_handlers() -> None:
    dispatcher = CapabilityDispatcher()
    assert dispatcher.can_dispatch("knowledge.answer") is False
    dispatcher.register("rag_orchestrator", _unused_handler)
    assert dispatcher.can_dispatch("knowledge.answer") is True
    assert dispatcher.handler_name("database.query") == "sql_expert"


# ---------------------------------------------------------------------------
# ZentRuntime execute step
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_runtime_execute_records_step() -> None:
    dispatcher = CapabilityDispatcher()

    async def handler(request, decision):
        return DispatchResult(capability=decision.capability, answer="done", tokens=7, cost=0.01)

    dispatcher.register("agent_runtime", handler)
    runtime = ZentRuntime(dispatcher=dispatcher)
    state = runtime.new_state(
        request="run agent",
        organization_id=uuid4(),
        include_advisory=True,
    )
    decision = _decision()
    result = await runtime.execute(state, decision, _request(agent_id=uuid4()))
    assert result.completed is True
    assert state.current_step == "execute"
    step = state.steps[-1]
    assert step.capability == "agent.execute"
    assert step.tokens == 7
    assert state.cost_so_far == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_runtime_execute_requires_dispatcher() -> None:
    runtime = ZentRuntime()
    state = runtime.new_state(request="x", organization_id=uuid4())
    with pytest.raises(RuntimeError):
        await runtime.execute(state, _decision(), _request(agent_id=uuid4()))


# ---------------------------------------------------------------------------
# Explicit targets act in every mode (legacy included)
# ---------------------------------------------------------------------------

def _engine(settings: DecisionEngineSettings) -> DecisionEngine:
    registry = InMemoryCapabilityRegistry()
    provider = CompositeDecisionProvider(
        settings=settings,
        rules=RulesDecisionProvider(),
        registry=registry,
    )
    return DecisionEngine(provider, settings, registry=registry)


@pytest.mark.asyncio
async def test_explicit_agent_acts_in_legacy_mode() -> None:
    agent_id = uuid4()
    engine = _engine(DecisionEngineSettings(routing_mode="legacy"))
    context = DecisionContext(
        user_request="resume esto",
        organization_id=uuid4(),
        explicit_agent_id=str(agent_id),
        permissions=frozenset({"agents:execute"}),
        available_capabilities=default_capability_ids(
            sql_enabled=True, include_advisory=True
        ),
    )
    decision = await engine.decide(context)
    assert decision.resolved is True
    assert decision.capability == "agent.execute"
    assert decision.metadata["acting"] is True
    assert decision.metadata["explicit"] is True
    assert decision.metadata["explicit_act"] is True


@pytest.mark.asyncio
async def test_explicit_tool_maps_to_capability() -> None:
    engine = _engine(DecisionEngineSettings(routing_mode="legacy"))
    context = DecisionContext(
        user_request="consulta",
        organization_id=uuid4(),
        explicit_tool="query_database",
        permissions=frozenset({"*"}),
        available_capabilities=default_capability_ids(
            sql_enabled=True, include_advisory=True
        ),
    )
    decision = await engine.decide(context)
    assert decision.capability == "database.query"
    assert decision.resolved is True


@pytest.mark.asyncio
async def test_advisory_not_routable_without_explicit_target() -> None:
    engine = _engine(DecisionEngineSettings(routing_mode="jev"))
    context = DecisionContext(
        user_request="haceme un email",
        organization_id=uuid4(),
        permissions=frozenset({"*"}),
        available_capabilities=default_capability_ids(
            sql_enabled=True, include_advisory=False
        ),
    )
    decision = await engine.decide(context)
    assert decision.capability != "agent.execute"


async def _unused_handler(request, decision):  # pragma: no cover — placeholder
    return DispatchResult(capability=decision.capability)
