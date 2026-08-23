# =============================================================================
# Usage Engine — idempotencia, pricing registry, cost, contadores
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.platform.billing.pricing import (
    estimate_cost,
    estimate_cost_from_price,
    extract_model,
    extract_provider,
    get_price,
    upsert_price,
)
from src.platform.usage.usage_engine import (
    UsageCounters,
    UsageEvent,
    record_event,
)


def _require_dev():
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres/Redis real (stack docker)")


class TestPricingRegistry:
    @pytest.mark.asyncio
    async def test_extract_provider_and_model(self) -> None:
        assert extract_provider("openai/baai/bge-m3") == "openai"
        assert extract_model("openai/baai/bge-m3") == "baai/bge-m3"
        assert extract_provider("gpt-4o-mini") == "default"
        assert extract_model("gpt-4o-mini") == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_price_fallback_default(self) -> None:
        _require_dev()
        price = await get_price("some/unknown-model")
        assert price.input_cost_per_1k > 0
        assert price.output_cost_per_1k > 0

    @pytest.mark.asyncio
    async def test_exact_model_price(self) -> None:
        _require_dev()
        price = await get_price("openai/gpt-4o-mini")
        assert price.input_cost_per_1k == 0.00015
        assert price.output_cost_per_1k == 0.00060

    @pytest.mark.asyncio
    async def test_update_price_without_deploy(self) -> None:
        _require_dev()
        model = f"test/model-{uuid4().hex[:6]}"
        await upsert_price(
            provider="test",
            model=model.split("/")[1],
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            embedding_cost_per_1k=0.0,
        )
        price = await get_price(model)
        assert price.input_cost_per_1k == 0.001
        assert price.output_cost_per_1k == 0.002

    def test_cost_math_exact(self) -> None:
        from src.platform.billing.pricing import PriceRecord

        price = PriceRecord(
            provider="t",
            model="m",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            embedding_cost_per_1k=0.0005,
        )
        cost = estimate_cost_from_price(
            price, prompt_tokens=1000, completion_tokens=500, embedding_tokens=2000
        )
        # 1000/1000*0.001 + 500/1000*0.002 + 2000/1000*0.0005
        assert cost == pytest.approx(0.001 + 0.001 + 0.001)

    @pytest.mark.asyncio
    async def test_estimate_cost_uses_registry(self) -> None:
        _require_dev()
        cost = await estimate_cost(
            "openai/gpt-4o-mini",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        assert cost == pytest.approx(0.00015 + 0.00060)


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_same_request_id_single_row(self) -> None:
        _require_dev()
        from src.platform.usage.usage_engine import ensure_usage_table

        await ensure_usage_table()
        request_id = uuid4()
        org = uuid4()
        event = UsageEvent(
            request_id=request_id,
            organization_id=org,
            total_tokens=100,
            estimated_cost=0.0001,
        )
        assert await record_event(event) is True
        assert await record_event(event) is False  # retry: no duplicado

        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM usage_events "
                        "WHERE request_id = :rid"
                    ),
                    {"rid": request_id},
                )
            ).scalar()
            assert count == 1
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_counters_dedupe_retry(self) -> None:
        _require_dev()
        counters = UsageCounters()
        org = uuid4()
        request_id = uuid4()
        created = datetime.now(timezone.utc)
        assert await counters.record(org, request_id, tokens=10, cost=0.01, created_at=created) is True
        assert await counters.record(org, request_id, tokens=10, cost=0.01, created_at=created) is False

        usage = await counters.window_usage(org, created_at=created)
        assert usage["daily"]["tokens"] == 10.0
        assert usage["daily"]["requests"] == 1.0
        assert usage["daily"]["cost"] == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_counter_windows_rollover(self) -> None:
        _require_dev()
        counters = UsageCounters()
        org = uuid4()
        today = datetime.now(timezone.utc)
        yesterday = today - timedelta(days=1)
        await counters.record(org, uuid4(), tokens=5, cost=0.005, created_at=yesterday)
        await counters.record(org, uuid4(), tokens=7, cost=0.007, created_at=today)

        usage_today = await counters.window_usage(org, created_at=today)
        assert usage_today["daily"]["tokens"] == 7.0
        # Misma ventana mensual: ambos cuentan.
        assert usage_today["monthly"]["tokens"] == 12.0


