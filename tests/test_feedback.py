# =============================================================================
# Sentiment & Feedback Analytics (PROMPT 40)
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
            "email": f"fb-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"fb-{uuid4().hex}",
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
async def test_submit_and_upsert_by_run(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "FB Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    run_id = str(uuid4())
    agent_id = str(uuid4())

    created = await async_client.post(
        "/api/v1/feedback",
        headers={**_headers(org), "Idempotency-Key": f"fb-c-{uuid4().hex}"},
        json={"rating": "down", "agent_id": agent_id, "run_id": run_id, "reason": "too_slow"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "created"

    updated = await async_client.post(
        "/api/v1/feedback",
        headers={**_headers(org), "Idempotency-Key": f"fb-u-{uuid4().hex}"},
        json={"rating": "up", "agent_id": agent_id, "run_id": run_id},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "updated"

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text("SELECT COUNT(*) FROM feedback WHERE run_id = :rid"),
                {"rid": UUID(run_id)},
            )
        ).scalar()
        rating = (
            await session.execute(
                text("SELECT rating FROM feedback WHERE run_id = :rid"),
                {"rid": UUID(run_id)},
            )
        ).scalar()
    finally:
        await session.close()
    assert count == 1  # upsert, no duplicado
    assert rating == "up"

    bad = await async_client.post(
        "/api/v1/feedback",
        headers={**_headers(org), "Idempotency-Key": f"fb-b-{uuid4().hex}"},
        json={"rating": "meh"},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_analytics_csat_nps_by_agent(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "FB Ana Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-fba-{uuid4().hex[:8]}@zent.example")
    agent_a = str(uuid4())

    from src.platform.feedback.feedback import submit_feedback

    for _ in range(3):
        await submit_feedback(UUID(org["organization_id"]), "up", agent_id=UUID(agent_a))
    for _ in range(1):
        await submit_feedback(UUID(org["organization_id"]), "down", agent_id=UUID(agent_a))

    tenant_ana = await async_client.get("/api/v1/feedback/analytics", headers={**_headers(org)})
    assert tenant_ana.status_code == 200, tenant_ana.text
    body = tenant_ana.json()
    assert body["total_feedback"] == 4
    assert body["csat"] == pytest.approx(0.75, abs=0.001)
    assert body["nps"] == pytest.approx(50.0, abs=0.1)
    entry = next(a for a in body["by_agent"] if a["agent_id"] == agent_a)
    assert entry["ups"] == 3
    assert entry["downs"] == 1
    assert entry["nps"] == pytest.approx(50.0, abs=0.1)

    global_ana = await async_client.get("/api/v1/platform/feedback/analytics", headers=plat)
    assert global_ana.status_code == 200, global_ana.text
    assert global_ana.json()["total_feedback"] >= 4


@pytest.mark.asyncio
async def test_negative_breakdown_with_correlation(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "FB Neg Org")
    plat = await _platform_admin(async_client, f"padmin-fbn-{uuid4().hex[:8]}@zent.example")

    from src.platform.feedback.feedback import submit_feedback
    from src.platform.tracing.traces import record_trace

    for i, reason in enumerate(["too_slow", "wrong_answer", "too_slow"]):
        trace_id = f"fb-neg-{i}"
        await record_trace(
            organization_id=UUID(org["organization_id"]),
            trace_id=trace_id,
            status="completed",
            model="gpt-4o-mini",
            input_text=f"pregunta {i}",
            output_text="respuesta " * (20 + i),
            error=None,
            total_latency_ms=900.0 + i * 400,
            total_tokens=300 + i * 100,
            cost=0.001,
            spans=[],
        )
        await submit_feedback(
            UUID(org["organization_id"]),
            "down",
            run_id=uuid4(),
            trace_id=trace_id,
            reason=reason,
        )

    neg = await async_client.get(
        f"/api/v1/platform/feedback/negative?organization_id={org['organization_id']}", headers=plat
    )
    assert neg.status_code == 200, neg.text
    body = neg.json()
    assert body["total_negative"] == 3
    reasons = {r["reason"]: r["total"] for r in body["by_reason"]}
    assert reasons["too_slow"] == 2
    assert reasons["wrong_answer"] == 1
    assert body["correlation"]["avg_latency_ms"] == pytest.approx(1300.0, abs=0.1)
    assert body["correlation"]["avg_tokens"] == pytest.approx(400.0, abs=0.1)
    assert body["correlation"]["avg_output_length"] is not None
    assert body["correlation"]["max_latency_ms"] == pytest.approx(1700.0, abs=0.1)


@pytest.mark.asyncio
async def test_trends_series(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "FB Tr Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.feedback.feedback import submit_feedback

    for i in range(4):
        await submit_feedback(UUID(org["organization_id"]), "up" if i % 2 == 0 else "down")

    trends = await async_client.get("/api/v1/feedback/trends?days=14", headers=h)
    assert trends.status_code == 200, trends.text
    series = trends.json()["series"]
    assert series
    today = series[-1]
    assert today["ups"] >= 2
    assert today["downs"] >= 2
    assert today["csat"] == pytest.approx(0.5, abs=0.01)
