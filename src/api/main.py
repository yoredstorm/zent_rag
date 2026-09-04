# =============================================================================
# main.py — FastAPI Entry Point — RAG-as-a-Service Platform
# =============================================================================
# Este es el punto de entrada principal de la API REST. Integra:
# 1. Inyección de dependencias (Clean Architecture)
# 2. Middleware de trazabilidad (trace_id en logs)
# 3. Métricas Prometheus expuestas en /metrics
# 4. Logs estructurados JSON para Loki (vía structlog)
# 5. Manejo de ciclo de vida (startup/shutdown graceful)
# 6. Seguridad CISO-grade (headers, CORS restrictivo, validación Pydantic)
# =============================================================================
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Asegura que src/ esté en el PYTHONPATH para imports absolutos
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from src.api.body_limit_middleware import BodySizeLimitMiddleware
from src.api.idempotency_middleware import IdempotencyMiddleware
from src.api.middleware import TraceMiddleware
from src.api.rate_limit_middleware import RateLimitMiddleware
from src.api.routes.admin import router as admin_router
from src.api.routes.agent_runs import router as agent_runs_router
from src.api.routes.agent_versions import router as agent_versions_router
from src.api.routes.agents import router as agents_router
from src.api.routes.audit import router as audit_router
from src.api.routes.audit_reports import router as audit_reports_router
from src.api.routes.auth import router as auth_router
from src.api.routes.billing import router as billing_router
from src.api.routes.billing_webhooks import router as billing_webhooks_router
from src.api.routes.chat_insights import router as chat_insights_router
from src.api.routes.connectors import router as connectors_router
from src.api.routes.copilot import router as copilot_router
from src.api.routes.deployments import router as deployments_router
from src.api.routes.devportal import router as devportal_router
from src.api.routes.dr import router as dr_router
from src.api.routes.ecosystem import router as ecosystem_router
from src.api.routes.embed import admin_router as embed_admin_router
from src.api.routes.embed import public_router as embed_public_router
from src.api.routes.embed import widget_router as embed_widget_router
from src.api.routes.evaluation import router as eval_router
from src.api.routes.federated import router as federated_router
from src.api.routes.feedback import router as feedback_router
from src.api.routes.gateway import router as gateway_router
from src.api.routes.governance import router as governance_router
from src.api.routes.health import router as health_router
from src.api.routes.ingestion import router as ingestion_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.knowledge_bases import router as kbs_router
from src.api.routes.knowledge_hub import router as knowledge_hub_router
from src.api.routes.migrations import router as migrations_router
from src.api.routes.notifications import router as notifications_router
from src.api.routes.onboarding import router as onboarding_router
from src.api.routes.organizations import router as organizations_router
from src.api.routes.payments_webhook import router as payments_webhook_router
from src.api.routes.platform import router as platform_router
from src.api.routes.projects import router as projects_router
from src.api.routes.prompt import router as prompt_router
from src.api.routes.public_query import router as public_query_router
from src.api.routes.query import router as query_router
from src.api.routes.releases import router as releases_router
from src.api.routes.risk_center import router as risk_center_router
from src.api.routes.scim import router as scim_router
from src.api.routes.share import router as share_router
from src.api.routes.soc import router as soc_router
from src.api.routes.sources import router as sources_router
from src.api.routes.sso import router as sso_router
from src.api.routes.training import router as training_router
from src.api.routes.workflows import router as workflows_router
from src.api.routes.workspaces import router as workspaces_router
from src.api.schemas import ErrorResponse
from src.api.security_headers_middleware import (
    OrgCorsMiddleware,
    SecurityHeadersMiddleware,
)
from src.api.tenant_middleware import TenantMiddleware
from src.api.versioning import API_VERSION
from src.connectors.sql.worker import request_shutdown, run_worker
from src.core.config import Settings, get_settings
from src.infrastructure.observability.logging_config import configure_logging, get_logger
from src.infrastructure.observability.metrics import setup_metrics
from src.infrastructure.observability.tracing import setup_tracing
from src.infrastructure.postgres.relational_db import close_db_connections
from src.infrastructure.qdrant.vector_store import close_qdrant_connection
from src.infrastructure.redis.cache import close_redis_connection

# -----------------------------------------------------------------------------
# Configuración inicial
# -----------------------------------------------------------------------------
settings: Settings = get_settings()
from src.infrastructure.secrets.vault import apply_vault_overrides  # noqa: E402

apply_vault_overrides(settings)
configure_logging(log_level=settings.LOG_LEVEL)
logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# MCP Server — transporte Streamable HTTP montado en /mcp
# -----------------------------------------------------------------------------
_worker_task: asyncio.Task | None = None


