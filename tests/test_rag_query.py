# =============================================================================
# Tests para el endpoint RAG Query — POST /api/v1/rag/query
# =============================================================================
from __future__ import annotations

import importlib.util
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.domain.entities import (
    LLMResponse,
    QueryStatus,
    RAGQueryResult,
    RetrievalChunk,
    RetrievalContext,
)
from src.domain.models import RAGQueryResponse, sources_for_client

_HAS_LITELLM = importlib.util.find_spec("litellm") is not None


def test_rag_query_response_lazy_ingested_defaults_false() -> None:
    payload = RAGQueryResponse(
        query_id=uuid4(),
        status="completed",
        answer="ok",
        model="none",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        latency_ms=1.0,
    )
    assert payload.lazy_ingested is False


def test_sql_method_hides_vector_sources() -> None:
    chunk = RetrievalChunk(
        document_id=uuid4(),
        content="Pañales y Toallitas FONASA",
        score=0.91,
        metadata={"image_base64": "abc"},
    )
    result = RAGQueryResult(
        tenant_id=uuid4(),
        user_id=uuid4(),
        query="último producto vendido",
        method="sql",
        retrieval_context=RetrievalContext(chunks=[chunk]),
    )
    assert sources_for_client(result) == []


def test_rag_method_keeps_vector_sources() -> None:
    chunk = RetrievalChunk(
        document_id=uuid4(),
        content="Pañales y Toallitas FONASA",
        score=0.91,
    )
    result = RAGQueryResult(
        tenant_id=uuid4(),
        user_id=uuid4(),
        query="qué pañales hay",
        method="rag",
        retrieval_context=RetrievalContext(chunks=[chunk]),
    )
    out = sources_for_client(result)
    assert len(out) == 1
    assert "Pañales" in out[0].content


class TestRAGQueryWithValidTenant:
    """Verifica que una consulta RAG con Bearer valido retorna 200."""

    @pytest.mark.asyncio
    async def test_valid_tenant_returns_200(
        self, async_client: AsyncClient, trial_auth: dict[str, str]
    ) -> None:
        body = {"query": "Cual es el precio del ZentPhone X1?"}

        response = await async_client.post(
            "/api/v1/rag/query", json=body, headers=trial_auth
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "Respuesta de prueba" in data["answer"]
        assert "query_id" in data
        assert "model" in data
        assert data.get("lazy_ingested") is False


class TestRAGQueryRequiresBearer:
    """Sin Bearer → 401."""

    @pytest.mark.asyncio
    async def test_missing_bearer_returns_401(
        self,
        async_client: AsyncClient,
        unknown_tenant_id: str,
    ) -> None:
        headers = {"X-Tenant-Id": unknown_tenant_id}
        body = {"query": "Cualquier pregunta"}

        response = await async_client.post("/api/v1/rag/query", json=body, headers=headers)

        assert response.status_code == 401
        data = response.json()
        assert data.get("error_code") == "missing_token"


class TestRAGQueryWithoutTenant:
    """Verifica que una consulta sin auth retorne 401."""

    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, async_client: AsyncClient) -> None:
        body = {"query": "Cual es el precio del ZentPhone X1?"}

        response = await async_client.post("/api/v1/rag/query", json=body)

        assert response.status_code == 401
        data = response.json()
        assert data.get("error_code") == "missing_token"


class TestHealthCheck:
    """Verifica que el health check retorna 200 con estado de dependencias."""

    @pytest.mark.asyncio
    async def test_health_check_returns_200_with_checks(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "environment" in data
        assert "checks" in data or "version" in data


class TestAntiHallucination:
    """Verifica que el sistema no alucina cuando no hay datos de contexto."""

    @pytest.mark.asyncio
    async def test_no_data_returns_no_tengo_suficiente_informacion(
        self,
        async_client: AsyncClient,
        trial_auth: dict[str, str],
        mock_orchestrator,
    ) -> None:
        mock_orchestrator._response = RAGQueryResult(
            query_id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            query="Pregunta sin datos",
            status=QueryStatus.COMPLETED,
            llm_response=LLMResponse(
                content="No tengo suficiente informacion para responder esta pregunta. Podrias reformularla o consultar sobre otro tema?",
                model="none",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
            total_latency_ms=10.0,
        )

        body = {"query": "Cual es el sentido de la vida segun tus datos?"}

        response = await async_client.post(
            "/api/v1/rag/query", json=body, headers=trial_auth
        )

        assert response.status_code == 200
        data = response.json()
        answer = data.get("answer", "")
        assert "No tengo suficiente" in answer or "no tengo suficiente" in answer.lower()
        assert data.get("usage", {}).get("total_tokens", 1) == 0


class TestSqlQueryAdminOnly:
    """sql_query solo se expone a role=admin cuando method=sql."""

    @pytest.mark.asyncio
    async def test_admin_receives_sql_query(
        self,
        async_client: AsyncClient,
        trial_auth: dict[str, str],
        mock_orchestrator,
    ) -> None:
        mock_orchestrator._response = RAGQueryResult(
            query_id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            query="Cuantas ventas?",
            role="admin",
            status=QueryStatus.COMPLETED,
            llm_response=LLMResponse(
                content="Hay 42 ventas.",
                model="gpt-4o-mini",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            total_latency_ms=100.0,
            method="sql",
            sql_query="SELECT COUNT(*) FROM sales",
        )
        response = await async_client.post(
            "/api/v1/rag/query",
            json={"query": "Cuantas ventas?", "role": "admin"},
            headers={**trial_auth, "X-User-Role": "admin"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "sql"
        assert data["sql_query"] == "SELECT COUNT(*) FROM sales"

    @pytest.mark.asyncio
    async def test_customer_does_not_receive_sql_query(
        self,
        async_client: AsyncClient,
        trial_auth: dict[str, str],
        mock_orchestrator,
    ) -> None:
        mock_orchestrator._response = RAGQueryResult(
            query_id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            query="Cuantas ventas?",
            role="customer",
            status=QueryStatus.COMPLETED,
            llm_response=LLMResponse(
                content="Hay 42 ventas.",
                model="gpt-4o-mini",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            total_latency_ms=100.0,
            method="sql",
            sql_query="SELECT COUNT(*) FROM sales",
        )
        response = await async_client.post(
            "/api/v1/rag/query",
            json={"query": "Cuantas ventas?", "role": "customer"},
            headers={**trial_auth, "X-User-Role": "customer"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "sql"
        assert data.get("sql_query") is None


@pytest.mark.skipif(not _HAS_LITELLM, reason="API tests require litellm")
class TestLazyIngestedFlag:
    """lazy_ingested se propaga en RAGQueryResponse solo cuando el orchestrator lo marca."""

    @pytest.mark.asyncio
    async def test_query_response_includes_lazy_ingested_true(
        self,
        async_client: AsyncClient,
        trial_auth: dict[str, str],
        mock_orchestrator,
    ) -> None:
        mock_orchestrator._response = RAGQueryResult(
            query_id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            query="precio del paracetamol",
            status=QueryStatus.COMPLETED,
            llm_response=LLMResponse(
                content="El paracetamol cuesta $1.990",
                model="gpt-4o-mini",
                prompt_tokens=10,
                completion_tokens=8,
                total_tokens=18,
            ),
            total_latency_ms=80.0,
            lazy_ingested=True,
        )
        response = await async_client.post(
            "/api/v1/rag/query",
            json={"query": "precio del paracetamol"},
            headers=trial_auth,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lazy_ingested"] is True
        assert "lazy_rows_indexed" not in data
        assert "lazy_tables" not in data
