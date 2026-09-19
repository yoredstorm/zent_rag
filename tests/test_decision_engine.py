# =============================================================================
# Decision Engine — unit tests (JEV mocked; no live API).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.decision import ComplexityLevel, DecisionContext, RoutingDecision
from src.core.domain.entities import LLMResponse
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.decision.composite import CompositeDecisionProvider
from src.decision.engine import DecisionEngine
from src.decision.hook import retrieval_hint
from src.decision.policy import authorize_decision
from src.decision.providers.jev import JevDecisionProvider, JevTransportError
from src.decision.providers.llm import LLMDecisionProvider
from src.decision.questions import (
    build_routing_questions,
    noul_certainty,
    noul_is_uncertain,
    noul_is_yes,
)
from src.decision.routing import in_canary
from src.decision.rules import RulesDecisionProvider
from src.decision.settings import DecisionEngineSettings
from src.decision.shadow import compare_shadow


def _ctx(**kwargs) -> DecisionContext:
    defaults = dict(
        user_request="hola",
        organization_id=uuid4(),
        request_id=uuid4(),
        sql_enabled=True,
        knowledge_enabled=True,
        available_capabilities=(
            "knowledge.search",
            "knowledge.answer",
            "database.query",
            "respond_directly",
            "llm.reason",
            "agent.execute",
            "workflow.execute",
            "tool.call_api",
        ),
        permissions=frozenset({"*"}),
    )
    defaults.update(kwargs)
    return DecisionContext(**defaults)


def _settings(**kwargs) -> DecisionEngineSettings:
    base = dict(
        routing_mode="jev",
        high_confidence=0.90,
        low_confidence=0.65,
        canary_percentage=100,
        fallback_model="cheap",
        jev_api_key="test-key",
    )
    base.update(kwargs)
    return DecisionEngineSettings(**base)


class FakeJev:
    def __init__(self, answers: dict, exc: Exception | None = None) -> None:
        self.answers = answers
        self.exc = exc
        self.calls = 0
        self.last_state = None
        self.last_questions = None

    async def system_one(self, **kwargs):
        self.calls += 1
        self.last_state = kwargs.get("state")
        self.last_questions = kwargs.get("questions")
        if self.exc:
            raise self.exc
        return {
            "model": "jev-latest",
            "answers": self.answers,
            "usage": {"input_tokens": 12, "output_tokens": 6},
        }


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def generate(self, **kwargs) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=self.content, model="novita-small")


def _choice_answers(capability: str, confidence: float, **noul: float) -> dict:
    return {
        "capability": {
            "type": "choice",
            "choice": capability,
            "confidence": confidence,
            "probabilities": {capability: max(confidence, 0.51), "respond_directly": 0.1},
        },
        "domain": {"type": "choice", "choice": "policy", "confidence": 0.8, "probabilities": {}},
        "complexity": {"type": "score", "score": 1.0, "confidence": 0.8},
        "needs_private_knowledge": {"type": "noul", "noul": noul.get("knowledge", 0.9)},
        "needs_complex_reasoning": {"type": "noul", "noul": noul.get("reasoning", 0.1)},
        "needs_action": {"type": "noul", "noul": noul.get("action", 0.1)},
        "retrieved_info_sufficient": {"type": "noul", "noul": noul.get("sufficient", 0.1)},
    }


# ---------------------------------------------------------------------------
# Questions / noul
# ---------------------------------------------------------------------------

def test_atomic_questions_share_one_state_payload() -> None:
    questions = build_routing_questions(("knowledge.answer", "database.query"))
    assert questions["capability"]["type"] == "choice"
    assert questions["complexity"]["type"] == "score"
    assert questions["needs_private_knowledge"]["type"] == "noul"
    assert "knowledge.answer" in questions["capability"]["criteria"]


def test_noul_certainty_and_gates() -> None:
    assert noul_certainty(0.5) == 0.0
    assert noul_certainty(1.0) == 1.0
    assert noul_is_yes(0.9, 0.65)
    assert noul_is_uncertain(0.5, 0.65, 0.35)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rules_explicit_capability() -> None:
    provider = RulesDecisionProvider()
    result = await provider.decide(_ctx(explicit_capability="workflow.execute"))
    assert result.resolved is True
    assert result.capability == "workflow.execute"
    assert result.provider == "rules"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_rules_explicit_tool_and_workflow() -> None:
    provider = RulesDecisionProvider()
    tool = await provider.decide(_ctx(explicit_tool="call_api"))
    assert tool.capability == "tool.call_api"
    wf = await provider.decide(_ctx(explicit_workflow_id="wf-1"))
    assert wf.capability == "workflow.execute"


