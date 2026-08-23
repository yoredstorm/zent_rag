# =============================================================================
# Usage Alerts — umbrales 50/80/90/100, anti-duplicado, ack
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.platform.billing.alerts import (
    acknowledge_alert,
    check_and_alert,
    list_alerts,
)
from src.platform.billing.quota_service import upsert_org_limits
from src.platform.usage.usage_engine import UsageCounters


def _require_dev():
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres/Redis real (stack docker)")


class TestAlerts:
    @pytest.mark.asyncio
    async def test_thresholds_trigger_once_per_window(self) -> None:
        _require_dev()
        org = uuid4()
        await upsert_org_limits(org, monthly_tokens=100)
        counters = UsageCounters()
        # 60 tokens sobre 100 = 60% → alerta 50.
        await counters.record(org, uuid4(), tokens=60, cost=0.01)
        created = await check_and_alert(org)
        thresholds = {a["threshold_pct"] for a in created}
        assert 50 in thresholds
        assert 80 not in thresholds
        assert 100 not in thresholds

        # Misma ventana: no duplica el umbral ya alertado.
        await counters.record(org, uuid4(), tokens=5, cost=0.01)
        created_again = await check_and_alert(org)
        assert all(a["threshold_pct"] != 50 for a in created_again)

    @pytest.mark.asyncio
    async def test_high_usage_triggers_all_thresholds(self) -> None:
        _require_dev()
        org = uuid4()
        await upsert_org_limits(org, monthly_tokens=100)
        counters = UsageCounters()
        await counters.record(org, uuid4(), tokens=120, cost=0.01)
        created = await check_and_alert(org)
        thresholds = {a["threshold_pct"] for a in created}
        assert thresholds == {50, 80, 90, 100}

    @pytest.mark.asyncio
    async def test_list_and_ack(self) -> None:
        _require_dev()
        org = uuid4()
        await upsert_org_limits(org, monthly_tokens=100)
        counters = UsageCounters()
        await counters.record(org, uuid4(), tokens=60, cost=0.01)
        await check_and_alert(org)

        alerts = await list_alerts(org)
        assert alerts, "alert must be listed"
        first = alerts[0]
        assert first["acknowledged_at"] is None

        from uuid import UUID

        ok = await acknowledge_alert(org, UUID(first["id"]))
        assert ok is True
        # Ack idempotente: segunda vez no modifica.
        assert await acknowledge_alert(org, UUID(first["id"])) is False

        alerts = await list_alerts(org)
        assert alerts[0]["acknowledged_at"] is not None

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation(self) -> None:
        _require_dev()
        org_a = uuid4()
        org_b = uuid4()
        await upsert_org_limits(org_a, monthly_tokens=100)
        counters = UsageCounters()
        await counters.record(org_a, uuid4(), tokens=60, cost=0.01)
        await check_and_alert(org_a)

        # B no ve las alertas de A.
        assert await list_alerts(org_b) == []

