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
from contextlib import asynccontextmanager
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

from src.api.billing_middleware import BillingMiddleware
from src.api.metrics import setup_metrics
from src.api.middleware import TraceMiddleware
from src.api.routes.admin import router as admin_router
from src.api.routes.auth import router as auth_router
from src.api.routes.billing import router as billing_router
from src.api.routes.evaluation import router as eval_router
from src.api.routes.health import router as health_router
from src.api.routes.ingestion import router as ingestion_router
from src.api.routes.prompt import router as prompt_router
from src.api.routes.query import router as query_router
from src.config import Settings, get_settings
from src.domain.models import ErrorResponse
from src.infrastructure.cache import close_redis_connection
from src.infrastructure.ingestion_worker import request_shutdown, run_worker
from src.infrastructure.logging_config import configure_logging, get_logger
from src.infrastructure.relational_db import close_db_connections
from src.infrastructure.tracing import setup_tracing
from src.infrastructure.vector_store import close_qdrant_connection

# -----------------------------------------------------------------------------
# Configuración inicial
# -----------------------------------------------------------------------------
settings: Settings = get_settings()
configure_logging(log_level=settings.LOG_LEVEL)
logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Lifecycle — Startup / Shutdown
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el ciclo de vida de la aplicación: inicialización y cierre graceful."""
    logger.info(
        "RAG Platform starting",
        environment=settings.ENVIRONMENT,
        api_port=settings.API_PORT,
        metrics_enabled=settings.METRICS_ENABLED,
        background_ingestion=settings.RAG_BACKGROUND_INGESTION,
    )

    if settings.ENVIRONMENT == "development":
        try:
            from src.infrastructure.passwords import hash_password
            from src.infrastructure.relational_db import PostgresUserRepository

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

    worker_task: asyncio.Task | None = None
    if settings.RAG_BACKGROUND_INGESTION:
        worker_task = asyncio.create_task(run_worker())
        logger.info("Background ingestion worker started")

    yield

    if worker_task is not None:
        request_shutdown()
        worker_task.cancel()
        try:
            await worker_task
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
app = FastAPI(
    title="RAG-as-a-Service Platform",
    description=(
        "Plataforma SaaS de Orquestación de Agentes de IA con RAG. "
        "Enruta consultas, busca contexto en BD vectorial, ejecuta herramientas "
        "y devuelve respuestas generadas por LLM con observabilidad completa."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    # Swagger/OpenAPI soporta autenticación por API Key
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
    },
)

# -----------------------------------------------------------------------------
# CORS — Política restrictiva por defecto
# -----------------------------------------------------------------------------
# En MVP permitimos un origen de desarrollo. En producción esto debe
# configurarse mediante una variable de entorno con la lista de orígenes
# permitidos por tenant (whitelist).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS.split(","),  # MVP: abierto. Producción: whitelist estricta
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Tenant-Id",
        "X-User-Id",
        "X-User-Role",
        "X-Trace-Id",
        "X-API-Key",
        "X-New-Plan",
        "X-Billing-Interval",
        "X-Tenant-Name",
    ],
    expose_headers=["X-Trace-Id", "X-Request-Duration-Ms"],
    max_age=3600,
)

# -----------------------------------------------------------------------------
# Middleware de Facturación (antes de Trace para inyectar tenant_id)
# -----------------------------------------------------------------------------
app.add_middleware(BillingMiddleware)

# -----------------------------------------------------------------------------
# Middleware de Trazabilidad (orden importa: se ejecuta de último a primero)
# -----------------------------------------------------------------------------
app.add_middleware(TraceMiddleware)

# -----------------------------------------------------------------------------
# Métricas Prometheus — Expone /metrics y añade instrumentación HTTP
# -----------------------------------------------------------------------------
if settings.METRICS_ENABLED:
    instrumentator = setup_metrics(app)
    logger.info("Prometheus metrics enabled at /metrics")
else:
    instrumentator = None

# OpenTelemetry distributed tracing (FastAPI auto-instrumentation)
if settings.TRACING_ENABLED:
    setup_tracing(app)

# -----------------------------------------------------------------------------
# Routers
# -----------------------------------------------------------------------------
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(eval_router)
app.include_router(health_router)
app.include_router(ingestion_router)
app.include_router(prompt_router)
app.include_router(query_router)


# -----------------------------------------------------------------------------
# Exception Handlers — Errores con logs estructurados y trace_id
# -----------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
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
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Captura errores de validación Pydantic (payload malformado)."""
    errors = exc.errors()
    detail = errors[0]["msg"] if errors else "Validation error"
    logger.warning(
        "Validation error",
        errors=errors,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="VALIDATION_ERROR",
            message=detail,
        ).model_dump(),
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
        headers={"Access-Control-Allow-Origin": "*"},
    )


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
