# =============================================================================
# Decision Learning — aprendizaje observacional, nunca mutación automática.
# =============================================================================
# Sólo lectura sobre `decision_traces` + `usage_events`:
#   - ¿dónde se equivoca JEV? (agreement por capability)
#   - ¿qué intents tienen más fallback?
#   - ¿qué tools/agentes/workflows tienen mala selección?
#   - ¿qué thresholds generan más errores? (fallback por bucket)
#   - ¿qué modelo JEV rinde mejor? (producción vs canary)
#
# NO hay fine-tuning, NO se mutan prompts, NO se promueven modelos: los
# reportes alimentan decisiones humanas desde el Control Center.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

CALIBRATION_BUCKETS: tuple[str, ...] = (
    "<0.50",
    "0.50-0.60",
    "0.60-0.70",
    "0.70-0.80",
    "0.80-0.90",
    "0.90-1.00",
)

_BUCKET_CASE = """
    CASE
        WHEN confidence < 0.50 THEN '<0.50'
        WHEN confidence < 0.60 THEN '0.50-0.60'
        WHEN confidence < 0.70 THEN '0.60-0.70'
        WHEN confidence < 0.80 THEN '0.70-0.80'
        WHEN confidence < 0.90 THEN '0.80-0.90'
        ELSE '0.90-1.00'
    END
"""


