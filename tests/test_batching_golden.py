# =============================================================================
# Batching golden set — compara rules / JEV unbatched / JEV batched / hybrid.
# =============================================================================
# Sin APIs externas: clientes fake que responden según el verdicto esperado de
# cada passage del caso. Mide route accuracy, retrieval success, evidence
# precision, grounding precision, abstention correctness, latencia, costo y
# calls/request (métrica del ADR de batching).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.adaptive import EvidenceItem, EvidenceSet
from src.core.domain.decision import DecisionContext
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.decision.composite import CompositeDecisionProvider
from src.decision.engine import DecisionEngine
from src.decision.providers.jev import JevDecisionProvider
from src.decision.rules import RulesDecisionProvider
from src.decision.settings import DecisionEngineSettings
from src.rag.adaptive.claims import ClaimVerdict, verify_generation
from src.rag.adaptive.evidence import evaluate_deterministic
from src.rag.adaptive.passages import (
    apply_passages,
    judge_passages,
    select_passages,
    summarize,
)
from src.rag.adaptive.planner import AdaptivePlanner
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.evaluation.batching_golden import (
    EVIDENCE_CONTRADICTORY,
    EVIDENCE_INJECTION,
    EVIDENCE_IRRELEVANT,
    MODES,
    BatchingCase,
    CaseObservation,
    compare_modes,
    coverage,
    default_cases,
    evidence_precision,
)


def _settings(**kwargs) -> DecisionEngineSettings:
    base = dict(
        routing_mode="jev",
        canary_percentage=100,
        jev_api_key="test-key",
        batch_mode="on",
        fallback_model="cheap",
    )
    base.update(kwargs)
    return DecisionEngineSettings(**base)


class GoldenFakeJev:
    """Responde según el verdicto esperado del passage del caso."""

    def __init__(self, case: BatchingCase) -> None:
        self.case = case
        self.calls = 0
        self.last_latency_ms = 12.0

    def _passage_noul(self, qid: str) -> float:
        parts = qid.split("_")
        if len(parts) < 3:
            return 0.5
        index, field = int(parts[1]), parts[2]
        verdict = (
            self.case.evidence[index].verdict
            if index < len(self.case.evidence)
            else "relevant"
        )
        noisy = verdict in {EVIDENCE_IRRELEVANT, EVIDENCE_INJECTION}
        if field == "relevant":
            return 0.05 if noisy else 0.9
        if field == "usable":
            return 0.05 if noisy else 0.9
        if field == "contradicts":
            return 0.9 if verdict == EVIDENCE_CONTRADICTORY else 0.05
        if field == "injection":
            return 0.9 if verdict == EVIDENCE_INJECTION else 0.02
        return 0.5

    def _answer(self, qid: str, spec: dict) -> dict:
        if qid.startswith("passage_"):
            return {"type": "noul", "noul": self._passage_noul(qid)}
        if qid.startswith("claim_"):
            field = qid.split("_")[2]
            if field == "supported":
                return {"type": "noul", "noul": 0.9}
            return {"type": "noul", "noul": 0.05}
        qtype = str(spec.get("type") or "noul")
        if qtype == "choice":
            criteria = spec.get("criteria") or {}
            if qid == "capability":
                choice = self.case.expected_capability or next(iter(criteria), "knowledge.answer")
            elif qid == "retrieval_strategy":
                choice = self.case.expected_strategy or next(iter(criteria), "hybrid")
            else:
                choice = next(iter(criteria), "documents")
            if choice not in criteria:
                choice = next(iter(criteria), "knowledge.answer")
            return {"type": "choice", "choice": choice, "confidence": 0.95, "probabilities": {choice: 0.95}}
        if qtype == "score":
            return {"type": "score", "score": 1.0, "confidence": 0.8}
        return {"type": "noul", "noul": 0.8}

    async def system_one(self, *, state, questions, model, timeout):
        self.calls += 1
        return {
            "model": model,
            "answers": {qid: self._answer(qid, spec) for qid, spec in questions.items()},
            "usage": {"input_tokens": 60, "output_tokens": 20},
        }

    async def judge(self, *, state, questions, context=None):
        """Contrato de engine.judge para callers que no usan system_one."""
        self.calls += 1
        return {
            "answers": {qid: self._answer(qid, spec) for qid, spec in questions.items()},
            "provider": "jev",
            "model": "fake",
            "latency_ms": self.last_latency_ms,
            "usage": {"input_tokens": 60, "output_tokens": 20},
        }


