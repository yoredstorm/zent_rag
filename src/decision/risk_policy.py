# =============================================================================
# Decision Risk Policy — un solo lugar para los thresholds.
# =============================================================================
# Ningún módulo inventa números: la política resuelve, por nivel de riesgo,
# el umbral de Choice, si hace falta una segunda señal (`action_warranted`),
# el umbral de esa señal, la acción ante duda y si requiere confirmación
# humana. Configurable por settings y por tenant (`tenant_policy.risk_policy`).
#
# Dos señales para HIGH/CRITICAL: NUNCA se combinan con max(); se exigen por
# separado (choice >= umbral AND warranted >= umbral).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.domain.decision import RiskLevel

FALLBACK_RESPOND = "respond_directly"
FALLBACK_CLARIFY = "ask_clarification"
FALLBACK_DEFAULT = "default_target"
FALLBACK_HUMAN = "human_review"

FALLBACK_ACTIONS = frozenset(
    {FALLBACK_RESPOND, FALLBACK_CLARIFY, FALLBACK_DEFAULT, FALLBACK_HUMAN}
)

RISK_LEVELS: tuple[str, ...] = (
    RiskLevel.LOW.value,
    RiskLevel.MEDIUM.value,
    RiskLevel.HIGH.value,
    RiskLevel.CRITICAL.value,
)


@dataclass(frozen=True, kw_only=True)
class RiskThresholds:
    risk: str
    choice_threshold: float
    warrant_required: bool = False
    warrant_threshold: float = 0.65
    on_low_confidence: str = FALLBACK_RESPOND
    human_confirmation: bool = False
    selectable: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "choice_threshold": round(self.choice_threshold, 4),
            "warrant_required": self.warrant_required,
            "warrant_threshold": round(self.warrant_threshold, 4),
            "on_low_confidence": self.on_low_confidence,
            "human_confirmation": self.human_confirmation,
            "selectable": self.selectable,
        }


_DEFAULTS: dict[str, RiskThresholds] = {
    RiskLevel.LOW.value: RiskThresholds(
        risk=RiskLevel.LOW.value,
        choice_threshold=0.60,
        on_low_confidence=FALLBACK_RESPOND,
    ),
    RiskLevel.MEDIUM.value: RiskThresholds(
        risk=RiskLevel.MEDIUM.value,
        choice_threshold=0.70,
        on_low_confidence=FALLBACK_CLARIFY,
    ),
    RiskLevel.HIGH.value: RiskThresholds(
        risk=RiskLevel.HIGH.value,
        choice_threshold=0.80,
        warrant_required=True,
        warrant_threshold=0.65,
        on_low_confidence=FALLBACK_HUMAN,
        human_confirmation=True,
    ),
    RiskLevel.CRITICAL.value: RiskThresholds(
        risk=RiskLevel.CRITICAL.value,
        choice_threshold=0.90,
        warrant_required=True,
        warrant_threshold=0.75,
        on_low_confidence=FALLBACK_HUMAN,
        human_confirmation=True,
        selectable=False,
    ),
}


