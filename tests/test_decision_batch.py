# =============================================================================
# Decision Engine batching — una llamada JEV por fase + cache request-scoped.
# =============================================================================
# Sin API JEV real: cliente fake. Cubre A-E, N, O, P del plan de batching:
#   A) routing + planner comparten una sola llamada en batch ON
#   B) batch OFF conserva el comportamiento legacy
#   C) shadow no cambia la ejecución
#   D) estado distinto produce un juicio nuevo
#   E) mismo request/estado/fase reutiliza el cache
#   N) los reintentos tienen límite
#   O) JEV caído cae al fallback determinístico
#   P) costo y usage incluyen las llamadas batched
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.adaptive import EvidenceItem, EvidenceSet
from src.core.domain.decision import DecisionContext
from src.decision.batch import (
    JudgmentCache,
    answer_for,
    build_agent_step_questions,
    build_phase_questions,
    build_post_generation_questions,
    build_post_retrieval_questions,
    compare_payloads,
    normalize_batch_mode,
    noul_for,
    state_fingerprint,
    validate_question_ids,
)
from src.decision.engine import DecisionEngine
from src.decision.judgment import (
    PHASE_AGENT_STEP,
    PHASE_POST_RETRIEVAL,
    PHASE_PRE_RETRIEVAL,
    JudgmentContext,
    call_phase_judge,
)
from src.decision.providers.jev import JevDecisionProvider, JevTransportError
from src.decision.rules import RulesDecisionProvider
from src.decision.settings import DecisionEngineSettings
from src.rag.adaptive.planner import AdaptivePlanner
from src.rag.adaptive.settings import AdaptiveRagSettings


def _settings(**kwargs) -> DecisionEngineSettings:
    base = dict(
        routing_mode="jev",
        canary_percentage=100,
        fallback_model="cheap",
        jev_api_key="test-key",
        batch_mode="on",
    )
    base.update(kwargs)
    return DecisionEngineSettings(**base)


def _ctx(request_id=None, **kwargs) -> DecisionContext:
    defaults = dict(
        user_request="¿Cuál es la política de devoluciones?",
        organization_id=uuid4(),
        request_id=request_id or uuid4(),
        sql_enabled=True,
        knowledge_enabled=True,
        available_capabilities=(
            "knowledge.answer",
            "database.query",
            "respond_directly",
        ),
        permissions=frozenset({"*"}),
    )
    defaults.update(kwargs)
    return DecisionContext(**defaults)


class FakeJev:
    """Responde cualquier pregunta pedida, sin tocar la API real."""

    def __init__(self) -> None:
        self.calls = 0
        self.questions: list[list[str]] = []
        self.states: list[dict] = []

    def _answer(self, qid: str, spec: dict) -> dict:
        qtype = str(spec.get("type") or "noul")
        if qtype == "choice":
            criteria = spec.get("criteria") or {}
            choice = next(
                (
                    key
                    for key in criteria
                    if key in {"knowledge.answer", "documents", "hybrid", "tool"}
                ),
                next(iter(criteria), "knowledge.answer"),
            )
            return {"type": "choice", "choice": choice, "confidence": 0.93, "probabilities": {choice: 0.93}}
        if qtype == "score":
            return {"type": "score", "score": 1.0, "confidence": 0.7}
        return {"type": "noul", "noul": 0.8}

    async def system_one(self, *, state, questions, model, timeout):
        self.calls += 1
        self.questions.append(sorted(questions))
        self.states.append(state)
        return {
            "model": model,
            "answers": {qid: self._answer(qid, spec) for qid, spec in questions.items()},
            "usage": {"input_tokens": 40, "output_tokens": 12},
        }


class DownJev:
    async def system_one(self, **kwargs):
        raise JevTransportError("down")


class RecordingUsage:
    def __init__(self) -> None:
        self.decisions: list = []
        self.judges: list = []

    async def record(self, context, decision) -> None:
        self.decisions.append((context, decision))

    async def record_judge(self, context, payload) -> None:
        self.judges.append((context, payload))


