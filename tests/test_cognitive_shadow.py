# =============================================================================
# Shadow evaluation — Phase 8 (baseline vs cognitive, sin cambiar respuestas)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.cognitive import CognitiveScope, ComplexityLevel
from src.core.domain.shadow import (
    ShadowComparison,
    ShadowMetrics,
    ShadowVerdict,
    compare_shadow,
)


def _metrics(**overrides) -> ShadowMetrics:
    base = dict(
        evidence_count=3,
        claims=2,
        supported=1,
        partial=0,
        conflicts=0,
        latency_ms=10.0,
        has_answer=True,
    )
    base.update(overrides)
    return ShadowMetrics(**base)


def test_compare_shadow_verdicts() -> None:
    verdict, reasons = compare_shadow(
        baseline=_metrics(),
        cognitive=_metrics(supported=2, partial=0, conflicts=2),
    )
    assert verdict is ShadowVerdict.COGNITIVE_BETTER
    assert any("supported_ratio" in reason for reason in reasons)

    verdict, _ = compare_shadow(
        baseline=_metrics(supported=2),
        cognitive=_metrics(supported=1, latency_ms=5.0),
    )
    assert verdict is ShadowVerdict.BASELINE_BETTER

    # mismo grounding, pero el cognitive detecta conflictos → mejor
    verdict, reasons = compare_shadow(
        baseline=_metrics(supported=1, conflicts=0),
        cognitive=_metrics(supported=1, conflicts=3),
    )
    assert verdict is ShadowVerdict.COGNITIVE_BETTER
    assert any("conflictos" in reason for reason in reasons)

    # mismo grounding y conflictos, latencia disparada → baseline
    verdict, _ = compare_shadow(
        baseline=_metrics(latency_ms=10.0),
        cognitive=_metrics(latency_ms=30.0),
    )
    assert verdict is ShadowVerdict.BASELINE_BETTER

    verdict, _ = compare_shadow(
        baseline=_metrics(),
        cognitive=_metrics(),
    )
    assert verdict is ShadowVerdict.TIE


class _FakeShadowRepo:
    def __init__(self) -> None:
        self.saved: list[ShadowComparison] = []

    async def save(self, comparison):
        self.saved.append(comparison)
        return comparison

    async def list(self, organization_id, limit=50):
        return [c for c in self.saved if c.organization_id == organization_id]


class _FakeCognitiveRepo:
    def __init__(self) -> None:
        self.runs: dict = {}
        self.tasks: dict = {}

    async def create_run(self, run):
        self.runs[str(run.id)] = run
        return run

    async def save_tasks(self, *, organization_id, tasks):
        for task in tasks:
            self.tasks[str(task.id)] = task


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute_run(self, *, organization_id, run_id, scope):
        self.calls += 1
        if self.calls == 1:  # baseline
            metrics = {
                "evidence_count": 1,
                "claims": 3,
                "supported": 1,
                "partial": 0,
                "conflicts": 0,
                "latency_ms": 10.0,
                "has_answer": True,
            }
        else:  # cognitive
            metrics = {
                "evidence_count": 5,
                "claims": 3,
                "supported": 2,
                "partial": 1,
                "conflicts": 2,
                "latency_ms": 20.0,
                "has_answer": True,
            }
        return {"metrics": metrics}


@pytest.mark.asyncio
async def test_shadow_evaluator_runs_both_and_persists_comparison() -> None:
    from src.platform.cognitive.shadow import ShadowEvaluator

    shadow_repo = _FakeShadowRepo()
    cognitive_repo = _FakeCognitiveRepo()
    executor = _FakeExecutor()
    evaluator = ShadowEvaluator(shadow_repo, cognitive_repo, executor)
    org_id = uuid4()

    comparison = await evaluator.evaluate(
        organization_id=org_id,
        query="Analiza todos los contratos e identifica riesgos y conflictos.",
        scope=CognitiveScope(organization_id=org_id),
    )

    assert executor.calls == 2
    assert len(cognitive_repo.runs) == 2  # baseline + cognitive persistidos
    assert comparison.verdict is ShadowVerdict.COGNITIVE_BETTER
    assert comparison.baseline_run_id is not None
    assert comparison.cognitive_run_id is not None
    assert shadow_repo.saved == [comparison]


@pytest.mark.asyncio
async def test_shadow_repo_roundtrip_and_isolation() -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.infrastructure.postgres.shadow import PostgresShadowRepository

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Shadow Org {uuid4().hex[:6]}"
    )
    repo = PostgresShadowRepository()
    comparison = ShadowComparison(
        organization_id=org.id,
        query="¿cuál es la penalidad?",
        level=ComplexityLevel.L3_MULTI_SOURCE,
        baseline=ShadowMetrics(claims=1, supported=0),
        cognitive=ShadowMetrics(claims=2, supported=2, conflicts=1),
        verdict=ShadowVerdict.COGNITIVE_BETTER,
        reasons=("supported_ratio +1.0",),
        baseline_run_id=uuid4(),
        cognitive_run_id=uuid4(),
    )
    saved = await repo.save(comparison)
    assert saved.id == comparison.id

    listed = await repo.list(org.id)
    assert [c.id for c in listed] == [comparison.id]
    assert listed[0].verdict is ShadowVerdict.COGNITIVE_BETTER
    assert listed[0].cognitive.supported == 2
    assert await repo.list(uuid4()) == []
