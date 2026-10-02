# =============================================================================
# Reportes del turno — budget por profundidad y loop controlado (C4).
# =============================================================================
from __future__ import annotations

from src.runtime.turn_reports import build_budget_report, build_loop_report


def test_budget_dentro_y_fuera() -> None:
    ok = build_budget_report(complexity="L1", llm_calls=1, tokens=900, elapsed_ms=1500)
    assert ok.max_llm_calls == 1
    assert ok.max_tokens == 1500
    assert ok.within_budget is True
    over = build_budget_report(complexity="L0", llm_calls=1, tokens=500, elapsed_ms=100)
    assert over.max_llm_calls == 0
    assert over.within_budget is False
    payload = ok.to_public_dict()
    assert payload["complexity"] == "L1"
    assert payload["within_budget"] is True


def test_budget_complejidad_desconocida() -> None:
    report = build_budget_report(complexity=None, llm_calls=1, tokens=10, elapsed_ms=1)
    assert report.complexity == "L1"
    assert report.within_budget is True


def test_loop_sin_rondas() -> None:
    report = build_loop_report({})
    assert report.rounds == ()
    assert report.extra_round is False
    assert report.exhausted is False


def test_loop_con_rondas_y_extra() -> None:
    adaptive = {
        "attempts": [
            {"attempt": 1, "strategy": "hybrid", "sufficient": False, "quality_score": 0.2},
            {"attempt": 2, "strategy": "exact", "sufficient": True, "quality_score": 0.8},
        ],
        "preflight_extra_round": True,
        "preflight_action": "retrieve_more",
    }
    report = build_loop_report(adaptive, max_rounds=3)
    assert [round_.attempt for round_ in report.rounds] == [1, 2]
    assert report.rounds[0].reason == "insuficiente"
    assert report.rounds[1].reason == "suficiente"
    assert report.extra_round is True
    assert report.exhausted is False


def test_loop_agotado() -> None:
    adaptive = {
        "attempts": [
            {"attempt": 1, "strategy": "hybrid", "sufficient": False},
            {"attempt": 2, "strategy": "hybrid", "sufficient": False},
            {"attempt": 3, "strategy": "hybrid", "sufficient": False},
        ]
    }
    report = build_loop_report(adaptive, max_rounds=3)
    assert report.exhausted is True
