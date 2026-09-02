# =============================================================================
# Organization Routes — Perfil, miembros y API keys
# =============================================================================
# Toda operación deriva la organización del TenantContext autenticado.
# organization_id en path/body NUNCA se confía: si difiere del contexto -> 403.
# =============================================================================
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from src.api.deps import (
    get_api_key_repo,
    get_membership_repo,
    get_organization_repo,
    get_user_repo,
)
from src.core.ports import (
    ApiKeyRepository,
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_INVITE_TTL = timedelta(days=7)
_INVITE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS organization_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(320) NOT NULL,
    role VARCHAR(20) NOT NULL
        CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


async def _ensure_invite_tables() -> None:
    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(text(_INVITE_TABLE_SQL))
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_org_invites_org_email "
                "ON organization_invites (organization_id, email)"
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _plan_limit_http(exc) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error_code": "plan_limit_reached",
            "message": str(exc),
            "resource": getattr(exc, "resource", "users"),
        },
    )


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _client_ip(request: Request) -> str | None:
    if request.client:
        return request.client.host
    return None


class UpdateOrganizationRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    ruc: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=100)


class InviteUserRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    role: str = Field(default="member", min_length=2, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Invalid email")
        return email


class AcceptInviteRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=200)


class AssignRoleRequest(BaseModel):
    role: str = Field(..., min_length=2, max_length=100)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["rag:read", "rag:write"])
    environment: Literal["live", "test"] = "live"

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        from src.platform.auth.scopes import InvalidApiKeyScope, canonicalize_scopes

        try:
            canonical = canonicalize_scopes(value)
        except InvalidApiKeyScope as exc:
            raise ValueError(str(exc)) from exc
        if not canonical:
            raise ValueError("At least one scope is required")
        return canonical


@router.get("", summary="Perfil de la organización autenticada")
async def get_organization(
    request: Request,
    repo: OrganizationRepository = Depends(get_organization_repo),
):
    from src.api.security import resolve_organization

    organization_id = resolve_organization(request)
    organization = await repo.get_by_id(organization_id)
    if organization is None:
        raise HTTPException(404, "Organization not found")
    return {
        "id": str(organization.id),
        "name": organization.name,
        "company_name": organization.company_name,
        "ruc": organization.ruc,
        "phone": organization.phone,
        "email": organization.email,
        "country": organization.country,
        "status": organization.status.value,
        "created_at": organization.created_at.isoformat(),
    }


@router.put("", summary="Actualizar datos de la organización autenticada")
async def update_organization(
    body: UpdateOrganizationRequest,
    request: Request,
    repo: OrganizationRepository = Depends(get_organization_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "org:write")
    fields = body.model_dump(exclude_none=True)
    organization = await repo.update_organization(ctx.organization_id, **fields)
    await _audit().write(
        ctx,
        "organization.updated",
        "organization",
        ctx.organization_id,
        ip_address=_client_ip(request),
    )
    return {"id": str(organization.id), "name": organization.name, **fields}


# ---------------------------------------------------------------------------
# Miembros (users + memberships)
# ---------------------------------------------------------------------------


@router.get("/members", summary="Listar miembros y sus roles")
async def list_members(
    request: Request,
    repo: MembershipRepository = Depends(get_membership_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "users:read")
    members = await repo.list_members(ctx.organization_id)
    return {
        "members": [
            {
                "user_id": str(user.id),
                "email": user.email,
                "external_id": user.external_id,
                "role": role.name,
                "is_system_role": role.is_system,
            }
            for user, role in members
        ],
        "count": len(members),
    }


@router.post("/members/{user_id}/role", summary="Asignar rol a un miembro")
async def assign_role(
    user_id: str,
    body: AssignRoleRequest,
    request: Request,
    repo: MembershipRepository = Depends(get_membership_repo),
    users: UserRepository = Depends(get_user_repo),
):
    from src.platform.billing.plan_limits import (
        PlanLimitError,
        check_resource_limit,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "users:write")
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "user_id must be a valid UUID")

    # Anti cross-organization: el usuario objetivo debe pertenecer a ESTA org.
    target = await users.get_by_id(uid, ctx.organization_id)
    if target is None:
        raise HTTPException(404, "User not found in this organization")

    # Límite de miembros del plan: solo aplica a miembros NUEVOS.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM memberships "
                    "WHERE organization_id = :org AND user_id = :uid"
                ),
                {"org": ctx.organization_id, "uid": uid},
            )
        ).scalar()
    finally:
        await session.close()
    if not existing:
        try:
            await check_resource_limit(ctx.organization_id, "users")
        except PlanLimitError as exc:
            raise HTTPException(409, str(exc)) from None

    # Proteger el rol owner: solo un owner puede transferir/otorgar owner.
    if body.role == "owner" and "owner" not in ctx.roles:
        raise HTTPException(403, "Only an owner can assign the owner role")

    # El rol debe existir (sistema o custom de la organización).
    from src.platform.rbac.repo import role_name_exists

    if not await role_name_exists(body.role, ctx.organization_id):
        raise HTTPException(400, f"Unknown role: {body.role}")

    membership = await repo.assign_role(ctx.organization_id, uid, body.role)
    await _audit().write(
        ctx,
        "member.role_assigned",
        "user",
        uid,
        ip_address=_client_ip(request),
        metadata={"role": body.role},
    )
    return {"user_id": str(uid), "role": body.role, "membership_id": str(membership.id)}


