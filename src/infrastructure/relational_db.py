# =============================================================================
# PostgreSQL Adapter — Implementación de TenantRepository y UserRepository
# =============================================================================
# Usa asyncpg vía SQLAlchemy 2.0 asíncrono. La conexión se gestiona con
# un pool configurable. Prepared Statements mitigan SQL Injection.
# =============================================================================
from __future__ import annotations

import time
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.domain.entities import (
    ApiToken,
    BillingInterval,
    Plan,
    Subscription,
    SubscriptionStatus,
    Tenant,
    TenantStatus,
    User,
)
from src.domain.ports import BillingRepository, TenantRepository, UserRepository
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Engine y Session Factory — Inicialización lazy, per-event-loop
# -----------------------------------------------------------------------------
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine_loop_id: int | None = None


async def get_async_session() -> AsyncSession:
    """Retorna una sesión asíncrona de SQLAlchemy desde el pool.

    Re-crea el engine si el event loop cambia (útil en tests con ASGITransport).
    """
    global _engine, _session_factory, _engine_loop_id

    import asyncio as _asyncio
    current_loop_id = id(_asyncio.get_running_loop())
    if _engine is None or _engine_loop_id != current_loop_id:
        if _engine is not None:
            await _engine.dispose()
        settings = get_settings()
        _engine = create_async_engine(
            settings.POSTGRES_DSN,
            pool_size=settings.POSTGRES_MIN_CONNECTIONS,
            max_overflow=settings.POSTGRES_MAX_CONNECTIONS - settings.POSTGRES_MIN_CONNECTIONS,
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _engine_loop_id = current_loop_id
    assert _session_factory is not None
    return _session_factory()


async def close_db_connections() -> None:
    """Cierra el pool de conexiones (útil en graceful shutdown)."""
    global _engine, _engine_loop_id
    if _engine:
        await _engine.dispose()
        _engine = None
        _engine_loop_id = None


# -----------------------------------------------------------------------------
# Implementaciones
# -----------------------------------------------------------------------------
class PostgresTenantRepository(TenantRepository):
    """Repositorio de Tenants sobre PostgreSQL con asyncpg."""

    async def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, api_key_hash, status, rate_limit_per_minute, "
                    "max_tokens_per_request, llm_model_override, embedding_model_override, "
                    "config_json, company_name, ruc, phone, email, country, "
                    "created_at FROM tenants WHERE id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return Tenant(
                id=row.id,
                name=row.name,
                api_key_hash=row.api_key_hash,
                status=TenantStatus(row.status),
                rate_limit_per_minute=row.rate_limit_per_minute,
                max_tokens_per_request=row.max_tokens_per_request,
                llm_model_override=row.llm_model_override,
                embedding_model_override=row.embedding_model_override,
                config_json=row.config_json if isinstance(row.config_json, dict) else {},
                company_name=row.company_name,
                ruc=row.ruc,
                phone=row.phone,
                email=row.email,
                country=row.country,
                created_at=row.created_at,
            )
        finally:
            await session.close()

    async def get_by_api_key_hash(self, api_key_hash: str) -> Tenant | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, api_key_hash, status, rate_limit_per_minute, "
                    "max_tokens_per_request, llm_model_override, embedding_model_override, "
                    "config_json, company_name, ruc, phone, email, country, "
                    "created_at FROM tenants WHERE api_key_hash = :api_key_hash AND status = 'active'"
                ),
                {"api_key_hash": api_key_hash},
            )
            row = result.fetchone()
            if row is None:
                return None
            return Tenant(
                id=row.id,
                name=row.name,
                api_key_hash=row.api_key_hash,
                status=TenantStatus(row.status),
                rate_limit_per_minute=row.rate_limit_per_minute,
                max_tokens_per_request=row.max_tokens_per_request,
                llm_model_override=row.llm_model_override,
                embedding_model_override=row.embedding_model_override,
                config_json=row.config_json if isinstance(row.config_json, dict) else {},
                company_name=row.company_name,
                ruc=row.ruc,
                phone=row.phone,
                email=row.email,
                country=row.country,
                created_at=row.created_at,
            )
        finally:
            await session.close()

    async def check_rate_limit(self, tenant_id: UUID) -> bool:
        """Verifica si el tenant ha excedido su rate limit en la ventana actual."""
        session = await get_async_session()
        try:
            minute_window = int(time.time()) // 60
            result = await session.execute(
                text(
                    "INSERT INTO rate_limit_counters (tenant_id, minute_window, counter) "
                    "VALUES (:tenant_id, :window, 1) "
                    "ON CONFLICT (tenant_id, minute_window) "
                    "DO UPDATE SET counter = rate_limit_counters.counter + 1 "
                    "RETURNING counter"
                ),
                {"tenant_id": tenant_id, "window": minute_window},
            )
            counter = result.scalar_one()
            tenant = await self.get_by_id(tenant_id)
            if tenant is None:
                return False
            return counter <= tenant.rate_limit_per_minute
        finally:
            await session.close()

    async def log_usage(
        self, tenant_id: UUID, user_id: UUID, tokens: int, latency_ms: float
    ) -> None:
        """Registra el uso de tokens para facturación por tenant."""
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO usage_logs (tenant_id, user_id, total_tokens, latency_ms) "
                    "VALUES (:tenant_id, :user_id, :tokens, :latency_ms)"
                ),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "tokens": tokens,
                    "latency_ms": latency_ms,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning("Failed to log usage", tenant_id=str(tenant_id))
        finally:
            await session.close()

    async def create_tenant(
        self, tenant_id: UUID, name: str, api_key_hash: str
    ) -> Tenant:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO tenants (id, name, api_key_hash, status, rate_limit_per_minute) "
                    "VALUES (:id, :name, :hash, 'active', 999999) "
                    "ON CONFLICT (id) DO UPDATE SET name = :name2, api_key_hash = :hash2 "
                    "RETURNING id, name, api_key_hash, status, rate_limit_per_minute, "
                    "max_tokens_per_request, llm_model_override, embedding_model_override, "
                    "config_json, created_at"
                ),
                {
                    "id": tenant_id, "name": name, "hash": api_key_hash,
                    "name2": name, "hash2": api_key_hash,
                },
            )
            row = result.fetchone()
            await session.commit()
            return Tenant(
                id=row.id, name=row.name, api_key_hash=row.api_key_hash,
                status=TenantStatus(row.status),
                rate_limit_per_minute=row.rate_limit_per_minute,
                max_tokens_per_request=row.max_tokens_per_request,
                llm_model_override=row.llm_model_override,
                embedding_model_override=row.embedding_model_override,
                config_json=row.config_json if isinstance(row.config_json, dict) else {},
                created_at=row.created_at,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_tenant(self, tenant_id: UUID, **fields) -> Tenant:
        allowed = {"company_name", "ruc", "phone", "email", "country", "name"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return await self.get_by_id(tenant_id)  # type: ignore[return-value]
        session = await get_async_session()
        try:
            set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
            params = {"tid": tenant_id, **updates}
            result = await session.execute(
                text(
                    f"UPDATE tenants SET {set_clauses}, updated_at = NOW() "
                    f"WHERE id = :tid "
                    f"RETURNING id, name, api_key_hash, status, rate_limit_per_minute, "
                    f"max_tokens_per_request, llm_model_override, embedding_model_override, "
                    f"config_json, company_name, ruc, phone, email, country, created_at"
                ),
                params,
            )
            row = result.fetchone()
            await session.commit()
            if row is None:
                raise ValueError(f"Tenant {tenant_id} not found")
            return Tenant(
                id=row.id, name=row.name, api_key_hash=row.api_key_hash,
                status=TenantStatus(row.status),
                rate_limit_per_minute=row.rate_limit_per_minute,
                max_tokens_per_request=row.max_tokens_per_request,
                llm_model_override=row.llm_model_override,
                embedding_model_override=row.embedding_model_override,
                config_json=row.config_json if isinstance(row.config_json, dict) else {},
                company_name=row.company_name, ruc=row.ruc,
                phone=row.phone, email=row.email, country=row.country,
                created_at=row.created_at,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_config(self, tenant_id: UUID, config: dict) -> Tenant:
        session = await get_async_session()
        import json as _json
        try:
            result = await session.execute(
                text(
                    "UPDATE tenants SET config_json = CAST(:config AS jsonb), updated_at = NOW() "
                    "WHERE id = :tid "
                    "RETURNING id, name, api_key_hash, status, rate_limit_per_minute, "
                    "max_tokens_per_request, llm_model_override, embedding_model_override, "
                    "config_json, company_name, ruc, phone, email, country, created_at"
                ),
                {"tid": tenant_id, "config": _json.dumps(config)},
            )
            row = result.fetchone()
            await session.commit()
            if row is None:
                raise ValueError(f"Tenant {tenant_id} not found")
            return Tenant(
                id=row.id, name=row.name, api_key_hash=row.api_key_hash,
                status=TenantStatus(row.status),
                rate_limit_per_minute=row.rate_limit_per_minute,
                max_tokens_per_request=row.max_tokens_per_request,
                llm_model_override=row.llm_model_override,
                embedding_model_override=row.embedding_model_override,
                config_json=row.config_json if isinstance(row.config_json, dict) else {},
                company_name=row.company_name, ruc=row.ruc,
                phone=row.phone, email=row.email, country=row.country,
                created_at=row.created_at,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_tenants(self) -> list[Tenant]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, api_key_hash, status, rate_limit_per_minute, "
                    "max_tokens_per_request, llm_model_override, embedding_model_override, "
                    "config_json, company_name, ruc, phone, email, country, "
                    "created_at FROM tenants ORDER BY created_at DESC"
                )
            )
            return [
                Tenant(
                    id=row.id, name=row.name, api_key_hash=row.api_key_hash,
                    status=TenantStatus(row.status),
                    rate_limit_per_minute=row.rate_limit_per_minute,
                    max_tokens_per_request=row.max_tokens_per_request,
                    llm_model_override=row.llm_model_override,
                    embedding_model_override=row.embedding_model_override,
                    config_json=row.config_json if isinstance(row.config_json, dict) else {},
                    company_name=row.company_name, ruc=row.ruc,
                    phone=row.phone, email=row.email, country=row.country,
                    created_at=row.created_at,
                )
                for row in result.fetchall()
            ]
        finally:
            await session.close()


class PostgresUserRepository(UserRepository):
    """Repositorio de Usuarios sobre PostgreSQL."""

    _USER_COLS = (
        "id, tenant_id, external_id, email_hash, role, email, password_hash, created_at"
    )

    @staticmethod
    def _row_to_user(row) -> User:
        return User(
            id=row.id,
            tenant_id=row.tenant_id,
            external_id=row.external_id,
            email_hash=row.email_hash,
            role=row.role,
            email=getattr(row, "email", None),
            password_hash=getattr(row, "password_hash", None),
            created_at=row.created_at,
        )

    async def get_by_id(self, user_id: UUID, tenant_id: UUID) -> User | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._USER_COLS} "
                    "FROM users WHERE id = :user_id AND tenant_id = :tenant_id"
                ),
                {"user_id": user_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_user(row)
        finally:
            await session.close()

    async def get_by_external_id(
        self, tenant_id: UUID, external_id: str
    ) -> User | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._USER_COLS} "
                    "FROM users WHERE tenant_id = :tid AND external_id = :ext_id"
                ),
                {"tid": tenant_id, "ext_id": external_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_user(row)
        finally:
            await session.close()

    async def get_any_user(self, tenant_id: UUID) -> User | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._USER_COLS} "
                    "FROM users WHERE tenant_id = :tid LIMIT 1"
                ),
                {"tid": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_user(row)
        finally:
            await session.close()

    async def get_by_email(self, email: str) -> User | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._USER_COLS} "
                    "FROM users WHERE lower(email) = lower(:email) LIMIT 1"
                ),
                {"email": email.strip()},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_user(row)
        finally:
            await session.close()

    async def set_password(self, user_id: UUID, password_hash: str) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE users SET password_hash = :ph WHERE id = :uid"
                ),
                {"ph": password_hash, "uid": user_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def create_default_user(
        self,
        tenant_id: UUID,
        email_hash: str,
        *,
        email: str | None = None,
        password_hash: str | None = None,
    ) -> User:
        session = await get_async_session()
        user_id = uuid4()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO users "
                    "(id, tenant_id, external_id, email_hash, role, email, password_hash) "
                    "VALUES (:id, :tid, :ext_id, :email_hash, 'admin', :email, :password_hash) "
                    "ON CONFLICT (tenant_id, external_id) DO NOTHING "
                    f"RETURNING {self._USER_COLS}"
                ),
                {
                    "id": user_id,
                    "tid": tenant_id,
                    "ext_id": "default-admin",
                    "email_hash": email_hash,
                    "email": email.lower().strip() if email else None,
                    "password_hash": password_hash,
                },
            )
            row = result.fetchone()
            await session.commit()
            if row is None:
                result2 = await session.execute(
                    text(
                        f"SELECT {self._USER_COLS} "
                        "FROM users WHERE tenant_id = :tid AND external_id = 'default-admin'"
                    ),
                    {"tid": tenant_id},
                )
                row = result2.fetchone()
                if email and password_hash and row is not None:
                    await session.execute(
                        text(
                            "UPDATE users SET email = COALESCE(email, :email), "
                            "password_hash = COALESCE(password_hash, :ph) "
                            "WHERE id = :uid"
                        ),
                        {
                            "email": email.lower().strip(),
                            "ph": password_hash,
                            "uid": row.id,
                        },
                    )
                    await session.commit()
                    result3 = await session.execute(
                        text(f"SELECT {self._USER_COLS} FROM users WHERE id = :uid"),
                        {"uid": row.id},
                    )
                    row = result3.fetchone()
            return self._row_to_user(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# =============================================================================
# PostgresBillingRepository — Planes, Suscripciones, Tokens y Cuotas
# =============================================================================
import json
from datetime import datetime, timezone
from uuid import uuid4 as _uuid4


class PostgresBillingRepository(BillingRepository):

    async def get_plan_by_id(self, plan_id: UUID) -> Plan | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, display_name, description, price_monthly_cents, "
                    "price_annual_cents, requests_per_month, max_tenants, "
                    "max_users_per_tenant, features, is_public, is_trial, "
                    "trial_days, sort_order "
                    "FROM plans WHERE id = :plan_id"
                ),
                {"plan_id": plan_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return Plan(
                id=row.id, name=row.name, display_name=row.display_name,
                description=row.description,
                price_monthly_cents=row.price_monthly_cents,
                price_annual_cents=row.price_annual_cents,
                requests_per_month=row.requests_per_month,
                max_tenants=row.max_tenants,
                max_users_per_tenant=row.max_users_per_tenant,
                features=list(row.features) if row.features else [],
                is_public=row.is_public, is_trial=row.is_trial,
                trial_days=row.trial_days, sort_order=row.sort_order,
            )
        finally:
            await session.close()

    async def get_plans(self, public_only: bool = True) -> list[Plan]:
        session = await get_async_session()
        try:
            query = (
                "SELECT id, name, display_name, description, price_monthly_cents, "
                "price_annual_cents, requests_per_month, max_tenants, "
                "max_users_per_tenant, features, is_public, is_trial, "
                "trial_days, sort_order FROM plans "
            )
            if public_only:
                query += "WHERE is_public = true "
            query += "ORDER BY sort_order"
            result = await session.execute(text(query))
            return [
                Plan(
                    id=row.id, name=row.name, display_name=row.display_name,
                    description=row.description,
                    price_monthly_cents=row.price_monthly_cents,
                    price_annual_cents=row.price_annual_cents,
                    requests_per_month=row.requests_per_month,
                    max_tenants=row.max_tenants,
                    max_users_per_tenant=row.max_users_per_tenant,
                    features=list(row.features) if row.features else [],
                    is_public=row.is_public, is_trial=row.is_trial,
                    trial_days=row.trial_days, sort_order=row.sort_order,
                )
                for row in result.fetchall()
            ]
        finally:
            await session.close()

    async def get_subscription_by_tenant(self, tenant_id: UUID) -> Subscription | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, tenant_id, plan_id, status, billing_interval, "
                    "trial_start, trial_end, current_period_start, current_period_end, "
                    "canceled_at, auto_renew, created_at "
                    "FROM subscriptions WHERE tenant_id = :tid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return Subscription(
                id=row.id, tenant_id=row.tenant_id, plan_id=row.plan_id,
                status=SubscriptionStatus(row.status),
                billing_interval=BillingInterval(row.billing_interval),
                trial_start=row.trial_start, trial_end=row.trial_end,
                current_period_start=row.current_period_start,
                current_period_end=row.current_period_end,
                canceled_at=row.canceled_at, auto_renew=row.auto_renew,
                created_at=row.created_at,
            )
        finally:
            await session.close()

    async def get_subscription_by_id(self, subscription_id: UUID) -> Subscription | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, tenant_id, plan_id, status, billing_interval, "
                    "trial_start, trial_end, current_period_start, current_period_end, "
                    "canceled_at, auto_renew, created_at "
                    "FROM subscriptions WHERE id = :sid"
                ),
                {"sid": subscription_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return Subscription(
                id=row.id, tenant_id=row.tenant_id, plan_id=row.plan_id,
                status=SubscriptionStatus(row.status),
                billing_interval=BillingInterval(row.billing_interval),
                trial_start=row.trial_start, trial_end=row.trial_end,
                current_period_start=row.current_period_start,
                current_period_end=row.current_period_end,
                canceled_at=row.canceled_at, auto_renew=row.auto_renew,
                created_at=row.created_at,
            )
        finally:
            await session.close()

    async def create_subscription(
        self, tenant_id: UUID, plan_id: UUID,
        interval: str = "monthly", trial_days: int = 0,
    ) -> Subscription:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        sub_id = _uuid4()
        session = await get_async_session()
        try:
            if trial_days > 0:
                trial_end = now + timedelta(days=trial_days)
                result = await session.execute(
                    text(
                        "INSERT INTO subscriptions (id, tenant_id, plan_id, status, "
                        "billing_interval, trial_start, trial_end, "
                        "current_period_start, current_period_end) "
                        "VALUES (:id, :tid, :pid, 'trialing', :interval, "
                        ":tstart, :tend, :tstart, :tend) "
                        "RETURNING id, tenant_id, plan_id, status, billing_interval, "
                        "trial_start, trial_end, current_period_start, current_period_end, "
                        "canceled_at, auto_renew, created_at"
                    ),
                    {"id": sub_id, "tid": tenant_id, "pid": plan_id,
                     "interval": interval, "tstart": now, "tend": trial_end},
                )
            else:
                period_end = now + timedelta(days=30 if interval == "monthly" else 365)
                result = await session.execute(
                    text(
                        "INSERT INTO subscriptions (id, tenant_id, plan_id, status, "
                        "billing_interval, current_period_start, current_period_end) "
                        "VALUES (:id, :tid, :pid, 'active', :interval, :pstart, :pend) "
                        "RETURNING id, tenant_id, plan_id, status, billing_interval, "
                        "trial_start, trial_end, current_period_start, current_period_end, "
                        "canceled_at, auto_renew, created_at"
                    ),
                    {"id": sub_id, "tid": tenant_id, "pid": plan_id,
                     "interval": interval, "pstart": now, "pend": period_end},
                )
            row = result.fetchone()
            await session.commit()
            return Subscription(
                id=row.id, tenant_id=row.tenant_id, plan_id=row.plan_id,
                status=SubscriptionStatus(row.status),
                billing_interval=BillingInterval(row.billing_interval),
                trial_start=row.trial_start, trial_end=row.trial_end,
                current_period_start=row.current_period_start,
                current_period_end=row.current_period_end,
                canceled_at=row.canceled_at, auto_renew=row.auto_renew,
                created_at=row.created_at,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_subscription_status(
        self, subscription_id: UUID, status: str
    ) -> None:
        session = await get_async_session()
        try:
            now = datetime.now(timezone.utc)
            extra = ""
            params: dict = {"sid": subscription_id, "status": status, "now": now}
            if status == "canceled":
                extra = ", canceled_at = :now"
            await session.execute(
                text(
                    f"UPDATE subscriptions SET status = :status, "
                    f"updated_at = :now{extra} WHERE id = :sid"
                ),
                params,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_token_by_hash(self, token_hash: str) -> ApiToken | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, subscription_id, token_hash, token_prefix, name, "
                    "scopes, is_active, last_used_at, expires_at, created_at "
                    "FROM api_tokens WHERE token_hash = :hash AND is_active = true"
                ),
                {"hash": token_hash},
            )
            row = result.fetchone()
            if row is None:
                return None
            if row.expires_at and row.expires_at < datetime.now(timezone.utc):
                return None
            return ApiToken(
                id=row.id, subscription_id=row.subscription_id,
                token_hash=row.token_hash, token_prefix=row.token_prefix,
                name=row.name,
                scopes=list(row.scopes) if row.scopes else [],
                is_active=row.is_active, last_used_at=row.last_used_at,
                expires_at=row.expires_at, created_at=row.created_at,
            )
        finally:
            await session.close()

    async def get_token_by_subscription(
        self, subscription_id: UUID
    ) -> ApiToken | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, subscription_id, token_hash, token_prefix, name, "
                    "scopes, is_active, last_used_at, expires_at, created_at "
                    "FROM api_tokens "
                    "WHERE subscription_id = :sid AND is_active = true "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"sid": subscription_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return ApiToken(
                id=row.id, subscription_id=row.subscription_id,
                token_hash=row.token_hash, token_prefix=row.token_prefix,
                name=row.name,
                scopes=list(row.scopes) if row.scopes else [],
                is_active=row.is_active, last_used_at=row.last_used_at,
                expires_at=row.expires_at, created_at=row.created_at,
            )
        finally:
            await session.close()

    async def create_token(
        self, subscription_id: UUID, token: str,
        name: str = "Default", scopes: list[str] | None = None,
    ) -> ApiToken:
        import hashlib as _hl
        token_hash = _hl.sha256(token.encode()).hexdigest()
        prefix = "rag_live_" if token.startswith("rag_live_") else "rag_test_"
        tid = _uuid4()
        sc = scopes or ["rag:query", "rag:ingest"]
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO api_tokens (id, subscription_id, token_hash, "
                    "token_prefix, name, scopes) "
                    "VALUES (:id, :sid, :hash, :prefix, :name, :scopes) "
                    "RETURNING id, subscription_id, token_hash, token_prefix, name, "
                    "scopes, is_active, last_used_at, expires_at, created_at"
                ),
                {"id": tid, "sid": subscription_id, "hash": token_hash,
                 "prefix": prefix, "name": name, "scopes": json.dumps(sc)},
            )
            row = result.fetchone()
            await session.commit()
            return ApiToken(
                id=row.id, subscription_id=row.subscription_id,
                token_hash=row.token_hash, token_prefix=row.token_prefix,
                name=row.name,
                scopes=list(row.scopes) if row.scopes else [],
                is_active=row.is_active, last_used_at=row.last_used_at,
                expires_at=row.expires_at, created_at=row.created_at,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def touch_token_last_used(self, token_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE api_tokens SET last_used_at = NOW() WHERE id = :tid"),
                {"tid": token_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()

    async def deactivate_token(self, token_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE api_tokens SET is_active = false WHERE id = :tid"),
                {"tid": token_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()

    async def check_and_increment_quota(
        self, subscription_id: UUID, plan_requests_per_month: int
    ) -> bool:
        session = await get_async_session()
        try:
            now = datetime.now(timezone.utc)
            year = now.year
            month = now.month
            result = await session.execute(
                text(
                    "INSERT INTO request_quota (subscription_id, quota_year, "
                    "quota_month, request_count, reset_at) "
                    "VALUES (:sid, :year, :month, 1, NOW()) "
                    "ON CONFLICT (subscription_id, quota_year, quota_month) "
                    "DO UPDATE SET request_count = request_quota.request_count + 1 "
                    "RETURNING request_count"
                ),
                {"sid": subscription_id, "year": year, "month": month},
            )
            count = result.scalar_one()
            return count <= plan_requests_per_month
        finally:
            await session.close()

    async def get_quota_usage(self, subscription_id: UUID) -> tuple[int, int]:
        session = await get_async_session()
        try:
            now = datetime.now(timezone.utc)
            result = await session.execute(
                text(
                    "SELECT request_count FROM request_quota "
                    "WHERE subscription_id = :sid AND quota_year = :year "
                    "AND quota_month = :month"
                ),
                {"sid": subscription_id, "year": now.year, "month": now.month},
            )
            row = result.fetchone()
            return (row.request_count if row else 0, now.month)
        finally:
            await session.close()

    async def list_subscriptions(self) -> list[dict]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT s.id, s.tenant_id, s.plan_id, s.status, s.billing_interval, "
                    "s.trial_start, s.trial_end, s.current_period_start, s.current_period_end, "
                    "s.auto_renew, s.created_at, "
                    "t.name AS tenant_name, t.company_name, t.ruc, t.email AS tenant_email, "
                    "p.name AS plan_name, p.display_name AS plan_display_name "
                    "FROM subscriptions s "
                    "JOIN tenants t ON s.tenant_id = t.id "
                    "JOIN plans p ON s.plan_id = p.id "
                    "ORDER BY s.created_at DESC"
                )
            )
            rows = result.fetchall()
            subs = []
            for row in rows:
                sub_id = row.id
                quota_result = await session.execute(
                    text(
                        "SELECT request_count FROM request_quota "
                        "WHERE subscription_id = :sid "
                        "AND quota_year = EXTRACT(YEAR FROM NOW())::int "
                        "AND quota_month = EXTRACT(MONTH FROM NOW())::int"
                    ),
                    {"sid": sub_id},
                )
                quota_row = quota_result.fetchone()
                subs.append({
                    "id": str(row.id),
                    "tenant_id": str(row.tenant_id),
                    "plan_id": str(row.plan_id),
                    "status": row.status,
                    "billing_interval": row.billing_interval,
                    "trial_start": row.trial_start.isoformat() if row.trial_start else None,
                    "trial_end": row.trial_end.isoformat() if row.trial_end else None,
                    "current_period_start": row.current_period_start.isoformat() if row.current_period_start else None,
                    "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
                    "auto_renew": row.auto_renew,
                    "created_at": row.created_at.isoformat(),
                    "tenant_name": row.tenant_name,
                    "company_name": row.company_name,
                    "ruc": row.ruc,
                    "tenant_email": row.tenant_email,
                    "plan_name": row.plan_name,
                    "plan_display_name": row.plan_display_name,
                    "requests_used": quota_row.request_count if quota_row else 0,
                })
            return subs
        finally:
            await session.close()

    async def change_plan(self, subscription_id: UUID, plan_id: UUID) -> Subscription:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE subscriptions SET plan_id = :plan_id, updated_at = NOW() "
                    "WHERE id = :sid "
                    "RETURNING id, tenant_id, plan_id, status, billing_interval, "
                    "trial_start, trial_end, current_period_start, current_period_end, "
                    "canceled_at, auto_renew, created_at"
                ),
                {"sid": subscription_id, "plan_id": plan_id},
            )
            row = result.fetchone()
            await session.commit()
            if row is None:
                raise ValueError(f"Subscription {subscription_id} not found")
            return Subscription(
                id=row.id, tenant_id=row.tenant_id, plan_id=row.plan_id,
                status=SubscriptionStatus(row.status),
                billing_interval=BillingInterval(row.billing_interval),
                trial_start=row.trial_start, trial_end=row.trial_end,
                current_period_start=row.current_period_start,
                current_period_end=row.current_period_end,
                canceled_at=row.canceled_at, auto_renew=row.auto_renew,
                created_at=row.created_at,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_subscription(self, subscription_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("DELETE FROM api_tokens WHERE subscription_id = :sid"),
                {"sid": subscription_id},
            )
            await session.execute(
                text("DELETE FROM request_quota WHERE subscription_id = :sid"),
                {"sid": subscription_id},
            )
            await session.execute(
                text("DELETE FROM subscriptions WHERE id = :sid"),
                {"sid": subscription_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
