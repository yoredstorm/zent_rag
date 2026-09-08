# =============================================================================
# Portal Auth — signup / login / me (email+password, AES-256-GCM session)
# =============================================================================
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
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


def _session_response(payload: dict, typ: str) -> JSONResponse:
    """Respuesta de sesión con cookies HttpOnly (FASE 05) cuando está habilitado."""
    from src.core.config import get_settings
    from src.platform.auth.cookies import (
        set_csrf_cookie,
        set_platform_session_cookie,
        set_portal_session_cookie,
    )

    settings = get_settings()
    resp = JSONResponse(payload)
    if settings.SESSION_COOKIE_ENABLED:
        set_csrf_cookie(resp)
        if typ == "portal":
            set_portal_session_cookie(resp, payload["access_token"])
        else:
            set_platform_session_cookie(resp, payload["access_token"])
    return resp


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

    from src.infrastructure.postgres.relational_db import PostgresWorkspaceRepository
    from src.platform.workspaces.context import set_active_workspace
    from src.platform.workspaces.service import ensure_demo_workspace

    demo_ws = await ensure_demo_workspace(
        PostgresWorkspaceRepository(), organization_id, created_by=user.id
    )
    await set_active_workspace(organization_id, user.id, demo_ws.id)
    try:
        from src.verticals.demo_farmacia.provisioning import provision_demo_kb

        await provision_demo_kb(organization_id, workspace_id=demo_ws.id)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Demo provisioning skipped on signup",
            organization_id=str(organization_id),
            exc_info=True,
        )

    access_token = encrypt_session(user.id, organization_id)
    await clear_auth_failures(email_key, ip_key)

    logger.info(
        "Portal signup",
        organization_id=str(organization_id),
        email=body.email,
    )
    return _session_response(
        {
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
        },
        "portal",
    )


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

    return _session_response(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "organization_id": str(user.organization_id),
            "company_name": company,
            "email": user.email or body.email,
        },
        "portal",
    )


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

    # FASE 07: si el platform admin tiene MFA habilitado, devolver desafío.
    from src.platform.auth.mfa import mfa_enabled

    if await mfa_enabled(user.id):
        challenge = encrypt_session(
            user.id, None, typ="mfa_challenge", ttl_hours=5 / 60
        )
        return {
            "mfa_required": True,
            "mfa_session": challenge,
            "token_type": "Bearer",
        }

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
    return _session_response(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "typ": "platform",
            "email": user.email or body.email,
        },
        "platform",
    )


@router.post("/logout", summary="Revocar la sesión portal actual")
async def logout(request: Request):
    """Invalida la sesión en el registro server-side (revocación real)."""
    from src.core.config import get_settings
    from src.platform.auth.cookies import (
        clear_platform_session_cookie,
        clear_portal_session_cookie,
    )
    from src.platform.auth.session import revoke_session

    settings = get_settings()

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        await revoke_session(auth_header[7:])
    resp = JSONResponse({"status": "logged_out"})
    if settings.SESSION_COOKIE_ENABLED:
        clear_portal_session_cookie(resp)
        clear_platform_session_cookie(resp)
    return resp


@router.post("/platform/mfa/enroll", summary="Iniciar enrollment TOTP (plataforma)")
async def platform_mfa_enroll(request: Request):
    """Genera un secreto TOTP pendiente de confirmación para el platform admin."""
    from src.platform.auth.mfa import (
        get_enrollment,
        new_totp_secret,
        otpauth_uri,
        save_enrollment,
    )

    ctx = _require_platform_session(request)
    if ctx is None or ctx.user_id is None:
        raise HTTPException(401, "Not authenticated")
    secret = new_totp_secret()
    await save_enrollment(ctx.user_id, secret)
    return {
        "secret": secret,
        "otpauth_url": otpauth_uri(ctx.user_id, secret),
        "confirmed": False,
        "existing": bool(await get_enrollment(ctx.user_id)),
    }