@router.delete("/members/{user_id}", summary="Remover miembro")
async def remove_member(
    user_id: str,
    request: Request,
    repo: MembershipRepository = Depends(get_membership_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "users:write")
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "user_id must be a valid UUID")

    if ctx.user_id == uid:
        raise HTTPException(400, "You cannot remove yourself")

    target = await get_user_repo().get_by_id(uid, ctx.organization_id)
    if target is None:
        raise HTTPException(404, "User not found in this organization")

    await repo.remove_member(ctx.organization_id, uid)
    await _audit().write(
        ctx,
        "member.removed",
        "user",
        uid,
        ip_address=_client_ip(request),
    )
    return {"status": "removed", "user_id": str(uid)}


# ---------------------------------------------------------------------------
# Invitaciones (el token se revela una sola vez; no hay mailer)
# ---------------------------------------------------------------------------


@router.post("/invites", summary="Invitar a un usuario por email", status_code=201)
async def create_invite(body: InviteUserRequest, request: Request):
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.billing.plan_limits import PlanLimitError, check_resource_limit
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "users:write")
    if body.role == "owner" and "owner" not in ctx.roles:
        raise HTTPException(403, "Only an owner can invite another owner")
    from src.platform.rbac.repo import role_name_exists

    if not await role_name_exists(body.role, ctx.organization_id):
        raise HTTPException(400, f"Unknown role: {body.role}")
    try:
        await check_resource_limit(ctx.organization_id, "users")
    except PlanLimitError as exc:
        raise _plan_limit_http(exc) from None

    await _ensure_invite_tables()
    session = await get_async_session()
    try:
        existing_member = (
            await session.execute(
                text(
                    "SELECT 1 FROM memberships m "
                    "JOIN users u ON u.id = m.user_id "
                    "WHERE m.organization_id = :org AND lower(u.email) = :email"
                ),
                {"org": ctx.organization_id, "email": body.email},
            )
        ).scalar()
        if existing_member:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "invite_conflict",
                    "message": "That email already belongs to this organization.",
                },
            )
        pending = (
            await session.execute(
                text(
                    "SELECT 1 FROM organization_invites "
                    "WHERE organization_id = :org AND lower(email) = :email "
                    "AND accepted_at IS NULL AND expires_at > NOW()"
                ),
                {"org": ctx.organization_id, "email": body.email},
            )
        ).scalar()
        if pending:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "invite_conflict",
                    "message": "A pending invite already exists for this email.",
                },
            )
        invite_id = uuid4()
        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + _INVITE_TTL
        await session.execute(
            text(
                "INSERT INTO organization_invites "
                "(id, organization_id, email, role, token_hash, expires_at, "
                "created_by_user_id) "
                "VALUES (:id, :org, :email, :role, :hash, :exp, :uid)"
            ),
            {
                "id": invite_id,
                "org": ctx.organization_id,
                "email": body.email,
                "role": body.role,
                "hash": _hash_invite_token(raw_token),
                "exp": expires_at,
                "uid": ctx.user_id,
            },
        )
        await session.commit()
        # Email real de la invitación (fail-soft si SMTP no está configurado).
        from src.platform.customer_success.customer_success import send_invite_email

        org_row = (
            await session.execute(
                text("SELECT COALESCE(company_name, name) FROM organizations WHERE id = :oid"),
                {"oid": ctx.organization_id},
            )
        ).scalar()
        email_sent = await send_invite_email(
            ctx.organization_id,
            body.email,
            raw_token,
            org_row or "tu organización",
            body.role,
        )
        await session.execute(
            text(
                "UPDATE organization_invites SET email_sent = :sent, "
                "delivery_status = :status WHERE id = :invite_id"
            ),
            {
                "sent": email_sent,
                "status": "delivered" if email_sent else "skipped_no_smtp",
                "invite_id": invite_id,
            },
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    await _audit().write(
        ctx,
        "invite.created",
        "invite",
        invite_id,
        ip_address=_client_ip(request),
        metadata={"email": body.email, "role": body.role},
    )
    return {
        "id": str(invite_id),
        "email": body.email,
        "role": body.role,
        "status": "pending",
        "expires_at": expires_at.isoformat(),
        "token": raw_token,
        "email_sent": email_sent,
    }


@router.get("/invites", summary="Listar invitaciones pendientes de la organización")
async def list_invites(request: Request):
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "users:read")
    await _ensure_invite_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, email, role, expires_at, accepted_at, created_at "
                    "FROM organization_invites "
                    "WHERE organization_id = :org "
                    "ORDER BY created_at DESC "
                    "LIMIT 100"
                ),
                {"org": ctx.organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    invites = []
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.accepted_at:
            status = "accepted"
        elif row.expires_at < now:
            status = "expired"
        else:
            status = "pending"
        invites.append(
            {
                "id": str(row.id),
                "email": row.email,
                "role": row.role,
                "status": status,
                "expires_at": row.expires_at.isoformat(),
                "created_at": row.created_at.isoformat(),
            }
        )
    return {"invites": invites, "count": len(invites)}


@router.post("/invites/{invite_id}/accept", summary="Aceptar una invitación")
async def accept_invite(
    invite_id: str,
    body: AcceptInviteRequest,
    request: Request,
    users: UserRepository = Depends(get_user_repo),
    members: MembershipRepository = Depends(get_membership_repo),
):
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.session import encrypt_session
    from src.platform.billing.plan_limits import PlanLimitError, check_resource_limit
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "org:read")
    try:
        iid = UUID(invite_id)
    except ValueError:
        raise HTTPException(404, "Invite not found")

    current = await users.get_by_id(ctx.user_id, ctx.organization_id) if ctx.user_id else None
    if current is None or not current.email:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "authentication_required",
                "message": "Sign up or log in with the invited email to accept.",
            },
        )
    actor_email = current.email.strip().lower()

    await _ensure_invite_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, email, role, token_hash, "
                    "expires_at, accepted_at FROM organization_invites "
                    "WHERE id = :id"
                ),
                {"id": iid},
            )
        ).fetchone()
    finally:
        await session.close()

    if row is None:
        raise HTTPException(404, "Invite not found")
    expected = row.token_hash
    given = _hash_invite_token(body.token)
    if not secrets.compare_digest(expected, given):
        raise HTTPException(404, "Invite not found")
    if row.accepted_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "invite_conflict",
                "message": "This invite was already accepted.",
            },
        )
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invite_expired",
                "message": "This invite has expired.",
            },
        )
    if actor_email != row.email.strip().lower():
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "invite_email_mismatch",
                "message": "This invite was sent to a different email.",
            },
        )

    try:
        await check_resource_limit(row.organization_id, "users")
    except PlanLimitError as exc:
        raise _plan_limit_http(exc) from None

    await members.assign_role(row.organization_id, current.id, row.role)

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organization_invites SET accepted_at = NOW() "
                "WHERE id = :id AND accepted_at IS NULL"
            ),
            {"id": iid},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    # Audit as the inviting org (membership just created).
    from src.core.domain.entities import TenantContext

    invite_ctx = TenantContext(
        tenant_id=row.organization_id,
        user_id=current.id,
        roles=ctx.roles,
        permissions=ctx.permissions,
        scopes=ctx.scopes,
        auth_type=ctx.auth_type,
    )
    await _audit().write(
        invite_ctx,
        "invite.accepted",
        "invite",
        iid,
        ip_address=_client_ip(request),
        metadata={"email": row.email, "role": row.role},
    )
    access_token = encrypt_session(current.id, row.organization_id)
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "role": row.role,
        "status": "accepted",
        "access_token": access_token,
        "token_type": "Bearer",
    }


