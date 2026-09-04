# =============================================================================
# PostgreSQL Adapter — Implementación de repositorios de plataforma
# =============================================================================
# Usa asyncpg vía SQLAlchemy 2.0 asíncrono. La conexión se gestiona con
# un pool configurable. Prepared Statements mitigan SQL Injection.
#
# REGLA DE AISLAMIENTO: todo método que lea/escriba datos de cliente exige
# organization_id como parámetro y lo aplica en el WHERE. Nunca se confía
# en identificadores provenientes de headers o bodies del cliente.
# =============================================================================
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from src.core.domain.entities import (
    Agent,
    AgentStatus,
    AgentVersion,
    AgentVersionStatus,
    ApiKey,
    AuditLogEntry,
    BillingInterval,
    Connector,
    Deployment,
    DeploymentStatus,
    Environment,
    KnowledgeBase,
    Membership,
    Organization,
    OrganizationStatus,
    Permission,
    Plan,
    Project,
    Role,
    Subscription,
    SubscriptionStatus,
    User,
    Workspace,
    WorkspaceStatus,
    display_api_key_prefix,
)
from src.core.ports import (
    AgentRepository,
    AgentVersionRepository,
    ApiKeyRepository,
    AuditLogRepository,
    BillingRepository,
    ConnectorRepository,
    DeploymentRepository,
    KnowledgeBaseRepository,
    MembershipRepository,
    OrganizationRepository,
    ProjectRepository,
    UserRepository,
    WorkspaceRepository,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import (  # noqa: F401  (re-export para compat)
    close_db_connections,
    get_async_session,
    get_engine,
)

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Organizaciones
# -----------------------------------------------------------------------------
_ORG_COLS = (
    "id, name, status, rate_limit_per_minute, max_tokens_per_request, "
    "llm_model_override, embedding_model_override, config_json, "
    "company_name, ruc, phone, email, country, created_at"
)


def _row_to_organization(row) -> Organization:
    return Organization(
        id=row.id,
        name=row.name,
        status=OrganizationStatus(row.status),
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


class PostgresOrganizationRepository(OrganizationRepository):
    """Repositorio de Organizations sobre PostgreSQL con asyncpg."""

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_ORG_COLS} FROM organizations WHERE id = :organization_id"
                ),
                {"organization_id": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return _row_to_organization(row)
        finally:
            await session.close()

    async def check_rate_limit(self, organization_id: UUID) -> bool:
        """Verifica si la organización ha excedido su rate limit en la ventana actual."""
        session = await get_async_session()
        try:
            minute_window = int(time.time()) // 60
            result = await session.execute(
                text(
                    "INSERT INTO rate_limit_counters (organization_id, minute_window, counter) "
                    "VALUES (:organization_id, :window, 1) "
                    "ON CONFLICT (organization_id, minute_window) "
                    "DO UPDATE SET counter = rate_limit_counters.counter + 1 "
                    "RETURNING counter"
                ),
                {"organization_id": organization_id, "window": minute_window},
            )
            counter = result.scalar_one()
            organization = await self.get_by_id(organization_id)
            if organization is None:
                return False
            return counter <= organization.rate_limit_per_minute
        finally:
            await session.close()

    async def log_usage(
        self, organization_id: UUID, user_id: UUID, tokens: int, latency_ms: float
    ) -> None:
        """Registra el uso de tokens para facturación por organización."""
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO usage_logs (organization_id, user_id, total_tokens, latency_ms) "
                    "VALUES (:organization_id, :user_id, :tokens, :latency_ms)"
                ),
                {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "tokens": tokens,
                    "latency_ms": latency_ms,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning("Failed to log usage", organization_id=str(organization_id))
        finally:
            await session.close()

    async def create_organization(
        self, organization_id: UUID, name: str
    ) -> Organization:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO organizations (id, name, status, rate_limit_per_minute, "
                    "primary_region_id) "
                    "VALUES (:id, :name, 'active', 600, "
                    "(SELECT id FROM regions WHERE code = 'us-east-1')) "
                    "ON CONFLICT (id) DO UPDATE SET name = :name2 "
                    f"RETURNING {_ORG_COLS}"
                ),
                {"id": organization_id, "name": name, "name2": name},
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_organization(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_organization(self, organization_id: UUID, **fields) -> Organization:
        allowed = {"company_name", "ruc", "phone", "email", "country", "name"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            org = await self.get_by_id(organization_id)
            if org is None:
                raise ValueError(f"Organization {organization_id} not found")
            return org
        session = await get_async_session()
        try:
            set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
            params = {"oid": organization_id, **updates}
            result = await session.execute(
                text(
                    f"UPDATE organizations SET {set_clauses}, updated_at = NOW() "
                    f"WHERE id = :oid RETURNING {_ORG_COLS}"
                ),
                params,
            )
            row = result.fetchone()
            await session.commit()
            if row is None:
                raise ValueError(f"Organization {organization_id} not found")
            return _row_to_organization(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_config(self, organization_id: UUID, config: dict) -> Organization:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE organizations SET config_json = CAST(:config AS jsonb), updated_at = NOW() "
                    f"WHERE id = :oid RETURNING {_ORG_COLS}"
                ),
                {"oid": organization_id, "config": json.dumps(config)},
            )
            row = result.fetchone()
            await session.commit()
            if row is None:
                raise ValueError(f"Organization {organization_id} not found")
            return _row_to_organization(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_organizations(self) -> list[Organization]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(f"SELECT {_ORG_COLS} FROM organizations ORDER BY created_at DESC")
            )
            return [_row_to_organization(row) for row in result.fetchall()]
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Usuarios
# -----------------------------------------------------------------------------
_platform_admin_schema_ready = False


async def ensure_platform_admin_schema() -> None:
    """Additive users.is_platform_admin + nullable organization_id for Control Center."""
    global _platform_admin_schema_ready
    if _platform_admin_schema_ready:
        return
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "is_platform_admin BOOLEAN NOT NULL DEFAULT false"
            )
        )
        await session.execute(text("ALTER TABLE users ALTER COLUMN organization_id DROP NOT NULL"))
        await session.execute(
            text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk")
        )
        await session.execute(
            text(
                """
                ALTER TABLE users ADD CONSTRAINT users_platform_admin_org_chk
                    CHECK (
                        (is_platform_admin = true AND organization_id IS NULL)
                        OR (is_platform_admin = false AND organization_id IS NOT NULL)
                    )
                """
            )
        )
        await session.commit()
        _platform_admin_schema_ready = True
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


