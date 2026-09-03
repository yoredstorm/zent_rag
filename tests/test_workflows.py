# =============================================================================
# AI Workflow Automation Studio v2 (PROMPT 44)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"wf-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(client: AsyncClient, organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
        "Idempotency-Key": f"wf-{uuid4().hex}",
    }


async def _platform_admin(client: AsyncClient, email: str) -> dict:
    import hashlib as hl

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash, is_platform_admin) "
                "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', :email, :ph, true)"
            ),
            {
                "ext": f"plat-{uuid4().hex[:12]}",
                "eh": hl.sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": hash_password("secret-123"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                "WHERE lower(u.email) = lower(:email) AND pr.name = 'super_admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"email": email},
        )
        await session.commit()
    finally:
        await session.close()
    login = await client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


STEPS_OK = [
    {"type": "kb_query", "config": {"query": "manual", "limit": 3}},
    {"type": "llm", "config": {"prompt": "Resume: {{steps.0.output.count}} documentos"}},
    {"type": "condition", "config": {"field": "trigger.severity", "operator": "==", "value": "high"}},
    {"type": "notify", "config": {"channel": "in_app", "title": "WF test", "message": "ok"}},
]


@pytest.mark.asyncio
async def test_crud_and_status(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF CRUD Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-c-{uuid4().hex}"},
        json={"name": "Mi Flujo", "trigger_type": "webhook", "steps": STEPS_OK},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["name"] == "Mi Flujo"
    assert detail.json()["status"] == "draft"
    assert len(detail.json()["steps"]) == 4

    # Tipo de paso inválido → 400.
    bad = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-b-{uuid4().hex}"},
        json={"name": "Mal", "trigger_type": "event", "steps": [{"type": "hack"}]},
    )
    assert bad.status_code == 400

    updated = await async_client.patch(
        f"/api/v1/workflows/{wid}",
        headers={**_headers(org), "Idempotency-Key": f"wf-u-{uuid4().hex}"},
        json={"name": "Mi Flujo v2"},
    )
    assert updated.status_code == 200, updated.text
    detail2 = await async_client.get(f"/api/v1/workflows/{wid}", headers=h)
    assert detail2.json()["name"] == "Mi Flujo v2"

    active = await async_client.post(f"/api/v1/workflows/{wid}/activate", headers={**_headers(org)})
    assert active.json()["status"] == "active"
    paused = await async_client.post(f"/api/v1/workflows/{wid}/pause", headers={**_headers(org)})
    assert paused.json()["status"] == "paused"

    listed = await async_client.get("/api/v1/workflows", headers=h)
    assert listed.status_code == 200, listed.text
    assert any(w["id"] == wid for w in listed.json()["workflows"])

    deleted = await async_client.delete(f"/api/v1/workflows/{wid}", headers={**_headers(org)})
    assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_run_multi_step_success(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Run Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    # Un documento para el kb_query.
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO documents (id, organization_id, title, content_hash, status) "
                "VALUES (gen_random_uuid(), :oid, 'Manual de operaciones', :ch, 'active')"
            ),
            {"oid": UUID(org["organization_id"]), "ch": uuid4().hex},
        )
        await session.commit()
    finally:
        await session.close()

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-r-{uuid4().hex}"},
        json={"name": "Flujo Run", "trigger_type": "webhook", "steps": STEPS_OK},
    )
    wid = created.json()["workflow_id"]

    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-rr-{uuid4().hex}"},
        json={"payload": {"severity": "high"}},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "succeeded"
    run_id = body["run_id"]

    detail = await async_client.get(f"/api/v1/workflows/runs/{run_id}", headers=h)
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["status"] == "succeeded"
    step_types = [s["step_type"] for s in d["steps"]]
    assert step_types == ["kb_query", "llm", "condition", "notify"]
    assert all(s["status"] == "succeeded" for s in d["steps"])
    kb = d["steps"][0]
    assert kb["output"]["count"] == 1
    assert kb["output"]["documents"][0]["title"] == "Manual de operaciones"
    llm = d["steps"][1]
    assert "1" in llm["output"]["text"]
    cond = d["steps"][2]
    assert cond["output"]["result"] is True

    # La notificación se creó (paso notify).
    session = await get_async_session()
    try:
        n = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM tenant_notifications "
                    "WHERE organization_id = :oid AND title = 'WF test'"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert int(n) >= 1

    runs = await async_client.get(f"/api/v1/workflows/{wid}/runs", headers=h)
    assert runs.json()["runs"][0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_retry_and_condition_false(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Retry Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    steps = [
        {"type": "llm", "config": {"prompt": "x", "fail_once": True}, "retries": 1},
        {"type": "condition", "config": {"field": "trigger.level", "operator": ">", "value": "5"}},
        {"type": "notify", "config": {"channel": "in_app", "title": "WF retry", "message": "falló"}},
    ]
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-t-{uuid4().hex}"},
        json={"name": "Retry Flujo", "steps": steps},
    )
    wid = created.json()["workflow_id"]

    # Condición false → el run marca fail (on_error default fail).
    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-tr-{uuid4().hex}"},
        json={"payload": {"level": "3"}},
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "failed"

    detail = await async_client.get(f"/api/v1/workflows/runs/{result.json()['run_id']}", headers=h)
    steps_detail = detail.json()["steps"]
    # Paso 0: falló la 1ª vez y tuvo retry → succeeded con retries=1.
    assert steps_detail[0]["status"] == "succeeded"
    assert steps_detail[0]["retries"] == 1
    # Condición falsa: el paso condition devuelve result False, no error —
    # el paso se marca failed cuando su output.result es False.
    assert steps_detail[1]["status"] == "failed"

    # on_error continue → sigue al paso siguiente.
    steps[1]["on_error"] = "continue"
    updated = await async_client.patch(
        f"/api/v1/workflows/{wid}",
        headers={**_headers(org), "Idempotency-Key": f"wf-tu-{uuid4().hex}"},
        json={"steps": steps},
    )
    assert updated.status_code == 200
    result2 = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-tr2-{uuid4().hex}"},
        json={"payload": {"level": "3"}},
    )
    assert result2.json()["status"] == "succeeded"
    detail2 = await async_client.get(f"/api/v1/workflows/runs/{result2.json()['run_id']}", headers=h)
    assert detail2.json()["steps"][1]["status"] == "failed"  # el paso falló pero continuó
    assert detail2.json()["steps"][2]["status"] == "succeeded"  # notify sí se ejecutó