@router.get("/roles", summary="Roles disponibles (sistema)")
async def list_roles(
    request: Request,
    repo: MembershipRepository = Depends(get_membership_repo),
):
    from src.platform.rbac.policy import require_permission

    require_permission(request, "users:read")
    roles = await repo.list_system_roles()
    return {
        "roles": [
            {"name": r.name, "description": r.description, "is_system": r.is_system}
            for r in roles
        ]
    }


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


@router.get("/api-keys", summary="Listar API keys de la organización")
async def list_api_keys(
    request: Request,
    repo: ApiKeyRepository = Depends(get_api_key_repo),
):
    from src.platform.auth.scopes import api_key_environment
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "apikeys:read")
    keys = await repo.list_keys(ctx.organization_id)
    return {
        "keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "prefix": k.key_prefix,
                "environment": api_key_environment(k.key_prefix),
                "scopes": k.scopes,
                "is_active": k.is_active,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "created_at": k.created_at.isoformat(),
            }
            for k in keys
        ],
        "count": len(keys),
    }


@router.post("/api-keys", summary="Crear API key (devuelve el token UNA sola vez)")
async def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
):
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "apikeys:write")
    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    token = await billing.create_api_key(
        ctx.organization_id,
        name=body.name,
        scopes=body.scopes,
        created_by=ctx.user_id,
        environment=body.environment,
    )
    await _audit().write(
        ctx,
        "apikey.created",
        "api_key",
        ip_address=_client_ip(request),
        metadata={
            "name": body.name,
            "scopes": body.scopes,
            "environment": body.environment,
        },
    )
    key_row = await PostgresApiKeyRepository().get_by_hash(
        __import__("hashlib").sha256(token.encode()).hexdigest()
    )
    return {
        "token": token,
        "key_id": str(key_row.id) if key_row else None,
        "name": body.name,
        "scopes": body.scopes,
        "environment": body.environment,
        "message": "Save this token now — it will not be shown again.",
    }