class PostgresUserRepository(UserRepository):
    """Repositorio de Usuarios sobre PostgreSQL."""

    _USER_COLS = (
        "id, organization_id, external_id, email_hash, role, email, password_hash, "
        "COALESCE(is_platform_admin, false) AS is_platform_admin, created_at"
    )

    @staticmethod
    def _row_to_user(row) -> User:
        return User(
            id=row.id,
            organization_id=row.organization_id,
            external_id=row.external_id,
            email_hash=row.email_hash,
            role=row.role,
            email=getattr(row, "email", None),
            password_hash=getattr(row, "password_hash", None),
            is_platform_admin=bool(getattr(row, "is_platform_admin", False)),
            created_at=row.created_at,
        )

    async def get_by_id(self, user_id: UUID, organization_id: UUID) -> User | None:
        await ensure_platform_admin_schema()
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._USER_COLS} "
                    "FROM users WHERE id = :user_id AND organization_id = :organization_id"
                ),
                {"user_id": user_id, "organization_id": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_user(row)
        finally:
            await session.close()

    async def get_by_external_id(
        self, organization_id: UUID, external_id: str
    ) -> User | None:
        await ensure_platform_admin_schema()
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._USER_COLS} "
                    "FROM users WHERE organization_id = :oid AND external_id = :ext_id"
                ),
                {"oid": organization_id, "ext_id": external_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_user(row)
        finally:
            await session.close()

    async def get_any_user(self, organization_id: UUID) -> User | None:
        await ensure_platform_admin_schema()
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._USER_COLS} "
                    "FROM users WHERE organization_id = :oid LIMIT 1"
                ),
                {"oid": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_user(row)
        finally:
            await session.close()

    async def get_by_email(self, email: str) -> User | None:
        await ensure_platform_admin_schema()
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
                text("UPDATE users SET password_hash = :ph WHERE id = :uid"),
                {"ph": password_hash, "uid": user_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def create_sso_user(
        self, organization_id: UUID, email: str, external_id: str
    ) -> UUID:
        """JIT provisioning (SSO/SCIM): crea usuario sin password."""
        import hashlib as _hl

        session = await get_async_session()
        user_id = uuid4()
        try:
            await session.execute(
                text(
                    "INSERT INTO users (id, organization_id, external_id, email_hash, "
                    "role, email) VALUES (:id, :oid, :ext, :eh, 'member', :email) "
                    "ON CONFLICT (organization_id, external_id) DO NOTHING"
                ),
                {
                    "id": user_id,
                    "oid": organization_id,
                    "ext": external_id[:255],
                    "eh": _hl.sha256(email.strip().lower().encode()).hexdigest(),
                    "email": email.strip(),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
        return user_id

    async def create_default_user(
        self,
        organization_id: UUID,
        email_hash: str,
        *,
        email: str | None = None,
        password_hash: str | None = None,
    ) -> User:
        await ensure_platform_admin_schema()
        session = await get_async_session()
        user_id = uuid4()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO users "
                    "(id, organization_id, external_id, email_hash, role, email, password_hash) "
                    "VALUES (:id, :oid, :ext_id, :email_hash, 'admin', :email, :password_hash) "
                    "ON CONFLICT (organization_id, external_id) DO NOTHING "
                    f"RETURNING {self._USER_COLS}"
                ),
                {
                    "id": user_id,
                    "oid": organization_id,
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
                        "FROM users WHERE organization_id = :oid AND external_id = 'default-admin'"
                    ),
                    {"oid": organization_id},
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


# -----------------------------------------------------------------------------
# RBAC — Membresías, Roles y Permisos
# -----------------------------------------------------------------------------
class PostgresMembershipRepository(MembershipRepository):

    @staticmethod
    def _row_to_membership(row) -> Membership:
        return Membership(
            id=row.id,
            organization_id=row.organization_id,
            user_id=row.user_id,
            role_id=row.role_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _row_to_role(row) -> Role:
        return Role(
            id=row.id,
            name=row.name,
            organization_id=row.organization_id,
            description=row.description,
            is_system=row.is_system,
        )

    async def get_membership(
        self, organization_id: UUID, user_id: UUID
    ) -> Membership | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, user_id, role_id, created_at "
                    "FROM memberships WHERE organization_id = :oid AND user_id = :uid"
                ),
                {"oid": organization_id, "uid": user_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_membership(row)
        finally:
            await session.close()

    async def list_members(self, organization_id: UUID) -> list[tuple[User, Role]]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT u.id AS u_id, u.organization_id AS u_org, u.external_id, "
                    "u.email_hash, u.role AS u_role, u.email, u.password_hash, u.created_at AS u_created, "
                    "r.id AS r_id, r.name AS r_name, r.organization_id AS r_org, "
                    "r.description, r.is_system "
                    "FROM memberships m "
                    "JOIN users u ON u.id = m.user_id "
                    "JOIN roles r ON r.id = m.role_id "
                    "WHERE m.organization_id = :oid "
                    "ORDER BY u.created_at"
                ),
                {"oid": organization_id},
            )
            members: list[tuple[User, Role]] = []
            for row in result.fetchall():
                user = User(
                    id=row.u_id,
                    organization_id=row.u_org,
                    external_id=row.external_id,
                    email_hash=row.email_hash,
                    role=row.u_role,
                    email=row.email,
                    password_hash=row.password_hash,
                    created_at=row.u_created,
                )
                role = Role(
                    id=row.r_id,
                    name=row.r_name,
                    organization_id=row.r_org,
                    description=row.description,
                    is_system=row.is_system,
                )
                members.append((user, role))
            return members
        finally:
            await session.close()

    async def assign_role(
        self, organization_id: UUID, user_id: UUID, role_name: str
    ) -> Membership:
        session = await get_async_session()
        try:
            role_row = await session.execute(
                text(
                    "SELECT id FROM roles "
                    "WHERE name = :name AND (organization_id IS NULL OR organization_id = :oid) "
                    "ORDER BY (organization_id IS NOT NULL) LIMIT 1"
                ),
                {"name": role_name, "oid": organization_id},
            )
            role = role_row.fetchone()
            if role is None:
                raise ValueError(f"Role '{role_name}' not found")
            membership_id = uuid4()
            await session.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role_id) "
                    "VALUES (:id, :oid, :uid, :rid) "
                    "ON CONFLICT (organization_id, user_id) "
                    "DO UPDATE SET role_id = :rid2, updated_at = NOW()"
                ),
                {
                    "id": membership_id,
                    "oid": organization_id,
                    "uid": user_id,
                    "rid": role.id,
                    "rid2": role.id,
                },
            )
            await session.execute(
                text(
                    "UPDATE users SET role = CASE WHEN :name IN ('owner', 'admin') "
                    "THEN 'admin' ELSE 'user' END WHERE id = :uid"
                ),
                {"name": role_name, "uid": user_id},
            )
            await session.commit()
            return Membership(
                id=membership_id,
                organization_id=organization_id,
                user_id=user_id,
                role_id=role.id,
            )
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def remove_member(self, organization_id: UUID, user_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM memberships WHERE organization_id = :oid AND user_id = :uid"
                ),
                {"oid": organization_id, "uid": user_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_user_roles(self, user_id: UUID, organization_id: UUID) -> list[Role]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT r.id, r.name, r.organization_id, r.description, r.is_system "
                    "FROM roles r "
                    "JOIN memberships m ON m.role_id = r.id "
                    "WHERE m.user_id = :uid AND m.organization_id = :oid"
                ),
                {"uid": user_id, "oid": organization_id},
            )
            return [self._row_to_role(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_role_permissions(self, role_ids: list[UUID]) -> list[Permission]:
        if not role_ids:
            return []
        session = await get_async_session()
        try:
            ids = ", ".join(f"'{r}'" for r in role_ids)
            result = await session.execute(
                text(
                    "SELECT DISTINCT p.id, p.code, p.description "
                    "FROM permissions p "
                    "JOIN role_permissions rp ON rp.permission_id = p.id "
                    f"WHERE rp.role_id IN ({ids})"
                )
            )
            return [
                Permission(id=row.id, code=row.code, description=row.description)
                for row in result.fetchall()
            ]
        finally:
            await session.close()

    async def list_system_roles(self) -> list[Role]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, organization_id, description, is_system "
                    "FROM roles WHERE organization_id IS NULL ORDER BY name"
                )
            )
            return [self._row_to_role(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_role_by_name(self, name: str) -> Role | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, organization_id, description, is_system "
                    "FROM roles WHERE organization_id IS NULL AND name = :name LIMIT 1"
                ),
                {"name": name},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_role(row)
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# API Keys (organización-scoped)
# -----------------------------------------------------------------------------
class PostgresApiKeyRepository(ApiKeyRepository):

    _KEY_COLS = (
        "id, organization_id, name, key_hash, key_prefix, scopes, is_active, "
        "created_by, last_used_at, expires_at, ip_allowlist, rate_limit_per_minute, "
        "created_at"
    )

    @staticmethod
    def _row_to_key(row) -> ApiKey:
        return ApiKey(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            key_hash=row.key_hash,
            key_prefix=row.key_prefix,
            scopes=list(row.scopes) if row.scopes else [],
            is_active=row.is_active,
            created_by=row.created_by,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            created_at=row.created_at,
            ip_allowlist=list(row.ip_allowlist) if row.ip_allowlist else [],
            rate_limit_per_minute=row.rate_limit_per_minute,
        )

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._KEY_COLS} FROM api_keys "
                    "WHERE key_hash = :hash AND is_active = true"
                ),
                {"hash": key_hash},
            )
            row = result.fetchone()
            if row is None:
                return None
            if row.expires_at and row.expires_at < datetime.now(timezone.utc):
                return None
            # Política de expiración forzada por organización (key_max_age_days).
            policy = (
                await session.execute(
                    text(
                        "SELECT key_max_age_days FROM organizations WHERE id = :oid"
                    ),
                    {"oid": row.organization_id},
                )
            ).scalar()
            if (
                policy
                and row.created_at
                and datetime.now(timezone.utc) - row.created_at
                > timedelta(days=int(policy))
            ):
                return None
            return self._row_to_key(row)
        finally:
            await session.close()

    async def get_key(self, key_id: UUID) -> ApiKey | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(f"SELECT {self._KEY_COLS} FROM api_keys WHERE id = :kid"),
                {"kid": key_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_key(row)
        finally:
            await session.close()

    async def update_key(
        self, organization_id: UUID, key_id: UUID, **fields
    ) -> ApiKey | None:
        allowed = {"name", "ip_allowlist", "rate_limit_per_minute", "expires_at"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        session = await get_async_session()
        try:
            if updates:
                if "ip_allowlist" in updates:
                    updates["ip_allowlist"] = json.dumps(updates["ip_allowlist"])
                set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                params = {"oid": organization_id, "kid": key_id, **updates}
                await session.execute(
                    text(
                        f"UPDATE api_keys SET {set_clauses} "
                        "WHERE id = :kid AND organization_id = :oid"
                    ),
                    params,
                )
                await session.commit()
            return await self.get_key(key_id)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_keys(self, organization_id: UUID) -> list[ApiKey]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._KEY_COLS} FROM api_keys "
                    "WHERE organization_id = :oid ORDER BY created_at DESC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_key(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def create_key(
        self,
        organization_id: UUID,
        token: str,
        name: str = "Default",
        scopes: list[str] | None = None,
        created_by: UUID | None = None,
        expires_at: datetime | None = None,
        ip_allowlist: list[str] | None = None,
        rate_limit_per_minute: int | None = None,
    ) -> ApiKey:
        import hashlib as _hl

        key_hash = _hl.sha256(token.encode()).hexdigest()
        prefix = display_api_key_prefix(token)
        key_id = uuid4()
        sc = scopes or ["rag:read", "rag:write"]
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO api_keys (id, organization_id, name, key_hash, "
                    "key_prefix, scopes, created_by, expires_at, ip_allowlist, "
                    "rate_limit_per_minute) "
                    "VALUES (:id, :oid, :name, :hash, :prefix, :scopes, :created_by, "
                    ":expires_at, :ip_allowlist, :rate_limit_per_minute) "
                    f"RETURNING {self._KEY_COLS}"
                ),
                {
                    "id": key_id,
                    "oid": organization_id,
                    "name": name,
                    "hash": key_hash,
                    "prefix": prefix,
                    "scopes": json.dumps(sc),
                    "created_by": created_by,
                    "expires_at": expires_at,
                    "ip_allowlist": (
                        json.dumps(ip_allowlist) if ip_allowlist else "[]"
                    ),
                    "rate_limit_per_minute": rate_limit_per_minute,
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_key(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def touch_last_used(self, key_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE api_keys SET last_used_at = NOW() WHERE id = :kid"),
                {"kid": key_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()

    async def deactivate_key(self, key_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE api_keys SET is_active = false WHERE id = :kid"),
                {"kid": key_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Proyectos
# -----------------------------------------------------------------------------
class PostgresProjectRepository(ProjectRepository):

    @staticmethod
    def _row_to_project(row) -> Project:
        return Project(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            description=row.description,
            created_at=row.created_at,
        )

    async def list_projects(self, organization_id: UUID) -> list[Project]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, description, created_at "
                    "FROM projects WHERE organization_id = :oid ORDER BY created_at DESC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_project(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_project(self, organization_id: UUID, project_id: UUID) -> Project | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, description, created_at "
                    "FROM projects WHERE id = :pid AND organization_id = :oid"
                ),
                {"pid": project_id, "oid": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_project(row)
        finally:
            await session.close()

    async def create_project(
        self, organization_id: UUID, name: str, description: str | None = None
    ) -> Project:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, description) "
                    "VALUES (uuid_generate_v4(), :oid, :name, :description) "
                    "RETURNING id, organization_id, name, description, created_at"
                ),
                {"oid": organization_id, "name": name, "description": description},
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_project(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_project(
        self,
        organization_id: UUID,
        project_id: UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> Project:
        session = await get_async_session()
        try:
            updates: list[str] = []
            params: dict = {"oid": organization_id, "pid": project_id}
            if name is not None:
                updates.append("name = :name")
                params["name"] = name
            if description is not None:
                updates.append("description = :description")
                params["description"] = description
            if not updates:
                project = await self.get_project(organization_id, project_id)
                if project is None:
                    raise ValueError(f"Project {project_id} not found")
                return project
            set_clause = ", ".join(updates)
            result = await session.execute(
                text(
                    f"UPDATE projects SET {set_clause}, updated_at = NOW() "
                    "WHERE id = :pid AND organization_id = :oid "
                    "RETURNING id, organization_id, name, description, created_at"
                ),
                params,
            )
            row = result.fetchone()
            await session.commit()
            if row is None:
                raise ValueError(f"Project {project_id} not found")
            return self._row_to_project(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_project(self, organization_id: UUID, project_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("DELETE FROM projects WHERE id = :pid AND organization_id = :oid"),
                {"pid": project_id, "oid": organization_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Knowledge Bases
# -----------------------------------------------------------------------------
class PostgresKnowledgeBaseRepository(KnowledgeBaseRepository):

    _KB_COLS = (
        "id, organization_id, name, project_id, description, status, "
        "embedding_model, chunking_strategy, chunk_size, chunk_overlap, "
        "retrieval_strategy, reranker, metadata_schema, config_json, workspace_id, created_at"
    )

    @staticmethod
    def _row_to_kb(row) -> KnowledgeBase:
        return KnowledgeBase(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            project_id=row.project_id,
            workspace_id=row.workspace_id,
            description=row.description,
            status=row.status,
            embedding_model=row.embedding_model,
            chunking_strategy=getattr(row, "chunking_strategy", "fixed") or "fixed",
            chunk_size=getattr(row, "chunk_size", 1200) or 1200,
            chunk_overlap=getattr(row, "chunk_overlap", 150) or 150,
            retrieval_strategy=getattr(row, "retrieval_strategy", "vector") or "vector",
            reranker=getattr(row, "reranker", None),
            metadata_schema=row.metadata_schema
            if isinstance(getattr(row, "metadata_schema", None), dict)
            else {},
            config_json=row.config_json if isinstance(row.config_json, dict) else {},
            created_at=row.created_at,
        )

    async def list_kbs(self, organization_id: UUID) -> list[KnowledgeBase]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._KB_COLS} FROM knowledge_bases "
                    "WHERE organization_id = :oid ORDER BY created_at DESC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_kb(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_kb(self, organization_id: UUID, kb_id: UUID) -> KnowledgeBase | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._KB_COLS} FROM knowledge_bases "
                    "WHERE id = :kid AND organization_id = :oid"
                ),
                {"kid": kb_id, "oid": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_kb(row)
        finally:
            await session.close()

    async def create_kb(
        self,
        organization_id: UUID,
        name: str,
        description: str | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        embedding_model: str | None = None,
        chunking_strategy: str = "fixed",
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
        retrieval_strategy: str = "vector",
        reranker: str | None = None,
        metadata_schema: dict | None = None,
    ) -> KnowledgeBase:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO knowledge_bases (id, organization_id, name, description, "
                    "project_id, workspace_id, embedding_model, chunking_strategy, chunk_size, "
                    "chunk_overlap, retrieval_strategy, reranker, metadata_schema) "
                    "VALUES (uuid_generate_v4(), :oid, :name, :description, :pid, :wid, :model, "
                    ":chunking, :csize, :coverlap, :retrieval, :reranker, CAST(:mschema AS jsonb)) "
                    f"RETURNING {self._KB_COLS}"
                ),
                {
                    "oid": organization_id,
                    "name": name,
                    "description": description,
                    "pid": project_id,
                    "wid": workspace_id,
                    "model": embedding_model,
                    "chunking": chunking_strategy,
                    "csize": chunk_size,
                    "coverlap": chunk_overlap,
                    "retrieval": retrieval_strategy,
                    "reranker": reranker,
                    "mschema": json.dumps(metadata_schema or {}),
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_kb(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_kb(self, organization_id: UUID, kb_id: UUID, **fields) -> KnowledgeBase:
        allowed = {
            "name", "description", "project_id", "status", "embedding_model",
            "config_json", "chunking_strategy", "chunk_size", "chunk_overlap",
            "retrieval_strategy", "reranker", "metadata_schema", "workspace_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        session = await get_async_session()
        try:
            if updates:
                for key in ("config_json", "metadata_schema"):
                    if key in updates:
                        updates[key] = json.dumps(updates[key] or {})
                set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                params = {"oid": organization_id, "kid": kb_id, **updates}
                await session.execute(
                    text(
                        f"UPDATE knowledge_bases SET {set_clauses}, updated_at = NOW() "
                        "WHERE id = :kid AND organization_id = :oid"
                    ),
                    params,
                )
                await session.commit()
            kb = await self.get_kb(organization_id, kb_id)
            if kb is None:
                raise ValueError(f"Knowledge base {kb_id} not found")
            return kb
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_kb(self, organization_id: UUID, kb_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM knowledge_bases WHERE id = :kid AND organization_id = :oid"
                ),
                {"kid": kb_id, "oid": organization_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Agentes
# -----------------------------------------------------------------------------
class PostgresAgentRepository(AgentRepository):

    @staticmethod
    def _row_to_agent(row) -> Agent:
        return Agent(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            project_id=row.project_id,
            workspace_id=row.workspace_id,
            description=row.description,
            system_prompt=row.system_prompt,
            tools=list(row.tools) if row.tools else [],
            model=row.model,
            config_json=row.config_json if isinstance(row.config_json, dict) else {},
            is_active=row.is_active,
            status=AgentStatus(row.status) if row.status else AgentStatus.DRAFT,
            created_at=row.created_at,
        )

    async def list_agents(self, organization_id: UUID) -> list[Agent]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, project_id, description, system_prompt, "
                    "tools, model, config_json, is_active, status, workspace_id, created_at "
                    "FROM agents WHERE organization_id = :oid ORDER BY created_at DESC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_agent(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_agent(self, organization_id: UUID, agent_id: UUID) -> Agent | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, project_id, description, system_prompt, "
                    "tools, model, config_json, is_active, status, workspace_id, created_at "
                    "FROM agents WHERE id = :aid AND organization_id = :oid"
                ),
                {"aid": agent_id, "oid": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_agent(row)
        finally:
            await session.close()

    async def create_agent(
        self,
        organization_id: UUID,
        name: str,
        description: str | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        config_json: dict | None = None,
    ) -> Agent:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO agents (id, organization_id, name, description, project_id, "
                    "workspace_id, system_prompt, tools, model, config_json) "
                    "VALUES (uuid_generate_v4(), :oid, :name, :description, :pid, "
                    ":wid, :prompt, :tools, :model, CAST(:config AS jsonb)) "
                    "RETURNING id, organization_id, name, project_id, description, system_prompt, "
                    "tools, model, config_json, is_active, status, workspace_id, created_at"
                ),
                {
                    "oid": organization_id,
                    "name": name,
                    "description": description,
                    "pid": project_id,
                    "wid": workspace_id,
                    "prompt": system_prompt,
                    "tools": json.dumps(tools or []),
                    "model": model,
                    "config": json.dumps(config_json or {}),
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_agent(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_agent(self, organization_id: UUID, agent_id: UUID, **fields) -> Agent:
        allowed = {
            "name",
            "description",
            "project_id",
            "system_prompt",
            "tools",
            "model",
            "is_active",
            "workspace_id",
            "status",
            "config_json",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        session = await get_async_session()
        try:
            if updates:
                if "tools" in updates:
                    updates["tools"] = json.dumps(updates["tools"])
                if "config_json" in updates:
                    updates["config_json"] = json.dumps(updates["config_json"])
                set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                params = {"oid": organization_id, "aid": agent_id, **updates}
                await session.execute(
                    text(
                        f"UPDATE agents SET {set_clauses}, updated_at = NOW() "
                        "WHERE id = :aid AND organization_id = :oid"
                    ),
                    params,
                )
                await session.commit()
            agent = await self.get_agent(organization_id, agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id} not found")
            return agent
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_agent(self, organization_id: UUID, agent_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("DELETE FROM agents WHERE id = :aid AND organization_id = :oid"),
                {"aid": agent_id, "oid": organization_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Conectores
# -----------------------------------------------------------------------------
class PostgresConnectorRepository(ConnectorRepository):

    @staticmethod
    def _row_to_connector(row) -> Connector:
        return Connector(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            type=row.type,
            project_id=row.project_id,
            workspace_id=row.workspace_id,
            config_json=row.config_json if isinstance(row.config_json, dict) else {},
            status=row.status,
            created_at=row.created_at,
        )

    async def list_connectors(self, organization_id: UUID) -> list[Connector]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, type, project_id, workspace_id, "
                    "config_json, status, created_at FROM connectors "
                    "WHERE organization_id = :oid "
                    "ORDER BY created_at DESC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_connector(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_connector(
        self, organization_id: UUID, connector_id: UUID
    ) -> Connector | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, type, project_id, workspace_id, "
                    "config_json, status, created_at FROM connectors "
                    "WHERE id = :cid AND organization_id = :oid"
                ),
                {"cid": connector_id, "oid": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_connector(row)
        finally:
            await session.close()

    async def create_connector(
        self,
        organization_id: UUID,
        name: str,
        connector_type: str,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        config_json: dict | None = None,
    ) -> Connector:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO connectors (id, organization_id, name, type, project_id, "
                    "workspace_id, config_json) "
                    "VALUES (uuid_generate_v4(), :oid, :name, :type, :pid, :wid, "
                    "CAST(:config AS jsonb)) "
                    "RETURNING id, organization_id, name, type, project_id, "
                    "workspace_id, config_json, status, created_at"
                ),
                {
                    "oid": organization_id,
                    "name": name,
                    "type": connector_type,
                    "pid": project_id,
                    "wid": workspace_id,
                    "config": json.dumps(config_json or {}),
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_connector(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_connector(
        self, organization_id: UUID, connector_id: UUID, **fields
    ) -> Connector:
        allowed = {"name", "project_id", "config_json", "status"}
        allowed.add("workspace_id")
        allowed.add("status")
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        session = await get_async_session()
        try:
            if updates:
                if "config_json" in updates:
                    updates["config_json"] = json.dumps(updates["config_json"])
                set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                params = {"oid": organization_id, "cid": connector_id, **updates}
                await session.execute(
                    text(
                        f"UPDATE connectors SET {set_clauses}, updated_at = NOW() "
                        "WHERE id = :cid AND organization_id = :oid"
                    ),
                    params,
                )
                await session.commit()
            connector = await self.get_connector(organization_id, connector_id)
            if connector is None:
                raise ValueError(f"Connector {connector_id} not found")
            return connector
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_connector(self, organization_id: UUID, connector_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM connectors WHERE id = :cid AND organization_id = :oid"
                ),
                {"cid": connector_id, "oid": organization_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Audit Logs
# -----------------------------------------------------------------------------
class PostgresAuditLogRepository(AuditLogRepository):

    async def write(self, entry: AuditLogEntry) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO audit_logs (organization_id, actor_user_id, action, "
                    "resource_type, resource_id, ip_address, metadata) "
                    "VALUES (:oid, :uid, :action, :rtype, :rid, :ip, CAST(:meta AS jsonb))"
                ),
                {
                    "oid": entry.organization_id,
                    "uid": entry.actor_user_id,
                    "action": entry.action,
                    "rtype": entry.resource_type,
                    "rid": entry.resource_id,
                    "ip": entry.ip_address,
                    "meta": json.dumps(entry.metadata or {}),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning("Failed to write audit log", action=entry.action)
        finally:
            await session.close()

    async def write_strict(self, entry: AuditLogEntry) -> None:
        """Inserta auditoría y propaga errores (impersonate / acciones de plataforma)."""
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO audit_logs (organization_id, actor_user_id, action, "
                    "resource_type, resource_id, ip_address, metadata) "
                    "VALUES (:oid, :uid, :action, :rtype, :rid, :ip, CAST(:meta AS jsonb))"
                ),
                {
                    "oid": entry.organization_id,
                    "uid": entry.actor_user_id,
                    "action": entry.action,
                    "rtype": entry.resource_type,
                    "rid": entry.resource_id,
                    "ip": entry.ip_address,
                    "meta": json.dumps(entry.metadata or {}),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()



    async def list_all_entries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        organization_id: UUID | None = None,
        action: str | None = None,
    ) -> list[AuditLogEntry]:
        """Viewer global de auditoría (Control Center, permiso audit.read)."""
        session = await get_async_session()
        try:
            query = (
                "SELECT organization_id, actor_user_id, action, resource_type, "
                "resource_id, ip_address, metadata, created_at FROM audit_logs WHERE true "
            )
            params: dict = {"limit": limit, "offset": offset}
            if organization_id is not None:
                query += "AND organization_id = :oid "
                params["oid"] = organization_id
            if action:
                query += "AND action = :action "
                params["action"] = action
            query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            result = await session.execute(text(query), params)
            rows = result.fetchall()
        finally:
            await session.close()
        return [
            AuditLogEntry(
                organization_id=row.organization_id,
                actor_user_id=row.actor_user_id,
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                ip_address=row.ip_address,
                metadata=row.metadata if isinstance(row.metadata, dict) else {},
                created_at=row.created_at,
            )
            for row in rows
        ]
    async def list_entries(
        self,
        organization_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
        resource_type: str | None = None,
    ) -> list[AuditLogEntry]:
        session = await get_async_session()
        try:
            query = (
                "SELECT organization_id, actor_user_id, action, resource_type, "
                "resource_id, ip_address, metadata, created_at "
                "FROM audit_logs WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if resource_type:
                query += "AND resource_type = :rtype "
                params["rtype"] = resource_type
            query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            result = await session.execute(text(query), params)
            return [
                AuditLogEntry(
                    organization_id=row.organization_id,
                    actor_user_id=row.actor_user_id,
                    action=row.action,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    ip_address=row.ip_address,
                    metadata=row.metadata if isinstance(row.metadata, dict) else {},
                    created_at=row.created_at,
                )
                for row in result.fetchall()
            ]
        finally:
            await session.close()


# =============================================================================
# PostgresBillingRepository — Planes, Suscripciones y Cuotas
# =============================================================================
class PostgresBillingRepository(BillingRepository):

    async def get_plan_by_id(self, plan_id: UUID) -> Plan | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, display_name, description, price_monthly_cents, "
                    "price_annual_cents, requests_per_month, max_organizations, "
                    "max_users_per_organization, features, is_public, is_trial, "
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
                max_organizations=row.max_organizations,
                max_users_per_organization=row.max_users_per_organization,
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
                "price_annual_cents, requests_per_month, max_organizations, "
                "max_users_per_organization, features, is_public, is_trial, "
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
                    max_organizations=row.max_organizations,
                    max_users_per_organization=row.max_users_per_organization,
                    features=list(row.features) if row.features else [],
                    is_public=row.is_public, is_trial=row.is_trial,
                    trial_days=row.trial_days, sort_order=row.sort_order,
                )
                for row in result.fetchall()
            ]
        finally:
            await session.close()

    async def get_subscription_by_organization(self, organization_id: UUID) -> Subscription | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, plan_id, status, billing_interval, "
                    "trial_start, trial_end, current_period_start, current_period_end, "
                    "canceled_at, auto_renew, created_at "
                    "FROM subscriptions WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return Subscription(
                id=row.id, organization_id=row.organization_id, plan_id=row.plan_id,
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
                    "SELECT id, organization_id, plan_id, status, billing_interval, "
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
                id=row.id, organization_id=row.organization_id, plan_id=row.plan_id,
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
        self, organization_id: UUID, plan_id: UUID,
        interval: str = "monthly", trial_days: int = 0,
    ) -> Subscription:
        now = datetime.now(timezone.utc)
        sub_id = uuid4()
        session = await get_async_session()
        try:
            if trial_days > 0:
                trial_end = now + timedelta(days=trial_days)
                result = await session.execute(
                    text(
                        "INSERT INTO subscriptions (id, organization_id, plan_id, status, "
                        "billing_interval, trial_start, trial_end, "
                        "current_period_start, current_period_end) "
                        "VALUES (:id, :oid, :pid, 'trialing', :interval, "
                        ":tstart, :tend, :tstart, :tend) "
                        "RETURNING id, organization_id, plan_id, status, billing_interval, "
                        "trial_start, trial_end, current_period_start, current_period_end, "
                        "canceled_at, auto_renew, created_at"
                    ),
                    {"id": sub_id, "oid": organization_id, "pid": plan_id,
                     "interval": interval, "tstart": now, "tend": trial_end},
                )
            else:
                period_end = now + timedelta(days=30 if interval == "monthly" else 365)
                result = await session.execute(
                    text(
                        "INSERT INTO subscriptions (id, organization_id, plan_id, status, "
                        "billing_interval, current_period_start, current_period_end) "
                        "VALUES (:id, :oid, :pid, 'active', :interval, :pstart, :pend) "
                        "RETURNING id, organization_id, plan_id, status, billing_interval, "
                        "trial_start, trial_end, current_period_start, current_period_end, "
                        "canceled_at, auto_renew, created_at"
                    ),
                    {"id": sub_id, "oid": organization_id, "pid": plan_id,
                     "interval": interval, "pstart": now, "pend": period_end},
                )
            row = result.fetchone()
            await session.commit()
            return Subscription(
                id=row.id, organization_id=row.organization_id, plan_id=row.plan_id,
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
                    "SELECT s.id, s.organization_id, s.plan_id, s.status, s.billing_interval, "
                    "s.trial_start, s.trial_end, s.current_period_start, s.current_period_end, "
                    "s.auto_renew, s.created_at, "
                    "o.name AS organization_name, o.company_name, o.ruc, o.email AS organization_email, "
                    "p.name AS plan_name, p.display_name AS plan_display_name "
                    "FROM subscriptions s "
                    "JOIN organizations o ON s.organization_id = o.id "
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
                    "organization_id": str(row.organization_id),
                    "plan_id": str(row.plan_id),
                    "status": row.status,
                    "billing_interval": row.billing_interval,
                    "trial_start": row.trial_start.isoformat() if row.trial_start else None,
                    "trial_end": row.trial_end.isoformat() if row.trial_end else None,
                    "current_period_start": row.current_period_start.isoformat() if row.current_period_start else None,
                    "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
                    "auto_renew": row.auto_renew,
                    "created_at": row.created_at.isoformat(),
                    "organization_name": row.organization_name,
                    "company_name": row.company_name,
                    "ruc": row.ruc,
                    "organization_email": row.organization_email,
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
                    "RETURNING id, organization_id, plan_id, status, billing_interval, "
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
                id=row.id, organization_id=row.organization_id, plan_id=row.plan_id,
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


class PostgresAgentVersionRepository(AgentVersionRepository):
    """Snapshot inmutables de configuracion de agentes (scoped por org)."""

    @staticmethod
    def _row_to_version(row) -> AgentVersion:
        return AgentVersion(
            id=row.id,
            organization_id=row.organization_id,
            agent_id=row.agent_id,
            version_number=row.version_number,
            status=AgentVersionStatus(row.status),
            config_snapshot=(
                row.config_snapshot if isinstance(row.config_snapshot, dict) else {}
            ),
            notes=row.notes,
            created_by=row.created_by,
            created_at=row.created_at,
        )

    async def list_versions(
        self, organization_id: UUID, agent_id: UUID
    ) -> list[AgentVersion]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, agent_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at "
                    "FROM agent_versions WHERE organization_id = :oid AND agent_id = :aid "
                    "ORDER BY version_number DESC"
                ),
                {"oid": organization_id, "aid": agent_id},
            )
            return [self._row_to_version(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_version(
        self, organization_id: UUID, agent_id: UUID, version_id: UUID
    ) -> AgentVersion | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, agent_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at "
                    "FROM agent_versions "
                    "WHERE id = :vid AND organization_id = :oid AND agent_id = :aid"
                ),
                {"vid": version_id, "oid": organization_id, "aid": agent_id},
            )
            row = result.fetchone()
            return self._row_to_version(row) if row is not None else None
        finally:
            await session.close()

    async def create_version(
        self,
        organization_id: UUID,
        agent_id: UUID,
        config_snapshot: dict,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> AgentVersion:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO agent_versions "
                    "(id, organization_id, agent_id, version_number, status, "
                    " config_snapshot, notes, created_by) "
                    "SELECT uuid_generate_v4(), :oid, :aid, "
                    "       COALESCE(MAX(version_number), 0) + 1, 'draft', "
                    "       CAST(:snapshot AS jsonb), :notes, :by "
                    "FROM agent_versions WHERE agent_id = :aid "
                    "RETURNING id, organization_id, agent_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at"
                ),
                {
                    "oid": organization_id,
                    "aid": agent_id,
                    "snapshot": json.dumps(config_snapshot or {}),
                    "notes": notes,
                    "by": created_by,
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_version(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def promote_version(
        self,
        organization_id: UUID,
        agent_id: UUID,
        version_id: UUID,
        status: str,
    ) -> AgentVersion | None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE agent_versions SET status = :status "
                    "WHERE id = :vid AND organization_id = :oid AND agent_id = :aid"
                ),
                {"status": status, "vid": version_id, "oid": organization_id, "aid": agent_id},
            )
            await session.commit()
            version = await self.get_version(organization_id, agent_id, version_id)
            if version is None:
                raise ValueError(f"Version {version_id} not found")
            return version
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class PostgresDeploymentRepository(DeploymentRepository):
    """Entornos y deployments de agentes (scoped por org)."""

    @staticmethod
    def _row_to_environment(row) -> Environment:
        return Environment(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            slug=row.slug,
            is_default=row.is_default,
            created_at=row.created_at,
        )

    @staticmethod
    def _row_to_deployment(row) -> Deployment:
        return Deployment(
            id=row.id,
            organization_id=row.organization_id,
            environment_id=row.environment_id,
            agent_id=row.agent_id,
            agent_version_id=row.agent_version_id,
            slug=row.slug,
            status=DeploymentStatus(row.status),
            endpoint=row.endpoint,
            deployed_by=row.deployed_by,
            deployed_at=row.deployed_at,
            rollback_from_id=row.rollback_from_id,
            created_at=row.created_at,
        )

    async def list_environments(self, organization_id: UUID) -> list[Environment]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, slug, is_default, created_at "
                    "FROM environments WHERE organization_id = :oid "
                    "ORDER BY is_default DESC, created_at ASC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_environment(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_environment(
        self, organization_id: UUID, environment_id: UUID
    ) -> Environment | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, slug, is_default, created_at "
                    "FROM environments WHERE id = :eid AND organization_id = :oid"
                ),
                {"eid": environment_id, "oid": organization_id},
            )
            row = result.fetchone()
            return self._row_to_environment(row) if row is not None else None
        finally:
            await session.close()

    async def get_environment_by_slug(
        self, organization_id: UUID, slug: str
    ) -> Environment | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, slug, is_default, created_at "
                    "FROM environments WHERE organization_id = :oid AND slug = :slug"
                ),
                {"oid": organization_id, "slug": slug},
            )
            row = result.fetchone()
            return self._row_to_environment(row) if row is not None else None
        finally:
            await session.close()

    async def create_environment(
        self, organization_id: UUID, name: str, slug: str, is_default: bool = False
    ) -> Environment:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO environments (id, organization_id, name, slug, is_default) "
                    "VALUES (uuid_generate_v4(), :oid, :name, :slug, :default) "
                    "RETURNING id, organization_id, name, slug, is_default, created_at"
                ),
                {"oid": organization_id, "name": name, "slug": slug, "default": is_default},
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_environment(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_deployments(self, organization_id: UUID) -> list[Deployment]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, environment_id, agent_id, "
                    "agent_version_id, slug, status, endpoint, deployed_by, "
                    "deployed_at, rollback_from_id, created_at "
                    "FROM deployments WHERE organization_id = :oid "
                    "ORDER BY created_at DESC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_deployment(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_deployment(
        self, organization_id: UUID, deployment_id: UUID
    ) -> Deployment | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, environment_id, agent_id, "
                    "agent_version_id, slug, status, endpoint, deployed_by, "
                    "deployed_at, rollback_from_id, created_at "
                    "FROM deployments WHERE id = :did AND organization_id = :oid"
                ),
{"did": deployment_id, "oid": organization_id},
            )
            row = result.fetchone()
            return self._row_to_deployment(row) if row is not None else None
        finally:
            await session.close()

    async def get_deployment_by_slug(
        self, organization_id: UUID, slug: str
    ) -> Deployment | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, environment_id, agent_id, "
                    "agent_version_id, slug, status, endpoint, deployed_by, "
                    "deployed_at, rollback_from_id, created_at "
                    "FROM deployments WHERE organization_id = :oid AND slug = :slug"
                ),
                {"oid": organization_id, "slug": slug},
            )
            row = result.fetchone()
            return self._row_to_deployment(row) if row is not None else None
        finally:
            await session.close()

    async def get_last_deployment(
        self,
        organization_id: UUID,
        environment_id: UUID,
        agent_id: UUID,
        exclude_version_id: UUID | None = None,
    ) -> Deployment | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, environment_id, agent_id, "
                    "agent_version_id, slug, status, endpoint, deployed_by, "
                    "deployed_at, rollback_from_id, created_at "
                    "FROM deployments "
                    "WHERE organization_id = :oid AND environment_id = :eid "
                    "AND agent_id = :aid AND status IN ('healthy', 'degraded') "
                    "AND (CAST(:xvid AS uuid) IS NULL OR agent_version_id <> CAST(:xvid AS uuid)) "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {
                    "oid": organization_id,
                    "eid": environment_id,
                    "aid": agent_id,
                    "xvid": exclude_version_id,
                },
            )
            row = result.fetchone()
            return self._row_to_deployment(row) if row is not None else None
        finally:
            await session.close()

    async def create_deployment(
        self,
        organization_id: UUID,
        environment_id: UUID,
        agent_id: UUID,
        agent_version_id: UUID,
        slug: str,
        endpoint: str | None = None,
        deployed_by: UUID | None = None,
        rollback_from_id: UUID | None = None,
    ) -> Deployment:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO deployments (id, organization_id, environment_id, "
                    "agent_id, agent_version_id, slug, status, endpoint, deployed_by, "
                    "deployed_at, rollback_from_id) "
                    "VALUES (uuid_generate_v4(), :oid, :eid, :aid, :vid, :slug, "
                    "'pending', :endpoint, :by, NOW(), :rb) "
                    "RETURNING id, organization_id, environment_id, agent_id, "
                    "agent_version_id, slug, status, endpoint, deployed_by, "
                    "deployed_at, rollback_from_id, created_at"
                ),
                {
                    "oid": organization_id,
                    "eid": environment_id,
                    "aid": agent_id,
                    "vid": agent_version_id,
                    "slug": slug,
                    "endpoint": endpoint,
                    "by": deployed_by,
                    "rb": rollback_from_id,
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_deployment(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_deployment_status(
        self,
        organization_id: UUID,
        deployment_id: UUID,
        status: str,
        deployed_at: datetime | None = None,
    ) -> Deployment | None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE deployments SET status = :status, "
                    "deployed_at = COALESCE(:deployed_at, deployed_at) "
                    "WHERE id = :did AND organization_id = :oid"
                ),
                {
                    "status": status,
                    "deployed_at": deployed_at,
                    "did": deployment_id,
                    "oid": organization_id,
                },
            )
            await session.commit()
            return await self.get_deployment(organization_id, deployment_id)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

class PostgresWorkspaceRepository(WorkspaceRepository):
    """Espacios de trabajo (scoped por org)."""

    @staticmethod
    def _row_to_workspace(row) -> Workspace:
        return Workspace(
            id=row.id,
            organization_id=row.organization_id,
            name=row.name,
            slug=row.slug,
            description=row.description,
            status=WorkspaceStatus(row.status),
            created_by=row.created_by,
            created_at=row.created_at,
        )

    async def list_workspaces(self, organization_id: UUID) -> list[Workspace]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, slug, description, status, "
                    "created_by, created_at FROM workspaces "
                    "WHERE organization_id = :oid ORDER BY created_at ASC"
                ),
                {"oid": organization_id},
            )
            return [self._row_to_workspace(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_workspace(
        self, organization_id: UUID, workspace_id: UUID
    ) -> Workspace | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, slug, description, status, "
                    "created_by, created_at FROM workspaces "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": workspace_id, "oid": organization_id},
            )
            row = result.fetchone()
            return self._row_to_workspace(row) if row is not None else None
        finally:
            await session.close()

    async def get_workspace_by_slug(
        self, organization_id: UUID, slug: str
    ) -> Workspace | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, name, slug, description, status, "
                    "created_by, created_at FROM workspaces "
                    "WHERE organization_id = :oid AND slug = :slug"
                ),
                {"oid": organization_id, "slug": slug},
            )
            row = result.fetchone()
            return self._row_to_workspace(row) if row is not None else None
        finally:
            await session.close()

    async def create_workspace(
        self,
        organization_id: UUID,
        name: str,
        slug: str,
        description: str | None = None,
        created_by: UUID | None = None,
    ) -> Workspace:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO workspaces (id, organization_id, name, slug, "
                    "description, created_by) "
                    "VALUES (uuid_generate_v4(), :oid, :name, :slug, :desc, :by) "
                    "RETURNING id, organization_id, name, slug, description, status, "
                    "created_by, created_at"
                ),
                {"oid": organization_id, "name": name, "slug": slug, "desc": description, "by": created_by},
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_workspace(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_workspace(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        **fields,
    ) -> Workspace | None:
        allowed = {"name", "slug", "description", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        session = await get_async_session()
        try:
            if updates:
                set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                params = {"oid": organization_id, "wid": workspace_id, **updates}
                await session.execute(
                    text(
                        f"UPDATE workspaces SET {set_clauses}, updated_at = NOW() "
                        "WHERE id = :wid AND organization_id = :oid"
                    ),
                    params,
                )
                await session.commit()
            return await self.get_workspace(organization_id, workspace_id)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def workspace_counts(
        self, organization_id: UUID
    ) -> dict[UUID, dict[str, int]]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT w.id AS wid, "
                        "(SELECT COUNT(*) FROM agents a WHERE a.workspace_id = w.id) AS agents, "
                        "(SELECT COUNT(*) FROM knowledge_bases k WHERE k.workspace_id = w.id) AS kbs, "
                        "(SELECT COUNT(*) FROM connectors c WHERE c.workspace_id = w.id) AS connectors "
                        "FROM workspaces w WHERE w.organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
        finally:
            await session.close()
        return {
            row.wid: {"agents": int(row.agents), "kbs": int(row.kbs), "connectors": int(row.connectors)}
            for row in rows
        }
