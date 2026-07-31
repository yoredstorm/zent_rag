# =============================================================================
# Configuración Central — Pydantic Settings con Validación CISO-Grade
# =============================================================================
# Principio: Cero secretos hardcodeados. Todo proviene de variables de entorno
# o de un vault externo (HashiCorp Vault / Azure Key Vault). Pydantic v2
# valida tipos estrictamente para prevenir inyección de configuración.
# =============================================================================
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración central tipada de la plataforma RAG.

    Cada campo se inyecta desde variables de entorno (prefijo opcional RAG_).
    SecretsStr oculta el valor en logs/repr automáticamente.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RAG_",
        case_sensitive=False,
        extra="forbid",  # Rechaza variables de entorno no declaradas (evita typosquatting)
    )

    # -------------------------------------------------------------------------
    # Entorno y Debug
    # -------------------------------------------------------------------------
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    API_PORT: int = Field(default=8000, ge=1, le=65535)
    CORS_ALLOWED_ORIGINS: str = Field(default="*")

    # -------------------------------------------------------------------------
    # PostgreSQL
    # -------------------------------------------------------------------------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = Field(default=5432, ge=1, le=65535)
    POSTGRES_USER: str = "rag_user"
    POSTGRES_PASSWORD: SecretStr = SecretStr("changeme_in_production")
    POSTGRES_DB: str = "rag_platform"
    # El mínimo de 5 asegura que haya conexiones "warm" para el health check
    # y tráfico bajo sin incurrir en el coste de creación de nuevas conexiones.
    POSTGRES_MIN_CONNECTIONS: int = Field(default=5, ge=1)
    # El máximo de 25 permite manejar ráfagas de tráfico concurrente sin
    # agotar el pool. En producción, ajustar según recursos de RDS/Cloud SQL.
    POSTGRES_MAX_CONNECTIONS: int = Field(default=25, ge=1)

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

    # -------------------------------------------------------------------------
    # Qdrant (Vector Store)
    # -------------------------------------------------------------------------
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = Field(default=6333, ge=1, le=65535)
    QDRANT_API_KEY: SecretStr | None = None
    QDRANT_GRPC_PORT: int = Field(default=6334, ge=1, le=65535)
    QDRANT_TIMEOUT_SECONDS: int = Field(default=30, ge=5, le=120)

    # -------------------------------------------------------------------------
    # Redis
    # -------------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"

    # -------------------------------------------------------------------------
    # LiteLLM (Proxy centralizado para LLMs)
    # -------------------------------------------------------------------------
    LITELLM_API_BASE: str | None = None  # URL del proxy LiteLLM
    LITELLM_API_KEY: SecretStr | None = None
    LITELLM_DEFAULT_MODEL: str = "gpt-4o-mini"
    LITELLM_TIMEOUT_SECONDS: int = Field(default=60, ge=1, le=300)
    LITELLM_MAX_RETRIES: int = Field(default=2, ge=0, le=5)

    # -------------------------------------------------------------------------
    # RAG / Embeddings
    # -------------------------------------------------------------------------
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    VECTOR_DIMENSION: int = Field(default=1536, ge=1)
    RAG_TOP_K: int = Field(default=200, ge=1, le=500)
    RAG_SCORE_THRESHOLD: float = Field(default=0.0, ge=0.0, le=1.0)
    RAG_CONVERSATION_TTL_SECONDS: int = Field(default=3600, ge=60, le=86400)
    RAG_SQL_EXPERT_ENABLED: bool = Field(default=False)
    RAG_SQL_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)
    RAG_MAX_CONTEXT_TOKENS: int = Field(default=32000, ge=1)

    # -------------------------------------------------------------------------
    # Billing
    # -------------------------------------------------------------------------
    # NOTA: Si BILLING_ENABLED está desactivado, las rutas de admin deben seguir
    # protegidas por autenticación/autorización.
    BILLING_ENABLED: bool = Field(default=True)
    BILLING_TRIAL_REQUESTS: int = Field(default=500, ge=1)
    BILLING_TRIAL_DAYS: int = Field(default=30, ge=1, le=365)

    # -------------------------------------------------------------------------
    # Vault (HashiCorp Vault) — Preparado para integración futura
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
    RATE_LIMIT_PER_TENANT_MINUTE: int = Field(default=600, ge=1)
    MAX_PROMPT_LENGTH_CHARS: int = Field(default=32000, ge=1)
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
    # Observabilidad
    # -------------------------------------------------------------------------
    # Expone /metrics para Prometheus. Desactivar solo en entornos sin scraper.
    METRICS_ENABLED: bool = True
    TRACING_ENABLED: bool = False  # Futuro: OpenTelemetry

    # -------------------------------------------------------------------------
    # Validaciones de Seguridad
    # -------------------------------------------------------------------------
    @field_validator("POSTGRES_PASSWORD", mode="before")
    @classmethod
    def warn_default_password(cls, v: str | SecretStr) -> str | SecretStr:
        raw = v.get_secret_value() if isinstance(v, SecretStr) else str(v) if v else ""
        if raw == "changeme_in_production":
            import warnings

            warnings.warn(
                "SECURITY: POSTGRES_PASSWORD tiene el valor por defecto. "
                "Cámbialo en producción mediante variable de entorno.",
                stacklevel=2,
            )
        return v

    @field_validator("LITELLM_API_KEY", mode="before")
    @classmethod
    def ensure_api_key_in_production(cls, v: str | SecretStr | None, info) -> str | SecretStr | None:
        env = info.data.get("ENVIRONMENT", "development")
        raw = v.get_secret_value() if isinstance(v, SecretStr) else str(v) if v else None
        if env == "production" and not raw:
            raise ValueError("LITELLM_API_KEY es obligatorio en entorno production")
        return v


# -----------------------------------------------------------------------------
# Singleton cacheado — Evita re-leer .env en cada instanciación
# -----------------------------------------------------------------------------
@lru_cache
def get_settings() -> Settings:
    """Retorna la instancia única de Settings (cacheada)."""
    return Settings()
