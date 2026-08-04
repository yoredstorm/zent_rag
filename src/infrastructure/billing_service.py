from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from src.domain.entities import (
    BillingContext,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from src.domain.ports import BillingRepository
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

PUBLIC_PATHS = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_token(prefix: str = "rag_live") -> str:
    return f"{prefix}_{secrets.token_hex(24)}"


class TokenValidationError(Exception):
    def __init__(self, message: str, status_code: int, error_code: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class BillingService:
    def __init__(self, repo: BillingRepository):
        self._repo = repo

    async def validate_token(self, token: str) -> BillingContext:
        from src.infrastructure.portal_session import (
            SessionTokenError,
            decrypt_session,
            is_portal_session_token,
        )

        if is_portal_session_token(token):
            try:
                session = decrypt_session(token)
            except SessionTokenError as exc:
                raise TokenValidationError(str(exc), 401, "invalid_session") from exc
            return await self._context_for_tenant(
                session.tenant_id,
                token_id=None,
                scopes=["rag:query", "rag:ingest", "portal"],
                user_id=session.user_id,
                auth_type="portal_session",
            )

        token_hash = _hash_token(token)
        api_token = await self._repo.get_token_by_hash(token_hash)
        if api_token is None:
            raise TokenValidationError(
                "Invalid or expired API token", 401, "invalid_token"
            )

        return await self._context_for_subscription(
            api_token.subscription_id,
            token_id=api_token.id,
            scopes=api_token.scopes,
            auth_type="api_token",
        )

    async def _context_for_tenant(
        self,
        tenant_id: UUID,
        *,
        token_id: UUID | None,
        scopes: list[str],
        user_id: UUID | None = None,
        auth_type: str = "api_token",
    ) -> BillingContext:
        subscription = await self._repo.get_subscription_by_tenant(tenant_id)
        if subscription is None:
            raise TokenValidationError(
                "Subscription not found", 401, "subscription_not_found"
            )
        return await self._build_context(
            subscription,
            token_id=token_id,
            scopes=scopes,
            user_id=user_id,
            auth_type=auth_type,
        )

    async def _context_for_subscription(
        self,
        subscription_id: UUID,
        *,
        token_id: UUID | None,
        scopes: list[str],
        user_id: UUID | None = None,
        auth_type: str = "api_token",
    ) -> BillingContext:
        subscription = await self._repo.get_subscription_by_id(subscription_id)
        if subscription is None:
            raise TokenValidationError(
                "Subscription not found", 401, "subscription_not_found"
            )
        return await self._build_context(
            subscription,
            token_id=token_id,
            scopes=scopes,
            user_id=user_id,
            auth_type=auth_type,
        )

    async def _build_context(
        self,
        subscription: Subscription,
        *,
        token_id: UUID | None,
        scopes: list[str],
        user_id: UUID | None = None,
        auth_type: str = "api_token",
    ) -> BillingContext:
        if subscription.status == SubscriptionStatus.EXPIRED:
            raise TokenValidationError(
                "Subscription has expired. Please renew your plan.",
                402,
                "subscription_expired",
            )

        if subscription.status == SubscriptionStatus.CANCELED:
            raise TokenValidationError(
                "Subscription was canceled.", 402, "subscription_canceled"
            )

        if subscription.status == SubscriptionStatus.PAUSED:
            raise TokenValidationError(
                "Subscription is paused.", 402, "subscription_paused"
            )

        if subscription.status == SubscriptionStatus.TRIALING:
            if subscription.is_trial_expired:
                await self._repo.update_subscription_status(
                    subscription.id, "expired"
                )
                raise TokenValidationError(
                    "Your free trial has expired. Upgrade to continue.",
                    402,
                    "trial_expired",
                )

        if subscription.is_period_expired and subscription.status == SubscriptionStatus.ACTIVE:
            if not subscription.auto_renew:
                await self._repo.update_subscription_status(
                    subscription.id, "expired"
                )
                raise TokenValidationError(
                    "Subscription period ended and auto-renew is disabled.",
                    402,
                    "subscription_expired",
                )

        if subscription.status == SubscriptionStatus.PAST_DUE:
            raise TokenValidationError(
                "Payment past due. Please update your billing information.",
                402,
                "payment_required",
            )

        plan = await self._repo.get_plan_by_id(subscription.plan_id)
        if plan is None:
            raise TokenValidationError(
                "Plan not found", 500, "plan_not_found"
            )

        return BillingContext(
            tenant_id=subscription.tenant_id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            plan_name=plan.name,
            token_id=token_id,
            scopes=scopes,
            requests_limit=plan.requests_per_month,
            status=subscription.status,
            user_id=user_id,
            auth_type=auth_type,
        )

    async def check_quota(self, ctx: BillingContext) -> bool:
        within = await self._repo.check_and_increment_quota(
            ctx.subscription_id, ctx.requests_limit
        )
        return within

    async def touch_token(self, token_id: UUID | None) -> None:
        if token_id is None:
            return
        try:
            await self._repo.touch_token_last_used(token_id)
        except Exception:
            pass

    async def get_token_for_tenant(self, tenant_id: UUID) -> str | None:
        subscription = await self._repo.get_subscription_by_tenant(tenant_id)
        if subscription is None:
            return None
        existing = await self._repo.get_token_by_subscription(subscription.id)
        if existing is not None:
            return f"{existing.token_prefix}[hidden]"
        return None

    async def get_token_info(self, subscription_id: UUID) -> dict | None:
        existing = await self._repo.get_token_by_subscription(subscription_id)
        if existing is None:
            return None
        return {
            "id": str(existing.id),
            "prefix": existing.token_prefix,
            "name": existing.name,
            "scopes": existing.scopes,
            "last_used_at": existing.last_used_at.isoformat() if existing.last_used_at else None,
            "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
            "created_at": existing.created_at.isoformat(),
        }

    async def rotate_token(self, subscription_id: UUID) -> str:
        existing = await self._repo.get_token_by_subscription(subscription_id)
        if existing:
            await self._repo.deactivate_token(existing.id)
        token = generate_api_token("rag_live")
        await self._repo.create_token(subscription_id, token, "API Token")
        return token

    async def create_trial_subscription(
        self, tenant_id: UUID, plan_id: UUID | None = None
    ) -> tuple[Subscription, str]:
        if plan_id is None:
            plans = await self._repo.get_plans(public_only=False)
            trial_plan = next((p for p in plans if p.is_trial), None)
            if trial_plan is None:
                raise ValueError("No trial plan configured")
            plan_id = trial_plan.id
            trial_days = trial_plan.trial_days
        else:
            plan = await self._repo.get_plan_by_id(plan_id)
            if plan is None:
                raise ValueError(f"Plan {plan_id} not found")
            trial_days = plan.trial_days

        subscription = await self._repo.create_subscription(
            tenant_id=tenant_id,
            plan_id=plan_id,
            interval="monthly",
            trial_days=trial_days,
        )
        token = generate_api_token("rag_live")
        await self._repo.create_token(
            subscription.id, token, "Default", ["rag:query", "rag:ingest"]
        )
        return subscription, token

    async def get_plans(self) -> list[Plan]:
        return await self._repo.get_plans(public_only=True)

    async def get_subscription(self, tenant_id: UUID) -> Subscription | None:
        return await self._repo.get_subscription_by_tenant(tenant_id)

    async def get_quota_usage(self, subscription_id: UUID) -> tuple[int, int]:
        return await self._repo.get_quota_usage(subscription_id)

    async def cancel_subscription(self, subscription_id: UUID) -> None:
        await self._repo.update_subscription_status(subscription_id, "canceled")

    async def list_all_subscriptions(self) -> list[dict]:
        return await self._repo.list_subscriptions()

    async def upgrade_plan(
        self, subscription_id: UUID, plan_name: str, interval: str = "monthly"
    ) -> dict:
        plans = await self._repo.get_plans(public_only=False)
        target = next((p for p in plans if p.name == plan_name), None)
        if target is None:
            raise ValueError(f"Plan '{plan_name}' not found")

        updated = await self._repo.change_plan(subscription_id, target.id)
        return {
            "subscription_id": subscription_id,
            "plan_name": target.name,
            "billing_interval": interval,
        }

    async def delete_subscription(self, subscription_id: UUID) -> None:
        await self._repo.delete_subscription(subscription_id)
