# =============================================================================
# Portal Auth — signup / login / me (email+password, AES-256-GCM session)
# =============================================================================
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.infrastructure.auth_rate_limit import (
    clear_auth_failures,
    is_auth_blocked,
    record_auth_failure,
)
from src.infrastructure.billing_service import BillingService
from src.infrastructure.logging_config import get_logger
from src.infrastructure.passwords import hash_password, verify_password
from src.infrastructure.portal_session import encrypt_session
from src.infrastructure.relational_db import (
    PostgresBillingRepository,
    PostgresTenantRepository,
    PostgresUserRepository,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_billing() -> BillingService:
    return BillingService(PostgresBillingRepository())


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


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


def _client_ip(request: Request) -> str:
    from src.config import get_settings

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

    tenant_id = uuid4()
    tenant_name = body.company_name.strip()
    tenant_repo = PostgresTenantRepository()
    api_key_hash = hashlib.sha256(f"auto-{tenant_id}".encode()).hexdigest()
    await tenant_repo.create_tenant(tenant_id, tenant_name, api_key_hash)
    await tenant_repo.update_tenant(
        tenant_id,
        company_name=tenant_name,
        email=body.email,
    )

    email_hash = hashlib.sha256(body.email.encode()).hexdigest()
    password_hash = hash_password(body.password)
    user = await user_repo.create_default_user(
        tenant_id,
        email_hash,
        email=body.email,
        password_hash=password_hash,
    )

    try:
        subscription, _api_token = await billing.create_trial_subscription(tenant_id)
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc

    access_token = encrypt_session(user.id, tenant_id)
    await clear_auth_failures(email_key, ip_key)

    logger.info(
        "Portal signup",
        tenant_id=str(tenant_id),
        email=body.email,
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "tenant_id": str(tenant_id),
        "company_name": tenant_name,
        "email": body.email,
        "subscription_id": str(subscription.id),
        "status": "trialing",
        "trial_end": subscription.trial_end.isoformat() if subscription.trial_end else None,
        "message": "Trial created. Use access_token as Authorization Bearer.",
    }


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
    if user is None or not verify_password(body.password, user.password_hash):
        await record_auth_failure(email_key, ip_key)
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "invalid_credentials",
                "message": "Invalid email or password.",
            },
        )

    access_token = encrypt_session(user.id, user.tenant_id)
    await clear_auth_failures(email_key, ip_key)

    tenant_repo = PostgresTenantRepository()
    tenant = await tenant_repo.get_by_id(user.tenant_id)
    company = (tenant.company_name or tenant.name) if tenant else ""

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "tenant_id": str(user.tenant_id),
        "company_name": company,
        "email": user.email or body.email,
    }


@router.post("/logout", summary="Revocar la sesión portal actual")
async def logout(request: Request):
    """Invalida la sesión en el registro server-side (revocación real)."""
    from src.infrastructure.portal_session import revoke_session

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        await revoke_session(auth_header[7:])
    return {"status": "logged_out"}


@router.get("/me", summary="Perfil de la sesión portal actual")
async def me(request: Request):
    ctx = getattr(request.state, "billing_context", None)
    if ctx is None:
        raise HTTPException(401, "Not authenticated")

    tenant_repo = PostgresTenantRepository()
    tenant = await tenant_repo.get_by_id(ctx.tenant_id)
    user_repo = PostgresUserRepository()
    user = None
    if ctx.user_id is not None:
        user = await user_repo.get_by_id(ctx.user_id, ctx.tenant_id)
    if user is None:
        user = await user_repo.get_any_user(ctx.tenant_id)

    return {
        "tenant_id": str(ctx.tenant_id),
        "company_name": (tenant.company_name or tenant.name) if tenant else "",
        "email": user.email if user else None,
        "user_id": str(user.id) if user else None,
        "role": user.role if user else None,
        "plan_name": ctx.plan_name,
        "status": ctx.status.value,
        "auth_type": ctx.auth_type,
    }
