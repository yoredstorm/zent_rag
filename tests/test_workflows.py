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

    # Condición false → skipped (no tumba el run). Notify top-level sí corre.
    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-tr-{uuid4().hex}"},
        json={"payload": {"level": "3"}},
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded"

    detail = await async_client.get(f"/api/v1/workflows/runs/{result.json()['run_id']}", headers=h)
    steps_detail = detail.json()["steps"]
    assert steps_detail[0]["status"] == "succeeded"
    assert steps_detail[0]["retries"] == 1
    assert steps_detail[1]["status"] == "skipped"
    assert steps_detail[2]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_templates_and_paused_guard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Tpl Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    tpls = await async_client.get("/api/v1/workflows/templates", headers=h)
    assert tpls.status_code == 200, tpls.text
    templates = tpls.json()["templates"]
    assert len(templates) >= 5
    assert any(t["slug"] == "kb-digest" for t in templates)
    assert any(t["slug"] == "low-stock-alert" for t in templates)
    # Phase 32C: plantillas de negocio proactivas
    assert any(t["slug"] == "daily-executive-sales-brief" for t in templates)
    assert any(t["slug"] == "new-business-customer-verification" for t in templates)

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


@pytest.mark.asyncio
async def test_condition_then_else_branches(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Branch Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    steps = [
        {
            "type": "condition",
            "config": {"field": "trigger.stock", "operator": "<", "value": "10"},
            "then": [
                {"type": "notify", "config": {"channel": "in_app", "title": "Stock bajo", "message": "bajo"}}
            ],
            "else": [
                {"type": "notify", "config": {"channel": "in_app", "title": "Stock OK", "message": "ok"}}
            ],
        }
    ]
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-br-{uuid4().hex}"},
        json={"name": "Ramas", "steps": steps},
    )
    wid = created.json()["workflow_id"]

    low = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-brl-{uuid4().hex}"},
        json={"payload": {"stock": "3"}},
    )
    assert low.json()["status"] == "succeeded"
    d1 = await async_client.get(f"/api/v1/workflows/runs/{low.json()['run_id']}", headers=h)
    titles = [s["input"].get("title") for s in d1.json()["steps"] if s["step_type"] == "notify"]
    assert titles == ["Stock bajo"]
    assert d1.json()["steps"][0]["status"] == "succeeded"

    ok = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-bro-{uuid4().hex}"},
        json={"payload": {"stock": "40"}},
    )
    assert ok.json()["status"] == "succeeded"
    d2 = await async_client.get(f"/api/v1/workflows/runs/{ok.json()['run_id']}", headers=h)
    cond = d2.json()["steps"][0]
    assert cond["status"] == "skipped"
    titles2 = [s["input"].get("title") for s in d2.json()["steps"] if s["step_type"] == "notify"]
    assert titles2 == ["Stock OK"]


