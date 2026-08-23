# =============================================================================
# Organization Routes — Perfil, miembros y API keys
# =============================================================================
# Toda operación deriva la organización del TenantContext autenticado.
# organization_id en path/body NUNCA se confía: si difiere del contexto -> 403.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

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
    role: str = Field(default="member", pattern=r"^(owner|admin|member|viewer)$")


class AssignRoleRequest(BaseModel):
    role: str = Field(..., pattern=r"^(owner|admin|member|viewer)$")


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["rag:read", "rag:write"])

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
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "apikeys:read")
    keys = await repo.list_keys(ctx.organization_id)
    return {
        "keys": [
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
    )
    await _audit().write(
        ctx,
        "apikey.created",
        "api_key",
        ip_address=_client_ip(request),
        metadata={"name": body.name, "scopes": body.scopes},
    )
    return {
        "token": token,
        "name": body.name,
        "scopes": body.scopes,
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
