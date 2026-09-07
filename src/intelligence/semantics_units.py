# =============================================================================
# Units / Currency / Grain semantics (Phase 28B)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AggregationKind(StrEnum):
    SUMMABLE = "SUMMABLE"
    SEMI_ADDITIVE = "SEMI_ADDITIVE"
    NON_ADDITIVE = "NON_ADDITIVE"
    DISTINCT_COUNT = "DISTINCT_COUNT"
    AVERAGE = "AVERAGE"
    RATE = "RATE"
    RATIO = "RATIO"


@dataclass
class CurrencyCheckResult:
    """Resultado de compatibilidad monetaria."""

    compatible: bool
    abstain: bool
    reason: str
    currencies: list[str] = field(default_factory=list)
    status_hint: str | None = None  # DATA_MISSING | CONTEXT_MISSING

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "abstain": self.abstain,
            "reason": self.reason,
            "currencies": list(self.currencies),
            "status_hint": self.status_hint,
        }


class CurrencyUnitGuard:
    """Impide sumar monedas mixtas sin autoridad FX."""

    def check_compatible(
        self,
        amounts: list[dict[str, Any]],
        *,
        fx_available: bool = False,
    ) -> CurrencyCheckResult:
        currencies = sorted(
            {
                str(a.get("currency") or a.get("currency_semantics") or "").upper()
                for a in amounts
                if (a.get("currency") or a.get("currency_semantics"))
            }
        )
        currencies = [c for c in currencies if c]
        if len(currencies) <= 1:
            return CurrencyCheckResult(
                compatible=True,
                abstain=False,
                reason="single_or_missing_currency",
                currencies=currencies,
            )
        if fx_available:
            return CurrencyCheckResult(
                compatible=True,
                abstain=False,
                reason="fx_authority_available",
                currencies=currencies,
            )
        return CurrencyCheckResult(
            compatible=False,
            abstain=True,
            reason="mixed_currencies_without_fx",
            currencies=currencies,
            status_hint="CONTEXT_MISSING",
        )


@dataclass
class GrainDefinition:
    object_id: str
    object_type: str  # table | metric
    grain: str
    aggregation_kind: AggregationKind = AggregationKind.SUMMABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "grain": self.grain,
            "aggregation_kind": self.aggregation_kind.value,
        }


class GrainRegistry:
    """Registro de grain de tablas/métricas para evitar dobles conteos."""

    def __init__(self) -> None:
        self._items: dict[str, GrainDefinition] = {}

    def register(
        self,
        object_id: str,
        grain: str,
        *,
        object_type: str = "table",
        aggregation_kind: AggregationKind = AggregationKind.SUMMABLE,
    ) -> GrainDefinition:
        item = GrainDefinition(
            object_id=object_id,
            object_type=object_type,
            grain=grain,
            aggregation_kind=aggregation_kind,
        )
        self._items[object_id] = item
        return item

    def get(self, object_id: str) -> GrainDefinition | None:
        return self._items.get(object_id)

    def allows_sum_across_time(self, object_id: str) -> bool:
        item = self._items.get(object_id)
        if item is None:
            return True
        return item.aggregation_kind == AggregationKind.SUMMABLE

    def list_all(self) -> list[dict[str, Any]]:
        return [i.to_dict() for i in self._items.values()]