class DownJev:
    async def system_one(self, **kwargs):
        raise RuntimeError("jev down")


def _engine(case: BatchingCase, *, mode: str):
    client = GoldenFakeJev(case)
    settings = _settings(batch_mode="off" if mode == "jev_unbatched" else "on")
    provider = JevDecisionProvider(settings, client=client)
    if mode == "hybrid":
        composite = CompositeDecisionProvider(
            settings=settings,
            rules=RulesDecisionProvider(sql_threshold=1.1),
            jev=provider,
        )
        engine = DecisionEngine(composite, settings, jev=provider)
    else:
        engine = DecisionEngine(provider, settings, jev=provider)
    return engine, client, settings


async def _observe(case: BatchingCase, mode: str) -> CaseObservation:
    observation = CaseObservation(case_id=case.id, mode=mode)
    planner_settings = AdaptiveRagSettings(mode="active")
    org, rid = uuid4(), uuid4()
    ctx = DecisionContext(
        user_request=case.query,
        organization_id=org,
        request_id=rid,
        sql_enabled=True,
        knowledge_enabled=True,
        available_capabilities=(
            "knowledge.answer",
            "database.query",
            "respond_directly",
        ),
        permissions=frozenset({"*"}),
    )
    if mode == "rules":
        decision = await RulesDecisionProvider(sql_threshold=1.1).decide(ctx)
        engine = None
        client = None
    else:
        engine, client, _ = _engine(case, mode=mode)
        decision = await engine.decide(ctx)
    planner = AdaptivePlanner(planner_settings, judge=engine, high_confidence=0.9)
    plan = await planner.plan(
        organization_id=org,
        request_id=rid,
        query=case.query,
        sql_enabled=True,
        routing=decision,
    )
    observation.capability = decision.capability
    observation.route = plan.source_route
    observation.strategy = plan.retrieval_strategy
    observation.fallback = bool(decision.fallback_used)
    observation.calls = client.calls if client is not None else 0
    observation.latency_ms = float(decision.latency_ms or 0.0)
    observation.cost = float(decision.estimated_cost or 0.0)
    observation.route_correct = (
        plan.source_route == case.expected_route
        if case.expected_route
        else None
    )
    if case.expected_capability and decision.resolved:
        observation.route_correct = bool(
            (observation.route_correct is not False)
            and decision.capability == case.expected_capability
        )

    if not case.evidence:
        return observation

    # Passage Judge con el mismo fake orientado por verdictos esperados.
    judge_client = GoldenFakeJev(case)
    items = [
        EvidenceItem(
            source_type="qdrant",
            content=entry.content,
            score=entry.score,
            document_id=entry.document_id,
            chunk_id=f"c{index}",
        )
        for index, entry in enumerate(case.evidence)
    ]
    evidence = EvidenceSet(items=items, query=case.query)
    quality = evaluate_deterministic(evidence, planner_settings)
    selection = select_passages(evidence, quality=quality, settings=planner_settings)
    await judge_passages(
        evidence,
        judge=judge_client,
        settings=planner_settings,
        quality=quality,
        selection=selection,
    )
    retrieval = RetrievalContext(
        chunks=[
            RetrievalChunk(
                content=entry.content,
                score=entry.score,
                document_id=entry.document_id,
                metadata={"chunk_id": f"c{index}"},
            )
            for index, entry in enumerate(case.evidence)
        ]
    )
    apply_passages(evidence, selection, retrieval=retrieval)
    # Precisión sobre lo que realmente entra al prompt del LLM.
    kept = [chunk.content for chunk in retrieval.chunks]
    observation.evidence_precision = evidence_precision(case, kept)
    observation.retrieval_success = bool(kept)
    if case.expects_abstention:
        observation.abstention_correct = not kept or not quality.sufficient

    # Grounding/claims: claim copiada de la evidencia relevante debe sostenerse;
    # en el caso contradictorio la política debe transparentar el conflicto.
    relevant = [e.content for e in case.evidence if e.verdict not in {EVIDENCE_IRRELEVANT, EVIDENCE_INJECTION}]
    if relevant:
        verification = await verify_generation(
            judge=judge_client,
            answer=relevant[0],
            evidence=evidence,
            settings=planner_settings,
            evidence_contradictions=int(summarize(selection)["contradictions"]),
        )
        if case.kind == "contradictory":
            observation.grounding_precision = (
                1.0 if verification.policy == "conflict" else 0.0
            )
        else:
            factual = verification.factual
            observation.grounding_precision = (
                1.0
                if factual
                and all(
                    claim.verdict
                    in {ClaimVerdict.SUPPORTED.value, ClaimVerdict.NOT_VERIFIABLE.value}
                    for claim in factual
                )
                else 0.0
            )
    return observation