@pytest.mark.asyncio
async def test_rules_sql_heuristic_slam_dunk() -> None:
    provider = RulesDecisionProvider()
    result = await provider.decide(
        _ctx(user_request="cuánto vendimos este mes en total")
    )
    assert result.resolved is True
    assert result.capability == "database.query"


@pytest.mark.asyncio
async def test_rules_ambiguous_stays_unresolved() -> None:
    provider = RulesDecisionProvider()
    result = await provider.decide(
        _ctx(user_request="qué es la política de vacaciones del manual")
    )
    assert result.resolved is False


# ---------------------------------------------------------------------------
# JEV Choice / Score / Noul
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jev_choice_routing() -> None:
    client = FakeJev(_choice_answers("database.query", 0.94))
    provider = JevDecisionProvider(_settings(), client=client)
    result = await provider.decide(_ctx(user_request="total de ventas"))
    assert result.capability == "database.query"
    assert result.confidence >= 0.9
    assert result.provider == "jev"
    assert "capability" in (client.last_questions or {})
    assert "user_request" in (client.last_state or {})


@pytest.mark.asyncio
async def test_jev_noul_gates() -> None:
    client = FakeJev(_choice_answers("llm.reason", 0.92, reasoning=0.95, knowledge=0.1))
    result = await JevDecisionProvider(_settings(), client=client).decide(_ctx())
    assert result.needs_reasoning is True
    assert result.needs_knowledge is False


@pytest.mark.asyncio
async def test_jev_score_complexity() -> None:
    answers = _choice_answers("llm.reason", 0.91)
    answers["complexity"] = {"type": "score", "score": 2.8, "confidence": 0.9}
    result = await JevDecisionProvider(_settings(), client=FakeJev(answers)).decide(_ctx())
    assert result.complexity == ComplexityLevel.REASONING


@pytest.mark.asyncio
async def test_jev_invalid_capability_raises() -> None:
    client = FakeJev(_choice_answers("not-a-cap", 0.99))
    with pytest.raises(JevTransportError):
        await JevDecisionProvider(_settings(), client=client).decide(_ctx())


@pytest.mark.asyncio
async def test_jev_unavailable_raises() -> None:
    client = FakeJev({}, exc=JevTransportError("down"))
    with pytest.raises(JevTransportError):
        await JevDecisionProvider(_settings(), client=client).decide(_ctx())


# ---------------------------------------------------------------------------
# Confidence / fallback / composite
# ---------------------------------------------------------------------------

def _composite(settings, jev=None, llm=None) -> CompositeDecisionProvider:
    return CompositeDecisionProvider(
        settings=settings,
        rules=RulesDecisionProvider(sql_threshold=1.1),  # force unresolved heuristics
        jev=jev,
        llm=llm,
        registry=InMemoryCapabilityRegistry(),
    )


@pytest.mark.asyncio
async def test_high_confidence_executes_jev() -> None:
    jev = JevDecisionProvider(
        _settings(), client=FakeJev(_choice_answers("knowledge.answer", 0.95))
    )
    result = await _composite(_settings(), jev=jev).decide(_ctx())
    assert result.resolved is True
    assert result.provider == "jev"
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_mid_confidence_secondary_llm() -> None:
    jev = JevDecisionProvider(
        _settings(), client=FakeJev(_choice_answers("database.query", 0.72))
    )
    llm = LLMDecisionProvider(
        FakeLLM(
            '{"capability":"knowledge.answer","intent":"docs","complexity":"bounded",'
            '"needs_knowledge":true,"needs_agent":false,"needs_workflow":false,'
            '"needs_tool":false,"needs_reasoning":false,"confidence":0.7}'
        ),
        _settings(),
    )
    result = await _composite(_settings(), jev=jev, llm=llm).decide(_ctx())
    assert result.fallback_used is True
    assert result.capability == "knowledge.answer"


@pytest.mark.asyncio
async def test_low_confidence_falls_to_llm() -> None:
    jev = JevDecisionProvider(
        _settings(), client=FakeJev(_choice_answers("database.query", 0.2))
    )
    llm = LLMDecisionProvider(
        FakeLLM(
            '{"capability":"knowledge.answer","intent":"docs","complexity":"bounded",'
            '"needs_knowledge":true,"needs_agent":false,"needs_workflow":false,'
            '"needs_tool":false,"needs_reasoning":false,"confidence":0.6}'
        ),
        _settings(),
    )
    result = await _composite(_settings(), jev=jev, llm=llm).decide(_ctx())
    assert result.provider == "llm"
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_jev_unavailable_uses_llm_fallback() -> None:
    jev = JevDecisionProvider(
        _settings(), client=FakeJev({}, exc=JevTransportError("timeout"))
    )
    llm = LLMDecisionProvider(
        FakeLLM(
            '{"capability":"knowledge.answer","intent":"docs","complexity":"bounded",'
            '"needs_knowledge":true,"needs_agent":false,"needs_workflow":false,'
            '"needs_tool":false,"needs_reasoning":false,"confidence":0.6}'
        ),
        _settings(),
    )
    result = await _composite(_settings(), jev=jev, llm=llm).decide(_ctx())
    assert result.fallback_used is True
    assert result.capability == "knowledge.answer"


