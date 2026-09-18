# =============================================================================
# Runtime info — visibilidad del motor de embeddings/LLM (sin secretos)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.core.runtime_info import (
    describe_model_runtime,
    embedding_runtime,
    llm_runtime,
)


@dataclass
class _FakeSettings:
    EMBEDDING_MODEL: str = "openai/baai/bge-m3"
    LITELLM_API_BASE: str = "https://api.novita.ai/openai"
    LITELLM_DEFAULT_MODEL: str = "openai/deepseek/deepseek-v3.2"
    VECTOR_DIMENSION: int = 1024


def test_embedding_runtime_detects_novita_hosted() -> None:
    info = embedding_runtime(_FakeSettings())
    assert info["provider"] == "novita"
    assert info["provider_label"] == "Novita AI (hosted)"
    assert info["served_model"] == "baai/bge-m3"
    assert info["dimension"] == 1024
    assert info["hosted"] is True
    assert info["base_url_host"] == "api.novita.ai"
    assert "api_key" not in str(info).lower()


def test_embedding_runtime_detects_ollama_local() -> None:
    settings = _FakeSettings(
        EMBEDDING_MODEL="ollama/bge-m3", LITELLM_API_BASE="http://ollama:11434"
    )
    info = embedding_runtime(settings)
    assert info["provider"] == "ollama"
    assert info["hosted"] is False
    assert info["provider_label"] == "Ollama (local)"
    assert info["served_model"] == "ollama/bge-m3"  # sin prefijo que quitar


def test_describe_model_runtime_openai_without_base() -> None:
    info = describe_model_runtime("openai/text-embedding-3-small", None)
    assert info["provider"] == "openai_compatible"
    assert info["host"] is None
    assert info["hosted"] is True


def test_llm_runtime_reports_provider_label() -> None:
    info = llm_runtime(_FakeSettings())
    assert info["provider"] == "novita"
    assert info["served_model"] == "deepseek/deepseek-v3.2"