@router.delete("/api-keys/{key_id}", summary="Revocar API key")
async def revoke_api_key(
    key_id: str,
    request: Request,
    repo: ApiKeyRepository = Depends(get_api_key_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "apikeys:write")
    try:
        kid = UUID(key_id)
    except ValueError:
        raise HTTPException(400, "key_id must be a valid UUID")

    # Anti cross-organization: solo se puede revocar una key de ESTA org.
    key = await repo.get_key(kid)
    if key is None or key.organization_id != ctx.organization_id:
        raise HTTPException(404, "API key not found")

    await repo.deactivate_key(kid)
    await _audit().write(
        ctx,
        "apikey.revoked",
        "api_key",
        kid,
        ip_address=_client_ip(request),
        metadata={"name": key.name},
    )
    return {"status": "revoked", "key_id": str(kid)}


class UpdateApiKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    ip_allowlist: list[str] | None = Field(
        default=None,
        description="IPs o CIDRs permitidas (vacío = sin restricción).",
    )
    rate_limit_per_minute: int | None = Field(
        default=None, ge=1, le=10000, description="Rate limit por key (null = sin límite)."
    )
    expires_at: datetime | None = None


@router.put("/api-keys/{key_id}", summary="Actualizar API key (allowlist/rate limit/expiry)")
async def update_api_key(
    key_id: str,
    body: UpdateApiKeyRequest,
    request: Request,
    repo: ApiKeyRepository = Depends(get_api_key_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "apikeys:write")
    try:
        kid = UUID(key_id)
    except ValueError:
        raise HTTPException(400, "key_id must be a valid UUID")

    key = await repo.get_key(kid)
    if key is None or key.organization_id != ctx.organization_id:
        raise HTTPException(404, "API key not found")

    fields = body.model_dump(exclude_none=True)
    await repo.update_key(ctx.organization_id, kid, **fields)
    await _audit().write(
        ctx,
        "apikey.updated",
        "api_key",
        kid,
        ip_address=_client_ip(request),
        metadata={"fields": list(fields.keys()), "name": key.name},
    )
    updated = await repo.get_key(kid)
    return {
        "key_id": str(kid),
        "name": updated.name if updated else key.name,
        "ip_allowlist": updated.ip_allowlist if updated else key.ip_allowlist,
        "rate_limit_per_minute": (
            updated.rate_limit_per_minute if updated else key.rate_limit_per_minute
        ),
        "expires_at": updated.expires_at if updated else key.expires_at,
    }


@router.post(
    "/api-keys/{key_id}/rotate",
    summary="Rotar API key (revoca la actual y emite una nueva)",
)
async def rotate_api_key(
    key_id: str,
    request: Request,
    repo: ApiKeyRepository = Depends(get_api_key_repo),
):
    from src.infrastructure.postgres.relational_db import PostgresApiKeyRepository
    from src.platform.billing.service import BillingService
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "apikeys:write")
    try:
        kid = UUID(key_id)
    except ValueError:
        raise HTTPException(400, "key_id must be a valid UUID")

    key = await repo.get_key(kid)
    if key is None or key.organization_id != ctx.organization_id:
        raise HTTPException(404, "API key not found")

    billing = BillingService(repo, PostgresApiKeyRepository())
    from src.platform.billing.service import generate_api_token

    new_token = generate_api_token("zent_sk_live")
    await repo.deactivate_key(kid)
    await repo.create_key(
        ctx.organization_id,
        new_token,
        name=key.name,
        scopes=list(key.scopes),
        created_by=ctx.user_id,
        expires_at=key.expires_at,
        ip_allowlist=key.ip_allowlist or None,
        rate_limit_per_minute=key.rate_limit_per_minute,
    )
    await _audit().write(
        ctx,
        "apikey.rotated",
        "api_key",
        kid,
        ip_address=_client_ip(request),
        metadata={"name": key.name, "scopes": list(key.scopes)},
    )
    return {
        "status": "rotated",
        "revoked_key_id": str(kid),
        "token": new_token,
        "name": key.name,
        "scopes": list(key.scopes),
    }


@router.get(
    "/api-keys/{key_id}/usage",
    summary="Uso de una API key (30d): requests, errores, tokens, costo",
)
async def api_key_usage(
    key_id: str,
    request: Request,
    days: int = 30,
    repo: ApiKeyRepository = Depends(get_api_key_repo),
):
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "apikeys:read")
    try:
        kid = UUID(key_id)
    except ValueError:
        raise HTTPException(400, "key_id must be a valid UUID")

    key = await repo.get_key(kid)
    if key is None or key.organization_id != ctx.organization_id:
        raise HTTPException(404, "API key not found")

    days = max(1, min(days, 365))
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COUNT(*) FILTER (WHERE status >= 400)::int AS errors, "
                    "COALESCE(SUM(tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(cost), 0)::float AS cost, "
                    "COALESCE(percentile_cont(0.95) WITHIN GROUP "
                    "(ORDER BY latency_ms), 0)::float AS p95, "
                    "MAX(created_at) AS last_request_at "
                    "FROM api_logs "
                    "WHERE api_key_id = :kid AND created_at > NOW() - "
                    "MAKE_INTERVAL(days => :days)"
                ),
                {"kid": kid, "days": days},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "key_id": str(kid),
        "name": key.name,
        "days": days,
        "requests": int(row.requests or 0),
        "errors": int(row.errors or 0),
        "tokens": int(row.tokens or 0),
        "cost": round(float(row.cost or 0.0), 6),
        "p95_ms": round(float(row.p95 or 0.0), 1),
        "last_request_at": (
            row.last_request_at.isoformat() if row.last_request_at else None
        ),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }
    return {"status": "updated", "key_id": str(kid)}