def _engine(client, *, batch_mode="on", usage=None, cache=None) -> DecisionEngine:
    settings = _settings(batch_mode=batch_mode)
    batch_cache = cache if cache is not None else JudgmentCache()
    provider = JevDecisionProvider(settings, client=client, cache=batch_cache)
    return DecisionEngine(
        provider, settings, usage=usage, jev=provider, cache=batch_cache
    )


# ---------------------------------------------------------------------------
# Composición de preguntas
# ---------------------------------------------------------------------------


def test_pre_retrieval_no_duplica_needs_reasoning() -> None:
    phase = build_phase_questions(
        "pre_retrieval",
        available_capabilities=("knowledge.answer", "respond_directly"),
    )
    assert "needs_reasoning" in phase.questions
    assert "needs_complex_reasoning" not in phase.questions
    assert phase.canonical("needs_complex_reasoning") == "needs_reasoning"
    assert set(phase.questions["needs_reasoning"].sources) == {"routing", "planner"}
    assert validate_question_ids(phase.to_jevy())
    # El mínimo exigido por la fase pre-retrieval.
    for required in (
        "capability",
        "domain",
        "complexity",
        "needs_private_knowledge",
        "needs_action",
        "needs_reasoning",
        "modality",
        "retrieval_strategy",
        "needs_rewrite",
    ):
        assert required in phase.questions


def test_ids_de_fase_validos_y_sin_duplicados() -> None:
    passages = [object(), object()]
    for phase in (
        build_post_retrieval_questions(passages=passages),
        build_post_generation_questions(claims=["a", "b"]),
        build_agent_step_questions(tool_criteria={"t": "d"}),
    ):
        ids = validate_question_ids(phase.to_jevy())
        assert len(ids) == len(set(ids))


def test_answer_for_respeta_alias_y_cero() -> None:
    payload = {"answers": {"needs_reasoning": {"type": "noul", "noul": 0.0}}}
    assert noul_for(payload, "needs_complex_reasoning", "needs_reasoning") == 0.0
    assert answer_for(payload, "needs_complex_reasoning") is None
    assert normalize_batch_mode("ON") == "on"
    assert normalize_batch_mode("nonsense") == "off"


def test_compare_payloads_marca_desacuerdo() -> None:
    diffs = compare_payloads(
        phase="pre_retrieval",
        legacy_answers={"complexity": {"score": 1.0, "confidence": 0.9}},
        batch_answers={"complexity": {"score": 2.0, "confidence": 0.4}},
    )
    assert len(diffs) == 1
    assert diffs[0].agreement is False
    assert diffs[0].to_public_dict()["batch"] == 2.0


# ---------------------------------------------------------------------------
# A / B — una llamada con routing + planner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_on_routing_y_planner_una_sola_llamada() -> None:
    client = FakeJev()
    engine = _engine(client)
    ctx = _ctx()
    decision = await engine.decide(ctx)
    assert client.calls == 1
    assert decision.capability == "knowledge.answer"
    # La llamada de routing ya trae las preguntas del planner.
    sent = set(client.questions[0])
    assert {"modality", "retrieval_strategy", "needs_rewrite", "needs_reasoning"} <= sent

    planner = AdaptivePlanner(
        AdaptiveRagSettings(mode="active"), judge=engine, high_confidence=0.9
    )
    plan = await planner.plan(
        organization_id=ctx.organization_id,
        request_id=ctx.request_id,
        query=ctx.user_request,
        sql_enabled=True,
        routing=decision,
    )
    assert client.calls == 1, "el planner debe reutilizar el payload de routing"
    assert plan.provider == "hybrid"
    assert plan.path == "complex"
    assert plan.modality == "documents"
    assert plan.retrieval_strategy == "hybrid"


