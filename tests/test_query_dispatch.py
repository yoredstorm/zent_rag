# =============================================================================
# RAG query route — explicit target dispatch branch (no DB, no network).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.routes.query import _has_dispatch_target, _maybe_dispatch
from src.api.schemas import RAGQueryRequest
from src.core.domain.decision import RoutingDecision
from src.runtime.dispatcher import CapabilityDispatcher, DispatchRequest, DispatchResult


class _State:
    tenant_context = SimpleNamespace(
        permissions=frozenset({"*"}),
        scopes=frozenset({"admin:*"}),
        token_id=None,
    )


class FakeRequest:
    state = _State()
    headers: dict[str, str] = {"X-Trace-Id": "trace-123"}


class FakeHook:
    def __init__(self, decision: RoutingDecision) -> None:
        self._decision = decision
        self.calls: list[dict] = []

    async def evaluate(self, **kwargs) -> RoutingDecision:
        self.calls.append(kwargs)
        return self._decision


def _acting_decision(capability: str) -> RoutingDecision:
    return RoutingDecision(
        capability=capability,
        resolved=True,
        provider="rules",
        confidence=1.0,
        metadata={"acting": True, "explicit": True},
    )


def _dispatcher_with(handler) -> CapabilityDispatcher:
    dispatcher = CapabilityDispatcher()
    dispatcher.register("agent_runtime", handler)
    return dispatcher


@pytest.fixture(autouse=True)
def _no_org_db(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_org_config(_oid):
        return {}

    monkeypatch.setattr("src.api.routes.query._organization_config", fake_org_config)


def test_dispatch_target_detection() -> None:
    assert _has_dispatch_target(RAGQueryRequest(query="hola")) is False
    assert _has_dispatch_target(
        RAGQueryRequest(query="hola", agent_id=uuid4())
    ) is True
    assert _has_dispatch_target(RAGQueryRequest(query="hola", tool="query_database")) is True


@pytest.mark.asyncio
async def test_maybe_dispatch_returns_none_without_target() -> None:
    result = await _maybe_dispatch(
        FakeRequest(),
        RAGQueryRequest(query="hola"),
        organization_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        workspace_id=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_maybe_dispatch_runs_agent_target(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_id = uuid4()
    hook = FakeHook(_acting_decision("agent.execute"))

    async def handler(request: DispatchRequest, decision: RoutingDecision) -> DispatchResult:
        assert request.agent_id == agent_id
        return DispatchResult(
            capability=decision.capability,
            answer="respuesta del agente",
            run_id="run-1",
            tokens=15,
            prompt_tokens=10,
            completion_tokens=5,
            data={"method": "agent", "model": "gpt-4o-mini"},
        )

    from src.api import deps

    monkeypatch.setattr(deps, "get_decision_hook", lambda: hook)
    monkeypatch.setattr(deps, "get_capability_dispatcher", lambda: _dispatcher_with(handler))

    result = await _maybe_dispatch(
        FakeRequest(),
        RAGQueryRequest(query="corré el agente", agent_id=agent_id),
        organization_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        workspace_id=None,
    )
    assert result is not None
    assert result.method == "agent"
    assert result.llm_response is not None
    assert result.llm_response.content == "respuesta del agente"
    assert result.llm_response.prompt_tokens == 10
    assert result.llm_response.completion_tokens == 5
    assert result.llm_response.total_tokens == 15
    assert result.rag_trace["dispatch"]["handler"] == "agent_runtime"
    # Explicit target reached the Decision Engine as explicit intent.
    assert hook.calls[0]["explicit_agent_id"] == str(agent_id)
    assert hook.calls[0]["include_advisory"] is True


@pytest.mark.asyncio
async def test_maybe_dispatch_denied_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api import deps

    decision = RoutingDecision(
        capability="knowledge.answer",
        resolved=True,
        provider="rules",
        metadata={
            "acting": True,
            "authorization_denied": True,
            "denied_capability": "agent.execute",
        },
    )
    monkeypatch.setattr(deps, "get_decision_hook", lambda: FakeHook(decision))

    with pytest.raises(HTTPException) as excinfo:
        await _maybe_dispatch(
            FakeRequest(),
            RAGQueryRequest(query="corré el agente", agent_id=uuid4()),
            organization_id=uuid4(),
            user_id=uuid4(),
            role="admin",
            workspace_id=None,
        )
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_maybe_dispatch_falls_back_when_handler_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request, decision):  # pragma: no cover — never reached
        return DispatchResult(capability=decision.capability)

    from src.api import deps

    monkeypatch.setattr(
        deps, "get_decision_hook", lambda: FakeHook(_acting_decision("workflow.execute"))
    )
    monkeypatch.setattr(
        deps, "get_capability_dispatcher", lambda: _dispatcher_with(handler)
    )
    # handler is agent_runtime but capability maps to workflow_engine → unavailable → None
    result = await _maybe_dispatch(
        FakeRequest(),
        RAGQueryRequest(query="corré", workflow_id=uuid4()),
        organization_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        workspace_id=None,
    )
    assert result is None