@pytest.mark.asyncio
async def test_templates_and_paused_guard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Tpl Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    tpls = await async_client.get("/api/v1/workflows/templates", headers=h)
    assert tpls.status_code == 200, tpls.text
    assert len(tpls.json()["templates"]) == 4
    assert any(t["slug"] == "kb-digest" for t in tpls.json()["templates"])

    installed = await async_client.post(
        "/api/v1/workflows/templates/kb-digest/install", headers={**_headers(org)}
    )
    assert installed.status_code == 200, installed.text
    wid = installed.json()["workflow_id"]
    detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=h)
    assert len(detail.json()["steps"]) == 3
    assert detail.json()["trigger_type"] == "schedule"

    # Pausado → run no ejecuta.
    await async_client.post(f"/api/v1/workflows/{wid}/pause", headers={**_headers(org)})
    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-tp-{uuid4().hex}"},
        json={"payload": {}},
    )
    assert result.json()["status"] == "paused"

    # Plantilla inexistente → 400.
    bad = await async_client.post(
        "/api/v1/workflows/templates/nope/install", headers={**_headers(org)}
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-wfd-{uuid4().hex[:8]}@zent.example")

    from src.platform.workflows.engine import create_workflow, run_workflow

    wf = await create_workflow(
        UUID(org["organization_id"]), "Dash Flow", "event", {}, STEPS_OK
    )
    await run_workflow(UUID(wf["workflow_id"]), {"severity": "high"})

    dash = await async_client.get("/api/v1/platform/workflows/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["total_runs"] >= 1
    assert body["success_rate"] > 0
    assert body["avg_duration_ms"] >= 0
    assert any(t["trigger_type"] == "event" for t in body["by_trigger"])
    assert any(r["workflow"] == "Dash Flow" for r in body["recent_runs"])
