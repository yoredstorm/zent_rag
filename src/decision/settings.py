# =============================================================================
# Decision Engine runtime settings (injectable; tests do not need env).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.core.domain.decision import RoutingMode


@dataclass(frozen=True, kw_only=True)
class DecisionEngineSettings:
    routing_mode: str = RoutingMode.LEGACY.value
    shadow_mode: bool = False
    high_confidence: float = 0.90
    low_confidence: float = 0.65
    canary_percentage: int = 0
    shadow_sample_rate: float = 0.0
    jev_timeout_seconds: float = 8.0
    jev_model: str = "jev-latest"
    jev_canary_model: str = ""
    jev_canary_percentage: int = 0
    jev_base_url: str = "https://api.typesafe.ai"
    jev_api_key: str = ""
    fallback_model: str = ""
    complex_model: str = ""
    noul_yes: float = 0.65
    noul_no: float = 0.35
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 30.0
    estimated_cost_per_1k: float = 0.0005

    @property
    def jev_configured(self) -> bool:
        return bool(self.jev_api_key.strip())

    def jev_model_for(self, request_id: UUID | None) -> str:
        """Modelo efectivo: producción, o candidato/canary si toca el request."""
        canary = (self.jev_canary_model or "").strip()
        if (
            canary
            and canary != self.jev_model
            and request_id is not None
            and int(self.jev_canary_percentage or 0) > 0
        ):
            from src.decision.routing import in_canary

            if in_canary(request_id, int(self.jev_canary_percentage)):
                return canary
        return self.jev_model

    @property
    def effective_mode(self) -> str:
        mode = (self.routing_mode or RoutingMode.LEGACY.value).strip().lower()
        if mode not in {m.value for m in RoutingMode}:
            return RoutingMode.LEGACY.value
        return mode

    def shadow_enabled(self) -> bool:
        return bool(self.shadow_mode) or self.effective_mode == RoutingMode.SHADOW.value

    def samples(self, request_id: UUID | None) -> bool:
        """Sampled observation for legacy traffic (never changes execution)."""
        if request_id is None:
            return False
        rate = max(0.0, min(1.0, float(self.shadow_sample_rate or 0.0)))
        if rate <= 0.0:
            return False
        from src.decision.routing import in_canary

        return in_canary(request_id, int(round(rate * 100)))

    def observes(self, request_id: UUID | None) -> bool:
        """True when JEV may run observationally (shadow or sampled)."""
        return self.shadow_enabled() or self.samples(request_id)

    def tracked(self, request_id: UUID | None) -> bool:
        """True when a decision trace should be written for this request."""
        return self.acts(request_id) or self.observes(request_id)

    def acts(self, request_id: UUID | None) -> bool:
        """True when the engine may change execution."""
        mode = self.effective_mode
        if mode == RoutingMode.JEV.value:
            return True
        if mode == RoutingMode.HYBRID.value:
            if request_id is None:
                return False
            from src.decision.routing import in_canary

            return in_canary(request_id, self.canary_percentage)
        return False


def settings_from_app() -> DecisionEngineSettings:
    from src.core.config import get_settings

    s = get_settings()
    key = s.JEV_API_KEY.get_secret_value() if s.JEV_API_KEY is not None else ""
    return DecisionEngineSettings(
        routing_mode=s.DECISION_ROUTING_MODE,
        shadow_mode=s.JEV_SHADOW_MODE,
        high_confidence=s.JEV_ROUTING_HIGH_CONFIDENCE,
        low_confidence=s.JEV_ROUTING_LOW_CONFIDENCE,
        canary_percentage=s.JEV_CANARY_PERCENTAGE,
        shadow_sample_rate=s.RUNTIME_SHADOW_SAMPLE_RATE,
        jev_timeout_seconds=float(s.JEV_TIMEOUT_SECONDS),
        jev_model=s.JEV_MODEL,
        jev_canary_model=s.JEV_CANARY_MODEL or "",
        jev_canary_percentage=int(s.JEV_CANARY_PERCENTAGE or 0),
        jev_base_url=s.JEV_BASE_URL.rstrip("/"),
        jev_api_key=key or "",
        fallback_model=s.DECISION_FALLBACK_MODEL or s.GATEWAY_CHEAP_MODEL or s.LITELLM_DEFAULT_MODEL,
        complex_model=s.DECISION_COMPLEX_MODEL or s.GATEWAY_QUALITY_MODEL or s.LITELLM_DEFAULT_MODEL,
        noul_yes=s.DECISION_NOUL_YES,
        noul_no=s.DECISION_NOUL_NO,
        circuit_failure_threshold=s.JEV_CIRCUIT_FAILURE_THRESHOLD,
        circuit_recovery_seconds=float(s.JEV_CIRCUIT_RECOVERY_SECONDS),
    )
