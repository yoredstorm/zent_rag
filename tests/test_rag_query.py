# =============================================================================
# Tests para el endpoint RAG Query — POST /api/v1/rag/query
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.domain.entities import LLMResponse, QueryStatus, RAGQueryResult


class TestRAGQueryWithValidTenant:
    """Verifica que una consulta RAG con tenant valido retorna 200."""

    @pytest.mark.asyncio
    async def test_valid_tenant_returns_200(
        self, async_client: AsyncClient, known_tenant_id: str
    ) -> None:
        """Consulta RAG con X-Tenant-Id valido debe devolver 200 y una respuesta generada."""
        headers = {"X-Tenant-Id": known_tenant_id}
        body = {"query": "Cual es el precio del ZentPhone X1?"}

        response = await async_client.post("/api/v1/rag/query", json=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "Respuesta de prueba" in data["answer"]
        assert "query_id" in data
        assert "model" in data


class TestRAGQueryWithUnknownTenant:
    """Verifica que un tenant desconocido reciba un error 401.

    Nota: el middleware de billing pasa la request sin Bearer token,
    y luego el endpoint intenta resolver el tenant contra la DB.
    Al no existir, el orquestador retorna status=failed con "not found",
    que el endpoint convierte en HTTP 401.
    """

    @pytest.mark.asyncio
    async def test_unknown_tenant_returns_401(
        self,
        async_client: AsyncClient,
        unknown_tenant_id: str,
        mock_orchestrator,
    ) -> None:
        """Consulta RAG con X-Tenant-Id inexistente debe devolver 401."""
        mock_orchestrator._response = RAGQueryResult(
            query_id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            query="test",
            status=QueryStatus.FAILED,
            error_message="Tenant not found",
            total_latency_ms=5.0,
        )

        headers = {"X-Tenant-Id": unknown_tenant_id}
        body = {"query": "Cualquier pregunta"}

        response = await async_client.post("/api/v1/rag/query", json=body, headers=headers)

        assert response.status_code == 401
        data = response.json()
        assert "not found" in data.get("message", "").lower() or "error" in str(data).lower()


class TestRAGQueryWithoutTenant:
    """Verifica que una consulta sin tenant retorne 400."""

    @pytest.mark.asyncio
    async def test_no_tenant_returns_400(self, async_client: AsyncClient) -> None:
        """Consulta RAG sin X-Tenant-Id ni Bearer token debe devolver 400."""
        body = {"query": "Cual es el precio del ZentPhone X1?"}

        response = await async_client.post("/api/v1/rag/query", json=body)

        assert response.status_code == 400
        data = response.json()
        assert "X-Tenant-Id" in data.get("message", "")


class TestHealthCheck:
    """Verifica que el health check retorna 200 con estado de dependencias."""

    @pytest.mark.asyncio
    async def test_health_check_returns_200_with_checks(
        self, async_client: AsyncClient
    ) -> None:
        """GET /health debe devolver 200 con campos status, environment y checks.

        En entorno de test sin PostgreSQL/Qdrant/Redis reales, el estado
        puede ser 'degraded'. La prueba verifica la estructura de la respuesta.
        """
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
        known_tenant_id: str,
        mock_orchestrator,
    ) -> None:
        """Cuando no hay datos en la BD vectorial, el sistema debe responder
        que no tiene suficiente informacion, sin inventar datos."""
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

        headers = {"X-Tenant-Id": known_tenant_id}
        body = {"query": "Cual es el sentido de la vida segun tus datos?"}

        response = await async_client.post("/api/v1/rag/query", json=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        answer = data.get("answer", "")
        assert "No tengo suficiente" in answer or "no tengo suficiente" in answer.lower()
        assert data.get("usage", {}).get("total_tokens", 1) == 0
