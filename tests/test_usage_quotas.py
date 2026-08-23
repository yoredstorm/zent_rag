# =============================================================================
# Usage Quotas — pre-flight, límites por tenant, rollover
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.platform.billing.quota_service import (
    QuotaExceededError,
    check_preflight,
    ensure_quota_table,
    get_limits,
    upsert_org_limits,
)
from src.platform.usage.usage_engine import UsageCounters


def _require_dev():
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres/Redis real (stack docker)")


class TestQuotas:
    @pytest.mark.asyncio
    async def test_limits_override_per_org(self) -> None:
        _require_dev()
        await ensure_quota_table()
        org = uuid4()
        await upsert_org_limits(
            org, monthly_tokens=10_000, monthly_cost=1.0, daily_tokens=1_000
        )
        limits = await get_limits(org)
        assert limits.monthly_tokens == 10_000
        assert limits.monthly_cost == pytest.approx(1.0)
        assert limits.daily_tokens == 1_000

    @pytest.mark.asyncio
    async def test_preflight_blocks_when_projected_over_limit(self) -> None:
        _require_dev()
        org = uuid4()
        await upsert_org_limits(org, daily_tokens=100)
        counters = UsageCounters()
        # Consumo real acumulado: 90 tokens.
        await counters.record(org, uuid4(), tokens=90, cost=0.01)
        # Margen default (1024) + estimado 100 → proyectado > 100 → 429.
        with pytest.raises(QuotaExceededError, match="daily_tokens"):
            await check_preflight(org, estimated_tokens=100, estimated_cost=0.0)

    @pytest.mark.asyncio
    async def test_preflight_passes_under_limit(self) -> None:
        _require_dev()
        org = uuid4()
        await upsert_org_limits(org, monthly_tokens=1_000_000)
        counters = UsageCounters()
        await counters.record(org, uuid4(), tokens=10, cost=0.01)
        # Sin límite diario; mensual holgado → pasa.
        await check_preflight(org, estimated_tokens=100, estimated_cost=0.001)

    @pytest.mark.asyncio
    async def test_cost_quota_blocked(self) -> None:
        _require_dev()
        org = uuid4()
        await upsert_org_limits(org, monthly_cost=0.10)
        counters = UsageCounters()
        await counters.record(org, uuid4(), tokens=1, cost=0.09)
        with pytest.raises(QuotaExceededError, match="monthly_cost"):
            await check_preflight(org, estimated_tokens=10, estimated_cost=0.05)

    @pytest.mark.asyncio
    async def test_rollover_previous_month_not_counted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _require_dev()
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "USAGE_QUOTA_MARGIN_TOKENS", 0)
        org = uuid4()
        await upsert_org_limits(org, monthly_tokens=100)
        counters = UsageCounters()
        last_month = datetime.now(timezone.utc) - timedelta(days=40)
        await counters.record(org, uuid4(), tokens=95, cost=0.1, created_at=last_month)
        # Ventana actual sin consumo: pre-flight pasa pese al uso del mes pasado.
        await check_preflight(org, estimated_tokens=1, estimated_cost=0.0)

