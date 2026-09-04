# =============================================================================
# Portal Auth — signup / login / me (email+password, AES-256-GCM session)
# =============================================================================
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import (
    PostgresBillingRepository,
    PostgresMembershipRepository,
    PostgresOrganizationRepository,
    PostgresUserRepository,
)
from src.platform.auth.passwords import hash_password, verify_password
from src.platform.auth.rate_limit import (
    clear_auth_failures,
    is_auth_blocked,
    record_auth_failure,
)
from src.platform.auth.session import encrypt_session
from src.platform.billing.service import BillingService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


async def _audit_login(
    *,
    organization_id,
    user_id,
    ip: str,
    action: str,
    email: str,
) -> None:
    """Registra LOGIN en el audit log (tenant y plataforma)."""
    from uuid import UUID

    from src.core.domain.entities import TenantContext
    from src.infrastructure.postgres.relational_db import (
        PostgresAuditLogRepository,
    )
    from src.platform.audit.service import AuditLogService

    uid = UUID(str(user_id)) if user_id is not None else None
    ctx = TenantContext(
        tenant_id=UUID(str(organization_id)) if organization_id is not None else None,
        user_id=uid,
        roles=frozenset(),
        permissions=frozenset(),
        scopes=frozenset(),
        auth_type="portal_session" if organization_id is not None else "platform_session",
    )
    await AuditLogService(PostgresAuditLogRepository()).write_or_raise(
        ctx,
        action,
        "auth",
        uid,
        ip_address=ip,
        metadata={"email": email},
    )

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_billing() -> BillingService:
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
    )

    return BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())


class SignupRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        email = v.strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Invalid email")
        return email

    @field_validator("password")
    @classmethod
    def check_password_bytes(cls, v: str) -> str:
        # bcrypt trunca a 72 bytes: rechazar passwords que excedan ese límite
        # en bytes (multi-byte UTF-8) para no crear clases de equivalencia.
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return v


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=200)
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def check_password_bytes(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return v


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


def _client_ip(request: Request) -> str:
    from src.core.config import get_settings

    trusted = {
        p.strip()
        for p in get_settings().TRUSTED_PROXIES.split(",")
        if p.strip()
    }
    if trusted:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.post("/signup", summary="Crear trial con email y contraseña")
async def signup(
    body: SignupRequest,
    request: Request,
    billing: BillingService = Depends(get_billing),
):
    ip = _client_ip(request)
    email_key = f"email:{body.email}"
    ip_key = f"ip:{ip}"

    if await is_auth_blocked(email_key, ip_key):
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "auth_rate_limited",
                "message": "Too many attempts. Try again later.",
            },
        )

    user_repo = PostgresUserRepository()
    existing = await user_repo.get_by_email(body.email)
    if existing is not None:
        await record_auth_failure(email_key, ip_key)
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "email_taken",
                "message": "An account with this email already exists.",
            },
        )

    organization_id = uuid4()
    organization_name = body.company_name.strip()
    organization_repo = PostgresOrganizationRepository()
    await organization_repo.create_organization(organization_id, organization_name)
    await organization_repo.update_organization(
        organization_id,
        company_name=organization_name,
        email=body.email,
    )

    email_hash = hashlib.sha256(body.email.encode()).hexdigest()
    password_hash = hash_password(body.password)
    user = await user_repo.create_default_user(
        organization_id,
        email_hash,
        email=body.email,
        password_hash=password_hash,
    )

    # El creador es owner de la organización (memberships = fuente de verdad RBAC).
    membership_repo = PostgresMembershipRepository()
    await membership_repo.assign_role(organization_id, user.id, "owner")

    try:
        subscription, api_token = await billing.create_trial_subscription(organization_id)
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc

    access_token = encrypt_session(user.id, organization_id)
    await clear_auth_failures(email_key, ip_key)

    logger.info(
        "Portal signup",
        organization_id=str(organization_id),
        email=body.email,
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "organization_id": str(organization_id),
        "company_name": organization_name,
        "email": body.email,
        "subscription_id": str(subscription.id),
        "status": "trialing",
        "trial_end": subscription.trial_end.isoformat() if subscription.trial_end else None,
        "api_key": api_token,
        "message": "Trial created. Save api_key now — it will not be shown again.",
    }


@router.post("/forgot-password", summary="Solicitar reset de contraseña")
async def forgot_password(body: ForgotPasswordRequest):
    from src.core.config import get_settings
    from src.platform.auth.password_reset import issue_reset_token

    payload = {"status": "accepted"}
    user_repo = PostgresUserRepository()
    user = await user_repo.get_by_email(body.email)
    if user is not None and not user.is_platform_admin and user.organization_id:
        token = await issue_reset_token(user.id)
        if get_settings().ENVIRONMENT == "development":
            payload["dev_reset_token"] = token
    return payload


