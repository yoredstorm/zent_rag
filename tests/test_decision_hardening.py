# =============================================================================
# Decision Engine P0 hardening — Noul 0.0, pricing registry, judge context.
# =============================================================================
# Sin API JEV real: cliente fake + resolvers inyectados. Postgres/Redis siguen
# viniendo del stack de la suite (fixtures autouse de conftest).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.decision.costs import (
    SOURCE_LEGACY,
    SOURCE_NONE,
    SOURCE_REGISTRY,
    DecisionCost,
    qualified_model,
    resolve_cost,
)
from src.decision.engine import DecisionEngine
from src.decision.judgment import (
    PHASE_EVIDENCE,
    PHASE_GROUNDING,
    PHASE_PRE_RETRIEVAL,
    PHASE_TOOL_ROUTING,
    JudgmentContext,
    call_judge,
)
from src.decision.providers.jev import JevDecisionProvider, JevTransportError
from src.decision.questions import noul_from_answer, safe_noul
from src.decision.rules import RulesDecisionProvider
from src.decision.settings import DecisionEngineSettings
from src.decision.usage import DecisionUsageRecorder


def _settings(**kwargs) -> DecisionEngineSettings:
    base = dict(
        routing_mode="jev",
        canary_percentage=100,
        fallback_model="cheap",
        jev_api_key="test-key",
        estimated_cost_per_1k=0.0005,
    )
    base.update(kwargs)
    return DecisionEngineSettings(**base)


def _ctx(**kwargs) -> DecisionContext:
    defaults = dict(
        user_request="hola",
        organization_id=uuid4(),
        request_id=uuid4(),
        sql_enabled=True,
        knowledge_enabled=True,
        available_capabilities=("knowledge.answer", "database.query", "respond_directly"),
        permissions=frozenset({"*"}),
    )
    defaults.update(kwargs)
    return DecisionContext(**defaults)


def _answers(
    capability: str = "knowledge.answer",
    confidence: float = 0.94,
    *,
    knowledge: float = 0.9,
    reasoning: float = 0.1,
    action: float = 0.1,
) -> dict:
    return {
        "capability": {
            "type": "choice",
            "choice": capability,
            "confidence": confidence,
            "probabilities": {capability: max(confidence, 0.51)},
        },
        "domain": {"type": "choice", "choice": "policy", "confidence": 0.8},
        "complexity": {"type": "score", "score": 1.0, "confidence": 0.8},
        "needs_private_knowledge": {"type": "noul", "noul": knowledge},
        "needs_complex_reasoning": {"type": "noul", "noul": reasoning},
        "needs_action": {"type": "noul", "noul": action},
        "retrieved_info_sufficient": {"type": "noul", "noul": 0.1},
    }


class FakeJev:
    """Transporte fake: nunca toca la API real."""

    def __init__(self, answers: dict, *, usage: dict | None = None) -> None:
        self.answers = answers
        self.usage = usage if usage is not None else {"input_tokens": 12, "output_tokens": 6}
        self.calls = 0
        self.last_model: str | None = None

    async def system_one(self, **kwargs):
        self.calls += 1
        self.last_model = kwargs.get("model")
        return {
            "model": kwargs.get("model") or "jev-latest",
            "answers": self.answers,
            "usage": self.usage,
        }


class RecordingUsage:
    def __init__(self) -> None:
        self.decisions: list = []
        self.judges: list = []

    async def record(self, context, decision) -> None:
        self.decisions.append((context, decision))

    async def record_judge(self, context, payload) -> None:
        self.judges.append((context, payload))


class RecordingTracer:
    def __init__(self) -> None:
        self.traces: list = []

    async def record(self, trace) -> None:
        self.traces.append(trace)


def _price(**kwargs):
    from src.platform.billing.pricing import PriceRecord

    base = dict(
        provider="jev",
        model="jev-latest",
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.02,
        embedding_cost_per_1k=0.0,
        request_cost=0.001,
        cost_kind="provider",
    )
    base.update(kwargs)
    return PriceRecord(**base)


# ---------------------------------------------------------------------------
# P0.2 — Noul 0.0 / 1.0 / missing / inválido
# ---------------------------------------------------------------------------


def test_safe_noul_conserva_cero_y_uno() -> None:
    assert safe_noul(0.0) == 0.0
    assert safe_noul(1.0) == 1.0
    assert safe_noul(0.42) == pytest.approx(0.42)
    assert safe_noul(False) == 0.0
    assert safe_noul(True) == 1.0


