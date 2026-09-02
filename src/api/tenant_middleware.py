# =============================================================================
# Tenant Middleware — Autenticación + Resolución de TenantContext
# =============================================================================
# PRINCIPIO DE SEGURIDAD (cross-tenant leakage prevention):
#
#   1. El tenant (organization_id) se deriva EXCLUSIVAMENTE de la identidad
#      autenticada: hash SHA-256 del API key o sesión portal AES-256-GCM.
#   2. NUNCA se confía en X-Organization-Id, X-User-Id, X-User-Role ni en
#      organization_id del body. Si esos valores llegan y difieren del
#      contexto autenticado, la request recibe 403 (nunca se ignora en
#      silencio para writes).
#   3. El TenantContext resultante (tenant_id, user_id, roles, permissions)
#      se publica en request.state y en un ContextVar para que TODAS las
#      capas (API, RAG, Vector Store, SQL, Connectors, Usage, Billing,
#      Audit) lo consuman sin re-derivar identidad.
# =============================================================================
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.core.config import get_settings
from src.core.domain.entities import TenantContext
from src.infrastructure.observability.logging_config import get_logger, set_trace_context
from src.platform.billing.service import (
    PUBLIC_PATHS,
    BillingService,
    TokenValidationError,
)
from src.platform.tenants.context import set_tenant_context

logger = get_logger(__name__)

_billing_service: BillingService | None = None
_membership_repo = None
_user_repo = None

# Exact public paths beyond PUBLIC_PATHS
_PUBLIC_BILLING_GET = {"/api/v1/billing/plans"}
_PUBLIC_BILLING_POST = {"/api/v1/billing/subscription/create-trial"}
_PUBLIC_AUTH_POST = {
    "/api/v1/auth/login",
    "/api/v1/auth/signup",
    "/api/v1/auth/platform/login",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
}
# Google redirect: identidad sale del state HMAC, no del Bearer.
_PUBLIC_OAUTH_GET = {"/api/v1/connectors/oauth/drive/callback"}
# SSO: la identidad sale del state HMAC, no del Bearer.
# Share links públicos: el token es la autorización.
_PUBLIC_SHARE_GET = {"/api/v1/share/agents"}
_PUBLIC_SSO_GET = {
    "/api/v1/auth/sso/start",
    "/api/v1/auth/sso/callback",
}
# Webhook de pagos (stripe-like): la firma es la autorización.
_PUBLIC_PAYMENTS_POST = {"/api/v1/payments/webhook"}

# Dev-only SQL admin (not prompt management)
_ADMIN_SQL_PREFIXES = (
    "/api/v1/admin/tables",
    "/api/v1/admin/sql",
)


def get_billing_service() -> BillingService:
    global _billing_service
    if _billing_service is None:
        from src.infrastructure.postgres.relational_db import (
            PostgresApiKeyRepository,
            PostgresBillingRepository,
        )
        _billing_service = BillingService(
            PostgresBillingRepository(), PostgresApiKeyRepository()
        )
    return _billing_service


def _get_membership_repo():
    global _membership_repo
    if _membership_repo is None:
        from src.infrastructure.postgres.relational_db import (
            PostgresMembershipRepository,
        )
        _membership_repo = PostgresMembershipRepository()
    return _membership_repo


def _get_user_repo():
    global _user_repo
    if _user_repo is None:
        from src.infrastructure.postgres.relational_db import (
            PostgresUserRepository,
        )
        _user_repo = PostgresUserRepository()
    return _user_repo


