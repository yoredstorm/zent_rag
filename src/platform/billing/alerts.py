# =============================================================================
# Usage Alerts — umbrales de quota 50/80/90/100 con anti-duplicado
# =============================================================================
# Tras cada record_event se chequean umbrales contra límites efectivos.
# Flags Redis evitan re-alertar el mismo umbral en la misma ventana.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.billing.quota_service import get_limits
from src.platform.usage.usage_engine import get_usage_counters

logger = get_logger(__name__)

_ALERTS_TABLE = """
CREATE TABLE IF NOT EXISTS usage_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    quota_type VARCHAR(30) NOT NULL,
    threshold_pct INTEGER NOT NULL,
    usage_value DOUBLE PRECISION NOT NULL,
    limit_value DOUBLE PRECISION NOT NULL,
    alerted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ
)
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_usage_alerts_org "
    "ON usage_alerts(organization_id, alerted_at DESC)"
)


def _thresholds() -> list[int]:
    settings = get_settings()
    return [
        int(t.strip())
        for t in settings.USAGE_ALERT_THRESHOLDS.split(",")
        if t.strip().isdigit()
    ]


async def ensure_alerts_table() -> None:
    session = await get_async_session()
    try:
        await session.execute(text(_ALERTS_TABLE))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(_INDEX_SQL))
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


async def _already_alerted(tenant_id: UUID, quota_type: str, threshold: int) -> bool:
    counters = get_usage_counters()
    redis = await counters._ensure_redis()
    if redis is None:
        return False
    key = f"rag:usage:alert:{tenant_id.hex}:{quota_type}:{threshold}"
    return bool(await redis.exists(key))


async def _mark_alerted(tenant_id: UUID, quota_type: str, threshold: int) -> None:
    counters = get_usage_counters()
    redis = await counters._ensure_redis()
    if redis is None:
        return
    key = f"rag:usage:alert:{tenant_id.hex}:{quota_type}:{threshold}"
    await redis.set(key, "1", ex=60 * 60 * 24 * 33)


async def check_and_alert(organization_id: UUID) -> list[dict]:
    """Chequea umbrales y persiste alertas nuevas. Retorna las creadas."""
    limits = await get_limits(organization_id)
    usage = await get_usage_counters().window_usage(organization_id)
    candidates: list[tuple[str, float, float]] = []
    if limits.daily_tokens:
        candidates.append(("daily_tokens", usage["daily"]["tokens"], float(limits.daily_tokens)))
    if limits.monthly_tokens:
        candidates.append(("monthly_tokens", usage["monthly"]["tokens"], float(limits.monthly_tokens)))
    if limits.daily_cost:
        candidates.append(("daily_cost", usage["daily"]["cost"], float(limits.daily_cost)))
    if limits.monthly_cost:
        candidates.append(("monthly_cost", usage["monthly"]["cost"], float(limits.monthly_cost)))

    created: list[dict] = []
    for quota_type, usage_value, limit_value in candidates:
        if limit_value <= 0:
            continue
        pct = usage_value / limit_value * 100
        for threshold in _thresholds():
            if pct < threshold:
                continue
            if await _already_alerted(organization_id, quota_type, threshold):
                continue
            await _insert_alert(
                organization_id, quota_type, threshold, usage_value, limit_value
            )
            await _mark_alerted(organization_id, quota_type, threshold)
            created.append(
                {
                    "quota_type": quota_type,
                    "threshold_pct": threshold,
                    "usage": round(usage_value, 2),
                    "limit": limit_value,
                }
            )
            logger.warning(
                "Usage quota alert triggered",
                organization_id=str(organization_id),
                quota_type=quota_type,
                threshold_pct=threshold,
            )
    return created


async def _insert_alert(
    organization_id: UUID,
    quota_type: str,
    threshold: int,
    usage_value: float,
    limit_value: float,
) -> None:
    try:
        await ensure_alerts_table()
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO usage_alerts "
                    "(organization_id, quota_type, threshold_pct, "
                    "usage_value, limit_value) "
                    "VALUES (:org, :type, :pct, :usage, :limit)"
                ),
                {
                    "org": organization_id,
                    "type": quota_type,
                    "pct": threshold,
                    "usage": round(usage_value, 2),
                    "limit": limit_value,
                },
            )
            await session.commit()
        finally:
            await session.close()
    except Exception as exc:
        logger.warning("Alert persist failed", error=str(exc))


async def list_alerts(
    organization_id: UUID, *, limit: int = 50, offset: int = 0
) -> list[dict]:
    await ensure_alerts_table()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, quota_type, threshold_pct, usage_value, "
                    "limit_value, alerted_at, acknowledged_at "
                    "FROM usage_alerts WHERE organization_id = :org "
                    "ORDER BY alerted_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"org": organization_id, "limit": limit, "offset": offset},
            )
        ).fetchall()
        return [
            {
                "id": str(r.id),
                "quota_type": r.quota_type,
                "threshold_pct": r.threshold_pct,
                "usage_value": r.usage_value,
                "limit_value": r.limit_value,
                "alerted_at": r.alerted_at.isoformat(),
                "acknowledged_at": (
                    r.acknowledged_at.isoformat()
                    if r.acknowledged_at
                    else None
                ),
            }
            for r in rows
        ]
    finally:
        await session.close()


async def acknowledge_alert(
    organization_id: UUID, alert_id: UUID
) -> bool:
    await ensure_alerts_table()
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE usage_alerts SET acknowledged_at = NOW() "
                "WHERE organization_id = :org AND id = :aid "
                "AND acknowledged_at IS NULL"
            ),
            {"org": organization_id, "aid": alert_id},
        )
        await session.commit()
        rowcount = getattr(result, "rowcount", 0)
        return bool(rowcount and rowcount > 0)
    finally:
        await session.close()