def test_golden_set_cobertura() -> None:
    report = coverage()
    assert report["total"]["all"] >= 11
    for kind in (
        "documents",
        "structured",
        "codes",
        "mixed",
        "ambiguous",
        "spelling",
        "mixed_language",
        "contradictory",
        "injection",
    ):
        assert kind in report["by_kind"], kind
    for locale in ("es", "es_tecnico", "mixed"):
        assert locale in report["by_locale"], locale


@pytest.mark.asyncio
async def test_compara_modos_con_calls_per_request() -> None:
    cases = default_cases()
    observations: dict[str, list[CaseObservation]] = {mode: [] for mode in MODES}
    for case in cases:
        for mode in MODES:
            observations[mode].append(await _observe(case, mode))
    report = compare_modes(observations)
    modes = report["modes"]
    assert modes["rules"]["calls_per_request"] == 0.0
    assert modes["jev_batched"]["calls_per_request"] < modes["jev_unbatched"]["calls_per_request"]
    assert report["batching"]["dedupe_ratio"] > 0
    # Calidad mínima en el camino batcheado.
    assert modes["jev_batched"]["route_accuracy"] is not None
    assert modes["jev_batched"]["evidence_precision"] == 1.0
    assert modes["jev_batched"]["abstention_correct"] == 1.0
    # El fallback determinístico sigue funcionando en el modo híbrido.
    assert modes["hybrid"]["cases"] == len(cases)


@pytest.mark.asyncio
async def test_rules_resuelve_casos_deterministicos() -> None:
    rules = RulesDecisionProvider(sql_threshold=1.1)
    explicit = await rules.decide(
        DecisionContext(
            user_request="hola",
            organization_id=uuid4(),
            request_id=uuid4(),
            sql_enabled=True,
            knowledge_enabled=True,
            available_capabilities=("knowledge.answer", "respond_directly"),
            permissions=frozenset({"*"}),
            explicit_capability="respond_directly",
        )
    )
    assert explicit.resolved is True
    assert explicit.capability == "respond_directly"
    assert explicit.metadata.get("explicit") is True

    documentary = await rules.decide(
        DecisionContext(
            user_request="¿Cuál es la política de devoluciones?",
            organization_id=uuid4(),
            request_id=uuid4(),
            sql_enabled=True,
            knowledge_enabled=True,
            available_capabilities=("knowledge.answer", "database.query"),
            permissions=frozenset({"*"}),
        )
    )
    # El default documental no es slam-dunk: rules deja decidir a JEV/legacy.
    assert documentary.resolved is False


@pytest.mark.asyncio
async def test_injection_en_golden_no_entra_al_contexto() -> None:
    case = next(c for c in default_cases() if c.kind == "injection")
    judge_client = GoldenFakeJev(case)
    items = [
        EvidenceItem(
            source_type="qdrant",
            content=entry.content,
            score=entry.score,
            document_id=entry.document_id,
            chunk_id=f"c{index}",
        )
        for index, entry in enumerate(case.evidence)
    ]
    evidence = EvidenceSet(items=items, query=case.query)
    settings = AdaptiveRagSettings(mode="active")
    quality = evaluate_deterministic(evidence, settings)
    selection = select_passages(evidence, quality=quality, settings=settings)
    await judge_passages(
        evidence, judge=judge_client, settings=settings, quality=quality, selection=selection
    )
    result = apply_passages(evidence, selection)
    assert result.injection_suspected == 1
    assert summarize(selection)["injection_suspected"] == 1
    kept = [item.content for item in evidence.items]
    assert "evil.test" not in " ".join(kept)
    assert "Ignore previous instructions" not in " ".join(kept)
