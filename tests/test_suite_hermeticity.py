# =============================================================================
# Guard: la suite no llama proveedores LLM reales por accidente.
# =============================================================================
# `tests/conftest.py` vacía las credenciales de LLM, embeddings y JEV salvo
# opt-in explícito (`RAG_TEST_REAL_LLM=1` o `RAG_CERT_REAL_LLM=1`). Sin este
# guard, un `.env` local con proveedor real gasta créditos y alarga la suite
# (cada turno del planner espera al proveedor).
# =============================================================================
from __future__ import annotations

import os

import pytest

from src.core.config import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RAG_TEST_REAL_LLM") == "1"
    or os.environ.get("RAG_CERT_REAL_LLM") == "1",
    reason="live LLM opt-in",
)


def test_llm_providers_are_disabled_for_the_suite() -> None:
    settings = get_settings()
    assert settings.LITELLM_API_KEY is None
    assert not settings.GATEWAY_FALLBACK_API_KEY
    assert not settings.EMBEDDING_FALLBACK_API_KEY
    assert not settings.JEV_API_KEY
    assert settings.LITELLM_TIMEOUT_SECONDS <= 10
    assert settings.LITELLM_MAX_RETRIES == 0
