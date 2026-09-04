# =============================================================================
# Billing Platform — estados, provider, overage, límites
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import Plan, Subscription, SubscriptionStatus
from src.platform.billing.service import BillingService


def _require_dev():
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres real (stack docker)")


class _FakeBillingRepo:
    def __init__(self, subscription: Subscription) -> None:
        self.subscription = subscription
        self.status_updates: list[str] = []
        self.plan = Plan(
            id=subscription.plan_id,
            name="starter",
            display_name="Starter",
            price_monthly_cents=4900,
            price_annual_cents=49000,
            requests_per_month=5000,
        )

    async def get_subscription_by_id(self, subscription_id: UUID):
        return self.subscription if subscription_id == self.subscription.id else None

    async def update_subscription_status(self, subscription_id: UUID, status: str) -> None:
        self.status_updates.append(status)

    async def get_plan_by_id(self, plan_id: UUID):
        return self.plan

    async def get_subscription_by_organization(self, organization_id: UUID):
        return self.subscription

    async def get_plans(self, public_only: bool = True):
        return [self.plan]


class _FakeApiKeys:
    async def create_key(self, *args, **kwargs) -> None:
        pass


class _FakeService(BillingService):
    def __init__(self, repo) -> None:
        super().__init__(repo, _FakeApiKeys())  # type: ignore[arg-type]


def _subscription(status: SubscriptionStatus) -> Subscription:
    return Subscription(
        id=uuid4(),
        organization_id=uuid4(),
        plan_id=uuid4(),
        status=status,
        billing_interval="monthly",
    )


class TestStateMachine:
    @pytest.mark.asyncio
    async def test_valid_transitions(self) -> None:
        cases = [
            (SubscriptionStatus.TRIALING, "active", True),
            (SubscriptionStatus.TRIALING, "past_due", True),
            (SubscriptionStatus.ACTIVE, "past_due", True),
            (SubscriptionStatus.ACTIVE, "suspended", True),
            (SubscriptionStatus.PAST_DUE, "suspended", True),
            (SubscriptionStatus.PAST_DUE, "active", True),
            (SubscriptionStatus.SUSPENDED, "active", True),
            (SubscriptionStatus.ACTIVE, "canceled", True),
            (SubscriptionStatus.EXPIRED, "active", True),
        ]
        for current, target, expected in cases:
            repo = _FakeBillingRepo(_subscription(current))
            service = _FakeService(repo)
            result = await service.transition_status(
                repo.subscription.id, target
            )
            assert result is expected, f"{current.value} -> {target}"

    @pytest.mark.asyncio
    async def test_illegal_transition_rejected(self) -> None:
        repo = _FakeBillingRepo(_subscription(SubscriptionStatus.CANCELED))
        service = _FakeService(repo)
        assert await service.transition_status(repo.subscription.id, "active") is False
        assert repo.status_updates == []

    @pytest.mark.asyncio
    async def test_payment_failed_escalates_to_suspended(self) -> None:
        repo = _FakeBillingRepo(_subscription(SubscriptionStatus.ACTIVE))
        service = _FakeService(repo)
        await service.handle_payment_failed(repo.subscription.id, 1)
        assert repo.status_updates[-1] == "past_due"
        await service.handle_payment_failed(repo.subscription.id, 3)
        assert repo.status_updates[-1] == "suspended"

    @pytest.mark.asyncio
    async def test_payment_succeeded_reactivates(self) -> None:
        repo = _FakeBillingRepo(_subscription(SubscriptionStatus.SUSPENDED))
        service = _FakeService(repo)
        await service.handle_payment_succeeded(repo.subscription.id)
        assert repo.status_updates[-1] == "active"


class TestPlanLimits:
    @pytest.mark.asyncio
    async def test_unknown_resource_rejected(self) -> None:
        from src.platform.billing.plan_limits import check_resource_limit

        with pytest.raises(ValueError, match="Unknown resource"):
            await check_resource_limit(uuid4(), "nope")

    @pytest.mark.asyncio
    async def test_limit_enforced_real_db(self) -> None:
        _require_dev()
        from sqlalchemy import text

        from src.infrastructure.postgres.relational_db import (
            PostgresApiKeyRepository,
            PostgresBillingRepository,
        )
        from src.infrastructure.postgres.session import get_async_session
        from src.platform.billing.plan_limits import (
            PlanLimitError,
            check_resource_limit,
        )
        from src.platform.billing.service import BillingService

        org = uuid4()
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name, status) "
                    "VALUES (:id, 'Limit Org', 'active') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": org},
            )
            await session.commit()
        finally:
            await session.close()

        billing = BillingService(
            PostgresBillingRepository(), PostgresApiKeyRepository()
        )
        await billing.create_trial_subscription(org)

        from src.platform.billing.entitlements import upsert_plan_entitlements

        trial_plan = UUID("10000000-0000-0000-0000-000000000001")
        await upsert_plan_entitlements(
            trial_plan,
            [{"key": "max_agents", "value_type": "int", "value_int": 0}],
        )

        try:
            with pytest.raises(PlanLimitError):
                await check_resource_limit(org, "agents")
        finally:
            await upsert_plan_entitlements(
                trial_plan,
                [{"key": "max_agents", "value_type": "int", "value_int": None}],
            )

    @pytest.mark.asyncio
    async def test_no_subscription_no_limit(self) -> None:
        _require_dev()
        from src.platform.billing.plan_limits import check_resource_limit

        # Org sin suscripción: permitido (fail-open).
        await check_resource_limit(uuid4(), "agents")
