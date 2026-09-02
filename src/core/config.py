# =============================================================================
# Configuración Central — Pydantic Settings con Validación CISO-Grade
# =============================================================================
# Principio: Cero secretos hardcodeados. Todo proviene de variables de entorno
# o de un vault externo (HashiCorp Vault / Azure Key Vault). Pydantic v2
# valida tipos estrictamente para prevenir inyección de configuración.
# =============================================================================
from __future__ import annotations

import warnings
from functools import lru_cache
from typing import Any, Literal, Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Known insecure defaults — refused in production, warned in development.
_INSECURE_PORTAL_SESSION_KEYS = frozenset(
    {
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
)
_INSECURE_PORTAL_DEV_PASSWORDS = frozenset(
    {
        "demo-password-change-me",
    }
)


def _secret_raw(v: SecretStr | str | None) -> str:
    if v is None:
        return ""
    if isinstance(v, SecretStr):
        return v.get_secret_value()
    return str(v)


def _decode_session_key_bytes(raw: str) -> bytes:
    """Validate PORTAL_SESSION_KEY decodes to 32 bytes (AES-256)."""
    import base64

    value = raw.strip()
    if len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        key = bytes.fromhex(value)
    else:
        pad = "=" * (-len(value) % 4)
        key = base64.urlsafe_b64decode(value + pad)
    if len(key) != 32:
        raise ValueError(
            "PORTAL_SESSION_KEY must decode to exactly 32 bytes (AES-256). "
            "Generate with: openssl rand -hex 32"
        )
    return key


class Settings(BaseSettings):
    """Configuración central tipada de la plataforma RAG.

    Cada campo se inyecta desde variables de entorno (prefijo RAG_).
    SecretStr oculta el valor en logs/repr automáticamente.
    extra=forbid evita typosquatting de variables de entorno.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RAG_",
        case_sensitive=False,
        extra="forbid",
    )

    # -------------------------------------------------------------------------
    # Entorno y Debug
    # -------------------------------------------------------------------------
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    API_PORT: int = Field(default=8000, ge=1, le=65535)
    CORS_ALLOWED_ORIGINS: str = Field(default="*")

    # -------------------------------------------------------------------------
    # Compose / ops vars that may appear in the shared .env file.
    # AliasChoices accept unprefixed names used by docker-compose substitution.
    # -------------------------------------------------------------------------
    PORTAL_PORT: int = Field(
        default=8080,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("PORTAL_PORT", "RAG_PORTAL_PORT"),
    )
    GRAFANA_ADMIN_USER: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GRAFANA_ADMIN_USER", "RAG_GRAFANA_ADMIN_USER"),
    )
    GRAFANA_ADMIN_PASSWORD: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GRAFANA_ADMIN_PASSWORD", "RAG_GRAFANA_ADMIN_PASSWORD"
        ),
    )
    # -------------------------------------------------------------------------
    # PostgreSQL
    # -------------------------------------------------------------------------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = Field(default=5432, ge=1, le=65535)
    POSTGRES_USER: str = "rag_user"
    POSTGRES_PASSWORD: SecretStr = SecretStr("changeme_in_production")
    POSTGRES_DB: str = "rag_platform"
    POSTGRES_MIN_CONNECTIONS: int = Field(default=5, ge=1)
    POSTGRES_MAX_CONNECTIONS: int = Field(default=25, ge=1)
    # Rol read-only dedicado para el SQL Expert (sin DDL/DML). El rol se
    # crea vía db_init/09-readonly-role.sql. Vacío = fallback a POSTGRES_USER
    # con warning (no rompe ambientes de desarrollo).
    POSTGRES_READONLY_USER: str = Field(
        default="",
        description="Rol PostgreSQL read-only para ejecución SQL del motor Text-to-SQL.",
    )
    POSTGRES_READONLY_PASSWORD: SecretStr = SecretStr("")

    @property
    def POSTGRES_DSN(self) -> str:
        """Construye el DSN asíncrono para asyncpg."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}"
            f":{self.POSTGRES_PASSWORD.get_secret_value()}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def POSTGRES_DSN_SYNC(self) -> str:
        """Construye el DSN síncrono para Alembic/SQLAlchemy sync."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}"
            f":{self.POSTGRES_PASSWORD.get_secret_value()}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def POSTGRES_READONLY_DSN(self) -> str | None:
        """DSN asíncrono del rol read-only (None si no está configurado)."""
        if not self.POSTGRES_READONLY_USER:
            return None
        return (
            f"postgresql+asyncpg://{self.POSTGRES_READONLY_USER}"
            f":{self.POSTGRES_READONLY_PASSWORD.get_secret_value()}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # -------------------------------------------------------------------------
    # Qdrant (Vector Store)
    # -------------------------------------------------------------------------
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = Field(default=6333, ge=1, le=65535)
    QDRANT_API_KEY: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("QDRANT_API_KEY", "RAG_QDRANT_API_KEY"),
    )
    QDRANT_HTTPS: bool = Field(
        default=False,
        description="Usar HTTPS para Qdrant (red interna docker = http con api_key).",
    )
    QDRANT_GRPC_PORT: int = Field(default=6334, ge=1, le=65535)
    QDRANT_TIMEOUT_SECONDS: int = Field(default=60, ge=5, le=300)
    QDRANT_UPSERT_CONCURRENCY: int = Field(
        default=2,
        ge=1,
        le=8,
        description="Max concurrent Qdrant upsert batches (across all tables).",
    )

    # -------------------------------------------------------------------------
    # Redis
    # -------------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"

    # -------------------------------------------------------------------------
    # LiteLLM (Proxy centralizado para LLMs)
    # -------------------------------------------------------------------------
    LITELLM_API_BASE: str | None = None
    LITELLM_API_KEY: SecretStr | None = None
    LITELLM_DEFAULT_MODEL: str = "gpt-4o-mini"
    LITELLM_TIMEOUT_SECONDS: int = Field(default=120, ge=1, le=300)
    LITELLM_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    GATEWAY_FALLBACK_MODEL: str = Field(
        default="",
        description="Modelo real si el primary falla. Vacío = sin fallback.",
    )
    GATEWAY_CHEAP_MODEL: str = Field(
        default="",
        description="Primary para alias zent-cheap. Vacío = LITELLM_DEFAULT_MODEL.",
    )
    GATEWAY_QUALITY_MODEL: str = Field(
        default="",
        description="Primary para alias zent-quality. Vacío = LITELLM_DEFAULT_MODEL.",
    )

    # -------------------------------------------------------------------------
    # RAG / Embeddings
    # -------------------------------------------------------------------------
    EMBEDDING_MODEL: str = "openai/baai/bge-m3"
    VECTOR_DIMENSION: int = Field(default=1024, ge=1)
    RAG_TOP_K: int = Field(default=200, ge=1, le=500)
    RAG_SCORE_THRESHOLD: float = Field(default=0.0, ge=0.0, le=1.0)
    RAG_CONVERSATION_TTL_SECONDS: int = Field(default=3600, ge=60, le=86400)
    RAG_SQL_EXPERT_ENABLED: bool = Field(default=False)
    RAG_SQL_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)
    RAG_SQL_MAX_ROWS: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Máximo de filas devueltas por consulta del SQL Expert.",
    )
    RAG_SQL_MAX_COST: float = Field(
        default=100_000.0,
        ge=1.0,
        description="Costo máximo del plan (EXPLAIN Total Cost) permitido.",
    )
    RAG_SQL_MAX_TABLES: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Máximo de tablas enviadas al LLM (schema relevance).",
    )
    RAG_SQL_SCHEMA_CACHE_TTL: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="TTL segundos del caché de schema por organization.",
    )
    RAG_SQL_ROUTER_THRESHOLD: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Score mínimo del router para correr SQL Expert.",
    )
    RAG_SQL_ROUTER_LLM_ENABLED: bool = Field(
        default=True,
        description="Confirmación LLM para intent dudoso del router.",
    )
    RAG_SQL_SENSITIVE_COLUMNS: str = Field(
        default="",
        description=(
            "Comma-separated: columnas sensibles bloqueadas globalmente "
            "(los tenants pueden extender vía config_json)."
        ),
    )
    # -------------------------------------------------------------------------
    # Agent Runtime
    # -------------------------------------------------------------------------
    RAG_AGENT_MODEL: str = Field(default="")
    RAG_AGENT_MAX_STEPS: int = Field(default=5, ge=1, le=20)
    RAG_AGENT_MAX_TOOL_CALLS: int = Field(default=8, ge=1, le=50)
    RAG_AGENT_MAX_EXECUTION_SECONDS: int = Field(default=60, ge=5, le=300)
    RAG_AGENT_MAX_TOKENS: int = Field(default=4000, ge=256, le=100_000)
    RAG_AGENT_MAX_COST: float = Field(default=0.05, ge=0.001, le=100.0)
    RAG_AGENT_COST_PER_1K_TOKENS: float = Field(
        default=0.001, ge=0.0, le=1.0,
        description="Precio estimado por 1000 tokens para cálculo de costo.",
    )
    RAG_AGENT_TOOL_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=120)
    RAG_AGENT_TOOL_RATE_LIMIT_PER_MINUTE: int = Field(default=20, ge=1, le=600)
    RAG_AGENT_TOOL_MODULES: str = Field(
        default="",
        description=(
            "Comma-separated module paths que registran tools verticales "
            "(patrón SQL_HEURISTICS_MODULES)."
        ),
    )
    # -------------------------------------------------------------------------
    # MCP Server (Model Context Protocol)
    # -------------------------------------------------------------------------
    RAG_MCP_ENABLED: bool = Field(
        default=True,
        description="Monta el MCP server (Streamable HTTP) en /mcp de la API.",
    )
    RAG_MCP_ALLOWED_HOSTS: str = Field(
        default="localhost:*,127.0.0.1:*,testserver",
        description=(
            "Comma-separated Host header allowlist para el guard DNS-rebinding "
            "del transporte MCP (entradas 'host' o 'host:*')."
        ),
    )
    RAG_MCP_DEFAULT_RPM: int = Field(
        default=60, ge=1, le=1000,
        description="Requests/minuto por defecto por tool MCP (override por org).",
    )
    # -------------------------------------------------------------------------
    # Connector Platform
    # -------------------------------------------------------------------------
    CONNECTOR_SECRETS_KEY: SecretStr = SecretStr(
        "zent-connector-secrets-dev-key-change-me"
    )
    CONNECTOR_TEST_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=120)
    CONNECTOR_DISCOVER_MAX_TABLES: int = Field(default=200, ge=1, le=5000)
    CONNECTOR_PLUGIN_MODULES: str = Field(
        default="",
        description=(
            "Comma-separated module paths que registran plugins de conectores "
            "(fallback a entry points zent_connectors)."
        ),
    )
    CONNECTOR_SSRF_BLOCK_PRIVATE: bool = Field(
        default=True,
        description="Bloquear hosts en redes privadas en plugins (SSRF guard).",
    )
    GOOGLE_OAUTH_CLIENT_ID: str = Field(
        default="",
        description="OAuth client ID de Google Drive (vacío = Drive deshabilitado).",
    )
    GOOGLE_OAUTH_CLIENT_SECRET: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GOOGLE_OAUTH_CLIENT_SECRET", "RAG_GOOGLE_OAUTH_CLIENT_SECRET"
        ),
    )
    GOOGLE_OAUTH_REDIRECT_URI: str = Field(
        default="http://localhost:8000/api/v1/connectors/oauth/drive/callback",
        description="Debe coincidir con el redirect URI registrado en Google Cloud.",
    )
    GOOGLE_OAUTH_PORTAL_RETURN_URL: str = Field(
        default="http://localhost:8080/knowledge/sources",
        description="Redirect post-callback al Knowledge Center.",
    )
    # -------------------------------------------------------------------------
    # Usage & Cost Engine
    # -------------------------------------------------------------------------
    USAGE_ENGINE_ENABLED: bool = Field(default=True)
    USAGE_COST_CURRENCY: str = Field(default="USD", max_length=3)
    USAGE_QUOTA_MARGIN_TOKENS: int = Field(
        default=1024,
        ge=0,
        le=100_000,
        description="Margen conservador de tokens reservados en pre-flight.",
    )
    USAGE_ALERT_THRESHOLDS: str = Field(
        default="50,80,90,100",
        description="Umbrales de alerta de quota en porcentaje.",
    )
    PRICING_CACHE_TTL: int = Field(default=300, ge=10, le=3600)
    FINOPS_INFRA_COST_PER_ORG_MONTH_CENTS: int = Field(
        default=0,
        ge=0,
        le=10_000_000,
        description=(
            "Coste de infra (Postgres/Redis) asignado por org y mes, en céntimos. "
            "Rate configurable — no es telemetría inventada. 0 = no imputar."
        ),
    )
    # -------------------------------------------------------------------------
    # Billing Platform
    # -------------------------------------------------------------------------
    PAYMENT_PROVIDER: str = Field(
        default="manual",
        description="Provider de pagos: manual | stripe.",
    )
    BILLING_WEBHOOK_SECRET: SecretStr = SecretStr(
        "zent-billing-webhook-secret-change-me"
    )
    BILLING_STRIPE_SECRET_KEY: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "BILLING_STRIPE_SECRET_KEY", "RAG_BILLING_STRIPE_SECRET_KEY"
        ),
    )
    BILLING_STRIPE_WEBHOOK_SECRET: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "BILLING_STRIPE_WEBHOOK_SECRET", "RAG_BILLING_STRIPE_WEBHOOK_SECRET"
        ),
    )
    BILLING_CHECKOUT_SUCCESS_URL: str = Field(
        default="http://localhost:8080/billing?checkout=success",
    )
    BILLING_CHECKOUT_CANCEL_URL: str = Field(
        default="http://localhost:8080/billing?checkout=cancel",
    )
    BILLING_PAST_DUE_GRACE_DAYS: int = Field(default=7, ge=1, le=90)
    BILLING_INVOICE_DAY: int = Field(default=1, ge=1, le=28)
    SQL_HEURISTICS_MODULES: str = Field(
        default="",
        description=(
            "Comma-separated module paths of SQL heuristics plugins (verticals). "
            "Empty = no business-specific SQL rewriting."
        ),
    )
    GOLDEN_SET_PATH: str = Field(
        default="",
        description="Path del golden set de evaluación (los verticals proveen el suyo).",
    )
    RAG_MAX_CONTEXT_TOKENS: int = Field(default=32000, ge=1)
    RAG_RERANK_ENABLED: bool = Field(default=False)
    RAG_RERANK_TOP_N: int = Field(default=20, ge=1, le=100)
    RAG_RERANK_MODEL: str = Field(default="")
    RAG_RETRIEVAL_STRATEGY: str = Field(
        default="vector",
        description="Estrategia por defecto del motor: vector|lexical|hybrid.",
    )
    RAG_HYBRID_FUSION: str = Field(default="rrf", description="rrf|weighted")
    RAG_RRF_K: int = Field(default=60, ge=1, le=1000)
    RAG_HYBRID_LEXICAL_WEIGHT: float = Field(default=0.3, ge=0.0, le=1.0)
    RAG_RERANKER: str = Field(
        default="",
        description="Reranker activo: llm|cross_encoder ('' = passthrough).",
    )
    RAG_CROSS_ENCODER_MODEL: str = Field(
        default="",
        description="Modelo cross-encoder vía LiteLLM rerank API (ej: cohere/rerank-v3.5).",
    )
    RAG_ADMIN_ENABLED: bool = Field(default=True)
    RAG_CHUNK_MAX_CHARS: int = Field(default=1200, ge=200, le=8000)
    RAG_CHUNK_OVERLAP: int = Field(default=150, ge=0, le=500)

    # -------------------------------------------------------------------------
    # Evaluation Engine — golden sets, LLM-judge, regresión de versiones
    # -------------------------------------------------------------------------
    EVAL_JUDGE_ENABLED: bool = Field(
        default=True,
        description="Habilita el LLM-judge para métricas de calidad (faithfulness, etc.).",
    )
    EVAL_JUDGE_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Modelo usado por el LLM-judge (LiteLLM).",
    )
    EVAL_JUDGE_MAX_TOKENS: int = Field(default=256, ge=64, le=2048)
    EVAL_DEFAULT_TOP_K: int = Field(
        default=200,
        ge=1,
        le=500,
        description="Top-k por defecto del runner de evaluación si el caso no lo fija.",
    )
    EVAL_REGRESSION_QUALITY_MIN_DELTA: float = Field(
        default=-0.05,
        ge=-1.0,
        le=1.0,
        description="Delta mínimo de score compuesto antes de marcar regresión de calidad.",
    )
    EVAL_REGRESSION_FAITHFULNESS_MIN_DELTA: float = Field(
        default=-0.10,
        ge=-1.0,
        le=1.0,
        description="Delta mínimo de faithfulness antes de marcar regresión.",
    )
    EVAL_REGRESSION_HALLUCINATION_MAX_DELTA: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="Aumento máximo de hallucination_rate antes de marcar regresión.",
    )
    EVAL_REGRESSION_COST_MAX_INCREASE_PCT: float = Field(
        default=10.0,
        ge=0.0,
        le=1000.0,
        description="Aumento porcentual máximo de costo/caso antes de marcar regresión.",
    )
    EVAL_REGRESSION_LATENCY_MAX_INCREASE_PCT: float = Field(
        default=10.0,
        ge=0.0,
        le=1000.0,
        description="Aumento porcentual máximo de latencia p95 antes de marcar regresión.",
    )
    EVAL_REGRESSION_LATENCY_MAX_INCREASE_MS: float = Field(
        default=200.0,
        ge=0.0,
        le=60000.0,
        description="Aumento absoluto máximo de latencia p95 (ms) antes de marcar regresión.",
    )
    # Promotion gate: bloquea promover una versión a production si su último
    # run de evaluación no alcanza los thresholds. 0 / 1.0 = gate desactivado.
    EVAL_PROMOTION_MIN_SCORE: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Score mínimo compuesto del último run para permitir promotion.",
    )
    EVAL_PROMOTION_MAX_HALLUCINATION: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Hallucination m\u00e1xima del \u00faltimo run para permitir promotion.",
    )

    # ------------------------------------------------------------------ PROMPT 08
    # Observability & incident thresholds
    OBS_ERROR_RATE_THRESHOLD_PCT: float = Field(
        default=5.0, ge=0.0, le=100.0, description="Error rate m\u00e1ximo para SLO."
    )
    OBS_P95_LATENCY_MS: float = Field(
        default=15000.0, ge=1.0, description="Latencia p95 m\u00e1xima (ms) para SLO."
    )
    OBS_AVAILABILITY_THRESHOLD_PCT: float = Field(
        default=99.0, ge=0.0, le=100.0, description="Disponibilidad m\u00ednima (%) para SLO."
    )
    OBS_WORKER_STALE_MINUTES: int = Field(
        default=5, ge=1, description="Minutos sin heartbeat del worker para alertar."
    )

    # ------------------------------------------------------------------ PROMPT 10
    # Disaster Recovery
    DR_BACKUP_DIR: str = "data/backups"
    DR_SCHEDULER_INTERVAL_SECONDS: int = Field(default=60, ge=10, le=3600)
    DR_POSTGRES_CONTAINER: str = Field(
        default="rag-postgres", description="Contenedor docker con el PostgreSQL."
    )

    # ------------------------------------------------------------------ PROMPT 12
    # Customer Success (SMTP)
    SMTP_HOST: str = ""
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_TLS: bool = True
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # -------------------------------------------------------------------------
    # Ingestion performance
    # -------------------------------------------------------------------------
    INGEST_EMBED_BATCH_SIZE: int = Field(default=64, ge=1, le=512)
    INGEST_EMBED_CONCURRENCY: int = Field(default=8, ge=1, le=32)
    INGEST_TABLE_CONCURRENCY: int = Field(default=3, ge=1, le=16)
    INGEST_UPSERT_BATCH_SIZE: int = Field(default=100, ge=1, le=500)
    INGEST_PAGE_SIZE: int = Field(default=1000, ge=100, le=10000)
    INGEST_SKIP_TABLES: str = Field(
        default="",
        description="Comma-separated table names to skip during sync (no business defaults).",
    )
    INGEST_MAX_ROWS_PER_TABLE: int = Field(
        default=0,
        ge=0,
        description="Cap rows per table during ingest (0 = no cap).",
    )
    RAG_LAZY_INGESTION_ENABLED: bool = Field(
        default=False,
        description="Enable lazy ingestion fallback when SQL Expert + vector search find nothing.",
    )
    RAG_LAZY_INGEST_MAX_ROWS_PER_TABLE: int = Field(
        default=25,
        ge=1,
        le=200,
        description="Max candidate rows to embed per table during lazy ingestion.",
    )
    RAG_LAZY_INGEST_MAX_TABLES: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max tables scanned during a lazy ingestion fallback.",
    )
    RAG_LAZY_INGEST_TIMEOUT_SECONDS: int = Field(
        default=4,
        ge=1,
        le=30,
        description="Global timeout for a lazy ingestion fallback attempt.",
    )
    RAG_LAZY_INGEST_PROMOTE_THRESHOLD: int = Field(
        default=10,
        ge=1,
        description=(
            "Triggers de lazy ingestion sobre una misma tabla antes de encolar "
            "automáticamente un sync_table completo en background."
        ),
    )
    RAG_LAZY_INGEST_PROMOTE_WINDOW_SECONDS: int = Field(
        default=86400,
        ge=300,
        le=604800,
        description="Ventana de conteo de triggers para la auto-promoción (default 24h).",
    )
    RAG_LAZY_INGEST_MAX_TRIGGERS_PER_HOUR: int = Field(
        default=20,
        ge=1,
        le=1000,
        description=(
            "Máximo de triggers de lazy ingestion por organization por hora. "
            "Al excederse, el fallback se desactiva temporalmente (no rompe la respuesta RAG)."
        ),
    )
    RAG_LAZY_INGEST_MAX_TABLE_ROWS_FOR_SCAN: int = Field(
        default=500_000,
        ge=1_000,
        description=(
            "Tope de filas de una tabla para intentar el escaneo ILIKE/% del "
            "fallback sin índice trigram confirmado. Tablas mayores se saltan "
            "para no arriesgar un full scan dentro del timeout."
        ),
    )
    RAG_LAZY_INGEST_COOLDOWN_SECONDS: int = Field(
        default=300,
        ge=60,
        le=86400,
        description="Cooldown por tabla tras un fallo de lazy ingestion (default 5 min).",
    )

    def ingestion_concurrency(self) -> tuple[int, int, int]:
        """Return (embed_batch, embed_concurrency, table_concurrency) with Ollama auto-limit."""
        is_ollama = self.EMBEDDING_MODEL.startswith("ollama/")
        embed_batch = 16 if is_ollama else self.INGEST_EMBED_BATCH_SIZE
        embed_conc = 1 if is_ollama else self.INGEST_EMBED_CONCURRENCY
        table_conc = 1 if is_ollama else self.INGEST_TABLE_CONCURRENCY
        return embed_batch, embed_conc, table_conc

    def ingest_skip_table_set(self) -> set[str]:
        return {
            t.strip().lower()
            for t in self.INGEST_SKIP_TABLES.split(",")
            if t.strip()
        }

    # -------------------------------------------------------------------------
    # Billing
    # -------------------------------------------------------------------------
    BILLING_ENABLED: bool = Field(default=True)
    BILLING_TRIAL_REQUESTS: int = Field(default=500, ge=1)
    BILLING_TRIAL_DAYS: int = Field(default=30, ge=1, le=365)

    # -------------------------------------------------------------------------
    # Portal auth (email/password + AES-256-GCM session tokens)
    # -------------------------------------------------------------------------
    # REQUIRED via env (RAG_PORTAL_SESSION_KEY). No insecure hardcoded default.
    PORTAL_SESSION_KEY: SecretStr
    PORTAL_SESSION_TTL_HOURS: int = Field(default=24, ge=1, le=168)
    PORTAL_BASE_URL: str = "http://localhost:5173"
    AUTH_LOGIN_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=50)
    AUTH_LOGIN_WINDOW_SECONDS: int = Field(default=900, ge=60, le=86400)
    PORTAL_DEV_PASSWORD: SecretStr | None = None
    PORTAL_DEV_EMAIL: str = Field(default="demo@zenttech.com")
    PLATFORM_ADMIN_EMAIL: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PLATFORM_ADMIN_EMAIL", "RAG_PLATFORM_ADMIN_EMAIL"),
        description="Email of the seeded platform admin (password is never stored in env).",
    )

    # -------------------------------------------------------------------------
    # Vault (HashiCorp Vault)
    # -------------------------------------------------------------------------
    VAULT_ADDR: str | None = None
    VAULT_TOKEN: SecretStr | None = None
    VAULT_MOUNT_POINT: str = "secret"
    VAULT_PATH: str = "rag-platform"

    # -------------------------------------------------------------------------
    # Background Ingestion Worker
    # -------------------------------------------------------------------------
    RAG_BACKGROUND_INGESTION: bool = Field(default=False)

    # -------------------------------------------------------------------------
    # Seguridad — Rate Limiting & Prompt Injection Mitigation
    # -------------------------------------------------------------------------
    RATE_LIMIT_PER_MINUTE: int = Field(default=60, ge=1)
    RATE_LIMIT_PER_ORGANIZATION_MINUTE: int = Field(default=600, ge=1)
    RATE_LIMIT_ENABLED: bool = Field(default=True)
    API_KEY_LIVE_RPM: int = Field(
        default=100, ge=1, le=10_000,
        description="Requests/minuto por API key live.",
    )
    API_KEY_LIVE_RPD: int = Field(
        default=10_000, ge=1, le=1_000_000,
        description="Requests/día por API key live.",
    )
    API_KEY_TEST_RPM: int = Field(
        default=30, ge=1, le=10_000,
        description="Requests/minuto por API key test (más estricto).",
    )
    API_KEY_TEST_RPD: int = Field(
        default=1_000, ge=1, le=1_000_000,
        description="Requests/día por API key test.",
    )
    RATE_LIMIT_PUBLIC_PER_MINUTE: int = Field(
        default=10,
        ge=1,
        description="Max requests/min per IP on public endpoints (signup/trial).",
    )
    MAX_PROMPT_LENGTH_CHARS: int = Field(default=32000, ge=1)
    MAX_BODY_BYTES: int = Field(
        default=1_048_576,
        ge=1024,
        description="Tamaño máximo del body HTTP (default 1 MB).",
    )
    METRICS_TOKEN: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("METRICS_TOKEN", "RAG_METRICS_TOKEN"),
    )
    TRUSTED_PROXIES: str = Field(
        default="",
        description="Comma-separated IPs/CIDRs de proxies confiables para X-Forwarded-For.",
    )
    SELF_SERVICE_UPGRADE_ENABLED: bool = Field(
        default=False,
        description=(
            "Permite cambios de plan self-service. Habilitar solo cuando exista "
            "un flujo de pago verificado (Stripe) con webhook."
        ),
    )
    SEED_DEMO_DATA: bool = Field(
        default=True,
        description="Permite sembrar datos demo/dev (token admin) en la BD.",
    )
    REDIS_PASSWORD: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_PASSWORD", "RAG_REDIS_PASSWORD"),
    )
    PROMPT_INJECTION_PATTERNS: list[str] = Field(
        default_factory=lambda: [
            "ignore previous instructions",
            "ignore all previous",
            "disregard prior",
            "forget everything",
            "system prompt:",
            "<<SYS>>",
            "you are now",
        ]
    )

    # -------------------------------------------------------------------------
    # Knowledge Platform (fuentes, uploads, jobs de ingestion)
    # -------------------------------------------------------------------------
    UPLOAD_DIR: str = Field(
        default="uploads",
        description="Directorio raíz de archivos subidos (Knowledge Platform).",
    )
    KNOWLEDGE_QUEUE_KEY: str = Field(
        default="rag:knowledge:queue",
        description="Redis list key de wakeup para jobs de la Knowledge Platform.",
    )

    # -------------------------------------------------------------------------
    # Observabilidad
    # -------------------------------------------------------------------------
    METRICS_ENABLED: bool = True
    TRACING_ENABLED: bool = False
    TRACING_OTLP_ENDPOINT: str | None = None

    # -------------------------------------------------------------------------
    # Validaciones de Seguridad
    # -------------------------------------------------------------------------
    @field_validator("QDRANT_API_KEY", "GRAFANA_ADMIN_PASSWORD", mode="before")
    @classmethod
    def empty_secret_to_none(cls, v: Any) -> Any:
        """Normalize blank env values to None (keeps SecretStr protection)."""
        if v is None:
            return None
        raw = _secret_raw(v)
        if not raw.strip():
            return None
        return v

    @field_validator("PORTAL_DEV_PASSWORD", mode="before")
    @classmethod
    def empty_portal_dev_password_to_none(cls, v: Any) -> Any:
        if v is None:
            return None
        raw = _secret_raw(v)
        if not raw.strip():
            return None
        return v

    @field_validator("POSTGRES_PASSWORD", mode="before")
    @classmethod
    def warn_default_password(cls, v: str | SecretStr) -> str | SecretStr:
        raw = _secret_raw(v)
        if raw == "changeme_in_production":
            warnings.warn(
                "SECURITY: POSTGRES_PASSWORD tiene el valor por defecto. "
                "Cámbialo en producción mediante variable de entorno.",
                stacklevel=2,
            )
        return v
    @field_validator("LITELLM_API_KEY", mode="before")
    @classmethod
    def ensure_api_key_in_production(
        cls, v: str | SecretStr | None, info: Any
    ) -> str | SecretStr | None:
        env = info.data.get("ENVIRONMENT", "development")
        raw = _secret_raw(v) or None
        if env == "production" and not raw:
            raise ValueError("LITELLM_API_KEY es obligatorio en entorno production")
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def guard_portal_session_key(self) -> Self:
        """Refuse insecure/missing PORTAL_SESSION_KEY in production; warn in dev."""
        raw = _secret_raw(self.PORTAL_SESSION_KEY)
        if not raw:
            raise ValueError(
                "RAG_PORTAL_SESSION_KEY is required. "
                "Generate with: openssl rand -hex 32"
            )

        try:
            _decode_session_key_bytes(raw)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        insecure = raw in _INSECURE_PORTAL_SESSION_KEYS
        if self.ENVIRONMENT == "production":
            if insecure:
                raise ValueError(
                    "PORTAL_SESSION_KEY is using the insecure development default. "
                    "Set RAG_PORTAL_SESSION_KEY to a unique secret "
                    "(openssl rand -hex 32) before starting in production."
                )
            dev_pw = _secret_raw(self.PORTAL_DEV_PASSWORD)
            if dev_pw in _INSECURE_PORTAL_DEV_PASSWORDS:
                raise ValueError(
                    "PORTAL_DEV_PASSWORD must not use the insecure development "
                    "default in production. Unset it or set a strong password."
                )
            if _secret_raw(self.POSTGRES_PASSWORD) == "changeme_in_production":
                raise ValueError(
                    "POSTGRES_PASSWORD must not use the insecure default "
                    "('changeme_in_production') in production."
                )
            if self.RAG_ADMIN_ENABLED:
                raise ValueError(
                    "RAG_ADMIN_ENABLED must be false in production. "
                    "Admin SQL/table endpoints are dev-only surfaces."
                )
            if "*" in {o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",")}:
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS='*' is not allowed in production. "
                    "Set explicit comma-separated origins."
                )
        elif insecure:
            warnings.warn(
                "SECURITY: PORTAL_SESSION_KEY is using the insecure development "
                "default. Set RAG_PORTAL_SESSION_KEY to `openssl rand -hex 32` "
                "before any real deployment.",
                stacklevel=2,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Retorna la instancia única de Settings (cacheada).

    Los overrides de Vault se aplican desde el composition root
    (infrastructure.secrets.vault.apply_vault_overrides): el core no
    depende de adaptadores de infraestructura.
    """
    return Settings()