def test_safe_noul_fallback_controlado() -> None:
    assert safe_noul(None, 0.5) == 0.5
    assert safe_noul(None, 0.0) == 0.0
    assert safe_noul("0") == 0.0
    assert safe_noul("1") == 1.0
    assert safe_noul("no-es-numero", 0.5) == 0.5
    assert safe_noul(object(), 0.35) == 0.35


def test_noul_from_answer_distingue_missing_de_cero() -> None:
    assert noul_from_answer(None, 0.5) == 0.5
    assert noul_from_answer({}, 0.5) == 0.5
    assert noul_from_answer({"type": "noul"}, 0.5) == 0.5
    assert noul_from_answer({"type": "noul", "noul": None}, 0.5) == 0.5
    assert noul_from_answer({"type": "noul", "noul": 0.0}, 0.5) == 0.0
    assert noul_from_answer({"type": "noul", "noul": 1.0}, 0.5) == 1.0


@pytest.mark.asyncio
async def test_jev_provider_conserva_noul_cero() -> None:
    client = FakeJev(_answers(knowledge=0.0, reasoning=0.0, action=0.0))
    result = await JevDecisionProvider(_settings(), client=client).decide(_ctx())
    assert result.needs_knowledge is False
    assert result.needs_reasoning is False
    assert result.needs_tool is False
    # Antes del fix, 0.0 caía a 0.5 (incierto) y capaba la confianza a 0.775.
    assert result.confidence == pytest.approx(0.94)
    assert result.metadata["noul_certainty"] == 1.0


@pytest.mark.asyncio
async def test_jev_provider_noul_uno_se_conserva() -> None:
    client = FakeJev(_answers(knowledge=1.0, reasoning=1.0, action=1.0))
    result = await JevDecisionProvider(_settings(), client=client).decide(_ctx())
    assert result.needs_knowledge is True
    assert result.needs_reasoning is True
    assert result.metadata["noul_certainty"] == 1.0


# ---------------------------------------------------------------------------
# P0.3 — Pricing Registry canónico para JEV
# ---------------------------------------------------------------------------


def test_qualified_model_prefixa_provider() -> None:
    assert qualified_model("jev", "jev-latest") == "jev/jev-latest"
    assert qualified_model("jev", "openai/gpt-4o-mini") == "openai/gpt-4o-mini"
    assert qualified_model("", "jev-latest") == "jev-latest"
    assert qualified_model("default", "x") == "x"


@pytest.mark.asyncio
async def test_resolve_cost_usa_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_price(_model: str):
        return _price()

    monkeypatch.setattr("src.platform.billing.pricing.get_price", fake_get_price)
    cost = await resolve_cost(
        provider="jev",
        model="jev-latest",
        prompt_tokens=12,
        completion_tokens=6,
        legacy_per_1k=0.0005,
    )
    assert cost.source == SOURCE_REGISTRY
    assert cost.provider == "jev" and cost.model == "jev-latest"
    assert cost.cost_kind == "provider"
    expected = 12 / 1000 * 0.01 + 6 / 1000 * 0.02 + 0.001
    assert cost.amount == pytest.approx(expected)


@pytest.mark.asyncio
async def test_resolve_cost_fallback_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(_model: str):
        raise RuntimeError("pricing registry down")

    monkeypatch.setattr("src.platform.billing.pricing.get_price", boom)
    cost = await resolve_cost(
        provider="jev",
        model="jev-latest",
        prompt_tokens=12,
        completion_tokens=6,
        legacy_per_1k=0.0005,
    )
    assert cost.source == SOURCE_LEGACY
    assert cost.amount == pytest.approx(18 / 1000 * 0.0005)


@pytest.mark.asyncio
async def test_resolve_cost_sin_tokens_no_cobra() -> None:
    cost = await resolve_cost(provider="jev", model="jev-latest", legacy_per_1k=0.001)
    assert cost.amount == 0.0
    assert cost.source == SOURCE_NONE


@pytest.mark.asyncio
async def test_jev_decide_cobra_desde_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_price(_model: str):
        return _price()

    monkeypatch.setattr("src.platform.billing.pricing.get_price", fake_get_price)
    provider = JevDecisionProvider(_settings(), client=FakeJev(_answers()))
    result = await provider.decide(_ctx())
    assert result.estimated_cost == pytest.approx(12 / 1000 * 0.01 + 6 / 1000 * 0.02 + 0.001)
    assert result.metadata["cost_source"] == SOURCE_REGISTRY
    assert result.metadata["model"] == "jev-latest"
    assert result.metadata["model_role"] == "production"