def _is_public(path: str, method: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if method == "GET" and path in _PUBLIC_BILLING_GET:
        return True
    if method == "POST" and path in _PUBLIC_BILLING_POST:
        return True
    if method == "POST" and path in _PUBLIC_AUTH_POST:
        return True
    if method == "GET" and path in _PUBLIC_OAUTH_GET:
        return True
    if method == "GET" and path.startswith("/api/v1/share/agents/"):
        return True
    # Dev portal público: status y changelog sin auth.
    if method == "GET" and path.startswith("/api/v1/dev/"):
        return True
    if method == "GET" and (
        path in _PUBLIC_SSO_GET
        or path == "/api/v1/auth/sso/callback"
        or (path.startswith("/api/v1/auth/sso/") and path.endswith("/start"))
    ):
        return True
    # SCIM: el bearer es el token SCIM de la org (validado en la ruta).
    if path.startswith("/api/v1/scim/v2/"):
        return True
    # Webhooks de billing: públicos; la ÚNICA protección es la firma
    # criptográfica verificada dentro de la ruta.
    if method == "POST" and path.startswith("/api/v1/billing/webhooks/"):
        return True
    if method == "POST" and path.startswith("/api/v1/payments/webhook"):
        return True
    if path.startswith("/api/v1/embed/"):
        return True
    if path == "/embed.js" or path.startswith("/embed/"):
        return True
    return False


def _is_admin_sql(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _ADMIN_SQL_PREFIXES)


async def _roles_permissions_for_user(
    user_id, organization_id
) -> tuple[frozenset[str], frozenset[str]]:
    """Roles y permisos del usuario desde memberships + role_permissions."""
    memberships = _get_membership_repo()
    try:
        roles = await memberships.get_user_roles(user_id, organization_id)
        if not roles:
            return frozenset(), frozenset()
        permissions = await memberships.get_role_permissions([r.id for r in roles])
        return (
            frozenset(r.name for r in roles),
            frozenset(p.code for p in permissions),
        )
    except Exception as exc:
        logger.warning(
            "Failed to resolve roles/permissions; denying elevated roles",
            error=str(exc),
        )
        return frozenset(), frozenset()


def _permissions_for_scopes(scopes: list[str]) -> frozenset[str]:
    """API keys: cada scope del allowlist se traduce a permisos RBAC."""
    from src.platform.auth.scopes import scope_to_permissions

    return scope_to_permissions(scopes or [])


class TenantMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        method = request.method.upper()

        # CORS preflight
        if method == "OPTIONS":
            return await call_next(request)

        if _is_public(path, method):
            return await call_next(request)

        settings = get_settings()
        if _is_admin_sql(path) and not settings.RAG_ADMIN_ENABLED:
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "admin_disabled",
                    "message": "Admin SQL endpoints are disabled. Set RAG_ADMIN_ENABLED=true for local use.",
                },
            )

        # /metrics: protegido. Token compartido si está configurado; si no,
        # solo accesible desde loopback (desarrollo local).
        if path == "/metrics":
            if settings.METRICS_TOKEN is not None:
                provided = request.headers.get("Authorization", "")
                if provided != f"Bearer {settings.METRICS_TOKEN.get_secret_value()}":
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error_code": "metrics_unauthorized",
                            "message": "Scrape token required for /metrics",
                        },
                    )
                return await call_next(request)
            client_ip = request.client.host if request.client else ""
            if client_ip not in ("127.0.0.1", "::1", "testclient"):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error_code": "metrics_unauthorized",
                        "message": "Metrics endpoint is not public",
                    },
                )
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error_code": "missing_token",
                    "message": "Authorization: Bearer <token> is required",
                },
            )

        token = auth_header[7:]
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
                return JSONResponse(
                    status_code=401,
                    content={"error_code": "invalid_session", "message": str(exc)},
                )
            if session.typ == "platform":
                if not await session_is_active(session.sid):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error_code": "session_revoked",
                            "message": "Session has been revoked. Log in again.",
                        },
                    )
                header_org = request.headers.get("X-Organization-Id", "")
                if header_org:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error_code": "organization_mismatch",
                            "message": "Platform admin cannot assume a tenant via X-Organization-Id",
                        },
                    )
                header_user = request.headers.get("X-User-Id", "")
                if header_user and session.user_id is not None:
                    try:
                        from uuid import UUID as _UUID

                        if _UUID(header_user) != session.user_id:
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "error_code": "user_mismatch",
                                    "message": "X-User-Id does not match the authenticated user",
                                },
                            )
                    except ValueError:
                        return JSONResponse(
                            status_code=400,
                            content={
                                "error_code": "invalid_user_header",
                                "message": "X-User-Id must be a valid UUID",
                            },
                        )
                from src.platform.rbac.repo import get_platform_roles_for_user

                platform_roles, platform_permissions = (
                    await get_platform_roles_for_user(session.user_id)
                    if session.user_id is not None
                    else (["read_only"], set())
                )
                elevated = bool(
                    set(platform_roles)
                    & {"super_admin", "platform_admin"}
                )
                tenant_ctx = TenantContext(
                    tenant_id=None,
                    user_id=session.user_id,
                    roles=frozenset(platform_roles or {"read_only"}),
                    permissions=frozenset(platform_permissions),
                    scopes=frozenset({"admin:*"}) if elevated else frozenset(),
                    auth_type="platform_session",
                )
                request.state.tenant_context = tenant_ctx
                request.state.billing_context = None
                request.state.organization_id = "platform"
                set_tenant_context(tenant_ctx)
                set_trace_context(
                    organization_id="platform",
                    user_id=str(session.user_id),
                )
                try:
                    response = await call_next(request)
                finally:
                    from src.platform.tenants.context import clear_tenant_context

                    clear_tenant_context()
                return response

        billing = get_billing_service()

        # Dev-only: token de administración local (admin/sql en desarrollo).
        if (
            settings.ENVIRONMENT in ("development", "test")
            and token == "rag_test_dev_token_for_local_testing_123"  # noqa: S105
        ):
            from uuid import UUID as _DevUUID

            from src.core.domain.entities import TenantContext as _TenantContext

            dev_org = _DevUUID("00000000-0000-0000-0000-000000000001")
            tenant_ctx = _TenantContext(
                tenant_id=dev_org,
                roles=frozenset({"super_admin"}),
                permissions=frozenset({"*"}),
                scopes=frozenset({"admin:*"}),
                auth_type="platform_session",
            )
            request.state.tenant_context = tenant_ctx
            request.state.organization_id = "00000000-0000-0000-0000-000000000001"
            set_tenant_context(tenant_ctx)
            set_trace_context(
                organization_id="00000000-0000-0000-0000-000000000001",
                user_id="dev",
            )
            try:
                response = await call_next(request)
            finally:
                from src.platform.tenants.context import clear_tenant_context

                clear_tenant_context()
            return response

        try:
            billing_ctx = await billing.validate_token(token)

            within_quota = await billing.check_quota(billing_ctx)
            if not within_quota:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "quota_exceeded",
                        "message": f"Monthly request quota ({billing_ctx.requests_limit}) exceeded. Upgrade your plan.",
                        "requests_limit": billing_ctx.requests_limit,
                    },
                )

            await billing.touch_token(billing_ctx.token_id)

            # -----------------------------------------------------------------
            # Resolver TenantContext (tenant_id, user_id, roles, permissions)
            # desde la identidad autenticada. NUNCA desde headers/body.
            # -----------------------------------------------------------------
            user_id = billing_ctx.user_id
            roles: frozenset[str] = frozenset()
            permissions: frozenset[str] = frozenset()

            if billing_ctx.auth_type == "portal_session":
                if user_id is None:
                    raise TokenValidationError(
                        "Session missing user identity", 401, "invalid_session"
                    )
                roles, permissions = await _roles_permissions_for_user(
                    user_id, billing_ctx.organization_id
                )
            else:
                # API key: permisos = scopes rag:*; usuario por defecto de la org.
                permissions = _permissions_for_scopes(billing_ctx.scopes)
                try:
                    default_user = await _get_user_repo().get_by_external_id(
                        billing_ctx.organization_id, "default-admin"
                    )
                    if default_user is None:
                        default_user = await _get_user_repo().get_any_user(
                            billing_ctx.organization_id
                        )
                    if default_user is not None:
                        user_id = default_user.id
                except Exception as exc:
                    logger.warning("Failed to resolve default user", error=str(exc))

            tenant_ctx = TenantContext(
                tenant_id=billing_ctx.organization_id,
                user_id=user_id,
                roles=roles,
                permissions=permissions,
                scopes=frozenset(billing_ctx.scopes or []),
                auth_type=billing_ctx.auth_type,
                subscription_id=billing_ctx.subscription_id,
                token_id=billing_ctx.token_id,
            )
            # Partner ecosystem: si la key es de un partner, propaga partner_id.
            if billing_ctx.token_id and "partner:*" in billing_ctx.scopes:
                try:
                    from sqlalchemy import text

                    from src.infrastructure.postgres.session import get_async_session

                    _s = await get_async_session()
                    try:
                        _pid = (
                            await _s.execute(
                                text(
                                    "SELECT partner_id FROM api_keys WHERE id = :kid"
                                ),
                                {"kid": billing_ctx.token_id},
                            )
                        ).scalar()
                    finally:
                        await _s.close()
                    if _pid:
                        object.__setattr__(tenant_ctx, "partner_id", _pid)
                    else:
                        logger.info("Partner key sin partner_id", key_id=str(billing_ctx.token_id))
                except Exception as exc:  # noqa: BLE001, S112
                    logger.warning("Partner ctx resolve failed", error=str(exc)[:150])

            # -----------------------------------------------------------------
            # ANTI-SPOOFING centralizado: si el cliente envía X-Organization-Id
            # o X-User-Id que no coinciden con la identidad autenticada,
            # 403 inmediato en TODA ruta autenticada (nunca ignorar en silencio).
            # -----------------------------------------------------------------
            header_org = request.headers.get("X-Organization-Id", "")
            if header_org:
                try:
                    from uuid import UUID as _UUID

                    if _UUID(header_org) != tenant_ctx.tenant_id:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error_code": "organization_mismatch",
                                "message": "X-Organization-Id does not match the authenticated organization",
                            },
                        )
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error_code": "invalid_organization_header",
                            "message": "X-Organization-Id must be a valid UUID",
                        },
                    )
            header_user = request.headers.get("X-User-Id", "")
            if header_user and tenant_ctx.user_id is not None:
                try:
                    from uuid import UUID as _UUID

                    if _UUID(header_user) != tenant_ctx.user_id:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error_code": "user_mismatch",
                                "message": "X-User-Id does not match the authenticated user",
                            },
                        )
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error_code": "invalid_user_header",
                            "message": "X-User-Id must be a valid UUID",
                        },
                    )

            from src.platform.auth.scopes import api_key_environment

            key_env = (
                api_key_environment(token)
                if billing_ctx.auth_type == "api_token"
                else "live"
            )
            # Hardening de API keys (PROMPT 06): IP allowlist + rate limit por key.
            if billing_ctx.auth_type == "api_token" and tenant_ctx.token_id is not None:
                enforcement = await _enforce_key_limits(
                    tenant_ctx.token_id, request.client.host if request.client else ""
                )
                if enforcement is not None:
                    return enforcement
            request.state.tenant_context = tenant_ctx
            request.state.billing_context = billing_ctx  # compat billing/quota
            request.state.organization_id = str(tenant_ctx.tenant_id)
            request.state.api_key_environment = key_env
            set_tenant_context(tenant_ctx)

            # Metering v2: rate limit por plan con burst (API tenant autenticada).
            if tenant_ctx.auth_type in ("api_token", "portal_session"):
                try:
                    from src.platform.metering.metering import enforce_plan_rate_limit

                    if not await enforce_plan_rate_limit(
                        tenant_ctx.organization_id, request.url.path
                    ):
                        return JSONResponse(
                            status_code=429,
                            content={
                                "error_code": "rate_limit_plan_exceeded",
                                "message": "Límite del plan excedido. Intenta de nuevo en un minuto.",
                            },
                        )
                except Exception:  # noqa: BLE001, S112
                    pass

            # Mantener el trace_id del request; solo fijar identidad real.
            set_trace_context(
                organization_id=str(tenant_ctx.tenant_id),
                user_id=str(tenant_ctx.user_id) if tenant_ctx.user_id else "anonymous",
            )
        except TokenValidationError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error_code": exc.error_code,
                    "message": str(exc),
                },
            )
        except Exception as exc:
            logger.error(
                "Tenant middleware error",
                error=str(exc),
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error_code": "TENANT_MIDDLEWARE_ERROR",
                    "message": "Internal error resolving identity. Reference the X-Trace-Id header for support.",
                },
            )

        try:
            response = await call_next(request)
        finally:
            from src.platform.tenants.context import clear_tenant_context

            clear_tenant_context()

        response.headers["X-Plan"] = billing_ctx.plan_name
        response.headers["X-Subscription-Status"] = billing_ctx.status.value
        if billing_ctx.auth_type == "api_token":
            response.headers["X-Zent-Environment"] = getattr(
                request.state, "api_key_environment", "live"
            )

        return response
async def _enforce_key_limits(key_id: UUID, client_ip: str):  # noqa: F821 (UUID importado arriba)
    """IP allowlist + rate limit por API key (fail-open ante errores internos)."""

    from src.platform.auth.key_limits import (
        check_key_ip_allowed,
        check_key_rate_limit,
        get_key_limits,
    )

    try:
        ip_allowlist, rate_limit = await get_key_limits(key_id)
        if ip_allowlist:
            from fastapi.responses import JSONResponse

            if not check_key_ip_allowed(ip_allowlist, client_ip):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error_code": "ip_not_allowed",
                        "message": f"IP {client_ip or 'desconocida'} no está en la allowlist de la API key",
                    },
                )
        if rate_limit:
            from fastapi.responses import JSONResponse

            allowed = await check_key_rate_limit(key_id, rate_limit)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "key_rate_limited",
                        "message": f"Rate limit de la API key excedido ({rate_limit}/min)",
                    },
                )
    except Exception:
        pass
    return None
