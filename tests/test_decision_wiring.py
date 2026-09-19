# =============================================================================
# Decision Engine wiring — authorization, shadow no-op and trace ground truth.
# Test bodies need no Postgres and no live JEV (wallet snapshot is
# monkeypatched); the suite's autouse fixtures may still require the stack.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.decision.capabilities import InMemoryCapabilityRegistry, default_capability_ids
from src.decision.composite import CompositeDecisionProvider
from src.decision.engine import DecisionEngine
from src.decision.hook import OrchestratorDecisionHook, retrieval_hint
from src.decision.providers.jev import JevDecisionProvider, JevTransportError
from src.decision.rules import RulesDecisionProvider
from src.decision.settings import DecisionEngineSettings

_SQL_QUERY = "cuánto vendimos este mes en total"
_DOC_QUERY = "qué es la política de vacaciones del manual"


def _settings(**kwargs) -> DecisionEngineSettings:
    base = dict(routing_mode="jev", canary_percentage=100, jev_api_key="test-key")
    base.update(kwargs)
    return DecisionEngineSettings(**base)


class FakeJev:
    def __init__(self, capability: str = "database.query", confidence: float = 0.94) -> None:
        self.calls = 0
        self._capability = capability
        self._confidence = confidence

    async def system_one(self, **kwargs):
        self.calls += 1
        return {
            "model": "jev-latest",
            "answers": {
                "capability": {
                    "type": "choice",
                    "choice": self._capability,
                    "confidence": self._confidence,
                    "probabilities": {self._capability: self._confidence},
                },
                "domain": {"type": "choice", "choice": "operations", "confidence": 0.8},
                "complexity": {"type": "score", "score": 1.0, "confidence": 0.8},
                "needs_private_knowledge": {"type": "noul", "noul": 0.9},
                "needs_complex_reasoning": {"type": "noul", "noul": 0.1},
                "needs_action": {"type": "noul", "noul": 0.1},
                "retrieved_info_sufficient": {"type": "noul", "noul": 0.1},
            },
            "usage": {"input_tokens": 12, "output_tokens": 6},
        }


class RecordingTracer:
    def __init__(self) -> None:
        self.traces: list = []

    async def record(self, trace) -> None:
        self.traces.append(trace)


class StubStore:
    def __init__(self) -> None:
        self.updated: list[dict] = []
        self.recorded: list = []

    async def update_actual(self, trace_id, *, actual_capability, jev_capability=None) -> None:
        self.updated.append(
            {
                "trace_id": trace_id,
                "actual": actual_capability,
                "jev": jev_capability,
            }
        )

    async def record(self, trace) -> None:
        self.recorded.append(trace)


def _hook(settings: DecisionEngineSettings, *, jev=None, tracer=None) -> OrchestratorDecisionHook:
    registry = InMemoryCapabilityRegistry()
    provider_obj = jev
    if jev is not None and not isinstance(jev, JevDecisionProvider):
        # Tests pass a raw client; the provider owns transport + circuit.
        provider_obj = JevDecisionProvider(settings, client=jev)
    provider = CompositeDecisionProvider(
        settings=settings,
        rules=RulesDecisionProvider(),
        jev=provider_obj,
        registry=registry,
    )
    engine = DecisionEngine(
        provider,
        settings,
        registry=registry,
        tracer=tracer,
        jev=provider_obj,
    )
    return OrchestratorDecisionHook(engine)