@pytest.mark.asyncio
async def test_batch_off_conserva_comportamiento_legacy() -> None:
    client = FakeJev()
    engine = _engine(client, batch_mode="off")
    ctx = _ctx()
    decision = await engine.decide(ctx)
    assert client.calls == 1
    assert "needs_complex_reasoning" in client.questions[0]
    assert "modality" not in client.questions[0]

    planner = AdaptivePlanner(
        AdaptiveRagSettings(mode="active"), judge=engine, high_confidence=0.9
    )
    plan = await planner.plan(
        organization_id=ctx.organization_id,
        request_id=ctx.request_id,
        query=ctx.user_request,
        sql_enabled=True,
        routing=decision,
    )
    assert client.calls == 2, "sin batching cada módulo paga su llamada"
    assert "modality" in client.questions[1]
    assert "capability" not in client.questions[1]
    assert plan.provider == "hybrid"


# ---------------------------------------------------------------------------
# C — shadow observa, no cambia
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_no_cambia_ejecucion_y_guarda_diff() -> None:
    client = FakeJev()
    engine = _engine(client, batch_mode="shadow")
    decision = await engine.decide(_ctx())
    # El batch corrió para observación: legacy + fase completa.
    assert client.calls == 2
    assert decision.resolved and decision.capability == "knowledge.answer"
    diffs = engine.batch_shadow_diffs()
    assert diffs
    assert {d["phase"] for d in diffs} == {"pre_retrieval"}
    assert all(d["agreement"] in (True, False, None) for d in diffs)


@pytest.mark.asyncio
async def test_shadow_no_duplica_cuando_las_preguntas_son_iguales() -> None:
    client = FakeJev()
    engine = _engine(client, batch_mode="shadow")
    await call_phase_judge(
        engine,
        phase=PHASE_AGENT_STEP,
        state={"user_request": "x", "tool_results": ["a"]},
        questions=build_agent_step_questions(
            tool_criteria={"t": "d"}, include_termination=False
        ).to_jevy(),
        batch_questions=build_agent_step_questions(
            tool_criteria={"t": "d"}, include_termination=False
        ).to_jevy(),
    )
    assert client.calls == 1


# ---------------------------------------------------------------------------
# D / E — cache request-scoped por estado
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_distinto_produce_juicio_nuevo() -> None:
    client = FakeJev()
    engine = _engine(client)
    ctx = _ctx()
    first = await engine.judge_phase(
        phase=PHASE_PRE_RETRIEVAL,
        state={"user_request": "consulta uno"},
        questions={"complexity": {"type": "score", "criteria": ["a", "b"]}},
        context=JudgmentContext(
            phase=PHASE_PRE_RETRIEVAL,
            organization_id=ctx.organization_id,
            request_id=ctx.request_id,
        ),
    )
    second = await engine.judge_phase(
        phase=PHASE_PRE_RETRIEVAL,
        state={"user_request": "consulta dos"},
        questions={"complexity": {"type": "score", "criteria": ["a", "b"]}},
        context=JudgmentContext(
            phase=PHASE_PRE_RETRIEVAL,
            organization_id=ctx.organization_id,
            request_id=ctx.request_id,
        ),
    )
    assert first is not None and second is not None
    assert client.calls == 2


@pytest.mark.asyncio
async def test_mismo_state_fase_y_request_reutiliza_cache() -> None:
    client = FakeJev()
    usage = RecordingUsage()
    engine = _engine(client, usage=usage)
    ctx = _ctx()
    context = JudgmentContext(
        phase=PHASE_PRE_RETRIEVAL,
        organization_id=ctx.organization_id,
        request_id=ctx.request_id,
    )
    questions = {"complexity": {"type": "score", "criteria": ["a", "b"]}}
    first = await engine.judge_phase(
        phase=PHASE_PRE_RETRIEVAL,
        state={"user_request": "misma consulta"},
        questions=questions,
        context=context,
    )
    second = await engine.judge_phase(
        phase=PHASE_PRE_RETRIEVAL,
        state={"user_request": "misma consulta"},
        questions=questions,
        context=context,
    )
    assert client.calls == 1
    assert first is not None and second is not None
    assert second["deduped"] is True
    assert second["estimated_cost"] == 0.0
    # El usage event se emite una sola vez (sin doble cobro).
    assert len(usage.judges) == 1