@pytest.mark.asyncio
async def test_jev_decide_fallback_legacy_si_registry_cae(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(_model: str):
        raise RuntimeError("db down")

    monkeypatch.setattr("src.platform.billing.pricing.get_price", boom)
    provider = JevDecisionProvider(_settings(), client=FakeJev(_answers()))
    result = await provider.decide(_ctx())
    assert result.estimated_cost == pytest.approx(18 / 1000 * 0.0005)
    assert result.metadata["cost_source"] == SOURCE_LEGACY


@pytest.mark.asyncio
async def test_jev_judge_usa_resolver_inyectado() -> None:
    async def resolver(*, provider, model, prompt_tokens, completion_tokens):
        assert provider == "jev"
        assert prompt_tokens == 12 and completion_tokens == 6
        return DecisionCost(amount=0.00042, source=SOURCE_REGISTRY, provider="jev", model=model)

    provider = JevDecisionProvider(
        _settings(), client=FakeJev(_answers()), cost_resolver=resolver
    )
    payload = await provider.judge(state={"x": 1}, questions={"y": 2})
    assert payload["estimated_cost"] == pytest.approx(0.00042)
    assert payload["provider"] == "jev"
    assert payload["model"] == "jev-latest"
    assert payload["latency_ms"] >= 0.0


# ---------------------------------------------------------------------------
# P0.4 — JudgmentContext + usage event por judge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_judge_respeta_fakes_sin_contexto() -> None:
    class Legacy:
        async def judge(self, *, state, questions):
            return {"legacy": True}

    class Aware:
        def __init__(self) -> None:
            self.context = None

        async def judge(self, *, state, questions, context=None):
            self.context = context
            return {"aware": True}

    ctx = JudgmentContext(phase=PHASE_TOOL_ROUTING)
    # Callable directo (bound method) y objeto con .judge (DecisionEngine).
    assert (await call_judge(Legacy().judge, state={}, questions={}, context=ctx))["legacy"] is True
    assert (await call_judge(Legacy(), state={}, questions={}, context=ctx))["legacy"] is True
    aware = Aware()
    await call_judge(aware, state={}, questions={}, context=ctx)
    assert aware.context is ctx


@pytest.mark.asyncio
async def test_engine_judge_enriquece_y_pasa_contexto() -> None:
    usage = RecordingUsage()
    provider = JevDecisionProvider(_settings(), client=FakeJev(_answers()))
    engine = DecisionEngine(
        RulesDecisionProvider(), _settings(), usage=usage, jev=provider
    )
    org, rid = uuid4(), uuid4()
    payload = await engine.judge(
        state={"user_request": "x"},
        questions={"q": {"type": "noul"}},
        context=JudgmentContext(
            phase=PHASE_EVIDENCE,
            organization_id=org,
            request_id=rid,
            capability="knowledge.answer",
        ),
    )
    assert payload is not None
    assert payload["provider"] == "jev"
    assert payload["model"] == "jev-latest"
    assert payload["estimated_cost"] >= 0.0
    assert payload["latency_ms"] >= 0.0
    assert usage.judges
    context, recorded = usage.judges[0]
    assert context.phase == PHASE_EVIDENCE
    assert context.organization_id == org and context.request_id == rid
    assert recorded["model"] == "jev-latest"


@pytest.mark.asyncio
async def test_engine_judge_sin_contexto_no_rompe() -> None:
    usage = RecordingUsage()
    provider = JevDecisionProvider(_settings(), client=FakeJev(_answers()))
    engine = DecisionEngine(
        RulesDecisionProvider(), _settings(), usage=usage, jev=provider
    )
    payload = await engine.judge(state={}, questions={})
    assert payload is not None and payload["model"] == "jev-latest"
    assert usage.judges[0][0].organization_id is None


@pytest.mark.asyncio
async def test_engine_judge_error_no_rompe_el_request() -> None:
    class Boom:
        async def judge(self, *, state, questions):
            raise RuntimeError("JEV down")

    engine = DecisionEngine(RulesDecisionProvider(), _settings(), jev=Boom())
    assert await engine.judge(state={}, questions={}) is None
    assert await engine.judge(state={}, questions={}, context=JudgmentContext(phase=PHASE_EVIDENCE)) is None


@pytest.mark.asyncio
async def test_usage_event_de_judge_lleva_provider_model_y_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list = []

    async def fake_record_event(event):
        captured.append(event)
        return True

    monkeypatch.setattr("src.platform.usage.usage_engine.record_event", fake_record_event)
    recorder = DecisionUsageRecorder()
    org, rid, aid, run, wf = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    context = JudgmentContext(
        phase=PHASE_EVIDENCE,
        organization_id=org,
        request_id=rid,
        agent_id=aid,
        run_id=run,
        workflow_id=wf,
        capability="knowledge.answer",
    )
    payload = {
        "provider": "jev",
        "model": "jev-latest",
        "usage": {"input_tokens": 10, "output_tokens": 4},
        "estimated_cost": 0.002,
        "latency_ms": 120.0,
    }
    await recorder.record_judge(context, payload)
    assert len(captured) == 1
    event = captured[0]
    assert event.event_type == "jev_judge:evidence"
    assert event.request_id == rid and event.organization_id == org
    assert event.provider == "jev" and event.model == "jev-latest"
    assert event.prompt_tokens == 10 and event.completion_tokens == 4
    assert event.total_tokens == 14
    assert event.estimated_cost == pytest.approx(0.002)
    assert event.routing["phase"] == PHASE_EVIDENCE
    assert event.routing["capability"] == "knowledge.answer"
    assert event.routing["workflow_id"] == str(wf)
    assert event.routing["run_id"] == str(run)


@pytest.mark.asyncio
async def test_usage_event_de_judge_no_se_duplica_por_fase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list = []

    async def fake_record_event(event):
        captured.append(event)
        return True

    monkeypatch.setattr("src.platform.usage.usage_engine.record_event", fake_record_event)
    recorder = DecisionUsageRecorder()
    org, rid = uuid4(), uuid4()
    payload = {"provider": "jev", "model": "jev-latest", "usage": {"input_tokens": 1}}
    evidence = JudgmentContext(phase=PHASE_EVIDENCE, organization_id=org, request_id=rid)
    await recorder.record_judge(evidence, payload)
    await recorder.record_judge(evidence, payload)  # retry del mismo juicio
    await recorder.record_judge(
        JudgmentContext(phase=PHASE_GROUNDING, organization_id=org, request_id=rid),
        payload,
    )
    keys = [(str(e.request_id), e.event_type) for e in captured]
    # Mismo (request_id, event_type) → el UNIQUE de usage_events dedupe el retry.
    assert keys[0] == keys[1] == (str(rid), "jev_judge:evidence")
    assert keys[2] == (str(rid), "jev_judge:grounding")


@pytest.mark.asyncio
async def test_usage_event_de_judge_no_doble_cobra_en_db() -> None:
    """Idempotencia real: dos retries del mismo juicio = una fila y un costo."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.usage.usage_engine import ensure_usage_table

    await ensure_usage_table()
    recorder = DecisionUsageRecorder()
    org, rid = uuid4(), uuid4()
    context = JudgmentContext(phase=PHASE_EVIDENCE, organization_id=org, request_id=rid)
    payload = {
        "provider": "jev",
        "model": "jev-latest",
        "usage": {"input_tokens": 5, "output_tokens": 2},
        "estimated_cost": 0.001,
    }
    await recorder.record_judge(context, payload)
    await recorder.record_judge(context, payload)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS n, "
                    "COALESCE(SUM(estimated_cost), 0)::float AS cost "
                    "FROM usage_events WHERE request_id = :rid"
                ),
                {"rid": rid},
            )
        ).fetchone()
        assert row.n == 1
        assert float(row.cost) == pytest.approx(0.001)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_judge_sin_tenant_no_emite_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list = []

    async def fake_record_event(event):
        captured.append(event)
        return True

    monkeypatch.setattr("src.platform.usage.usage_engine.record_event", fake_record_event)
    recorder = DecisionUsageRecorder()
    await recorder.record_judge(
        JudgmentContext(phase=PHASE_PRE_RETRIEVAL), {"provider": "jev"}
    )
    await recorder.record_judge(
        JudgmentContext(phase=PHASE_PRE_RETRIEVAL, organization_id=uuid4()),
        {"provider": "jev"},
    )
    assert captured == []


@pytest.mark.asyncio
async def test_run_id_actua_como_request_id_en_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list = []

    async def fake_record_event(event):
        captured.append(event)
        return True

    monkeypatch.setattr("src.platform.usage.usage_engine.record_event", fake_record_event)
    recorder = DecisionUsageRecorder()
    run_id = uuid4()
    await recorder.record_judge(
        JudgmentContext(
            phase=PHASE_TOOL_ROUTING,
            organization_id=uuid4(),
            run_id=run_id,
        ),
        {"provider": "jev", "usage": {"input_tokens": 3, "output_tokens": 1}},
    )
    assert captured and captured[0].request_id == run_id


# ---------------------------------------------------------------------------
# P0.5 — Modelo efectivo observable (producción vs canary)
# ---------------------------------------------------------------------------


def test_jev_model_for_respeta_canary() -> None:
    settings = _settings(
        jev_model="jev-latest",
        jev_canary_model="jev-canary",
        jev_canary_percentage=100,
    )
    assert settings.jev_model_for(uuid4()) == "jev-canary"
    off = _settings(
        jev_model="jev-latest", jev_canary_model="jev-canary", jev_canary_percentage=0
    )
    assert off.jev_model_for(uuid4()) == "jev-latest"
    empty = _settings(jev_model="jev-latest", jev_canary_model="")
    assert empty.jev_model_for(uuid4()) == "jev-latest"


@pytest.mark.asyncio
async def test_jev_canary_model_queda_en_decision_y_trace() -> None:
    settings = _settings(
        jev_model="jev-latest",
        jev_canary_model="jev-canary",
        jev_canary_percentage=100,
    )
    client = FakeJev(_answers())
    tracer = RecordingTracer()
    provider = JevDecisionProvider(settings, client=client)
    engine = DecisionEngine(provider, settings, tracer=tracer)
    decision = await engine.decide(_ctx())
    assert client.last_model == "jev-canary"
    assert decision.metadata["model"] == "jev-canary"
    assert decision.metadata["model_role"] == "canary"
    assert tracer.traces and tracer.traces[0].model == "jev-canary"


# ---------------------------------------------------------------------------
# P0.6 / P0.7 — métricas por fase y circuit breaker
# ---------------------------------------------------------------------------


def test_record_judge_acepta_phase() -> None:
    from src.decision.metrics import record_judge

    record_judge(
        {"usage": {"input_tokens": 2, "output_tokens": 1}, "estimated_cost": 0.0001},
        phase=PHASE_EVIDENCE,
        latency_ms=15.0,
    )
    record_judge(None, error=True, phase="fase-desconocida", latency_ms=1.0)


@pytest.mark.asyncio
async def test_circuit_breaker_sigue_abriendo() -> None:
    class Down:
        def __init__(self) -> None:
            self.calls = 0

        async def system_one(self, **kwargs):
            self.calls += 1
            raise JevTransportError("down")

    client = Down()
    settings = _settings(circuit_failure_threshold=2, circuit_recovery_seconds=60.0)
    provider = JevDecisionProvider(settings, client=client)
    for _ in range(2):
        with pytest.raises(JevTransportError):
            await provider.decide(_ctx())
    with pytest.raises(JevTransportError, match="circuit open"):
        await provider.decide(_ctx())
    assert client.calls == 2


@pytest.mark.asyncio
async def test_composite_sobrevive_a_jev_caido() -> None:
    from src.decision.composite import CompositeDecisionProvider

    class Down:
        async def system_one(self, **kwargs):
            raise JevTransportError("down")

    settings = _settings()
    jev = JevDecisionProvider(settings, client=Down())
    composite = CompositeDecisionProvider(
        settings=settings,
        rules=RulesDecisionProvider(sql_threshold=1.1),
        jev=jev,
    )
    result = await composite.decide(_ctx())
    assert result.resolved is False
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_decision_trace_publica_no_cambia() -> None:
    """Backward compatibility: RoutingDecision.to_public_dict sigue igual."""
    decision = RoutingDecision(capability="knowledge.answer", resolved=True, provider="jev")
    public = decision.to_public_dict()
    assert set(public) == {
        "intent",
        "capability",
        "complexity",
        "needs_knowledge",
        "needs_agent",
        "needs_workflow",
        "needs_tool",
        "needs_reasoning",
        "risk",
        "confidence",
        "provider",
        "latency_ms",
        "alternatives",
        "fallback_used",
        "resolved",
    }