@router.post("/platform/mfa/verify", summary="Confirmar enrollment TOTP")
async def platform_mfa_verify(body: dict, request: Request):
    from src.platform.auth.mfa import confirm_enrollment

    ctx = _require_platform_session(request)
    if ctx is None or ctx.user_id is None:
        raise HTTPException(401, "Not authenticated")
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "code requerido")
    if await confirm_enrollment(ctx.user_id, code):
        return {"status": "enabled"}
    raise HTTPException(400, detail={"error_code": "mfa_code_invalid", "message": "Código TOTP inválido."})


@router.post("/platform/mfa/disable", summary="Deshabilitar MFA")
async def platform_mfa_disable(request: Request):
    from src.platform.auth.mfa import disable_mfa

    ctx = _require_platform_session(request)
    if ctx is None or ctx.user_id is None:
        raise HTTPException(401, "Not authenticated")
    await disable_mfa(ctx.user_id)
    return {"status": "disabled"}


@router.get("/platform/mfa/status", summary="Estado MFA del platform admin")
async def platform_mfa_status(request: Request):
    from src.platform.auth.mfa import get_enrollment

    ctx = _require_platform_session(request)
    if ctx is None or ctx.user_id is None:
        raise HTTPException(401, "Not authenticated")
    enrollment = await get_enrollment(ctx.user_id)
    return {
        "enabled": bool(enrollment and enrollment["enabled"]),
        "pending": bool(enrollment and not enrollment["enabled"]),
    }


@router.post("/platform/login/mfa", summary="Completar login de plataforma con TOTP")
async def platform_login_mfa(body: dict, request: Request):
    """Intercambia el desafío MFA por la sesión de plataforma completa."""
    from src.platform.auth.mfa import mfa_enabled, verify_totp
    from src.platform.auth.session import SessionTokenError, decrypt_session

    challenge = (body.get("mfa_session") or "").strip()
    code = (body.get("code") or "").strip()
    if not challenge or not code:
        raise HTTPException(400, "mfa_session y code requeridos")
    try:
        session = decrypt_session(challenge)
    except SessionTokenError as exc:
        raise HTTPException(400, detail={"error_code": "mfa_session_invalid", "message": str(exc)}) from None
    if session.typ != "mfa_challenge":
        raise HTTPException(400, "mfa_session inválido")
    if not await mfa_enabled(session.user_id):
        raise HTTPException(400, "MFA no habilitado")
    if not await verify_totp(session.user_id, code):
        await record_auth_failure(f"mfa:{session.user_id}", _client_ip(request))
        raise HTTPException(
            401,
            detail={"error_code": "mfa_code_invalid", "message": "Código TOTP inválido."},
        )
    await clear_auth_failures(f"mfa:{session.user_id}", _client_ip(request))
    import time as _time

    access_token = encrypt_session(
        session.user_id,
        None,
        typ="platform",
        assurance="totp",
        mfa_confirmed_at=int(_time.time()),
    )
    await _audit_login(
        organization_id=None,
        user_id=session.user_id,
        ip=_client_ip(request),
        action="auth.platform_login",
        email="platform-admin",
    )
    return _session_response(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "typ": "platform",
            "email": None,
        },
        "platform",
    )


@router.post("/platform/step-up", summary="Step-up: confirmar MFA para operación crítica")
async def platform_step_up(body: dict, request: Request):
    """Re-emite la sesión de plataforma con mfa_confirmed_at fresco (FASE 08)."""
    import time as _time

    from src.platform.auth.mfa import verify_totp
    from src.platform.auth.session import decrypt_session

    auth_header = request.headers.get("Authorization", "")
    code = (body.get("code") or "").strip()
    if not auth_header.startswith("Bearer ") or not code:
        raise HTTPException(400, "Authorization y code requeridos")
    try:
        current = decrypt_session(auth_header[7:])
    except Exception as exc:
        raise HTTPException(401, "Session inválida") from exc
    if current.typ != "platform":
        raise HTTPException(403, "Se requiere sesión de plataforma")
    if not await verify_totp(current.user_id, code):
        raise HTTPException(
            401,
            detail={"error_code": "mfa_code_invalid", "message": "Código TOTP inválido."},
        )
    access_token = encrypt_session(
        current.user_id,
        None,
        typ="platform",
        assurance="totp",
        mfa_confirmed_at=int(_time.time()),
    )
    return _session_response(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "typ": "platform",
            "step_up": True,
        },
        "platform",
    )