@router.post("/reset-password", summary="Aplicar reset de contraseña")
async def reset_password(body: ResetPasswordRequest):
    from src.platform.auth.password_reset import consume_reset_token

    try:
        user_id = await consume_reset_token(body.token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user_repo = PostgresUserRepository()
    await user_repo.set_password(user_id, hash_password(body.password))
    return {"status": "reset"}


@router.post("/login", summary="Login con email y contraseña")
async def login(body: LoginRequest, request: Request):
    ip = _client_ip(request)
    email_key = f"email:{body.email}"
    ip_key = f"ip:{ip}"

    if await is_auth_blocked(email_key, ip_key):
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "auth_rate_limited",
                "message": "Too many login attempts. Try again later.",
            },
        )

    user_repo = PostgresUserRepository()
    user = await user_repo.get_by_email(body.email)
    password_ok = user is not None and verify_password(
        body.password, user.password_hash
    )
    if user is not None and user.is_platform_admin and password_ok:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "platform_login_required",
                "message": "Este usuario es de Control Center. Entra en /admin/login",
            },
        )
    if (
        user is None
        or user.is_platform_admin
        or user.organization_id is None
        or not password_ok
    ):
        await record_auth_failure(email_key, ip_key)
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "invalid_credentials",
                "message": "Invalid email or password.",
            },
        )

    access_token = encrypt_session(user.id, user.organization_id)
    await clear_auth_failures(email_key, ip_key)

    await _audit_login(
        organization_id=user.organization_id,
        user_id=user.id,
        ip=ip,
        action="auth.login",
        email=user.email or body.email,
    )

    organization_repo = PostgresOrganizationRepository()
    organization = await organization_repo.get_by_id(user.organization_id)
    company = (organization.company_name or organization.name) if organization else ""

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "organization_id": str(user.organization_id),
        "company_name": company,
        "email": user.email or body.email,
    }


@router.post("/platform/login", summary="Login de platform admin (Control Center)")
async def platform_login(body: LoginRequest, request: Request):
    ip = _client_ip(request)
    email_key = f"email:{body.email}"
    ip_key = f"ip:{ip}"

    if await is_auth_blocked(email_key, ip_key):
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "auth_rate_limited",
                "message": "Too many login attempts. Try again later.",
            },
        )

    from src.infrastructure.postgres.relational_db import ensure_platform_admin_schema

    await ensure_platform_admin_schema()
    user_repo = PostgresUserRepository()
    user = await user_repo.get_by_email(body.email)
    if (
        user is None
        or not user.is_platform_admin
        or not verify_password(body.password, user.password_hash)
    ):
        await record_auth_failure(email_key, ip_key)
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "invalid_credentials",
                "message": "Invalid email or password.",
            },
        )

    access_token = encrypt_session(user.id, None, typ="platform")
    await clear_auth_failures(email_key, ip_key)
    logger.info("Platform admin login", user_id=str(user.id), email=body.email)

    # Compatibilidad legacy: admin con is_platform_admin pero sin roles de
    # plataforma (creados antes del RBAC 023, o vía SQL directo) → super_admin.
    # El baseline SQL 26 y la migración 023 hacen lo mismo para admins
    # preexistentes; el login lo aplica en runtime.
    from src.platform.rbac.repo import (
        assign_platform_role,
        get_platform_roles_for_user,
    )

    platform_roles, _ = await get_platform_roles_for_user(user.id)
    if not platform_roles:
        await assign_platform_role(user.id, "super_admin")

    await _audit_login(
        organization_id=None,
        user_id=user.id,
        ip=ip,
        action="auth.platform_login",
        email=user.email or body.email,
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "typ": "platform",
        "email": user.email or body.email,
    }


@router.post("/logout", summary="Revocar la sesión portal actual")
async def logout(request: Request):
    """Invalida la sesión en el registro server-side (revocación real)."""
    from src.platform.auth.session import revoke_session

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        await revoke_session(auth_header[7:])
    return {"status": "logged_out"}


@router.get("/me", summary="Perfil de la sesión portal actual")
async def me(request: Request):
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        raise HTTPException(401, "Not authenticated")
    if ctx.auth_type == "platform_session":
        return {
            "organization_id": None,
            "company_name": "Zent plataforma",
            "email": None,
            "user_id": str(ctx.user_id) if ctx.user_id else None,
            "role": "platform",
            "roles": sorted(ctx.roles),
            "permissions": sorted(ctx.permissions),
            "plan_name": None,
            "status": None,
            "auth_type": ctx.auth_type,
            "typ": "platform",
        }
    billing_ctx = getattr(request.state, "billing_context", None)

    organization_repo = PostgresOrganizationRepository()
    organization = await organization_repo.get_by_id(ctx.organization_id)
    user_repo = PostgresUserRepository()
    user = None
    if ctx.user_id is not None:
        user = await user_repo.get_by_id(ctx.user_id, ctx.organization_id)
    if user is None:
        user = await user_repo.get_any_user(ctx.organization_id)

    return {
        "organization_id": str(ctx.organization_id),
        "company_name": (organization.company_name or organization.name) if organization else "",
        "email": user.email if user else None,
        "user_id": str(user.id) if user else None,
        "role": user.role if user else None,
        "roles": sorted(ctx.roles),
        "permissions": sorted(ctx.permissions),
        "plan_name": billing_ctx.plan_name if billing_ctx else None,
        "status": billing_ctx.status.value if billing_ctx else None,
        "auth_type": ctx.auth_type,
    }