@pytest.mark.asyncio
async def test_reuse_sin_payload_previo_devuelve_none() -> None:
    client = FakeJev()
    engine = _engine(client)
    payload = await call_phase_judge(
        engine,
        phase=PHASE_PRE_RETRIEVAL,
        state={"user_request": "nunca juzgado"},
        questions=None,
        context=JudgmentContext(phase=PHASE_PRE_RETRIEVAL, request_id=uuid4()),
    )
    assert payload is None
    assert client.calls == 0


@pytest.mark.asyncio
async def test_cache_no_cruza_requests() -> None:
    client = FakeJev()
    engine = _engine(client)
    org = uuid4()
    questions = {"complexity": {"type": "score", "criteria": ["a", "b"]}}
    for _ in range(2):
        await engine.judge_phase(
            phase=PHASE_PRE_RETRIEVAL,
            state={"user_request": "misma consulta"},
            questions=questions,
            context=JudgmentContext(
                phase=PHASE_PRE_RETRIEVAL,
                organization_id=org,
                request_id=uuid4(),
            ),
        )
    assert client.calls == 2


@pytest.mark.asyncio
async def test_agent_step_cambia_con_cada_tool_result() -> None:
    client = FakeJev()
    engine = _engine(client)
    ctx = _ctx()
    context = JudgmentContext(
        phase=PHASE_AGENT_STEP,
        organization_id=ctx.organization_id,
        request_id=ctx.request_id,
    )
    questions = build_agent_step_questions(tool_criteria={"t": "d"}).to_jevy()
    for results in (["a"], ["a", "b"]):
        await engine.judge_phase(
            phase=PHASE_AGENT_STEP,
            state={"user_request": "x", "tool_results": results},
            questions=questions,
            context=context,
        )
    assert client.calls == 2


def test_state_fingerprint_por_fase() -> None:
    same_a = state_fingerprint("pre_retrieval", {"user_request": "x", "extra": 1})
    same_b = state_fingerprint("pre_retrieval", {"user_request": "x", "extra": 2})
    assert same_a == same_b, "la proyección PRE_RETRIEVAL sólo mira user_request"
    different = state_fingerprint("pre_retrieval", {"user_request": "y"})
    assert same_a != different
    step_a = state_fingerprint("agent_step", {"user_request": "x", "tool_results": ["a"]})
    step_b = state_fingerprint("agent_step", {"user_request": "x", "tool_results": ["a", "b"]})
    assert step_a != step_b


# ---------------------------------------------------------------------------
# N — límites de reintento
# ---------------------------------------------------------------------------


def test_reintento_de_retrieval_tiene_limite() -> None:
    from src.core.domain.adaptive import AdaptivePlan, EvidenceQuality
    from src.rag.adaptive.retry import next_plan

    settings = AdaptiveRagSettings(mode="active", max_retrieval_attempts=2)
    plan = AdaptivePlan(mode="active", apply=True)
    quality = EvidenceQuality(sufficient=False, score=0.1, reason="weak")
    assert next_plan(plan, quality, 2, settings) is not None
    assert next_plan(plan, quality, 3, settings) is None


