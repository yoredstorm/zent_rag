# =============================================================================
# Test Suite — Fixtures compartidos para tests de API
# =============================================================================
# Provee un async client httpx que habla directo con la aplicacion FastAPI
# via ASGITransport (sin levantar servidor real). Mockea dependencias pesadas
# (Qdrant, Redis, LLM) que no estan disponibles en CI/test local.
# =============================================================================
from __future__ import annotations

import sys
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from src.domain.entities import LLMResponse, QueryStatus, RAGQueryResult


class MockRAGOrchestrator:
    """Orquestador falso que retorna respuestas controladas para tests.

    Permite inyectar una respuesta custom por test sin tocar infraestructura real.
    """

    def __init__(self, response: RAGQueryResult | None = None) -> None:
        self._response = response
        self.last_kwargs: dict = {}

    async def execute(self, **kwargs) -> RAGQueryResult:
        self.last_kwargs = kwargs
        if self._response is not None:
            return self._response
        return RAGQueryResult(
            query_id=uuid4(),
            tenant_id=kwargs.get("tenant_id", uuid4()),
            user_id=kwargs.get("user_id", uuid4()),
            query=kwargs.get("query", ""),
            status=QueryStatus.COMPLETED,
            llm_response=LLMResponse(
                content="Respuesta de prueba generada por el mock del orquestador.",
                model=kwargs.get("model") or "gpt-4o-mini",
                prompt_tokens=120,
                completion_tokens=60,
                total_tokens=180,
                latency_ms=250.0,
            ),
            total_latency_ms=350.0,
        )


@pytest.fixture
def mock_orchestrator() -> MockRAGOrchestrator:
    """Retorna un MockRAGOrchestrator fresco por test."""
    return MockRAGOrchestrator()


@pytest_asyncio.fixture
async def async_client(mock_orchestrator: MockRAGOrchestrator) -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP asincrono que habla directo con la app FastAPI.

    Sobrescribe la dependencia del orquestador RAG para evitar llamadas
    reales a Qdrant, Redis, LLM, etc.
    """
    from src.api.deps import get_rag_orchestrator
    from src.api.main import app

    app.dependency_overrides[get_rag_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def known_tenant_id() -> str:
    """UUID del tenant de desarrollo pre-seeded en la base de datos."""
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def dev_api_token() -> str:
    """Token de API de desarrollo para autenticacion Bearer."""
    return "rag_test_dev_token_for_local_testing_123"


@pytest.fixture
def unknown_tenant_id() -> str:
    """UUID de un tenant que no existe en la base de datos."""
    return "ffffffff-ffff-ffff-ffff-ffffffffffff"


@pytest.fixture
def new_tenant_id() -> str:
    """UUID unico para crear un tenant nuevo en cada test."""
    return str(uuid4())
