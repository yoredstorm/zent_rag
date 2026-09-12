# =============================================================================
# Cognitive OS API — Phase 3 (planning runs, persistidos y tenant-scoped)
# =============================================================================
from __future__ import annotations

from uuid import uuid4


async def _trial_headers(async_client) -> dict[str, str]:
    resp = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": "Cognitive Co",
            "email": f"cog-{uuid4().hex[:8]}@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    auth = resp.json()
    return {
        "Authorization": f"Bearer {auth['api_token']}",
        "X-Organization-Id": auth["organization_id"],
    }


async def test_cognitive_flag_off_returns_503(async_client, monkeypatch) -> None:
    from src.core.config import get_settings

    monkeypatch.setenv("RAG_COGNITIVE_OS_ENABLED", "off")
    get_settings.cache_clear()
    try:
        headers = await _trial_headers(async_client)
        resp = await async_client.post(
            "/api/v1/cognitive/runs",
            headers=headers,
            json={"query": "¿Dónde está la política de vacaciones?"},
        )
        assert resp.status_code == 503, resp.text
    finally:
        get_settings.cache_clear()


async def test_cognitive_plan_created_and_tenant_scoped(
    async_client, monkeypatch
) -> None:
    from src.core.config import get_settings

    monkeypatch.setenv("RAG_COGNITIVE_OS_ENABLED", "limited")
    get_settings.cache_clear()
    try:
        headers = await _trial_headers(async_client)
        created = await async_client.post(
            "/api/v1/cognitive/runs",
            headers=headers,
            json={
                "query": (
                    "Analiza todos los contratos de proveedores, identifica "
                    "riesgos, contradicciones y cambios en los últimos tres años."
                )
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["run"]["complexity"] == "L5"
        assert body["run"]["status"] == "planned"
        assert len(body["tasks"]) >= 8

        run_id = body["run"]["id"]
        detail = await async_client.get(
            f"/api/v1/cognitive/runs/{run_id}", headers=headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["id"] == run_id

        tasks = await async_client.get(
            f"/api/v1/cognitive/runs/{run_id}/tasks", headers=headers
        )
        assert tasks.status_code == 200, tasks.text
        assert len(tasks.json()["tasks"]) == len(body["tasks"])

        messages = await async_client.get(
            f"/api/v1/cognitive/runs/{run_id}/messages", headers=headers
        )
        assert messages.status_code == 200
        assert messages.json()["messages"] == []

        # cross-tenant: otro token no ve el run
        other = await _trial_headers(async_client)
        foreign = await async_client.get(
            f"/api/v1/cognitive/runs/{run_id}", headers=other
        )
        assert foreign.status_code == 404
    finally:
        get_settings.cache_clear()
