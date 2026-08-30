# =============================================================================
# Test Suite — Fixtures compartidos para tests de API
# =============================================================================
# Provee un async client httpx que habla directo con la aplicacion FastAPI
# via ASGITransport (sin levantar servidor real). Mockea dependencias pesadas
# (Qdrant, Redis, LLM) que no estan disponibles en CI/test local.
# =============================================================================
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

# Allow running pytest from a worktree without a local .env. Same documented
# development default as .env.example / CI (production still refuses it).
os.environ.setdefault(
    "RAG_PORTAL_SESSION_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)
os.environ.setdefault("RAG_ENVIRONMENT", "development")
# Match docker-compose defaults so local pytest can talk to rag-redis / rag-qdrant.
os.environ.setdefault(
    "RAG_REDIS_URL",
    "redis://:dev-redis-password-change-me@localhost:6379/0",
)
# Prefixed RAG_QDRANT_API_KEY is extra=forbid when QDRANT_API_KEY uses AliasChoices.
os.environ.pop("RAG_QDRANT_API_KEY", None)
os.environ.setdefault("QDRANT_API_KEY", "dev-qdrant-key-change-me")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from src.core.domain.entities import LLMResponse, QueryStatus, RAGQueryResult


def attach_auto_idempotency(client: AsyncClient) -> AsyncClient:
    """Añade Idempotency-Key en mutaciones required salvo X-Skip-Idempotency-Auto."""
    from src.api.idempotency_middleware import is_idempotency_required

    original = client.request

    async def request(method: str, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        skip = any(k.lower() == "x-skip-idempotency-auto" for k in headers)
        if skip:
            headers = {
                k: v for k, v in headers.items() if k.lower() != "x-skip-idempotency-auto"
            }
        path = str(url).split("?", 1)[0]
        has_key = any(k.lower() == "idempotency-key" for k in headers)
        if not skip and not has_key and is_idempotency_required(method, path):
            headers["Idempotency-Key"] = uuid4().hex
        kwargs["headers"] = headers
        return await original(method, url, **kwargs)

    client.request = request  # type: ignore[method-assign]
    return client


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
            organization_id=kwargs.get("organization_id", uuid4()),
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
        yield attach_auto_idempotency(client)

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def _reset_rate_limits() -> AsyncGenerator[None, None]:
    """Limpia contadores de rate-limit (Redis + in-memory) entre tests.

    Los tests de auth registran fallos bajo ip:testclient que persisten en
    Redis local entre ejecuciones y contaminan tests posteriores.
    """
    from src.api.idempotency_middleware import reset_memory_idempotency
    from src.platform.auth.rate_limit import (
        clear_auth_failures,
        reset_memory_rate_limits,
    )

    reset_memory_rate_limits()
    reset_memory_idempotency()
    await clear_auth_failures("ip:testclient", "ip:127.0.0.1")
    yield
    from src.infrastructure.redis.cache import close_redis_connection

    await close_redis_connection()


@pytest_asyncio.fixture(autouse=True)
async def _ensure_developer_scopes() -> None:
    """Inserta rag:read / rag:write / agents:execute si la DB local es anterior."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO permissions (id, code, description) VALUES
                    ('40000000-0000-0000-0000-000000000023', 'rag:read',
                     'Leer / consultar RAG (chat)'),
                    ('40000000-0000-0000-0000-000000000024', 'rag:write',
                     'Escribir en RAG (ingestion, fuentes, KBs)'),
                    ('40000000-0000-0000-0000-000000000025', 'agents:execute',
                     'Ejecutar agentes'),
                    ('40000000-0000-0000-0000-000000000026', 'admin:sql',
                     'Ejecutar SQL de solo lectura (consola admin)'),
                    ('40000000-0000-0000-0000-000000000027', 'prompt:read',
                     'Ver system prompts de la organización'),
                    ('40000000-0000-0000-0000-000000000028', 'prompt:write',
                     'Editar system prompts de la organización')
                ON CONFLICT (code) DO NOTHING
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
                WHERE r.organization_id IS NULL AND r.name = 'owner'
                ON CONFLICT DO NOTHING
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
                WHERE r.organization_id IS NULL AND r.name = 'admin'
                  AND p.code <> 'billing:write'
                ON CONFLICT DO NOTHING
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
                WHERE r.organization_id IS NULL AND r.name = 'member'
                  AND p.code IN ('rag:read', 'rag:write', 'agents:execute')
                ON CONFLICT DO NOTHING
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
                WHERE r.organization_id IS NULL AND r.name = 'viewer'
                  AND p.code IN ('rag:read')
                ON CONFLICT DO NOTHING
                """
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@pytest_asyncio.fixture
async def trial_auth(async_client: AsyncClient) -> dict[str, str]:
    """Crea un trial fresco y retorna headers Authorization + X-Organization-Id."""
    response = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Test Co {uuid4().hex[:8]}",
            "email": f"test-{uuid4().hex[:8]}@example.com",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {
        "Authorization": f"Bearer {data['api_token']}",
        "X-Organization-Id": data["organization_id"],
    }


@pytest.fixture
def known_organization_id() -> str:
    """UUID del organization de desarrollo pre-seeded en la base de datos."""
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def dev_api_token() -> str:
    """Token de API de desarrollo para autenticacion Bearer."""
    return "rag_test_dev_token_for_local_testing_123"


@pytest.fixture
def unknown_organization_id() -> str:
    """UUID de un organization que no existe en la base de datos."""
    return "ffffffff-ffff-ffff-ffff-ffffffffffff"


@pytest.fixture
def new_organization_id() -> str:
    """UUID unico para crear un organization nuevo en cada test."""
    return str(uuid4())