@router.post("/step-up", summary="Step-up tenant: MFA o contraseña")
async def tenant_step_up(body: dict, request: Request):
    import time as _time

    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.mfa import mfa_enabled, verify_totp
    from src.platform.auth.passwords import verify_password
    from src.platform.auth.session import decrypt_session

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        current = decrypt_session(auth_header[7:])
    except Exception as exc:
        raise HTTPException(401, "Session inválida") from exc
    if current.typ != "portal":
        raise HTTPException(403, "Se requiere sesión de portal")
    user = await PostgresUserRepository().get_by_id(current.user_id, current.organization_id)
    if user is None:
        raise HTTPException(401, "User not found")
    if await mfa_enabled(current.user_id):
        code = (body.get("code") or "").strip()
        if not await verify_totp(current.user_id, code):
            raise HTTPException(
                401,
                detail={"error_code": "mfa_code_invalid", "message": "Código TOTP inválido."},
            )
        assurance = "totp"
    else:
        password = body.get("password") or ""
        if not verify_password(password, user.password_hash):
            raise HTTPException(
                401,
                detail={"error_code": "password_invalid", "message": "Contraseña inválida."},
            )
        assurance = "password"
    access_token = encrypt_session(
        current.user_id,
        current.organization_id,
        typ="portal",
        assurance=assurance,
        mfa_confirmed_at=int(_time.time()),
    )
    return _session_response(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "step_up": True,
            "organization_id": str(current.organization_id),
        },
        "portal",
    )


def _require_platform_session(request: Request):
    """Devuelve la sesión de plataforma del request o None."""
    from src.platform.auth.session import SessionTokenError, decrypt_session

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    try:
        session = decrypt_session(auth_header[7:])
    except SessionTokenError:
        return None
    if session.typ != "platform":
        return None
    return session


@router.get("/impersonation/status", summary="Estado de la sesión impersonada (FASE 09)")
async def impersonation_status(request: Request):
    from src.platform.auth.cookies import PORTAL_SESSION_COOKIE
    from src.platform.auth.session import SessionTokenError, decrypt_session

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else request.cookies.get(PORTAL_SESSION_COOKIE)
    if not token:
        return {"impersonating": False}
    try:
        session = decrypt_session(token)
    except SessionTokenError:
        return {"impersonating": False}
    if session.typ != "portal" or session.imp_by is None:
        return {"impersonating": False}
    return {
        "impersonating": True,
        "target_organization_id": str(session.organization_id),
        "expires_at": session.exp,
        "impersonated_by": str(session.imp_by),
    }


@router.post("/impersonation/exit", summary="Salir de la impersonación (FASE 09)")
async def impersonation_exit(request: Request):
    """Revoca la sesión impersonada y limpia la cookie del portal."""

    from src.core.config import get_settings as _get_settings
    from src.platform.auth.cookies import (
        PORTAL_SESSION_COOKIE,
        clear_portal_session_cookie,
    )
    from src.platform.auth.session import SessionTokenError, decrypt_session, revoke_session

    settings = _get_settings()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else request.cookies.get(PORTAL_SESSION_COOKIE)
    if token:
        try:
            session = decrypt_session(token)
            if session.typ == "portal" and session.imp_by is not None:
                await revoke_session(token)
                await _audit_login(
                    organization_id=session.organization_id,
                    user_id=session.user_id,
                    ip=_client_ip(request),
                    action="auth.impersonation_exit",
                    email="impersonated",
                )
        except SessionTokenError:
            pass
    resp = JSONResponse({"status": "exited"})
    if settings.SESSION_COOKIE_ENABLED:
        clear_portal_session_cookie(resp)
    return resp


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

    payload = {
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
    from src.platform.workspaces.context import resolve_workspace

    try:
        ws = await resolve_workspace(request)
        payload["active_workspace_id"] = str(ws.id)
        payload["workspace_kind"] = getattr(ws.kind, "value", str(ws.kind))
    except HTTPException:
        payload["active_workspace_id"] = None
        payload["workspace_kind"] = None
    return payload
