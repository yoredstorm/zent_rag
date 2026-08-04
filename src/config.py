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
    RAG_MAX_CONTEXT_TOKENS: int = Field(default=32000, ge=1)
    RAG_RERANK_ENABLED: bool = Field(default=False)
    RAG_RERANK_TOP_N: int = Field(default=20, ge=1, le=100)
    RAG_RERANK_MODEL: str = Field(default="")
    RAG_ADMIN_ENABLED: bool = Field(default=True)
    RAG_CHUNK_MAX_CHARS: int = Field(default=1200, ge=200, le=8000)
    RAG_CHUNK_OVERLAP: int = Field(default=150, ge=0, le=500)

    # -------------------------------------------------------------------------
    # Ingestion performance
    # -------------------------------------------------------------------------
    INGEST_EMBED_BATCH_SIZE: int = Field(default=64, ge=1, le=512)
    INGEST_EMBED_CONCURRENCY: int = Field(default=8, ge=1, le=32)
    INGEST_TABLE_CONCURRENCY: int = Field(default=3, ge=1, le=16)
    INGEST_UPSERT_BATCH_SIZE: int = Field(default=100, ge=1, le=500)
    INGEST_PAGE_SIZE: int = Field(default=1000, ge=100, le=10000)
    INGEST_SKIP_TABLES: str = Field(
        default="sales,product_reviews,inventory",
        description="Comma-separated table names to skip during sync",
    )
    INGEST_MAX_ROWS_PER_TABLE: int = Field(
        default=0,
        ge=0,
        description="Cap rows per table during ingest (0 = no cap).",
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
    AUTH_LOGIN_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=50)
    AUTH_LOGIN_WINDOW_SECONDS: int = Field(default=900, ge=60, le=86400)
    PORTAL_DEV_PASSWORD: SecretStr | None = None
    PORTAL_DEV_EMAIL: str = Field(default="demo@zenttech.com")

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
        elif insecure:
            warnings.warn(
                "SECURITY: PORTAL_SESSION_KEY is using the insecure development "
                "default. Set RAG_PORTAL_SESSION_KEY to `openssl rand -hex 32` "
                "before any real deployment.",
                stacklevel=2,
            )
        return self

    def apply_vault_overrides(self) -> None:
        """Override sensitive fields from Vault if available (falls back to .env)."""
        try:
            from src.infrastructure.vault import get_secret, vault_is_available

            if not vault_is_available():
                return
            if secret := get_secret("POSTGRES_PASSWORD"):
                object.__setattr__(self, "POSTGRES_PASSWORD", SecretStr(secret))
            if secret := get_secret("LITELLM_API_KEY"):
                object.__setattr__(self, "LITELLM_API_KEY", SecretStr(secret))
            if secret := get_secret("REDIS_URL"):
                object.__setattr__(self, "REDIS_URL", secret)
            if secret := get_secret("PORTAL_SESSION_KEY"):
                object.__setattr__(self, "PORTAL_SESSION_KEY", SecretStr(secret))
            if secret := get_secret("QDRANT_API_KEY"):
                object.__setattr__(self, "QDRANT_API_KEY", SecretStr(secret))
        except Exception:
            pass


@lru_cache
def get_settings() -> Settings:
    """Retorna la instancia única de Settings (cacheada)."""
    settings = Settings()
    settings.apply_vault_overrides()
    return settings
