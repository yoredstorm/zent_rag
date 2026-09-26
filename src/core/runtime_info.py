# =============================================================================
# Runtime info — qué motor de embeddings/LLM está usando esta instancia
# =============================================================================
# Deriva un resumen legible (sin secretos) de la configuración efectiva para
# exponerlo en /api/v1/platform/settings y en el portal. Nunca devuelve keys.
# =============================================================================
from __future__ import annotations

from urllib.parse import urlparse

_LOCAL_PROVIDERS = {"ollama", "local"}

_PROVIDER_LABELS = {
    "novita": "Novita AI (hosted)",
    "deepinfra": "DeepInfra (hosted)",
    "openai": "OpenAI (hosted)",
    "openai_compatible": "Endpoint compatible OpenAI (hosted)",
    "azure": "Azure OpenAI (hosted)",
    "cohere": "Cohere (hosted)",
    "voyage": "Voyage AI (hosted)",
    "jina": "Jina AI (hosted)",
    "mistral": "Mistral AI (hosted)",
    "ollama": "Ollama (local)",
    "local": "Local",
}


def _host(base_url: str | None) -> str | None:
    if not base_url:
        return None
    parsed = urlparse(str(base_url))
    return parsed.netloc or parsed.path or None


def describe_model_runtime(model: str, base_url: str | None) -> dict:
    """Describe un modelo LiteLLM: proveedor real, host y si es local."""
    model = (model or "").strip()
    provider = model.split("/", 1)[0].lower() if "/" in model else "unknown"
    host = _host(base_url)
    hosted = provider not in _LOCAL_PROVIDERS

    if provider == "openai" and host and "novita" in host.lower():
        provider = "novita"
    elif provider == "openai" and host and "deepinfra" in host.lower():
        provider = "deepinfra"
    elif provider == "openai" and not host:
        provider = "openai_compatible"

    # Modelo realmente servido: en LiteLLM el prefijo es el proveedor
    # (openai/baai/bge-m3 → baai/bge-m3 en el endpoint OpenAI-compatible).
    strip_prefix = provider in ("novita", "deepinfra", "openai_compatible")
    served = model.split("/", 1)[1] if strip_prefix and "/" in model else model
    return {
        "provider": provider,
        "provider_label": _PROVIDER_LABELS.get(provider, f"{provider} (hosted)"),
        "model": model,
        "served_model": served,
        "host": host,
        "hosted": hosted,
    }


def embedding_runtime(settings) -> dict:
    """Resumen del motor de embeddings activo (sin secretos)."""
    info = describe_model_runtime(
        str(getattr(settings, "EMBEDDING_MODEL", "") or ""),
        getattr(settings, "LITELLM_API_BASE", None),
    )
    info["dimension"] = int(getattr(settings, "VECTOR_DIMENSION", 0) or 0)
    info["base_url_host"] = info.pop("host")

    # Respaldo: sólo informa si está configurado y con key. Nunca expone la key.
    fallback_model = str(getattr(settings, "EMBEDDING_FALLBACK_MODEL", "") or "").strip()
    fallback_key = getattr(settings, "EMBEDDING_FALLBACK_API_KEY", None)
    key_defined = fallback_key is not None and bool(fallback_key.get_secret_value())
    fallback = describe_model_runtime(
        fallback_model,
        getattr(settings, "EMBEDDING_FALLBACK_API_BASE", None),
    )
    fallback["enabled"] = bool(fallback_model) and key_defined
    fallback["base_url_host"] = fallback.pop("host")
    if not fallback_model:
        fallback["provider"] = None
        fallback["provider_label"] = None
        fallback["served_model"] = None
    info["fallback"] = fallback
    return info


def llm_runtime(settings) -> dict:
    """Resumen del LLM por defecto (sin secretos)."""
    return describe_model_runtime(
        str(getattr(settings, "LITELLM_DEFAULT_MODEL", "") or ""),
        getattr(settings, "LITELLM_API_BASE", None),
    )