def test_politica_regenera_una_sola_vez() -> None:
    from src.rag.adaptive.claims import (
        ClaimJudgment,
        ClaimVerdict,
        ClaimVerification,
        response_policy,
    )

    verification = ClaimVerification(
        claims=[
            ClaimJudgment(text="a", verdict=ClaimVerdict.SUPPORTED.value),
            ClaimJudgment(text="b", verdict=ClaimVerdict.UNSUPPORTED.value),
        ]
    )
    assert response_policy(verification) == "regenerate_once"
    assert response_policy(verification, regeneration_used=True) == "answer"
    many = ClaimVerification(
        claims=[
            ClaimJudgment(text=str(i), verdict=ClaimVerdict.UNSUPPORTED.value)
            for i in range(4)
        ]
    )
    assert response_policy(many, retrieval_budget_left=2) == "retry_retrieval"
    assert response_policy(many, retrieval_budget_left=0) == "abstain"


# ---------------------------------------------------------------------------
# O — JEV caído
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jev_caido_no_rompe_routing_ni_planner() -> None:
    from src.decision.composite import CompositeDecisionProvider

    settings = _settings(batch_mode="on")
    jev = JevDecisionProvider(settings, client=DownJev())
    composite = CompositeDecisionProvider(
        settings=settings, rules=RulesDecisionProvider(sql_threshold=1.1), jev=jev
    )
    engine = DecisionEngine(composite, settings, jev=jev)
    decision = await engine.decide(_ctx())
    assert decision.resolved is False
    assert decision.fallback_used is True

    planner = AdaptivePlanner(AdaptiveRagSettings(mode="active"), judge=engine)
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="pregunta sin jev",
        sql_enabled=False,
    )
    assert plan.provider == "rules"
    assert plan.apply is True


@pytest.mark.asyncio
async def test_judge_phase_error_devuelve_none_y_no_cachea() -> None:
    engine = _engine(DownJev())
    payload = await engine.judge_phase(
        phase=PHASE_POST_RETRIEVAL,
        state={"user_request": "x", "evidence_preview": "y", "n_items": 1},
        questions={"evidence_sufficient": {"type": "noul"}},
        context=JudgmentContext(phase=PHASE_POST_RETRIEVAL, request_id=uuid4()),
    )
    assert payload is None
    assert len(engine.batch_cache) == 0


# ---------------------------------------------------------------------------
# P — costo y usage de llamadas batched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_y_costo_incluyen_llamada_batched() -> None:
    client = FakeJev()
    usage = RecordingUsage()
    engine = _engine(client, usage=usage)
    ctx = _ctx()
    decision = await engine.decide(ctx)
    assert decision.prompt_tokens == 40
    assert decision.completion_tokens == 12
    assert usage.decisions and usage.decisions[0][1].prompt_tokens == 40
    assert usage.decisions[0][1].metadata["batch_questions"] >= 9

    await engine.judge_phase(
        phase=PHASE_POST_RETRIEVAL,
        state={"user_request": "x", "evidence_preview": "y", "n_items": 1},
        questions={"evidence_sufficient": {"type": "noul"}},
        context=JudgmentContext(
            phase=PHASE_POST_RETRIEVAL,
            organization_id=ctx.organization_id,
            request_id=ctx.request_id,
        ),
    )
    assert len(usage.judges) == 1
    context, payload = usage.judges[0]
    assert context.phase == PHASE_POST_RETRIEVAL
    assert payload["usage"]["input_tokens"] == 40


@pytest.mark.asyncio
async def test_post_generation_comparte_grounding_y_claims() -> None:
    client = FakeJev()
    engine = _engine(client)
    ctx = _ctx()
    from src.rag.adaptive.claims import verify_generation

    evidence = EvidenceSet(
        items=[EvidenceItem(source_type="qdrant", content="contenido", score=0.4)],
        query="pregunta",
    )
    verification = await verify_generation(
        judge=engine,
        answer="El horario de atención es de 8 a 12.",
        evidence=evidence,
        settings=AdaptiveRagSettings(mode="active"),
        organization_id=ctx.organization_id,
        request_id=ctx.request_id,
    )
    assert client.calls == 1
    assert verification.jev_used
    assert any(q.startswith("claim_") for q in client.questions[0])
    assert "answer_grounded" in client.questions[0]
