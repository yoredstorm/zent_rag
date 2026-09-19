# =============================================================================
# Adaptive RAG health snapshot.
# =============================================================================
from __future__ import annotations

from src.rag.adaptive.settings import AdaptiveRagSettings, settings_from_app


def adaptive_health(settings: AdaptiveRagSettings | None = None) -> dict:
    cfg = settings or settings_from_app()
    mode = cfg.effective_mode
    status = "ok"
    if mode == "active":
        status = "ok"
    return {
        "name": "adaptive_rag",
        "status": status,
        "mode": mode,
        "apply_default": mode == "active",
        "canary_percentage": cfg.canary_percentage,
        "max_retrieval_attempts": cfg.max_retrieval_attempts,
        "top_k_min": cfg.top_k_min,
        "top_k_max": cfg.top_k_max,
        "jev_evidence": cfg.jev_evidence_enabled,
        "fast_path": cfg.fast_path_enabled,
        "rewrite": cfg.rewrite_enabled,
        "policy_version": cfg.policy_version,
        "detail": f"mode={mode} canary={cfg.canary_percentage}",
    }
