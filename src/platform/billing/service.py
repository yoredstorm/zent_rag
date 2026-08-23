from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from src.core.config import get_settings
from src.core.domain.entities import (
    BillingContext,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from src.core.ports import ApiKeyRepository, BillingRepository
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# /metrics NO es pública: si RAG_METRICS_TOKEN está configurado exige token.
PUBLIC_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
    "/api/v1",
    "/api/v1/openapi.json",
}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_token(prefix: str = "zent_sk_live") -> str:
    return f"{prefix}_{secrets.token_hex(24)}"


class TokenValidationError(Exception):
    def __init__(self, message: str, status_code: int, error_code: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class BillingService:
    def __init__(self, repo: BillingRepository, api_keys: ApiKeyRepository):
        self._repo = repo
        self._api_keys = api_keys

    async def validate_token(self, token: str) -> BillingContext:
        from src.platform.auth.session import (
            SessionTokenError,
            decrypt_session,
            is_portal_session_token,
            session_is_active,
        )

        if is_portal_session_token(token):
            try:
                session = decrypt_session(token)
            except SessionTokenError as exc:
                raise TokenValidationError(str(exc), 401, "invalid_session") from exc
            if not await session_is_active(session.sid):
                raise TokenValidationError(
                    "Session has been revoked. Log in again.",
                    401,
                    "session_revoked",
                )
            return await self._context_for_organization(
                session.organization_id,
                token_id=None,
                scopes=["rag:read", "rag:write", "portal"],
                user_id=session.user_id,
                auth_type="portal_session",
            )

        token_hash = _hash_token(token)
        api_key = await self._api_keys.get_by_hash(token_hash)
        if api_key is None:
            raise TokenValidationError(
                "Invalid or expired API key", 401, "invalid_token"
            )

        return await self._context_for_organization(
            api_key.organization_id,
            token_id=api_key.id,
            scopes=api_key.scopes,
            auth_type="api_token",
        )

    async def _context_for_organization(
        self,
        organization_id: UUID,
        *,
        token_id: UUID | None,
        scopes: list[str],
        user_id: UUID | None = None,
        auth_type: str = "api_token",
    ) -> BillingContext:
        subscription = await self._repo.get_subscription_by_organization(organization_id)
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

        if subscription.status == SubscriptionStatus.SUSPENDED:
            raise TokenValidationError(
                "Subscription is suspended due to unpaid invoices.",
                402,
                "payment_required",
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
            organization_id=subscription.organization_id,
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
            await self._api_keys.touch_last_used(token_id)
        except Exception:
            pass

    async def list_api_keys(self, organization_id: UUID) -> list[dict]:
        keys = await self._api_keys.list_keys(organization_id)
        return [
            {
                "id": str(k.id),
                "name": k.name,
                "prefix": k.key_prefix,
                "scopes": k.scopes,
                "is_active": k.is_active,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "created_at": k.created_at.isoformat(),
            }
            for k in keys
        ]

    async def create_api_key(
        self,
        organization_id: UUID,
        name: str = "Default",
        scopes: list[str] | None = None,
        created_by: UUID | None = None,
    ) -> str:
        from src.platform.auth.scopes import (
            DEFAULT_API_KEY_SCOPES,
            canonicalize_scopes,
        )

        token = generate_api_token("zent_sk_live")
        resolved = canonicalize_scopes(scopes or DEFAULT_API_KEY_SCOPES)
        await self._api_keys.create_key(
            organization_id, token, name=name, scopes=resolved, created_by=created_by
        )
        return token

    async def revoke_api_key(self, organization_id: UUID, key_id: UUID) -> None:
        key = await self._api_keys.get_key(key_id)
        if key is None or key.organization_id != organization_id:
            raise ValueError("API key not found")
        await self._api_keys.deactivate_key(key_id)

    async def create_trial_subscription(
        self, organization_id: UUID, plan_id: UUID | None = None
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
            organization_id=organization_id,
            plan_id=plan_id,
            interval="monthly",
            trial_days=trial_days,
        )
        from src.platform.auth.scopes import DEFAULT_API_KEY_SCOPES

        token = generate_api_token("zent_sk_live")
        await self._api_keys.create_key(
            subscription.organization_id, token, "Default", DEFAULT_API_KEY_SCOPES
        )
        return subscription, token

    async def get_plans(self) -> list[Plan]:
        return await self._repo.get_plans(public_only=True)

    async def get_subscription(self, organization_id: UUID) -> Subscription | None:
        return await self._repo.get_subscription_by_organization(organization_id)

    async def get_quota_usage(self, subscription_id: UUID) -> tuple[int, int]:
        return await self._repo.get_quota_usage(subscription_id)

    async def cancel_subscription(self, subscription_id: UUID) -> None:
        await self._repo.update_subscription_status(subscription_id, "canceled")

    # -------------------------------------------------------------------------
    # Máquina de estados — ÚNICO mutador de estados de suscripción
    # -------------------------------------------------------------------------
    # El frontend NUNCA escribe estados: solo el webhook firmado (o una
    # operación interna del backend) transiciona la suscripción.
    _VALID_TRANSITIONS: dict[str, set[str]] = {
        "trialing": {"active", "past_due", "canceled", "expired", "suspended"},
        "active": {"past_due", "canceled", "expired", "paused", "suspended"},
        "past_due": {"active", "canceled", "expired", "suspended"},
        "suspended": {"active", "canceled"},
        "paused": {"active", "canceled", "expired"},
        "canceled": set(),
        "expired": {"active"},
    }

    async def transition_status(
        self, subscription_id: UUID, new_status: str
    ) -> bool:
        """Transiciona estado con validación. Retorna False si es ilegal.

        Único punto por el que un estado cambia. Los webhooks llaman acá.
        """
        subscription = await self._repo.get_subscription_by_id(subscription_id)
        if subscription is None:
            raise ValueError(f"Subscription {subscription_id} not found")
        current = str(subscription.status)
        allowed = self._VALID_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            logger.warning(
                "Illegal subscription transition rejected",
                subscription_id=str(subscription_id),
                current=current,
                attempted=new_status,
            )
            return False
        await self._repo.update_subscription_status(
            subscription_id, new_status
        )
        return True

    async def handle_payment_failed(
        self, subscription_id: UUID, consecutive_failures: int = 1
    ) -> None:
        """payment_failed: past_due, o suspended tras gracia/repeticiones."""
        settings = get_settings()
        if consecutive_failures >= 3:
            await self._repo.update_subscription_status(
                subscription_id, "suspended"
            )
            return
        await self._repo.update_subscription_status(
            subscription_id, "past_due"
        )
        _ = settings.BILLING_PAST_DUE_GRACE_DAYS

    async def handle_payment_succeeded(self, subscription_id: UUID) -> None:
        """payment_succeeded: reactiva hacia active."""
        await self._repo.update_subscription_status(subscription_id, "active")

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