@pytest.mark.asyncio
async def test_api_call_allowlist_and_json_path(async_client: AsyncClient, monkeypatch) -> None:
    org = await _create_org(async_client, "WF Api Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organizations SET config_json = CAST(:cfg AS jsonb) WHERE id = :oid"
            ),
            {
                "oid": UUID(org["organization_id"]),
                "cfg": '{"agent": {"api_allowlist": ["stock.example.com"]}}',
            },
        )
        await session.commit()
    finally:
        await session.close()

    class _Resp:
        status_code = 200
        text = '{"quantity": 3, "sku": "ABC"}'

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url):
            assert "stock.example.com" in url
            return _Resp()

        async def post(self, url, json=None):
            return _Resp()

    import src.platform.workflows.engine as wf_engine
    from src.agents.tools.tools_builtin import CallApiTool

    async def _fake_org_cfg(_oid):
        return {"agent": {"api_allowlist": ["stock.example.com"]}}

    monkeypatch.setattr(wf_engine, "_org_config", _fake_org_cfg)
    monkeypatch.setattr(CallApiTool, "_ssrf_check", classmethod(lambda cls, host: None))
    monkeypatch.setattr(wf_engine.httpx, "AsyncClient", _Client)

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-api-{uuid4().hex}"},
        json={
            "name": "API stock",
            "steps": [
                {
                    "type": "api_call",
                    "config": {
                        "url": "https://stock.example.com/qty",
                        "method": "GET",
                        "json_path": "quantity",
                    },
                }
            ],
        },
    )
    wid = created.json()["workflow_id"]
    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-apir-{uuid4().hex}"},
        json={"payload": {}},
    )
    assert result.json()["status"] == "succeeded", result.text
    detail = await async_client.get(f"/api/v1/workflows/runs/{result.json()['run_id']}", headers=h)
    out = detail.json()["steps"][0]["output"]
    assert out["status_code"] == 200
    assert out["extracted"] == 3

    blocked = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-ssrf-{uuid4().hex}"},
        json={
            "name": "SSRF",
            "steps": [{"type": "api_call", "config": {"url": "http://127.0.0.1/secret"}}],
        },
    )
    run_b = await async_client.post(
        f"/api/v1/workflows/{blocked.json()['workflow_id']}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-ssrfr-{uuid4().hex}"},
        json={"payload": {}},
    )
    assert run_b.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_kb_query_foreign_kb_rejected(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "WF Kb A")
    org_b = await _create_org(async_client, "WF Kb B")
    org_a["session"] = await _owner_session(async_client, org_a["organization_id"])

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    foreign_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (id, organization_id, name) "
                "VALUES (:id, :oid, 'KB B')"
            ),
            {"id": foreign_id, "oid": UUID(org_b["organization_id"])},
        )
        await session.commit()
    finally:
        await session.close()

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org_a), "Idempotency-Key": f"wf-kbf-{uuid4().hex}"},
        json={
            "name": "KB ajena",
            "steps": [
                {
                    "type": "kb_query",
                    "config": {"query": "stock", "knowledge_base_id": str(foreign_id)},
                }
            ],
        },
    )
    run = await async_client.post(
        f"/api/v1/workflows/{created.json()['workflow_id']}/run",
        headers={**_headers(org_a), "Idempotency-Key": f"wf-kbfr-{uuid4().hex}"},
        json={"payload": {}},
    )
    assert run.json()["status"] == "failed"
    detail = await async_client.get(
        f"/api/v1/workflows/runs/{run.json()['run_id']}", headers=_headers(org_a)
    )
    assert "no pertenece" in (detail.json()["steps"][0]["error"] or "")


@pytest.mark.asyncio
async def test_notify_channel_webhook_skips_in_app(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Chan Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-ch-{uuid4().hex}"},
        json={
            "name": "Solo webhook",
            "steps": [
                {
                    "type": "notify",
                    "config": {
                        "channel": "webhook",
                        "title": "WF webhook only",
                        "message": "hola",
                        "data": {"sku": "ABC", "stock": 3},
                    },
                }
            ],
        },
    )
    await async_client.post(
        f"/api/v1/workflows/{created.json()['workflow_id']}/run",
        headers={**_headers(org), "Idempotency-Key": f"wf-chr-{uuid4().hex}"},
        json={"payload": {}},
    )

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        n = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM tenant_notifications "
                    "WHERE organization_id = :oid AND title = 'WF webhook only'"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert int(n) == 0


@pytest.mark.asyncio
async def test_public_hook_secret_and_scheduler(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "WF Hook Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-hk-{uuid4().hex}"},
        json={
            "name": "Inbound",
            "trigger_type": "webhook",
            "steps": [
                {"type": "notify", "config": {"channel": "in_app", "title": "hook", "message": "x"}}
            ],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    wid = body["workflow_id"]
    secret = body["hook_secret"]
    assert secret
    detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=h)
    assert detail.json()["hook_url"].endswith(f"/api/v1/public/workflows/{wid}/hook")
    assert "hook_secret" not in detail.json()
    assert detail.json()["has_hook_secret"] is True

    await async_client.post(f"/api/v1/workflows/{wid}/activate", headers={**_headers(org)})

    denied = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook", json={"sku": "ABC"}
    )
    assert denied.status_code == 401

    ok = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook",
        headers={"X-Zent-Workflow-Secret": secret},
        json={"sku": "ABC"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "succeeded"

    sched = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"wf-sc-{uuid4().hex}"},
        json={
            "name": "Cada 5",
            "trigger_type": "schedule",
            "trigger_config": {"every_minutes": 5},
            "steps": [
                {"type": "notify", "config": {"channel": "in_app", "title": "tick", "message": "t"}}
            ],
        },
    )
    swid = sched.json()["workflow_id"]
    await async_client.post(f"/api/v1/workflows/{swid}/activate", headers={**_headers(org)})

    from src.platform.workflows.engine import run_due_scheduled_workflows

    n1 = await run_due_scheduled_workflows(organization_id=UUID(org["organization_id"]))
    assert n1 >= 1
    n2 = await run_due_scheduled_workflows(organization_id=UUID(org["organization_id"]))
    assert n2 == 0

