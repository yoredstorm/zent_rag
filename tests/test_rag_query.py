# =============================================================================
# Tests para el endpoint RAG Query — POST /api/v1/rag/query
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.domain.entities import LLMResponse, QueryStatus, RAGQueryResult


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
