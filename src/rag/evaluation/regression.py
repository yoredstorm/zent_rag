# =============================================================================
# Evaluation Regression — comparación de dos runs (baseline vs current)
# =============================================================================
# Alerta cuando la versión nueva empeora:
#   - quality: score compuesto y faithfulness bajan más del umbral,
#     hallucination_rate sube más del umbral.
#   - cost: costo promedio por caso sube más del umbral porcentual.
#   - latency: p95 sube más del umbral porcentual o absoluto.
# Veredictos por dimensión: pass | warn | fail; overall = peor de todos.
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings

_STATUS_RANK = {"pass": 0, "unknown": 0, "warn": 1, "fail": 2}


def _thresholds() -> dict:
    settings = get_settings()
    return {
        "quality_min_delta": settings.EVAL_REGRESSION_QUALITY_MIN_DELTA,
        "faithfulness_min_delta": settings.EVAL_REGRESSION_FAITHFULNESS_MIN_DELTA,
        "hallucination_max_delta": settings.EVAL_REGRESSION_HALLUCINATION_MAX_DELTA,
        "cost_max_increase_pct": settings.EVAL_REGRESSION_COST_MAX_INCREASE_PCT,
        "latency_max_increase_pct": settings.EVAL_REGRESSION_LATENCY_MAX_INCREASE_PCT,
        "latency_max_increase_ms": settings.EVAL_REGRESSION_LATENCY_MAX_INCREASE_MS,
    }


def _verdict_for_downward(
    delta: float,
    warn_at: float,
    fail_at: float,
) -> str:
    """Veredicto para métricas donde menor = peor (score, faithfulness)."""
    if delta <= fail_at:
        return "fail"
    if delta <= warn_at:
        return "warn"
    return "pass"


def _verdict_for_upward(
    delta: float,
    warn_at: float,
    fail_at: float,
) -> str:
    """Veredicto para métricas donde mayor = peor (hallucination, cost, latency)."""
    if delta >= fail_at:
        return "fail"
    if delta >= warn_at:
        return "warn"
    return "pass"


def _quality_dimension(current: dict, baseline: dict, t: dict) -> dict:
    current_score = current.get("quality", {}).get("composite_score")
    baseline_score = baseline.get("quality", {}).get("composite_score")
    if current_score is None or baseline_score is None:
        return _unknown("quality", "composite_score", current_score, baseline_score)
    delta = round(current_score - baseline_score, 4)
    return {
        "dimension": "quality",
        "metric": "composite_score",
        "baseline": baseline_score,
        "current": current_score,
        "delta": delta,
        "warn_at": round(t["quality_min_delta"] / 2, 4),
        "fail_at": t["quality_min_delta"],
        "status": _verdict_for_downward(
            delta, t["quality_min_delta"] / 2, t["quality_min_delta"]
        ),
    }


def _faithfulness_dimension(current: dict, baseline: dict, t: dict) -> dict:
    current_value = current.get("quality", {}).get("faithfulness")
    baseline_value = baseline.get("quality", {}).get("faithfulness")
    if current_value is None or baseline_value is None:
        return _unknown("faithfulness", "faithfulness", current_value, baseline_value)
    delta = round(current_value - baseline_value, 4)
    return {
        "dimension": "faithfulness",
        "metric": "faithfulness",
        "baseline": baseline_value,
        "current": current_value,
        "delta": delta,
        "warn_at": round(t["faithfulness_min_delta"] / 2, 4),
        "fail_at": t["faithfulness_min_delta"],
        "status": _verdict_for_downward(
            delta, t["faithfulness_min_delta"] / 2, t["faithfulness_min_delta"]
        ),
    }


def _hallucination_dimension(current: dict, baseline: dict, t: dict) -> dict:
    current_value = current.get("quality", {}).get("hallucination_rate")
    baseline_value = baseline.get("quality", {}).get("hallucination_rate")
    if current_value is None or baseline_value is None:
        return _unknown(
            "hallucination", "hallucination_rate", current_value, baseline_value
        )
    delta = round(current_value - baseline_value, 4)
    return {
        "dimension": "hallucination",
        "metric": "hallucination_rate",
        "baseline": baseline_value,
        "current": current_value,
        "delta": delta,
        "warn_at": round(t["hallucination_max_delta"] / 2, 4),
        "fail_at": t["hallucination_max_delta"],
        "status": _verdict_for_upward(
            delta, t["hallucination_max_delta"] / 2, t["hallucination_max_delta"]
        ),
    }


