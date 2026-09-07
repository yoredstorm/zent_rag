"""Phase 28B — Units, currency, grain."""
from __future__ import annotations

from src.intelligence.semantics_units import (
    AggregationKind,
    CurrencyUnitGuard,
    GrainRegistry,
)


def test_aggregation_kind_enum() -> None:
    assert AggregationKind.SUMMABLE.value == "SUMMABLE"
    assert AggregationKind.SEMI_ADDITIVE.value == "SEMI_ADDITIVE"
    assert AggregationKind.NON_ADDITIVE.value == "NON_ADDITIVE"
    assert AggregationKind.DISTINCT_COUNT.value == "DISTINCT_COUNT"
    assert AggregationKind.AVERAGE.value == "AVERAGE"
    assert AggregationKind.RATE.value == "RATE"
    assert AggregationKind.RATIO.value == "RATIO"


def test_currency_guard_abstains_without_fx() -> None:
    guard = CurrencyUnitGuard()
    ok = guard.check_compatible(
        [{"amount": 10, "currency": "PEN"}, {"amount": 5, "currency": "PEN"}]
    )
    assert ok.compatible and not ok.abstain

    mixed = guard.check_compatible(
        [
            {"amount": 10, "currency": "PEN"},
            {"amount": 5, "currency": "USD"},
        ]
    )
    assert mixed.compatible is False
    assert mixed.abstain is True
    assert mixed.status_hint == "CONTEXT_MISSING"
    assert set(mixed.currencies) == {"PEN", "USD"}

    with_fx = guard.check_compatible(
        [
            {"amount": 10, "currency": "PEN"},
            {"amount": 5, "currency": "USD"},
        ],
        fx_available=True,
    )
    assert with_fx.compatible and not with_fx.abstain


def test_grain_registry_semi_additive() -> None:
    reg = GrainRegistry()
    reg.register(
        "account_balance",
        "one row per account/day",
        object_type="metric",
        aggregation_kind=AggregationKind.SEMI_ADDITIVE,
    )
    assert reg.allows_sum_across_time("account_balance") is False
    assert reg.get("account_balance").grain == "one row per account/day"
    assert reg.allows_sum_across_time("unknown_metric") is True
