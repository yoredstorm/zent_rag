# =============================================================================
# Billing Webhooks — firma, idempotencia, mapeo de eventos
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.entities import Plan, Subscription, SubscriptionStatus
from src.infrastructure.billing.manual_provider import sign_manual_webhook
from src.platform.billing.service import BillingService
from src.platform.billing.webhooks import (
    WebhookSignatureError,
    process_webhook,
)


def _require_dev():
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres real (stack docker)")


class _FakeBillingRepo:
    def __init__(self) -> None:
        self.status_updates: list[str] = []
        self.subscription = Subscription(
            id=uuid4(),
            organization_id=uuid4(),
            plan_id=uuid4(),
            status=SubscriptionStatus.TRIALING,
            billing_interval="monthly",
        )
        self.plan = Plan(
            id=self.subscription.plan_id,
            name="trial",
            display_name="Trial",
            price_monthly_cents=0,
            price_annual_cents=0,
            requests_per_month=500,
            is_trial=True,
        )

    async def get_subscription_by_id(self, subscription_id):
        return self.subscription if subscription_id == self.subscription.id else None

    async def update_subscription_status(self, subscription_id, status: str) -> None:
        self.status_updates.append(status)

    async def get_plan_by_id(self, plan_id):
        return self.plan

    async def get_subscription_by_organization(self, organization_id):
        return self.subscription

    async def get_plans(self, public_only: bool = True):
        return [self.plan]


class _FakeApiKeys:
    async def create_key(self, *args, **kwargs) -> None:
        pass


def _service(repo) -> BillingService:
    return BillingService(repo, _FakeApiKeys())  # type: ignore[arg-type]


def _payload(event_type: str, repo, **extra) -> dict:
    return {
        "id": f"evt_{uuid4().hex[:12]}",
        "type": event_type,
        "organization_id": str(repo.subscription.organization_id),
        "subscription_id": str(repo.subscription.id),
        "data": dict(extra),
    }


class TestWebhookSignature:
    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self) -> None:
        _require_dev()
        repo = _FakeBillingRepo()
        with pytest.raises(WebhookSignatureError):
            await process_webhook(
                "manual",
                b'{"id": "x", "type": "subscription_created"}',
                {"x-zent-signature": "t=0,v1=deadbeef"},
                _service(repo),
            )

    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self) -> None:
        _require_dev()
        repo = _FakeBillingRepo()
        with pytest.raises(WebhookSignatureError):
            await process_webhook(
                "manual",
                b'{"id": "x", "type": "subscription_created"}',
                {},
                _service(repo),
            )

    @pytest.mark.asyncio
    async def test_unknown_provider_rejected(self) -> None:
        _require_dev()
        repo = _FakeBillingRepo()
        from src.platform.billing.webhooks import UnknownProviderError

        with pytest.raises(UnknownProviderError):
            await process_webhook(
                "stripe", b"{}", {}, _service(repo)
            )