async def _evaluate(hook: OrchestratorDecisionHook, *, query: str, **kwargs):
    kwargs.setdefault("sql_enabled", True)
    return await hook.evaluate(
        organization_id=uuid4(),
        request_id=uuid4(),
        user_id=None,
        query=query,
        role="admin",
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _no_wallet_db(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_budget(_oid):
        return {"remaining_ok": True, "prefer_cheap": False, "on_limit": "block"}

    monkeypatch.setattr("src.runtime.wallet.snapshot_budget", fake_budget)


# ---------------------------------------------------------------------------
# Authorization: SQL availability must not be stripped by the hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hook_keeps_sql_routing_without_caller_permissions() -> None:
    hook = _hook(_settings())
    decision = await _evaluate(hook, query=_SQL_QUERY)
    assert decision.capability == "database.query"
    assert decision.resolved is True
    assert decision.metadata["acting"] is True


@pytest.mark.asyncio
async def test_hook_downgrades_sql_when_sql_disabled() -> None:
    hook = _hook(_settings())
    decision = await _evaluate(hook, query=_SQL_QUERY, sql_enabled=False)
    assert decision.capability == "knowledge.answer"
    assert decision.resolved is False
    assert retrieval_hint(decision)["prefer_sql"] is False


@pytest.mark.asyncio
async def test_hook_tenant_allowlist_blocks_sql() -> None:
    hook = _hook(_settings())
    decision = await _evaluate(
        hook,
        query=_SQL_QUERY,
        tenant_policy={"capability_allowlist": ["knowledge.answer"]},
    )
    assert decision.capability == "knowledge.answer"
    assert decision.metadata.get("authorization_denied") is True


# ---------------------------------------------------------------------------
# Shadow / sampling never act
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shadow_rules_do_not_act_and_hints_are_noop() -> None:
    settings = _settings(routing_mode="legacy", shadow_mode=True)
    hook = _hook(settings)
    decision = await _evaluate(hook, query=_SQL_QUERY)
    assert decision.resolved is False
    assert decision.provider == "legacy"
    assert decision.metadata["acting"] is False
    assert decision.metadata["rules_candidate"] is not None
    assert retrieval_hint(decision) == {"prefer_sql": False, "skip_sql": False}


@pytest.mark.asyncio
async def test_sampled_shadow_observes_without_acting() -> None:
    settings = _settings(routing_mode="legacy", shadow_sample_rate=1.0)
    jev = FakeJev()
    hook = _hook(settings, jev=jev)
    decision = await _evaluate(hook, query=_DOC_QUERY)
    assert jev.calls == 1
    assert decision.resolved is False
    assert decision.metadata["acting"] is False
    assert decision.raw_answers["jev"]["capability"] == "database.query"


@pytest.mark.asyncio
async def test_acting_decision_records_trace_id() -> None:
    tracer = RecordingTracer()
    hook = _hook(_settings(), tracer=tracer)
    decision = await _evaluate(hook, query=_DOC_QUERY)
    assert tracer.traces
    assert decision.metadata.get("trace_id") == str(tracer.traces[0].decision_id)


# ---------------------------------------------------------------------------
# Ground truth after execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_after_actual_updates_trace_with_actual_capability() -> None:
    tracer = RecordingTracer()
    hook = _hook(_settings(), tracer=tracer)
    decision = await _evaluate(hook, query=_DOC_QUERY)
    store = StubStore()
    hook._store = store  # noqa: SLF001 — test seam
    await hook.after_actual(
        organization_id=uuid4(),
        request_id=uuid4(),
        user_id=None,
        query=_DOC_QUERY,
        actual_method="rag",
        engine_decision=decision,
        sql_enabled=True,
    )
    assert store.updated
    assert store.updated[0]["actual"] == "knowledge.answer"
    assert store.updated[0]["trace_id"] == decision.metadata["trace_id"]


# ---------------------------------------------------------------------------
# Capability catalog: advisory capabilities are not routable
# ---------------------------------------------------------------------------

def test_advisory_capabilities_are_not_offered() -> None:
    ids = default_capability_ids(sql_enabled=True, knowledge_enabled=True)
    assert "agent.execute" not in ids
    assert "workflow.execute" not in ids
    assert "tool.call_api" not in ids
    assert "database.query" in ids
    assert "respond_directly" in ids


def test_registry_marks_advisory_availability() -> None:
    registry = InMemoryCapabilityRegistry()
    assert registry.is_allowed(
        "agent.execute", permissions=frozenset({"*"})
    )
    spec = registry.get("agent.execute")
    assert spec is not None and spec.availability == "advisory"
    assert registry.get("database.query").availability == "available"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Transport errors never break the caller
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jev_transport_error_falls_back_to_legacy() -> None:
    class DownJev:
        calls = 0

        async def system_one(self, **kwargs):
            self.calls += 1
            raise JevTransportError("down")

    hook = _hook(_settings(routing_mode="legacy", shadow_mode=True), jev=DownJev())
    decision = await _evaluate(hook, query=_DOC_QUERY)
    assert decision.resolved is False
    assert decision.provider == "legacy"


def test_decision_context_defaults_remain_legacy() -> None:
    ctx = DecisionContext(user_request="hola", organization_id=uuid4())
    assert ctx.permissions == frozenset()
    decision = RoutingDecision()
    assert decision.provider == "legacy"
    assert retrieval_hint(decision) == {"prefer_sql": False, "skip_sql": False}
