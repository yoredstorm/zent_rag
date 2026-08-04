# =============================================================================
# Tests para el endpoint Billing — /api/v1/billing/*
# =============================================================================
# Estos tests requieren PostgreSQL corriendo con el esquema completo
# (tablas de billing, tenants, plans pre-seeded).
# =============================================================================
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


class TestListPlans:
    """Verifica el endpoint de listado de planes."""

    @pytest.mark.asyncio
    async def test_list_plans_returns_200_with_4_plans(
        self, async_client: AsyncClient
    ) -> None:
        """GET /api/v1/billing/plans debe devolver 200 y exactamente 4 planes."""
        response = await async_client.get("/api/v1/billing/plans")

        assert response.status_code == 200
        data = response.json()
        plans = data.get("plans", [])
        assert len(plans) == 4, f"Se esperaban 4 planes, se obtuvieron {len(plans)}"
        plan_names = {p["name"] for p in plans}
        assert plan_names == {"trial", "starter", "pro", "enterprise"}


class TestCreateTrialNewTenant:
    """Verifica la creacion de trial para un tenant nuevo."""

    @pytest.mark.asyncio
    async def test_create_trial_with_new_tenant_returns_200(
        self, async_client: AsyncClient
    ) -> None:
        """POST /api/v1/billing/subscription/create-trial crea tenant server-side."""
        response = await async_client.post(
            "/api/v1/billing/subscription/create-trial",
            json={"company_name": "Test Tenant S.A.", "email": "test@example.com"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "trialing"
        assert "api_token" in data
        assert "subscription_id" in data
        assert "tenant_id" in data
        assert data["company_name"] == "Test Tenant S.A."

    @pytest.mark.asyncio
    async def test_create_trial_requires_company_name(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.post(
            "/api/v1/billing/subscription/create-trial",
            json={},
        )
        assert response.status_code == 422


class TestBearerTokenAuth:
    """Verifica autenticacion via Bearer token en el endpoint de query."""

    @pytest.mark.asyncio
    async def test_bearer_token_on_query_endpoint_returns_200(
        self, async_client: AsyncClient, trial_auth: dict[str, str]
    ) -> None:
        """POST /api/v1/rag/query con Authorization: Bearer <token_valido>
        debe autenticar al tenant via el token y devolver 200."""
        body = {"query": "Cual es el producto mas vendido de ZentStore?"}

        response = await async_client.post("/api/v1/rag/query", json=body, headers=trial_auth)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "Respuesta de prueba" in data["answer"]


class TestInvalidToken:
    """Verifica que un token invalido reciba 401."""

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, async_client: AsyncClient) -> None:
        """POST /api/v1/rag/query con un token inventado debe devolver 401
        desde el middleware de billing."""
        headers = {"Authorization": "Bearer token_totalmente_inventado_123456"}
        body = {"query": "Alguna pregunta"}

        response = await async_client.post("/api/v1/rag/query", json=body, headers=headers)

        assert response.status_code == 401
        data = response.json()
        assert "invalid" in str(data).lower() or "token" in str(data).lower()
