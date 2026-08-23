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
_PUBLIC_AUTH_POST = {"/api/v1/auth/login", "/api/v1/auth/signup"}

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
    # Webhooks de billing: públicos; la ÚNICA protección es la firma
    # criptográfica verificada dentro de la ruta.
    if method == "POST" and path.startswith("/api/v1/billing/webhooks/"):
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
        billing = get_billing_service()

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

            request.state.tenant_context = tenant_ctx
            request.state.billing_context = billing_ctx  # compat billing/quota
            request.state.organization_id = str(tenant_ctx.tenant_id)
            set_tenant_context(tenant_ctx)

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

        return response