@pytest.mark.asyncio
async def test_legacy_does_not_act() -> None:
    jev = JevDecisionProvider(
        _settings(), client=FakeJev(_choice_answers("database.query", 0.99))
    )
    result = await _composite(_settings(routing_mode="legacy"), jev=jev).decide(_ctx())
    assert result.resolved is False
    assert result.provider == "legacy"


# ---------------------------------------------------------------------------
# Shadow / canary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shadow_records_jev_without_acting() -> None:
    client = FakeJev(_choice_answers("database.query", 0.93))
    jev = JevDecisionProvider(_settings(), client=client)
    result = await _composite(
        _settings(routing_mode="legacy", shadow_mode=True), jev=jev
    ).decide(_ctx())
    assert result.resolved is False
    assert client.calls == 1
    assert result.raw_answers["jev"]["capability"] == "database.query"
    trace = compare_shadow(
        actual_method="rag",
        engine_decision=result,
        context=_ctx(),
    )
    assert trace.shadow is True
    assert trace.agreement is False


def test_canary_boundaries() -> None:
    rid = uuid4()
    assert in_canary(rid, 0) is False
    assert in_canary(rid, 100) is True
    hits = sum(1 for _ in range(40) if in_canary(uuid4(), 5))
    assert 0 <= hits <= 20


@pytest.mark.asyncio
async def test_hybrid_canary_zero_stays_legacy() -> None:
    jev = JevDecisionProvider(
        _settings(), client=FakeJev(_choice_answers("database.query", 0.99))
    )
    result = await _composite(
        _settings(routing_mode="hybrid", canary_percentage=0), jev=jev
    ).decide(_ctx())
    assert result.resolved is False


# ---------------------------------------------------------------------------
# Authorization / tenant
# ---------------------------------------------------------------------------

def test_authorization_blocks_tool_without_permission() -> None:
    decision = RoutingDecision(
        capability="tool.call_api",
        resolved=True,
        provider="jev",
        confidence=0.99,
    )
    out = authorize_decision(
        decision,
        _ctx(permissions=frozenset()),
    )
    assert out.capability == "knowledge.answer"
    assert out.fallback_used is True
    assert out.metadata["denied_capability"] == "tool.call_api"


def test_tenant_allowlist_blocks_capability() -> None:
    decision = RoutingDecision(
        capability="database.query",
        resolved=True,
        provider="jev",
        confidence=0.99,
    )
    ctx = _ctx(
        tenant_policy={"capability_allowlist": ["knowledge.answer"]},
        permissions=frozenset({"*"}),
    )
    out = authorize_decision(decision, ctx)
    assert out.capability == "knowledge.answer"


def test_capability_not_in_available_is_denied() -> None:
    decision = RoutingDecision(capability="agent.execute", resolved=True, provider="jev")
    out = authorize_decision(decision, _ctx(available_capabilities=("knowledge.answer",)))
    assert out.capability == "knowledge.answer"


def test_retrieval_hint_only_when_resolved() -> None:
    unresolved = RoutingDecision(resolved=False, capability="database.query")
    assert retrieval_hint(unresolved)["prefer_sql"] is False
    resolved = RoutingDecision(resolved=True, capability="database.query")
    assert retrieval_hint(resolved)["prefer_sql"] is True


# ---------------------------------------------------------------------------
# Engine facade + metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_authorize_after_provider() -> None:
    class Granting:
        name = "rules"

        async def decide(self, context):
            return RoutingDecision(
                capability="tool.call_api",
                resolved=True,
                provider="jev",
                confidence=0.99,
            )

    engine = DecisionEngine(
        Granting(),
        _settings(),
        registry=InMemoryCapabilityRegistry(),
    )
    out = await engine.decide(_ctx(permissions=frozenset()))
    assert out.capability == "knowledge.answer"


def test_metrics_record_does_not_raise() -> None:
    from src.decision.metrics import record_agreement, record_decision

    record_decision(
        RoutingDecision(provider="jev", capability="knowledge.answer", resolved=True, fallback_used=True, metadata={"reason": "timeout"})
    )
    record_agreement(True)


def test_health_snapshot() -> None:
    from src.decision.health import decision_health

    snap = decision_health(_settings(fallback_model="novita-small", jev_api_key=""))
    assert snap["rules_loaded"] is True
    assert snap["jev"] == "not_configured"
    assert snap["fallback_available"] == "available"
