# =============================================================================
# Decision Engine health snapshot.
# =============================================================================
from __future__ import annotations

from src.decision.settings import DecisionEngineSettings, settings_from_app


def decision_health(settings: DecisionEngineSettings | None = None) -> dict:
    cfg = settings or settings_from_app()
    jev = "connected" if cfg.jev_configured else "not_configured"
    fallback = "available" if bool(cfg.fallback_model) else "missing"
    return {
        "name": "decision_engine",
        "status": "ok" if fallback == "available" else "degraded",
        "primary": "jev" if cfg.jev_configured else "rules",
        "fallback": cfg.fallback_model or "",
        "mode": cfg.effective_mode,
        "shadow": cfg.shadow_enabled(),
        "high_confidence": cfg.high_confidence,
        "low_confidence": cfg.low_confidence,
        "canary_percentage": cfg.canary_percentage,
        "jev": jev,
        "fallback_available": fallback,
        "rules_loaded": True,
        "detail": f"jev={jev} fallback={fallback} mode={cfg.effective_mode}",
    }
