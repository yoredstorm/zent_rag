# =============================================================================
# AI Observability Traces & Spans v2 (PROMPT 36)
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
            "email": f"tr-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"tr-{uuid4().hex}",
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


@pytest.mark.asyncio
async def test_record_list_and_detail(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TR Org")
    plat = await _platform_admin(async_client, f"padmin-tr-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from src.platform.tracing.traces import record_trace

    trace_id = f"trc_{uuid4().hex[:12]}"
    await record_trace(
        organization_id=UUID(oid),
        trace_id=trace_id,
        status="completed",
        model="gpt-4o-mini",
        input_text="¿cuál es el margen bruto?",
        output_text="El margen bruto es 35%",
        error=None,
        total_latency_ms=850.0,
        total_tokens=420,
        cost=0.0021,
        spans=[
            {"stage": "total", "name": "agent_run", "duration_ms": 850.0, "tokens": 420},
            {"stage": "llm", "name": "llm:gpt-4o-mini", "duration_ms": 600.0, "tokens": 400},
            {"stage": "retrieval", "name": "tool:search_kb", "duration_ms": 200.0, "tokens": 0, "metadata": {"tool": "search_kb"}},
        ],
        agent_id=None,
        deployment_id=None,
        run_id=uuid4(),
    )

    listed = await async_client.get(
        f"/api/v1/platform/observability/traces?organization_id={oid}", headers=plat
    )
    assert listed.status_code == 200, listed.text
    assert any(t["trace_id"] == trace_id for t in listed.json()["traces"])
    entry = next(t for t in listed.json()["traces"] if t["trace_id"] == trace_id)
    assert entry["total_latency_ms"] == pytest.approx(850.0, abs=0.1)
    assert entry["status"] == "completed"

    detail = await async_client.get(
        f"/api/v1/platform/observability/traces/{trace_id}", headers=plat
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["output"] == "El margen bruto es 35%"
    assert len(body["spans"]) == 3
    stages = {s["stage"] for s in body["spans"]}
    assert {"total", "llm", "retrieval"} <= stages
    llm = next(s for s in body["spans"] if s["stage"] == "llm")
    assert llm["duration_ms"] == pytest.approx(600.0, abs=0.1)
    assert llm["tokens"] == 400


@pytest.mark.asyncio
async def test_trace_filters_and_search(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TR Filter Org")
    plat = await _platform_admin(async_client, f"padmin-trf-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from src.platform.tracing.traces import record_trace

    for i, status in enumerate(["completed", "error"]):
        await record_trace(
            organization_id=UUID(oid),
            trace_id=f"trf_{uuid4().hex[:10]}",
            status=status,
            model="zent-cheap",
            input_text="pregunta especial de búsqueda" if i == 0 else "otra cosa",
            output_text="respuesta" if status == "completed" else "",
            error=None if status == "completed" else "llm down",
            total_latency_ms=100.0 + i,
            total_tokens=50,
            cost=0.0001,
            spans=[],
        )

    only_errors = await async_client.get(
        f"/api/v1/platform/observability/traces?organization_id={oid}&status=error", headers=plat
    )
    assert only_errors.json()["traces"]
    assert all(t["status"] == "error" for t in only_errors.json()["traces"])

    by_model = await async_client.get(
        f"/api/v1/platform/observability/traces?organization_id={oid}&model=zent-cheap", headers=plat
    )
    assert by_model.json()["traces"]

    by_query = await async_client.get(
        f"/api/v1/platform/observability/traces?organization_id={oid}&q=especial", headers=plat
    )
    assert all("especial" in (t["input"] or "") for t in by_query.json()["traces"])


@pytest.mark.asyncio
async def test_compare_traces_side_by_side(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TR Cmp Org")
    plat = await _platform_admin(async_client, f"padmin-trc-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from src.platform.tracing.traces import record_trace

    t_a = f"trc_a_{uuid4().hex[:8]}"
    t_b = f"trc_b_{uuid4().hex[:8]}"
    await record_trace(
        organization_id=UUID(oid), trace_id=t_a, status="completed", model="gpt-4o-mini",
        input_text="misma pregunta", output_text="v1", error=None,
        total_latency_ms=500.0, total_tokens=200, cost=0.001,
        spans=[
            {"stage": "llm", "name": "llm:gpt-4o-mini", "duration_ms": 400.0, "tokens": 190},
            {"stage": "tool", "name": "tool:search_kb", "duration_ms": 80.0, "tokens": 0},
        ],
    )
    await record_trace(
        organization_id=UUID(oid), trace_id=t_b, status="completed", model="zent-fast",
        input_text="misma pregunta", output_text="v2", error=None,
        total_latency_ms=900.0, total_tokens=320, cost=0.002,
        spans=[
            {"stage": "llm", "name": "llm:zent-fast", "duration_ms": 700.0, "tokens": 300},
            {"stage": "tool", "name": "tool:search_kb", "duration_ms": 150.0, "tokens": 0},
        ],
    )

    cmp = await async_client.get(
        f"/api/v1/platform/observability/traces/compare?a={t_a}&b={t_b}", headers=plat
    )
    assert cmp.status_code == 200, cmp.text
    body = cmp.json()
    assert body["same_input"] is True
    assert body["deltas"]["latency_ms"] == pytest.approx(400.0, abs=0.1)
    assert body["deltas"]["tokens"] == 120
    assert body["a"]["model"] == "gpt-4o-mini"
    assert body["b"]["model"] == "zent-fast"
    llm = next(s for s in body["spans_diff"] if s["stage"] == "llm")
    assert llm["a_duration_ms"] == pytest.approx(400.0, abs=0.1)
    assert llm["b_duration_ms"] == pytest.approx(700.0, abs=0.1)


@pytest.mark.asyncio
async def test_runtime_integration_creates_trace_with_spans(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TR Runtime Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    from src.agents.runtime.agent_runtime import AgentRuntime
    from src.api.deps import get_agent_runtime
    from src.api.main import app
    from src.infrastructure.llm.provider import LiteLLMProvider

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"tr-a-{uuid4().hex}"},
            json={"name": "TR Agent", "system_prompt": "t", "model": "gpt-4o-mini"},
        )
    ).json()

    real_runtime = AgentRuntime(llm_provider=LiteLLMProvider())

    async def fake_loop(request, ctx, config, result):
        result.spans.append({"stage": "llm", "name": "llm:gpt-4o-mini", "duration_ms": 120.0, "tokens": 60})
        result.status = "completed"
        result.answer = "respuesta traceada"
        result.total_tokens = 60
        result.cost = 0.0002

    real_runtime._run_loop = fake_loop  # type: ignore[method-assign]
    app.dependency_overrides[get_agent_runtime] = lambda: real_runtime

    run = await async_client.post(
        f"/api/v1/agents/{agent['id']}/run",
        headers={**_headers(org), "X-Trace-Id": "rt-trace-123", "Idempotency-Key": f"tr-r-{uuid4().hex}"},
        json={"message": "hola"},
    )
    assert run.status_code == 200, run.text

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        trace = (
            await session.execute(
                text("SELECT status, total_tokens, total_latency_ms FROM traces WHERE trace_id = 'rt-trace-123'")
            )
        ).fetchone()
        spans = (
            await session.execute(
                text("SELECT stage, duration_ms FROM trace_spans WHERE trace_id = 'rt-trace-123' ORDER BY started_ms")
            )
        ).fetchall()
        usage = (
            await session.execute(
                text("SELECT trace_id FROM usage_events WHERE trace_id = 'rt-trace-123' LIMIT 1")
            )
        ).fetchone()
    finally:
        await session.close()
    assert trace is not None
    assert trace.status == "completed"
    assert trace.total_tokens == 60
    stages = [s.stage for s in spans]
    assert "total" in stages
    assert "llm" in stages
    assert usage is not None and usage.trace_id == "rt-trace-123"  # correlación

    # Dashboard por etapa.
    plat = await _platform_admin(async_client, f"padmin-trd-{uuid4().hex[:8]}@zent.example")
    stages_dash = await async_client.get("/api/v1/platform/observability/stages?hours=24", headers=plat)
    assert stages_dash.status_code == 200, stages_dash.text
    assert any(s["stage"] == "llm" for s in stages_dash.json()["stages"])