def _cost_dimension(current: dict, baseline: dict, t: dict) -> dict:
    current_value = current.get("performance", {}).get("avg_cost")
    baseline_value = baseline.get("performance", {}).get("avg_cost")
    if not current_value or not baseline_value:
        return _unknown("cost", "avg_cost", current_value, baseline_value)
    pct = round((current_value - baseline_value) / baseline_value * 100, 2)
    return {
        "dimension": "cost",
        "metric": "avg_cost",
        "baseline": baseline_value,
        "current": current_value,
        "delta_pct": pct,
        "warn_at_pct": round(t["cost_max_increase_pct"] / 2, 2),
        "fail_at_pct": t["cost_max_increase_pct"],
        "status": _verdict_for_upward(
            pct, t["cost_max_increase_pct"] / 2, t["cost_max_increase_pct"]
        ),
    }


def _latency_dimension(current: dict, baseline: dict, t: dict) -> dict:
    current_value = (
        current.get("performance", {}).get("latency", {}).get("p95_ms") or 0.0
    )
    baseline_value = (
        baseline.get("performance", {}).get("latency", {}).get("p95_ms") or 0.0
    )
    if not current_value or not baseline_value:
        return _unknown("latency", "p95_ms", current_value, baseline_value)
    abs_delta = round(current_value - baseline_value, 2)
    pct = round(abs_delta / baseline_value * 100, 2) if baseline_value else 0.0
    status = _verdict_for_upward(
        pct, t["latency_max_increase_pct"] / 2, t["latency_max_increase_pct"]
    )
    abs_status = _verdict_for_upward(
        abs_delta,
        t["latency_max_increase_ms"] / 2,
        t["latency_max_increase_ms"],
    )
    if _STATUS_RANK[abs_status] > _STATUS_RANK[status]:
        status = abs_status
    return {
        "dimension": "latency",
        "metric": "p95_ms",
        "baseline": baseline_value,
        "current": current_value,
        "delta_ms": abs_delta,
        "delta_pct": pct,
        "warn_at_pct": round(t["latency_max_increase_pct"] / 2, 2),
        "fail_at_pct": t["latency_max_increase_pct"],
        "warn_at_ms": round(t["latency_max_increase_ms"] / 2, 2),
        "fail_at_ms": t["latency_max_increase_ms"],
        "status": status,
    }


def _unknown(dimension: str, metric: str, current_value, baseline_value) -> dict:
    return {
        "dimension": dimension,
        "metric": metric,
        "baseline": baseline_value,
        "current": current_value,
        "status": "unknown",
    }


def compare_runs(current: dict, baseline: dict, thresholds: dict | None = None) -> dict:
    """Compara dos runs y devuelve el reporte de regresión.

    current  = summary del run de la versión nueva.
    baseline = summary del run de la versión anterior.
    """
    t = thresholds or _thresholds()
    dimensions = [
        _quality_dimension(current, baseline, t),
        _faithfulness_dimension(current, baseline, t),
        _hallucination_dimension(current, baseline, t),
        _cost_dimension(current, baseline, t),
        _latency_dimension(current, baseline, t),
    ]
    worst = max((d["status"] for d in dimensions), key=lambda s: _STATUS_RANK.get(s, 0))
    quality = next((d for d in dimensions if d["dimension"] == "quality"), None)
    if quality is None or quality.get("status") == "unknown":
        classification = "no_material_change"
    elif worst == "fail":
        classification = "regression"
    elif worst == "pass" and quality.get("current") is not None and (
        quality.get("delta", 0) > 0
    ):
        classification = "improvement"
    else:
        classification = "no_material_change"
    return {
        "baseline_run_id": baseline.get("run_id"),
        "current_run_id": current.get("run_id"),
        "baseline_version_id": baseline.get("version_id"),
        "current_version_id": current.get("version_id"),
        "overall": worst,
        "classification": classification,
        "dimensions": dimensions,
    }
