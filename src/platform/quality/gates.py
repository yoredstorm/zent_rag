"""Quality Gates (FASE 03, S4/S5).

Gates configurables por organización o workspace sobre métricas del engine
(composite_score, faithfulness, answer_relevance, hallucination_rate,
sql_accuracy — solo métricas que el engine realmente calcula) y bloqueo de
regresiones comparando la versión candidata vs la actualmente desplegada.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

# Métricas que el eval engine soporta realmente (spec: no hardcodear otras).
SUPPORTED_THRESHOLD_METRICS = (
    "composite_score",
    "faithfulness",
    "answer_relevance",
    "context_relevance",
    "retrieval_precision",
    "retrieval_recall",
    "citation_accuracy",
    "sql_accuracy",
)

DEFAULT_GATE = {
    "thresholds": {},
    "max_hallucination": None,
    "max_regression_pct": 5.0,
}

_VALID_KEYS = set(SUPPORTED_THRESHOLD_METRICS) | {"max_hallucination", "max_regression_pct"}


def sanitize_gate(payload: dict) -> dict:
    """Valida un payload de gate: solo métricas soportadas, 0..1."""
    thresholds_raw = payload.get("thresholds") or {}
    thresholds: dict[str, float] = {}
    for key, value in thresholds_raw.items():
        if key not in SUPPORTED_THRESHOLD_METRICS:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if key == "max_hallucination":
            thresholds["max_hallucination"] = v
        elif 0.0 <= v <= 1.0:
            thresholds[key] = v
    max_hallucination = payload.get("max_hallucination")
    if max_hallucination is not None:
        max_hallucination = float(max_hallucination)
        if not 0.0 <= max_hallucination <= 1.0:
            max_hallucination = None
    max_regression_pct = float(payload.get("max_regression_pct", 5.0))
    if not 0.0 <= max_regression_pct <= 50.0:
        max_regression_pct = 5.0
    return {
        "thresholds": thresholds,
        "max_hallucination": max_hallucination,
        "max_regression_pct": max_regression_pct,
    }


def gate_enabled(gate: dict | None) -> bool:
    if not gate:
        return False
    return bool(
        gate.get("thresholds")
        or gate.get("max_hallucination") is not None
    )


def _metric_value(quality: dict | None, key: str) -> float | None:
    if not quality:
        return None
    value = quality.get(key)
    if value is None or value is True or value is False:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def get_gate(organization_id: UUID, workspace_id: UUID | None) -> dict:
    session = await get_async_session()
    try:
        if workspace_id is not None:
            row = (
                await session.execute(
                    text(
                        "SELECT thresholds, max_hallucination, max_regression_pct "
                        "FROM quality_gates WHERE organization_id = :oid AND workspace_id = :wid"
                    ),
                    {"oid": organization_id, "wid": workspace_id},
                )
            ).fetchone()
            if row is not None:
                return _row_to_gate(row)
        row = (
            await session.execute(
                text(
                    "SELECT thresholds, max_hallucination, max_regression_pct "
                    "FROM quality_gates WHERE organization_id = :oid AND workspace_id IS NULL"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return dict(DEFAULT_GATE)
    return _row_to_gate(row)


def _row_to_gate(row) -> dict:
    return {
        "thresholds": dict(row.thresholds or {}),
        "max_hallucination": float(row.max_hallucination) if row.max_hallucination is not None else None,
        "max_regression_pct": float(row.max_regression_pct or 5.0),
    }


async def upsert_gate(
    organization_id: UUID,
    payload: dict,
    workspace_id: UUID | None = None,
    updated_by: UUID | None = None,
) -> dict:
    import json

    clean = sanitize_gate(payload)
    thresholds = {k: v for k, v in clean["thresholds"].items()}
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO quality_gates "
                "(organization_id, workspace_id, thresholds, max_hallucination, "
                "max_regression_pct, updated_by) "
                "VALUES (:oid, :wid, CAST(:thresholds AS jsonb), :hall, :reg, :by) "
                "ON CONFLICT (organization_id, workspace_id) DO UPDATE SET "
                "thresholds = EXCLUDED.thresholds, "
                "max_hallucination = EXCLUDED.max_hallucination, "
                "max_regression_pct = EXCLUDED.max_regression_pct, "
                "updated_by = EXCLUDED.updated_by, updated_at = now()"
            ),
            {
                "oid": organization_id,
                "wid": workspace_id,
                "thresholds": json.dumps(thresholds),
                "hall": clean["max_hallucination"],
                "reg": clean["max_regression_pct"],
                "by": updated_by,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return clean


async def gate_blocked(quality: dict | None, gate: dict | None) -> list[str]:
    """Reasons por thresholds si la calidad no pasa el gate (vacío = pasa)."""
    if not gate_enabled(gate):
        return []
    reasons: list[str] = []
    for key, minimum in (gate or {}).get("thresholds", {}).items():
        value = _metric_value(quality, key)
        if value is not None and value < minimum:
            reasons.append(
                f"{key} {value:.3f} < umbral {minimum:.3f}"
            )
    max_hall = (gate or {}).get("max_hallucination")
    if max_hall is not None:
        hall = _metric_value(quality, "hallucination_rate")
        if hall is not None and hall > max_hall:
            reasons.append(f"hallucination_rate {hall:.3f} > {max_hall:.3f}")
    return reasons


async def regression_blocked(
    candidate_quality: dict | None,
    baseline_quality: dict | None,
    gate: dict | None,
) -> list[str]:
    """Compara la calidad candidata vs la desplegada (S5).

    Solo métricas presentes en AMBOS runs; una caída mayor a
    max_regression_pct en cualquiera bloquea.
    """
    if not baseline_quality or not candidate_quality:
        return []
    max_drop = (gate or {}).get("max_regression_pct", 5.0) / 100.0
    reasons: list[str] = []
    shared = [
        key
        for key in (*SUPPORTED_THRESHOLD_METRICS, "hallucination_rate")
        if key in baseline_quality and key in candidate_quality
    ]
    for key in shared:
        base = _metric_value(baseline_quality, key)
        cand = _metric_value(candidate_quality, key)
        if base is None or cand is None:
            continue
        if key == "hallucination_rate":
            # Menor es mejor: regresión = sube
            drop = cand - base
        else:
            drop = base - cand
        if drop > max_drop:
            reasons.append(
                f"{key} bajó {drop * 100:.1f} p.p. "
                f"({base * 100:.1f}% → {cand * 100:.1f}%) vs versión desplegada"
            )
    return reasons