class TestWebhookProcessing:
    @pytest.mark.asyncio
    async def test_subscription_canceled_transitions(self) -> None:
        _require_dev()
        repo = _FakeBillingRepo()
        payload = _payload("subscription_canceled", repo)
        signed = sign_manual_webhook(
            payload,
            pytest.importorskip("src.core.config").get_settings()
            .BILLING_WEBHOOK_SECRET.get_secret_value(),
        )
        result = await process_webhook(
            "manual",
            signed["body"].encode("utf-8"),
            {"x-zent-signature": signed["X-Zent-Signature"]},
            _service(repo),
        )
        assert result["status"] == "processed"
        assert repo.status_updates[-1] == "canceled"

    @pytest.mark.asyncio
    async def test_replay_is_idempotent(self) -> None:
        _require_dev()
        from src.core.config import get_settings

        repo = _FakeBillingRepo()
        payload = _payload("subscription_canceled", repo)
        signed = sign_manual_webhook(
            payload, get_settings().BILLING_WEBHOOK_SECRET.get_secret_value()
        )
        service = _service(repo)
        first = await process_webhook(
            "manual",
            signed["body"].encode("utf-8"),
            {"x-zent-signature": signed["X-Zent-Signature"]},
            service,
        )
        assert first["status"] == "processed"
        updates_after_first = len(repo.status_updates)

        second = await process_webhook(
            "manual",
            signed["body"].encode("utf-8"),
            {"x-zent-signature": signed["X-Zent-Signature"]},
            service,
        )
        assert second["status"] == "duplicate"
        assert len(repo.status_updates) == updates_after_first  # sin doble transición

    @pytest.mark.asyncio
    async def test_payment_succeeded_reactivates_and_records_payment(self) -> None:
        _require_dev()
        repo = _FakeBillingRepo()
        payload = _payload(
            "payment_succeeded", repo,
            payment_id="pay_1",
            amount_cents=4900,
            currency="USD",
        )
        from src.core.config import get_settings

        signed = sign_manual_webhook(
            payload, get_settings().BILLING_WEBHOOK_SECRET.get_secret_value()
        )
        result = await process_webhook(
            "manual",
            signed["body"].encode("utf-8"),
            {"x-zent-signature": signed["X-Zent-Signature"]},
            _service(repo),
        )
        assert result["status"] == "processed"
        assert repo.status_updates[-1] == "active"

        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM payments "
                        "WHERE provider = 'manual' AND provider_payment_id = 'pay_1'"
                    )
                )
            ).scalar()
            assert row == 1
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_payment_failed_suspends_after_failures(self) -> None:
        _require_dev()
        repo = _FakeBillingRepo()
        payload = _payload(
            "payment_failed", repo,
            payment_id="pay_fail_1",
            amount_cents=0,
            consecutive_failures=3,
        )
        from src.core.config import get_settings

        signed = sign_manual_webhook(
            payload, get_settings().BILLING_WEBHOOK_SECRET.get_secret_value()
        )
        result = await process_webhook(
            "manual",
            signed["body"].encode("utf-8"),
            {"x-zent-signature": signed["X-Zent-Signature"]},
            _service(repo),
        )
        assert result["status"] == "processed"
        assert repo.status_updates[-1] == "suspended"

    @pytest.mark.asyncio
    async def test_unknown_event_recorded_without_crash(self) -> None:
        _require_dev()
        repo = _FakeBillingRepo()
        payload = _payload("weird_event", repo)
        from src.core.config import get_settings

        signed = sign_manual_webhook(
            payload, get_settings().BILLING_WEBHOOK_SECRET.get_secret_value()
        )
        result = await process_webhook(
            "manual",
            signed["body"].encode("utf-8"),
            {"x-zent-signature": signed["X-Zent-Signature"]},
            _service(repo),
        )
        assert result["status"] == "processed"
        assert repo.status_updates == []  # sin transición


class TestWebhookEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_public_with_valid_signature(
        self, async_client
    ) -> None:
        from src.core.config import get_settings

        # Evento sin side-effects en DB (unhandled): valida ruta pública,
        # firma y persistencia del evento.
        payload = {
            "id": f"evt_{uuid4().hex[:12]}",
            "type": "ping_event",
            "data": {},
        }
        signed = sign_manual_webhook(
            payload, get_settings().BILLING_WEBHOOK_SECRET.get_secret_value()
        )
        resp = await async_client.post(
            "/api/v1/billing/webhooks/manual",
            content=signed["body"],
            headers={
                "Content-Type": "application/json",
                "X-Zent-Signature": signed["X-Zent-Signature"],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processed"

    @pytest.mark.asyncio
    async def test_endpoint_rejects_bad_signature(self, async_client) -> None:
        resp = await async_client.post(
            "/api/v1/billing/webhooks/manual",
            content='{"id": "x", "type": "y"}',
            headers={
                "Content-Type": "application/json",
                "X-Zent-Signature": "t=0,v1=invalid",
            },
        )
        assert resp.status_code == 400, resp.text