class DecisionRiskPolicy:
    """Resuelve thresholds por riesgo. Inmutable por construcción."""

    def __init__(
        self,
        thresholds: dict[str, RiskThresholds] | None = None,
        *,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        base = dict(thresholds or _DEFAULTS)
        if overrides:
            base = _apply_overrides(base, overrides)
        self._thresholds = base

    def thresholds(self, risk: str, *, action_type: str = "") -> RiskThresholds:
        """Thresholds del nivel. `action_type` queda para overrides futuros."""
        value = str(risk or RiskLevel.LOW.value).lower()
        return self._thresholds.get(value, self._thresholds[RiskLevel.LOW.value])

    def action_for(self, risk: str, *, action_type: str = "") -> str:
        return self.thresholds(risk, action_type=action_type).on_low_confidence

    def selectable(self, risk: str) -> bool:
        return self.thresholds(risk).selectable

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "levels": {level: self._thresholds[level].to_public_dict() for level in RISK_LEVELS},
            "two_signals_for": [
                level for level in RISK_LEVELS if self._thresholds[level].warrant_required
            ],
        }

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        *,
        tenant_policy: dict[str, Any] | None = None,
    ) -> "DecisionRiskPolicy":
        """Defaults del código + overrides de settings + overrides del tenant."""
        overrides: dict[str, dict[str, Any]] = {
            RiskLevel.LOW.value: {
                "choice_threshold": getattr(settings, "DECISION_RISK_LOW_CHOICE", 0.60),
                "on_low_confidence": getattr(
                    settings, "DECISION_RISK_LOW_FALLBACK", FALLBACK_RESPOND
                ),
            },
            RiskLevel.MEDIUM.value: {
                "choice_threshold": getattr(settings, "DECISION_RISK_MEDIUM_CHOICE", 0.70),
                "on_low_confidence": getattr(
                    settings, "DECISION_RISK_MEDIUM_FALLBACK", FALLBACK_CLARIFY
                ),
            },
            RiskLevel.HIGH.value: {
                "choice_threshold": getattr(settings, "DECISION_RISK_HIGH_CHOICE", 0.80),
                "warrant_required": bool(
                    getattr(settings, "DECISION_RISK_HIGH_WARRANT_REQUIRED", True)
                ),
                "warrant_threshold": getattr(settings, "DECISION_RISK_HIGH_WARRANT", 0.65),
                "on_low_confidence": getattr(
                    settings, "DECISION_RISK_HIGH_FALLBACK", FALLBACK_HUMAN
                ),
            },
            RiskLevel.CRITICAL.value: {
                "choice_threshold": getattr(settings, "DECISION_RISK_CRITICAL_CHOICE", 0.90),
                "warrant_required": bool(
                    getattr(settings, "DECISION_RISK_CRITICAL_WARRANT_REQUIRED", True)
                ),
                "warrant_threshold": getattr(
                    settings, "DECISION_RISK_CRITICAL_WARRANT", 0.75
                ),
                "on_low_confidence": getattr(
                    settings, "DECISION_RISK_CRITICAL_FALLBACK", FALLBACK_HUMAN
                ),
            },
        }
        tenant = (tenant_policy or {}).get("risk_policy")
        if isinstance(tenant, dict):
            overrides = _merge_overrides(overrides, tenant)
        return cls(overrides=overrides)


def _merge_overrides(
    base: dict[str, dict[str, Any]], extra: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    merged = {level: dict(values) for level, values in base.items()}
    for level in RISK_LEVELS:
        values = extra.get(level)
        if isinstance(values, dict):
            merged.setdefault(level, {}).update(values)
    return merged


def _apply_overrides(
    base: dict[str, RiskThresholds], overrides: dict[str, dict[str, Any]]
) -> dict[str, RiskThresholds]:
    out: dict[str, RiskThresholds] = {}
    for level in RISK_LEVELS:
        current = base.get(level) or _DEFAULTS[level]
        values = overrides.get(level) or {}
        payload = current.to_public_dict()
        payload.pop("risk", None)
        for key in (
            "choice_threshold",
            "warrant_required",
            "warrant_threshold",
            "on_low_confidence",
            "human_confirmation",
            "selectable",
        ):
            if key not in values:
                continue
            value = values[key]
            if key in {"choice_threshold", "warrant_threshold"}:
                try:
                    payload[key] = min(1.0, max(0.0, float(value)))
                except (TypeError, ValueError):
                    continue
            elif key in {"warrant_required", "human_confirmation", "selectable"}:
                payload[key] = bool(value)
            else:
                action = str(value or "")
                payload[key] = action if action in FALLBACK_ACTIONS else current.on_low_confidence
        out[level] = RiskThresholds(risk=level, **payload)
    return out
