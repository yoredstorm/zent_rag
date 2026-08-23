# =============================================================================
# Quota Service — límites por tenant (daily/monthly: requests, tokens, cost)
# =============================================================================
# Límites: usage_quotas por org (overrides) → plan (tokens_per_month,
# monthly_cost_limit, requests_per_month) → defaults de settings.
# Consumo: contadores Redis del Usage Engine (dedupe idempotente).
# Pre-flight: chequeo ANTES de ejecutar con margen conservador.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.usage.usage_engine import get_usage_counters

logger = get_logger(__name__)

_QUOTAS_TABLE = """
CREATE TABLE IF NOT EXISTS usage_quotas (
    organization_id UUID PRIMARY KEY,
    daily_requests BIGINT,
    daily_tokens BIGINT,
    daily_cost DOUBLE PRECISION,
    monthly_requests BIGINT,
    monthly_tokens BIGINT,
    monthly_cost DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_PLANS_COLUMNS = (
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS tokens_per_month BIGINT",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS monthly_cost_limit DOUBLE PRECISION",
)


class QuotaExceededError(Exception):
    """Quota excedida (tokens o costo). El caller mapea a 429."""

    def __init__(self, message: str, quota_type: str = "") -> None:
        super().__init__(message)
        self.quota_type = quota_type


@dataclass(kw_only=True, frozen=True)
class QuotaLimits:
    daily_tokens: int | None = None
    daily_cost: float | None = None
    monthly_tokens: int | None = None
    monthly_cost: float | None = None


async def ensure_quota_table() -> None:
    session = await get_async_session()
    try:
        try:
            await session.execute(text(_QUOTAS_TABLE))
            await session.commit()
        except Exception:
            await session.rollback()
        for ddl in _PLANS_COLUMNS:
            try:
                await session.execute(text(ddl))
                await session.commit()
            except Exception:
                await session.rollback()
    finally:
        await session.close()


async def get_limits(organization_id: UUID) -> QuotaLimits:
    """Límites efectivos: overrides de usage_quotas → plan → settings."""
    settings = get_settings()
    await ensure_quota_table()
    session = await get_async_session()
    limits = QuotaLimits()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT daily_tokens, daily_cost, monthly_tokens, "
                    "monthly_cost FROM usage_quotas "
                    "WHERE organization_id = :org"
                ),
                {"org": organization_id},
            )
        ).fetchone()
        if row is not None:
            return QuotaLimits(
                daily_tokens=int(row.daily_tokens) if row.daily_tokens else None,
                daily_cost=float(row.daily_cost) if row.daily_cost else None,
                monthly_tokens=(
                    int(row.monthly_tokens) if row.monthly_tokens else None
                ),
                monthly_cost=float(row.monthly_cost) if row.monthly_cost else None,
            )

        plan_row = None
        try:
            plan_row = (
                await session.execute(
                    text(
                        "SELECT p.tokens_per_month, p.monthly_cost_limit "
                        "FROM subscriptions s JOIN plans p ON s.plan_id = p.id "
                        "WHERE s.organization_id = :org "
                        "AND s.status IN ('TRIALING','ACTIVE') "
                        "ORDER BY s.created_at DESC LIMIT 1"
                    ),
                    {"org": organization_id},
                )
            ).fetchone()
        except Exception as exc:
            # Fail-open: si el schema de planes aún no tiene las columnas,
            # no bloquear el request (el pre-flight queda sin límites).
            logger.warning("Plan quota lookup failed (fail-open)", error=str(exc))
        if plan_row is not None:
            limits = QuotaLimits(
                monthly_tokens=(
                    int(plan_row.tokens_per_month)
                    if plan_row.tokens_per_month
                    else None
                ),
                monthly_cost=(
                    float(plan_row.monthly_cost_limit)
                    if plan_row.monthly_cost_limit
                    else None
                ),
            )
    finally:
        await session.close()
    return limits


async def check_preflight(
    organization_id: UUID,
    *,
    estimated_tokens: int = 0,
    estimated_cost: float = 0.0,
) -> None:
    """Chequea consumo acumulado + margen vs límites. Lanza QuotaExceededError."""
    limits = await get_limits(organization_id)
    settings = get_settings()
    margin_tokens = int(settings.USAGE_QUOTA_MARGIN_TOKENS)
    usage = await get_usage_counters().window_usage(organization_id)

    checks: list[tuple[str, float, int | float | None]] = [
        (
            "daily_tokens",
            usage["daily"]["tokens"] + estimated_tokens + margin_tokens,
            limits.daily_tokens,
        ),
        (
            "monthly_tokens",
            usage["monthly"]["tokens"] + estimated_tokens + margin_tokens,
            limits.monthly_tokens,
        ),
        (
            "daily_cost",
            usage["daily"]["cost"] + estimated_cost,
            limits.daily_cost,
        ),
        (
            "monthly_cost",
            usage["monthly"]["cost"] + estimated_cost,
            limits.monthly_cost,
        ),
    ]
    for quota_type, projected, limit in checks:
        if limit is None:
            continue
        if projected > float(limit):
            raise QuotaExceededError(
                f"{quota_type} quota exceeded: projected {projected:.1f} "
                f"> limit {float(limit):.1f}",
                quota_type=quota_type,
            )


async def upsert_org_limits(
    organization_id: UUID,
    *,
    daily_tokens: int | None = None,
    daily_cost: float | None = None,
    monthly_tokens: int | None = None,
    monthly_cost: float | None = None,
) -> None:
    """Actualiza overrides de límites de un tenant (admin)."""
    await ensure_quota_table()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_quotas "
                "(organization_id, daily_tokens, daily_cost, monthly_tokens, "
                "monthly_cost) VALUES (:org, :dt, :dc, :mt, :mc) "
                "ON CONFLICT (organization_id) DO UPDATE SET "
                "daily_tokens = EXCLUDED.daily_tokens, "
                "daily_cost = EXCLUDED.daily_cost, "
                "monthly_tokens = EXCLUDED.monthly_tokens, "
                "monthly_cost = EXCLUDED.monthly_cost, updated_at = NOW()"
            ),
            {
                "org": organization_id,
                "dt": daily_tokens,
                "dc": daily_cost,
                "mt": monthly_tokens,
                "mc": monthly_cost,
            },
        )
        await session.commit()
    finally:
        await session.close()

