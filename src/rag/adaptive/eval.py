# =============================================================================
# Adaptive vs Legacy evaluation — uses existing compare_runs.
# =============================================================================
from __future__ import annotations

from src.rag.evaluation.regression import compare_runs


def compare_legacy_vs_adaptive(
    adaptive: dict,
    legacy: dict,
    thresholds: dict | None = None,
) -> dict:
    """Shadow / A/B / canary must beat or match legacy before 100% cutover."""
    report = compare_runs(adaptive, legacy, thresholds=thresholds)
    report["comparison"] = "legacy_vs_adaptive"
    adaptive_perf = adaptive.get("performance") or {}
    legacy_perf = legacy.get("performance") or {}
    adaptive_tokens = float(adaptive_perf.get("avg_tokens") or 0.0)
    legacy_tokens = float(legacy_perf.get("avg_tokens") or 0.0)
    adaptive_cost = float(adaptive_perf.get("avg_cost") or 0.0)
    legacy_cost = float(legacy_perf.get("avg_cost") or 0.0)
    tokens_saved = round(legacy_tokens - adaptive_tokens, 2) if legacy_tokens else 0.0
    cost_saved = round(legacy_cost - adaptive_cost, 6) if legacy_cost else 0.0
    llm_avoided = int(
        (adaptive.get("adaptive") or {}).get("llm_calls_avoided") or 0
    )
    report["savings"] = {
        "tokens_saved_vs_baseline": tokens_saved,
        "cost_saved_vs_baseline": cost_saved,
        "llm_calls_avoided": llm_avoided,
    }
    report["rollout"] = {
        "shadow": "observe AdaptivePlan without changing retrieval",
        "canary": "ADAPTIVE_RAG_MODE=canary + ADAPTIVE_RAG_CANARY_PERCENTAGE",
        "ab": "run golden dataset twice (legacy vs active) then compare_legacy_vs_adaptive",
        "cutover": "only after faithfulness and hallucination pass against legacy",
    }
    return report