# ---------------------------------------------------------------------------
# Customer Success (tenant): onboarding, branding, reportes de uso
# ---------------------------------------------------------------------------
@router.get("/onboarding", summary="Checklist de onboarding de la organización")
async def tenant_onboarding(request: Request):
    from src.platform.customer_success.customer_success import onboarding_checklist
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "org:read")
    return await onboarding_checklist(ctx.organization_id)


class BrandingIn(BaseModel):
    branding: dict = Field(default_factory=dict)


@router.get("/branding", summary="Branding de la organización")
async def tenant_branding_get(request: Request):
    from src.platform.customer_success.customer_success import get_branding
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "org:read")
    return await get_branding(ctx.organization_id)


@router.put("/branding", summary="Guardar branding de la organización")
async def tenant_branding_put(body: BrandingIn, request: Request):
    from src.platform.customer_success.customer_success import set_branding
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "org:write")
    await set_branding(ctx.organization_id, body.branding)
    return {"status": "saved"}


class ReportSubscribeIn(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    frequency: str = Field(default="monthly", pattern="^(weekly|monthly)$")


@router.get("/reports", summary="Suscripciones a reportes de uso (tenant)")
async def tenant_reports_get(request: Request):
    from src.platform.customer_success.customer_success import list_report_subscriptions
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "usage:read")
    subs = await list_report_subscriptions(ctx.organization_id)
    return {"subscriptions": subs, "count": len(subs)}


@router.post("/reports", status_code=201, summary="Suscribir reporte de uso (tenant)")
async def tenant_reports_post(body: ReportSubscribeIn, request: Request):
    from src.platform.customer_success.customer_success import subscribe_report
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "usage:read")
    return await subscribe_report(ctx.organization_id, body.email, body.frequency)


@router.delete("/reports/{sub_id}", summary="Cancelar suscripción de reporte (tenant)")
async def tenant_reports_delete(sub_id: str, request: Request):
    from src.platform.customer_success.customer_success import unsubscribe_report
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "usage:read")
    ok = await unsubscribe_report(UUID(sub_id))
    if not ok:
        raise HTTPException(404, "Subscription not found")
    return {"status": "deleted"}
