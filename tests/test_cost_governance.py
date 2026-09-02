# =============================================================================
# Cost Governance & FinOps v2 (PROMPT 29)
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
            "email": f"cg-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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


async def _seed_event(
    organization_id: UUID,
    cost: float,
    tags: dict | None = None,
    days_ago: int = 0,
) -> None:
    import json

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, "
                "model, total_tokens, status, estimated_cost, actual_cost, cost_tags, "
                "created_at) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 100, "
                "'completed', :cost, :cost, :tags, NOW() - make_interval(days => :ago))"
            ),
            {
                "oid": organization_id,
                "cost": cost,
                "tags": json.dumps(tags or {}),
                "ago": days_ago,
            },
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_cost_tags_crud_and_breakdown(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CG Tags Org")
    plat = await _platform_admin(async_client, f"padmin-cgt-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    created = await async_client.post(
        "/api/v1/platform/cost-governance/tags",
        headers=plat,
        json={"organization_id": oid, "key": "team", "value": "finanzas"},
    )
    assert created.status_code == 201, created.text
    dup = await async_client.post(
        "/api/v1/platform/cost-governance/tags",
        headers=plat,
        json={"organization_id": oid, "key": "team", "value": "finanzas"},
    )
    assert dup.status_code == 201, dup.text
    assert dup.json()["status"] == "exists"

    await _seed_event(UUID(oid), 1.5, {"team": "finanzas"})
    await _seed_event(UUID(oid), 0.5, {"team": "ops"})
    await _seed_event(UUID(oid), 2.0, {"team": "finanzas"})

    costs = await async_client.get(
        f"/api/v1/platform/cost-governance/costs?key=team&days=30&organization_id={oid}",
        headers=plat,
    )
    assert costs.status_code == 200, costs.text
    body = costs.json()
    assert body["total"] == pytest.approx(4.0, abs=1e-3)
    by_value = {b["tag_value"]: b for b in body["breakdown"]}
    assert by_value["finanzas"]["cost"] == pytest.approx(3.5, abs=1e-3)
    assert by_value["finanzas"]["requests"] == 2
    assert by_value["ops"]["cost"] == pytest.approx(0.5, abs=1e-3)

    tags = await async_client.get(
        f"/api/v1/platform/cost-governance/tags?organization_id={oid}", headers=plat
    )
    assert tags.json()["tags"][0]["key"] == "team"
    tag_id = tags.json()["tags"][0]["id"]
    deleted = await async_client.delete(f"/api/v1/platform/cost-governance/tags/{tag_id}", headers=plat)
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_showback_by_team(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "CG SB A")
    org_b = await _create_org(async_client, "CG SB B")
    plat = await _platform_admin(async_client, f"padmin-cgs-{uuid4().hex[:8]}@zent.example")
    TEAM_A = f"team-a-{uuid4().hex[:6]}"
    TEAM_B = f"team-b-{uuid4().hex[:6]}"

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE organizations SET cost_team = :team WHERE id = :oid"),
            {"team": TEAM_A, "oid": UUID(org_a["organization_id"])},
        )
        await session.commit()
    finally:
        await session.close()

    await _seed_event(UUID(org_a["organization_id"]), 3.0)
    await _seed_event(UUID(org_b["organization_id"]), 1.0, {"team": TEAM_B})

    sb = await async_client.get(
        "/api/v1/platform/cost-governance/showback?days=30", headers=plat
    )
    assert sb.status_code == 200, sb.text
    teams = {t["team"]: t for t in sb.json()["teams"]}
    assert teams[TEAM_A]["cost"] == pytest.approx(3.0, abs=1e-3)
    assert teams[TEAM_B]["cost"] == pytest.approx(1.0, abs=1e-3)
    # Share = cost/total global (el total incluye otras orgs de la suite).
    total = sb.json()["total_cost"]
    assert total >= 4.0
    assert teams[TEAM_A]["share_pct"] == pytest.approx(3.0 / total * 100, abs=0.1)
    assert teams[TEAM_B]["share_pct"] == pytest.approx(1.0 / total * 100, abs=0.1)


@pytest.mark.asyncio
async def test_adaptive_alert_baseline_and_dedupe(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CG Alert Org")
    plat = await _platform_admin(async_client, f"padmin-cga-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Baseline: 6 días previos a $1/día.
    for d in range(1, 7):
        await _seed_event(UUID(oid), 1.0, days_ago=d)
    # Hoy: pico de $5 (baseline $1 + 20% → umbral $1.20 → dispara).
    await _seed_event(UUID(oid), 5.0, days_ago=0)

    rule = await async_client.post(
        "/api/v1/platform/cost-governance/alerts/rules",
        headers=plat,
        json={"organization_id": oid, "category": "total", "threshold_pct": 20, "adaptive": True},
    )
    assert rule.status_code == 201, rule.text
    rule_id = rule.json()["id"]

    run = await async_client.post(
        f"/api/v1/platform/cost-governance/alerts/run?organization_id={oid}", headers=plat
    )
    assert run.status_code == 200, run.text
    assert run.json()["fired"][0]["rule_id"] == rule_id
    assert run.json()["fired"][0]["today_cents"] == pytest.approx(500.0, abs=0.1)
    assert run.json()["fired"][0]["baseline_daily_cents"] == pytest.approx(100.0, abs=0.1)

    # Dedupe: segundo run no dispara de nuevo (UNIQUE rule_id + triggered_at).
    run2 = await async_client.post(
        f"/api/v1/platform/cost-governance/alerts/run?organization_id={oid}", headers=plat
    )
    assert run2.json()["fired"] == []

    alerts = await async_client.get(
        f"/api/v1/platform/cost-governance/alerts?organization_id={oid}", headers=plat
    )
    assert alerts.json()["alerts"][0]["category"] == "total"
    assert alerts.json()["alerts"][0]["today_cents"] == pytest.approx(500.0, abs=0.1)


@pytest.mark.asyncio
async def test_forecast_by_plan_and_model(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CG Forecast Org")
    plat = await _platform_admin(async_client, f"padmin-cgf-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    for d in range(10):
        await _seed_event(UUID(oid), 1.0, days_ago=d)

    fc = await async_client.get(
        f"/api/v1/platform/cost-governance/forecast?days=30&organization_id={oid}",
        headers=plat,
    )
    assert fc.status_code == 200, fc.text
    body = fc.json()
    assert body["total_cost"] == pytest.approx(10.0, abs=1e-3)
    assert body["trend_per_day"] >= 0
    assert body["projected_next_30d"] >= 10.0
    assert any(p["plan"] == "trial" for p in body["by_plan"])
    assert body["by_model"][0]["model"] == "gpt-4o-mini"