async def _rows(query: str, params: dict[str, Any]) -> list[dict]:
    session = await get_async_session()
    try:
        result = await session.execute(text(query), params)
        return [dict(row) for row in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001 — reportes nunca rompen el request
        logger.warning("decision learning query failed", error=str(exc)[:200])
        return []
    finally:
        await session.close()


def _scope(organization_id: UUID | None, days: int) -> tuple[str, dict[str, Any]]:
    window = max(1, min(int(days or 30), 365))
    if organization_id is None:
        return "", {"days": window}
    return " AND organization_id = :oid", {"days": window, "oid": organization_id}


async def decision_learning_report(
    *,
    organization_id: UUID | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Agregaciones para responder dónde se equivoca el Judgment Fabric."""
    where, params = _scope(organization_id, days)
    window = "created_at > NOW() - (:days * INTERVAL '1 day')"
    base = f"FROM decision_traces WHERE {window}{where}"

    mismatches = await _rows(
        f"""
        SELECT selected_capability AS capability,
               COALESCE(jev_capability, selected_capability) AS jev_capability,
               actual_capability,
               COUNT(*)::int AS cases,
               AVG(confidence)::float AS avg_confidence
        {base}
          AND agreement IS FALSE
        GROUP BY 1, 2, 3
        ORDER BY cases DESC
        LIMIT 20
        """,
        params,
    )
    fallbacks = await _rows(
        f"""
        SELECT selected_capability AS capability,
               COUNT(*)::int AS decisions,
               COUNT(*) FILTER (WHERE fallback_used)::int AS fallbacks,
               AVG(confidence)::float AS avg_confidence
        {base}
        GROUP BY 1
        HAVING COUNT(*) > 0
        ORDER BY fallbacks DESC, decisions DESC
        LIMIT 20
        """,
        params,
    )
    targets = await _rows(
        f"""
        SELECT selected_capability AS capability,
               COUNT(*)::int AS decisions,
               COUNT(*) FILTER (WHERE agreement IS FALSE)::int AS mismatches,
               COUNT(*) FILTER (WHERE fallback_used)::int AS fallbacks
        {base}
          AND (selected_capability LIKE 'tool.%'
               OR selected_capability LIKE 'agent.%'
               OR selected_capability LIKE 'workflow.%')
        GROUP BY 1
        ORDER by mismatches DESC, decisions DESC
        LIMIT 20
        """,
        params,
    )
    fallback_confidence = await _rows(
        f"""
        SELECT {_BUCKET_CASE} AS bucket,
               COUNT(*)::int AS fallbacks,
               COUNT(*) FILTER (WHERE agreement IS FALSE)::int AS mismatches
        {base}
          AND fallback_used
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )
    volume = await _rows(
        f"""
        SELECT COUNT(*)::int AS decisions,
               COUNT(*) FILTER (WHERE agreement IS NOT NULL)::int AS labeled,
               COUNT(*) FILTER (WHERE agreement IS TRUE)::int AS agreed,
               COUNT(*) FILTER (WHERE fallback_used)::int AS fallbacks,
               COUNT(*) FILTER (WHERE shadow)::int AS shadow
        {base}
        """,
        params,
    )
    totals = volume[0] if volume else {}
    labeled = int(totals.get("labeled") or 0)
    agreed = int(totals.get("agreed") or 0)
    return {
        "window_days": params["days"],
        "totals": {
            "decisions": int(totals.get("decisions") or 0),
            "labeled": labeled,
            "agreed": agreed,
            "fallbacks": int(totals.get("fallbacks") or 0),
            "shadow": int(totals.get("shadow") or 0),
            "routing_accuracy": round(agreed / labeled, 4) if labeled else None,
        },
        "mismatches": mismatches,
        "fallbacks_by_capability": fallbacks,
        "target_selection": targets,
        "fallbacks_by_confidence": fallback_confidence,
        "notes": [
            "user_retry no está instrumentado todavía (se aproxima con mismatches).",
            "Sin chain-of-thought: sólo etiquetas, confianza y resultado.",
        ],
    }


async def confidence_calibration(
    *,
    organization_id: UUID | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """¿Cuando JEV dice 0.9 acierta ~90%? Buckets con agreement real."""
    where, params = _scope(organization_id, days)
    window = "created_at > NOW() - (:days * INTERVAL '1 day')"
    rows = await _rows(
        f"""
        SELECT {_BUCKET_CASE} AS bucket,
               COUNT(*)::int AS decisions,
               COUNT(*) FILTER (WHERE agreement IS NOT NULL)::int AS labeled,
               COUNT(*) FILTER (WHERE agreement IS TRUE)::int AS agreed,
               COUNT(*) FILTER (WHERE fallback_used)::int AS fallbacks,
               AVG(confidence)::float AS avg_confidence,
               AVG(latency_ms)::float AS avg_latency_ms,
               COALESCE(SUM(estimated_cost), 0)::float AS cost
        FROM decision_traces
        WHERE {window}{where}
        GROUP BY 1
        """,
        params,
    )
    by_bucket = {str(row["bucket"]): row for row in rows}
    buckets: list[dict[str, Any]] = []
    for name in CALIBRATION_BUCKETS:
        row = by_bucket.get(name)
        if row is None:
            buckets.append(
                {
                    "bucket": name,
                    "decisions": 0,
                    "labeled": 0,
                    "accuracy": None,
                    "fallback_rate": None,
                    "avg_confidence": None,
                    "cost": 0.0,
                    "calibrated": None,
                }
            )
            continue
        labeled = int(row.get("labeled") or 0)
        agreed = int(row.get("agreed") or 0)
        decisions = int(row.get("decisions") or 0)
        accuracy = round(agreed / labeled, 4) if labeled else None
        avg_conf = float(row.get("avg_confidence") or 0.0)
        expected = _bucket_midpoint(name)
        buckets.append(
            {
                "bucket": name,
                "decisions": decisions,
                "labeled": labeled,
                "agreed": agreed,
                "accuracy": accuracy,
                "fallback_rate": (
                    round(int(row.get("fallbacks") or 0) / decisions, 4) if decisions else None
                ),
                "avg_confidence": round(avg_conf, 4),
                "expected_accuracy": expected,
                "calibration_gap": (
                    round(accuracy - expected, 4)
                    if accuracy is not None and expected is not None
                    else None
                ),
                "avg_latency_ms": round(float(row.get("avg_latency_ms") or 0.0), 2),
                "cost": round(float(row.get("cost") or 0.0), 6),
            }
        )
    labeled_total = sum(int(b["labeled"] or 0) for b in buckets)
    agreed_total = sum(int(b.get("agreed") or 0) for b in buckets)
    return {
        "window_days": params["days"],
        "buckets": buckets,
        "labeled": labeled_total,
        "accuracy": round(agreed_total / labeled_total, 4) if labeled_total else None,
        "note": "accuracy = agreement real contra lo que efectivamente se ejecutó",
    }


def _bucket_midpoint(name: str) -> float | None:
    if name.startswith("<"):
        return None
    try:
        low, high = name.split("-")
        return round((float(low) + float(high)) / 2, 4)
    except (ValueError, AttributeError):
        return None


async def model_comparison(
    *,
    organization_id: UUID | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Producción vs candidato/canary por modelo JEV. Sin promoción automática."""
    where, params = _scope(organization_id, days)
    window = "created_at > NOW() - (:days * INTERVAL '1 day')"
    rows = await _rows(
        f"""
        SELECT COALESCE(payload->>'model', provider) AS model,
               provider,
               COUNT(*)::int AS decisions,
               COUNT(*) FILTER (WHERE canary)::int AS canary_decisions,
               COUNT(*) FILTER (WHERE agreement IS NOT NULL)::int AS labeled,
               COUNT(*) FILTER (WHERE agreement IS TRUE)::int AS agreed,
               COUNT(*) FILTER (WHERE fallback_used)::int AS fallbacks,
               AVG(confidence)::float AS avg_confidence,
               AVG(latency_ms)::float AS avg_latency_ms,
               COALESCE(SUM(estimated_cost), 0)::float AS cost
        FROM decision_traces
        WHERE {window}{where}
        GROUP BY 1, 2
        ORDER BY decisions DESC
        LIMIT 20
        """,
        params,
    )
    models = []
    for row in rows:
        labeled = int(row.get("labeled") or 0)
        decisions = int(row.get("decisions") or 0)
        models.append(
            {
                "model": str(row.get("model") or "unknown")[:120],
                "provider": str(row.get("provider") or "")[:40],
                "role": "canary" if int(row.get("canary_decisions") or 0) > 0 else "production",
                "decisions": decisions,
                "routing_accuracy": (
                    round(int(row.get("agreed") or 0) / labeled, 4) if labeled else None
                ),
                "fallback_rate": (
                    round(int(row.get("fallbacks") or 0) / decisions, 4) if decisions else None
                ),
                "avg_confidence": round(float(row.get("avg_confidence") or 0.0), 4),
                "avg_latency_ms": round(float(row.get("avg_latency_ms") or 0.0), 2),
                "cost": round(float(row.get("cost") or 0.0), 6),
            }
        )
    return {
        "window_days": params["days"],
        "models": models,
        "flow": ["candidate", "shadow", "evaluation", "manual_promote"],
        "note": "La promoción es manual: el reporte no cambia JEV_MODEL.",
    }
