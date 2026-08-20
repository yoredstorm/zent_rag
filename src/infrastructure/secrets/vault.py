# =============================================================================
# Vault Secret Loader — HashiCorp Vault integration with .env fallback
# =============================================================================
# If VAULT_ADDR is set, authenticates and reads secrets from Vault.
# Otherwise falls back to environment variables (.env).
# Supports token and approle authentication.
# =============================================================================
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import SecretStr

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_vault_client: Any = None
_vault_available: bool | None = None


def _get_vault_client() -> Any | None:
    global _vault_client, _vault_available
    if _vault_available is not None:
        return _vault_client

    try:
        import hvac  # type: ignore[import-untyped]
    except ImportError:
        logger.info("hvac not installed — Vault integration disabled")
        _vault_available = False
        return None

    from src.core.config import get_settings
    settings = get_settings()

    if not settings.VAULT_ADDR:
        logger.info("VAULT_ADDR not configured — using .env fallback")
        _vault_available = False
        return None

    try:
        client = hvac.Client(url=settings.VAULT_ADDR)

        if settings.VAULT_TOKEN:
            raw = settings.VAULT_TOKEN.get_secret_value() if hasattr(settings.VAULT_TOKEN, "get_secret_value") else ""
            if raw:
                client.token = raw
                if client.is_authenticated():
                    logger.info("Vault authenticated via token")
                    _vault_available = True
                    _vault_client = client
                    return client

        logger.warning("Vault authentication failed — falling back to .env")
    except Exception as exc:
        logger.warning("Vault connection failed, falling back to .env", error=str(exc))

    _vault_available = False
    return None


@lru_cache(maxsize=1)
def _get_vault_secrets() -> dict[str, str]:
    client = _get_vault_client()
    if client is None:
        return {}

    from src.core.config import get_settings
    settings = get_settings()
    path = f"{settings.VAULT_MOUNT_POINT}/data/{settings.VAULT_PATH}"

    try:
        response = client.secrets.kv.v2.read_secret_version(path=path)
        secrets: dict[str, str] = response.get("data", {}).get("data", {})
        logger.info("Secrets loaded from Vault", path=path, keys=len(secrets))
        return secrets
    except Exception as exc:
        logger.warning("Failed to read Vault secrets", path=path, error=str(exc))
        return {}


def get_secret(key: str, fallback: str = "") -> str:
    """Retorna un secreto de Vault si está disponible, o el fallback (.env)."""
    secrets = _get_vault_secrets()
    if key in secrets:
        return secrets[key]
    return fallback


def vault_is_available() -> bool:
    return _get_vault_client() is not None


def apply_vault_overrides(settings: Any) -> None:
    """Override sensitive fields from Vault if available (falls back to .env).

    Se invoca desde el composition root (api/main.py, worker) DESPUÉS de
    crear Settings; el core no depende de infrastructure.
    """
    if not settings.VAULT_ADDR:
        return
    try:
        if not vault_is_available():
            raise RuntimeError("Vault configured but not available")
        if secret := get_secret("POSTGRES_PASSWORD"):
            object.__setattr__(settings, "POSTGRES_PASSWORD", SecretStr(secret))
        if secret := get_secret("LITELLM_API_KEY"):
            object.__setattr__(settings, "LITELLM_API_KEY", SecretStr(secret))
        if secret := get_secret("REDIS_URL"):
            object.__setattr__(settings, "REDIS_URL", secret)
        if secret := get_secret("PORTAL_SESSION_KEY"):
            object.__setattr__(settings, "PORTAL_SESSION_KEY", SecretStr(secret))
        if secret := get_secret("QDRANT_API_KEY"):
            object.__setattr__(settings, "QDRANT_API_KEY", SecretStr(secret))
    except Exception as exc:
        # Fail-closed: con Vault configurado, correr con secretos de
        # .env (posiblemente defaults) es peor que no arrancar.
        if settings.ENVIRONMENT == "production":
            raise RuntimeError(
                "Vault is configured (VAULT_ADDR) but secrets could not be "
                "loaded. Refusing to start with fallback secrets."
            ) from exc
        import warnings as _warnings

        _warnings.warn(
            "Vault configured but unavailable; falling back to .env secrets.",
            stacklevel=2,
        )