# -----------------------------------------------------------------------------
# Lifecycle — Startup / Shutdown
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el ciclo de vida de la aplicación: inicialización y cierre graceful.

    Anida el lifespan de la sub-app MCP: el transporte Streamable HTTP
    requiere su task group inicializado (Starlette no propaga lifespan a
    sub-apps montadas).
    """
    logger.info(
        "RAG Platform starting",
        environment=settings.ENVIRONMENT,
        api_port=settings.API_PORT,
        metrics_enabled=settings.METRICS_ENABLED,
        background_ingestion=settings.RAG_BACKGROUND_INGESTION,
        mcp_enabled=settings.RAG_MCP_ENABLED,
    )

    mcp_sub_app = getattr(app.state, "mcp_http_app", None)
    mcp_lifespan = (
        mcp_sub_app.router.lifespan_context(mcp_sub_app)
        if mcp_sub_app is not None
        else nullcontext()
    )
    async with mcp_lifespan:
        await _run_startup()
        try:
            _region_health_task = asyncio.create_task(_region_health_loop())
            _cost_alerts_task = asyncio.create_task(_cost_alerts_loop())
            _escalation_task = asyncio.create_task(_escalation_loop())
            _retention_task = asyncio.create_task(_retention_loop())
            _webhook_deliveries_task = asyncio.create_task(_webhook_deliveries_loop())
            _knowledge_refresh_task = asyncio.create_task(_knowledge_refresh_loop())
            yield
        finally:
            _region_health_task.cancel()
            _cost_alerts_task.cancel()
            _escalation_task.cancel()
            _retention_task.cancel()
            _webhook_deliveries_task.cancel()
            _knowledge_refresh_task.cancel()
            await _run_shutdown()


async def _webhook_deliveries_loop() -> None:
    """Procesa la cola de webhook deliveries con backoff (fail-soft)."""
    try:
        while True:
            try:
                from src.platform.notifyv2.notifications import process_deliveries

                await process_deliveries()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Webhook deliveries loop error", error=str(exc)[:150])
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        pass


async def _knowledge_refresh_loop() -> None:
    """Scheduler del Knowledge Hub: refresca fuentes vencidas cada 300s."""
    import asyncio as _asyncio

    while True:
        try:
            from src.platform.knowledgehub.hub import run_refresh_loop

            result = await run_refresh_loop()
            if result["refreshed"]:
                logger.info("knowledge refresh loop", refreshed=result["refreshed"])
        except Exception:  # noqa: BLE001
            logger.exception("knowledge refresh loop failed")
        await _asyncio.sleep(300)


async def _retention_loop() -> None:
    """Purga de retención diaria (fail-soft)."""
    try:
        while True:
            try:
                from src.platform.datacompliance.data_export import run_retention_purges

                await run_retention_purges()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Retention loop error", error=str(exc)[:150])
            await asyncio.sleep(86400)
    except asyncio.CancelledError:
        pass


async def _escalation_loop() -> None:
    """Dispara escalamientos pendientes de incidentes (fail-soft)."""
    try:
        while True:
            try:
                from src.platform.opscenter.runbooks import check_escalations

                await check_escalations()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Escalation loop error", error=str(exc)[:150])
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass


async def _cost_alerts_loop() -> None:
    """Evaluación periódica de alertas de costo (umbrales adaptativos)."""
    try:
        while True:
            try:
                from src.platform.costgov.cost_governance import run_cost_alerts

                await run_cost_alerts()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Cost alerts loop error", error=str(exc)[:150])
            await asyncio.sleep(300)
    except asyncio.CancelledError:
        pass


async def _region_health_loop() -> None:
    """Healthcheck periódico de réplicas regionales (fail-soft)."""
    try:
        while True:
            try:
                from src.platform.edge.multiregion import run_healthcheck

                await run_healthcheck()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Region healthcheck loop error", error=str(exc)[:150])
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass


async def _run_startup() -> None:
    global _worker_task
    if settings.ENVIRONMENT == "development":
        try:
            from src.infrastructure.postgres.relational_db import PostgresUserRepository
            from src.platform.auth.passwords import hash_password

            user_repo = PostgresUserRepository()
            demo = await user_repo.get_by_email(settings.PORTAL_DEV_EMAIL)
            if demo is not None and not demo.password_hash:
                await user_repo.set_password(
                    demo.id,
                    hash_password(settings.PORTAL_DEV_PASSWORD.get_secret_value()),
                )
                logger.info(
                    "Dev portal password seeded",
                    email=settings.PORTAL_DEV_EMAIL,
                )
        except Exception as exc:
            logger.warning("Could not seed portal dev password", error=str(exc))

    _worker_task = None
    if settings.RAG_BACKGROUND_INGESTION:
        _worker_task = asyncio.create_task(run_worker())
        logger.info("Background ingestion worker started")


async def _run_shutdown() -> None:
    global _worker_task
    if _worker_task is not None:
        request_shutdown()
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        logger.info("Background ingestion worker stopped")

    # Graceful shutdown: cerrar conexiones a bases de datos
    logger.info("RAG Platform shutting down — closing connections")
    await close_db_connections()
    await close_qdrant_connection()
    await close_redis_connection()
    logger.info("RAG Platform shutdown complete")


# -----------------------------------------------------------------------------
# FastAPI Application Factory
# -----------------------------------------------------------------------------
def create_app(*, metrics_enabled: bool | None = None, tracing_enabled: bool | None = None) -> FastAPI:
    """Construye la app completa. MCP se monta como sub-app fresca por app
    (su session manager solo puede arrancar una vez por instancia).

    metrics_enabled/tracing_enabled: override para tests (los registros
    globales de Prometheus/OTel no toleran múltiples instancias).
    """
    metrics_on = settings.METRICS_ENABLED if metrics_enabled is None else metrics_enabled
    tracing_on = settings.TRACING_ENABLED if tracing_enabled is None else tracing_enabled
    new_app = FastAPI(
        title="Zent API",
        description=(
            "Zent developer API (v1). Chat, RAG, agents, connectors and usage. "
            "Authenticate with Authorization: Bearer <api_key>."
        ),
        version=API_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        swagger_ui_parameters={
            "persistAuthorization": True,
            "displayRequestDuration": True,
        },
    )

    # -------------------------------------------------------------------------
    # CORS — Política restrictiva por defecto
    # -------------------------------------------------------------------------
    # En MVP permitimos un origen de desarrollo. En producción esto debe
    # configurarse mediante una variable de entorno con la lista de orígenes
    # permitidos por organization (whitelist).
    new_app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS.split(","),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Organization-Id",
            "X-User-Id",
            "X-User-Role",
            "X-Trace-Id",
            "X-API-Key",
            "X-New-Plan",
            "X-Billing-Interval",
            "X-Organization-Name",
            "Idempotency-Key",
        ],
        expose_headers=[
            "X-Trace-Id",
            "X-Request-Duration-Ms",
            "Idempotency-Replayed",
            "X-Zent-Environment",
        ],
        max_age=3600,
    )

    # -------------------------------------------------------------------------
    # Middleware de seguridad (orden de ejecución: Trace -> Tenant -> RateLimit
    # -> Idempotency -> BodyLimit -> CORS -> rutas)
    # -------------------------------------------------------------------------
    new_app.add_middleware(BodySizeLimitMiddleware)
    new_app.add_middleware(IdempotencyMiddleware)
    new_app.add_middleware(RateLimitMiddleware)
    new_app.add_middleware(OrgCorsMiddleware)

    # -------------------------------------------------------------------------
    # Middleware de Tenant (autenticación + TenantContext; inyecta organización)
    # -------------------------------------------------------------------------
    new_app.add_middleware(TenantMiddleware)
    new_app.add_middleware(SecurityHeadersMiddleware)

    # -------------------------------------------------------------------------
    # Middleware de Trazabilidad (orden importa: se ejecuta de último a primero)
    # -------------------------------------------------------------------------
    new_app.add_middleware(TraceMiddleware)

    # -------------------------------------------------------------------------
    # Métricas Prometheus — Expone /metrics y añade instrumentación HTTP
    # -------------------------------------------------------------------------
    if metrics_on:
        setup_metrics(new_app)
        logger.info("Prometheus metrics enabled at /metrics")

    # OpenTelemetry distributed tracing (FastAPI auto-instrumentation)
    if tracing_on:
        setup_tracing(new_app)

    # -------------------------------------------------------------------------
    # Routers
    # -------------------------------------------------------------------------
    new_app.include_router(admin_router)
    new_app.include_router(audit_reports_router)
    new_app.include_router(agent_runs_router)
    new_app.include_router(agent_versions_router)
    new_app.include_router(agents_router)
    new_app.include_router(embed_admin_router)
    new_app.include_router(embed_public_router)
    new_app.include_router(embed_widget_router)
    new_app.include_router(audit_router)
    new_app.include_router(auth_router)
    new_app.include_router(billing_router)
    new_app.include_router(billing_webhooks_router)
    new_app.include_router(connectors_router)
    new_app.include_router(dr_router)
    new_app.include_router(governance_router)
    new_app.include_router(soc_router)
    new_app.include_router(ecosystem_router)
    new_app.include_router(risk_center_router)
    new_app.include_router(knowledge_hub_router)
    new_app.include_router(chat_insights_router)
    new_app.include_router(workflows_router)
    new_app.include_router(copilot_router)
    new_app.include_router(releases_router)
    new_app.include_router(migrations_router)
    new_app.include_router(feedback_router)
    new_app.include_router(onboarding_router)
    new_app.include_router(notifications_router)
    new_app.include_router(payments_webhook_router)
    new_app.include_router(public_query_router)
    new_app.include_router(scim_router)
    new_app.include_router(sso_router)
    new_app.include_router(federated_router)
    new_app.include_router(share_router)
    new_app.include_router(dr_router)
    new_app.include_router(governance_router)
    new_app.include_router(soc_router)
    new_app.include_router(ecosystem_router)
    new_app.include_router(risk_center_router)
    new_app.include_router(knowledge_hub_router)
    new_app.include_router(chat_insights_router)
    new_app.include_router(workflows_router)
    new_app.include_router(devportal_router)
    new_app.include_router(deployments_router)
    new_app.include_router(workspaces_router)
    new_app.include_router(training_router)
    new_app.include_router(eval_router)
    new_app.include_router(gateway_router)
    new_app.include_router(health_router)
    new_app.include_router(ingestion_router)
    new_app.include_router(jobs_router)
    new_app.include_router(kbs_router)
    new_app.include_router(organizations_router)
    new_app.include_router(platform_router)
    new_app.include_router(projects_router)
    new_app.include_router(prompt_router)
    new_app.include_router(query_router)
    new_app.include_router(sources_router)

    # -------------------------------------------------------------------------
    # MCP Server — montado como sub-app: TODOS los middleware de la API
    # (Trace, Tenant, RateLimit, Idempotency, BodyLimit) aplican antes de
    # llegar al protocolo. Sin bypass posible.
    # -------------------------------------------------------------------------
    if settings.RAG_MCP_ENABLED:
        from src.mcp_server.app import build_mcp_http_app

        new_app.state.mcp_http_app = build_mcp_http_app()
        new_app.mount("/mcp", new_app.state.mcp_http_app)
        logger.info("MCP server enabled at /mcp (Streamable HTTP, stateless)")

    @new_app.get("/api/v1", tags=["Meta"], summary="Versión del contrato público")
    async def api_v1_root() -> dict[str, str]:
        return {"version": API_VERSION, "docs": "/docs"}

    @new_app.get("/api/v1/openapi.json", include_in_schema=False)
    async def openapi_v1() -> JSONResponse:
        return JSONResponse(new_app.openapi())

    # -------------------------------------------------------------------------
    # Exception Handlers — Errores con logs estructurados y trace_id
    # -------------------------------------------------------------------------
    @new_app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Captura errores HTTP y los registra con trace_id en el log JSON."""
        if isinstance(exc.detail, dict):
            error_code = str(exc.detail.get("error_code") or f"HTTP_{exc.status_code}")
            message = str(exc.detail.get("message") or exc.detail)
        else:
            error_code = f"HTTP_{exc.status_code}"
            message = str(exc.detail)

        logger.warning(
            "HTTP exception",
            status_code=exc.status_code,
            detail=message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_code=error_code,
                message=message,
            ).model_dump(),
        )

    @new_app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Captura errores de validación Pydantic (payload malformado)."""
        errors = exc.errors()
        detail = errors[0]["msg"] if errors else "Validation error"
        # No loguear el valor `input` de cada error: puede contener passwords
        # o datos sensibles del cliente.
        safe_errors = [
            {k: v for k, v in e.items() if k != "input"}
            for e in errors[:20]
        ]
        logger.warning(
            "Validation error",
            errors=safe_errors,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="VALIDATION_ERROR",
                message=detail,
            ).model_dump(),
        )

    @new_app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Último recurso: captura excepciones no manejadas."""
        logger.error(
            "Unhandled exception",
            error_type=type(exc).__name__,
            error=str(exc),
            path=request.url.path,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred. Reference the X-Trace-Id header for support.",
            ).model_dump(),
        )

    return new_app


app = create_app()


# -----------------------------------------------------------------------------
# Entrypoint para ejecución directa
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=settings.API_PORT,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=False,  # Usamos nuestro propio middleware de logging
        reload=settings.ENVIRONMENT == "development",
    )
