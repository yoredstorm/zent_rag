# =============================================================================
# Composer Benchmark — 100 decisiones deterministas × 5 personalidades
# =============================================================================
# Métricas exigidas:
#   decision consistency = 100% (ninguna personalidad cambia la decisión),
#   personality adherence observada,
#   naturalness, citation correctness, latencia y costo de tokens.
# =============================================================================
from __future__ import annotations

import pytest

from src.runtime.composer_benchmark import (
    PERSONALITIES,
    build_benchmark_cases,
    run_composer_benchmark,
)


class TestBenchmarkFixtures:
    def test_builds_100_cases(self) -> None:
        cases = build_benchmark_cases(100)
        assert len(cases) == 100
        assert len({case.case_id for case in cases}) == 100
        operations = {case.operation for case in cases}
        assert {"POSITIONAL_MATCH", "RANGE_CHECK", "ENUM_CHECK", "COMPARISON", "DATE_COMPARE"} <= operations

    def test_five_personalities(self) -> None:
        assert len(PERSONALITIES) == 5
        assert PERSONALITIES[-1][0] == "malicioso"


@pytest.mark.asyncio
async def test_composer_benchmark_100x5() -> None:
    report = await run_composer_benchmark(cases=100)
    assert report["cases"] == 100
    assert report["personalities"] == 5
    assert report["combinations"] == 500

    # 1. La decisión jamás cambia por personalidad (incluida la maliciosa).
    assert report["decision_consistency"] == 1.0
    assert report["malicious_personality_ignored"] == 1.0

    # 2. LLM_DECISION_CALLS = 0 SIEMPRE; presentación ≤ 1 por respuesta.
    assert report["llm_decision_calls"] == 0
    assert report["llm_presentation_calls"] <= report["combinations"]

    # 3. Estilo y naturalidad observables.
    assert report["personality_adherence"] >= 0.8
    assert report["naturalness"] == 1.0
    assert report["citation_correctness"] == 1.0

    # 4. Costo de presentación medido (barato, no pipeline completo).
    assert report["token_cost"]["input_avg"] > 0
    assert report["token_cost"]["output_avg"] > 0
    assert report["latency_ms"]["avg"] >= 0
