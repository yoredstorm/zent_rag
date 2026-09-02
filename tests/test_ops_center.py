# =============================================================================
# AI Ops Runbook & Incident Management v2 (PROMPT 30)
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
            "email": f"ops-{uuid4().hex[:8]}@example.com",
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


@pytest.mark.asyncio
async def test_runbooks_seeded_and_crud(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-ops-{uuid4().hex[:8]}@zent.example")

    rbs = await async_client.get("/api/v1/platform/ops/runbooks", headers=plat)
    assert rbs.status_code == 200, rbs.text
    assert len(rbs.json()["runbooks"]) >= 3
    cost = next(r for r in rbs.json()["runbooks"] if r["trigger_type"] == "cost_alert")
    assert cost["steps"][0]["action"] == "annotate"

    created = await async_client.post(
        "/api/v1/platform/ops/runbooks",
        headers=plat,
        json={
            "trigger_type": "deployment",
            "trigger_match": "*",
            "title": "Rollback rápido",
            "description": "d",
            "steps": [{"action": "annotate", "params": {"title": "Rollback"}}],
        },
    )
    assert created.status_code == 201, created.text
    deleted = await async_client.delete(
        f"/api/v1/platform/ops/runbooks/{created.json()['id']}", headers=plat
    )
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_incident_lifecycle_ack_resolve_mttr(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Ops Org")
    plat = await _platform_admin(async_client, f"padmin-opsl-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    opened = await async_client.post(
        "/api/v1/platform/ops/incidents",
        headers=plat,
        json={
            "organization_id": oid,
            "title": "Latencia alta en producción",
            "description": "p95 supera 5s",
            "source": "slo",
            "severity": "severe",
            "auto_runbook": True,
        },
    )
    assert opened.status_code == 201, opened.text
    incident_id = opened.json()["id"]

    # Timeline: created + runbook steps (seed 'slo' runbook).
    detail = await async_client.get(f"/api/v1/platform/ops/incidents/{incident_id}", headers=plat)
    assert detail.status_code == 200, detail.text
    types = [e["type"] for e in detail.json()["timeline"]]
    assert "created" in types
    assert "runbook_step" in types
    assert detail.json()["severity"] == "severe"
    assert detail.json()["status"] == "open"
    assert detail.json()["mttd_seconds"] == 0.0

    ack = await async_client.post(f"/api/v1/platform/ops/incidents/{incident_id}/ack", headers=plat)
    assert ack.status_code == 200, ack.text

    import asyncio

    await asyncio.sleep(1.1)
    resolved = await async_client.post(
        f"/api/v1/platform/ops/incidents/{incident_id}/resolve?resolution=rotado+modelo",
        headers=plat,
    )
    assert resolved.status_code == 200, resolved.text

    detail2 = await async_client.get(f"/api/v1/platform/ops/incidents/{incident_id}", headers=plat)
    assert detail2.json()["status"] == "resolved"
    assert detail2.json()["resolved_at"] is not None
    assert detail2.json()["mttr_seconds"] >= 1.0
    timeline_types = [e["type"] for e in detail2.json()["timeline"]]
    ordered = [t for t in timeline_types if t != "runbook_step"]
    assert ordered == ["created", "acknowledged", "resolved"]

    listed = await async_client.get("/api/v1/platform/ops/incidents?status=resolved", headers=plat)
    assert any(i["id"] == incident_id for i in listed.json()["incidents"])


@pytest.mark.asyncio
async def test_cost_alert_opens_incident_with_runbook(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Ops Alert Org")
    plat = await _platform_admin(async_client, f"padmin-opsc-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.costgov.cost_governance import create_alert_rule

    # Baseline bajo y pico hoy.
    session = await get_async_session()
    try:
        for d in range(1, 6):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "model, status, estimated_cost, actual_cost, cost_tags, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', "
                    "'completed', 1.0, 1.0, '{}', NOW() - make_interval(days => :ago))"
                ),
                {"oid": UUID(oid), "ago": d},
            )
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, "
                "model, status, estimated_cost, actual_cost, cost_tags) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', "
                "'completed', 9.0, 9.0, '{}')"
            ),
            {"oid": UUID(oid)},
        )
        await session.commit()
    finally:
        await session.close()

    rule = await create_alert_rule(UUID(oid), "total", None, 20.0, True)
    run = await async_client.post(
        f"/api/v1/platform/cost-governance/alerts/run?organization_id={oid}", headers=plat
    )
    assert run.status_code == 200, run.text
    assert run.json()["fired"][0]["rule_id"] == rule["id"]

    incidents = await async_client.get(
        f"/api/v1/platform/ops/incidents?organization_id={oid}&status=open", headers=plat
    )
    assert incidents.status_code == 200, incidents.text
    assert len(incidents.json()["incidents"]) >= 1
    auto = next(i for i in incidents.json()["incidents"] if i["source"] == "cost_alert")
    assert "Costo alto" in auto["title"]
    assert auto["severity"] == "major"

    detail = await async_client.get(f"/api/v1/platform/ops/incidents/{auto['id']}", headers=plat)
    types = [e["type"] for e in detail.json()["timeline"]]
    assert "runbook_step" in types  # runbook seed de cost_alert se ejecutó
    assert any("send_webhook" in (e["detail"] or "") for e in detail.json()["timeline"])


@pytest.mark.asyncio
async def test_escalation_policy_fires_once(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Ops Esc Org")
    plat = await _platform_admin(async_client, f"padmin-opses-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    opened = await async_client.post(
        "/api/v1/platform/ops/incidents",
        headers=plat,
        json={
            "organization_id": oid,
            "title": "Incidente severo sin ack",
            "source": "manual",
            "severity": "severe",
            "auto_runbook": False,
        },
    )
    incident_id = opened.json()["id"]

    # Retroceder detected_at para que los pasos ya estén vencidos.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE incidents SET detected_at = NOW() - interval '30 minutes' "
                "WHERE id = :iid"
            ),
            {"iid": UUID(incident_id)},
        )
        await session.commit()
    finally:
        await session.close()

    check1 = await async_client.post("/api/v1/platform/ops/escalations/check", headers=plat)
    assert check1.status_code == 200, check1.text
    fired = [t for t in check1.json()["triggered"] if t["incident_id"] == incident_id]
    assert len(fired) == 2  # severe: 5min y 15min, ambos vencidos
    assert fired[0]["notify"][0].startswith("webhook")

    check2 = await async_client.post("/api/v1/platform/ops/escalations/check", headers=plat)
    fired2 = [t for t in check2.json()["triggered"] if t["incident_id"] == incident_id]
    assert fired2 == []  # dedupe

    detail = await async_client.get(f"/api/v1/platform/ops/incidents/{incident_id}", headers=plat)
    escalations = [e for e in detail.json()["timeline"] if e["type"] == "escalation"]
    assert len(escalations) == 2


@pytest.mark.asyncio
async def test_incident_metrics(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Ops Met Org")
    plat = await _platform_admin(async_client, f"padmin-opsm-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from src.platform.opscenter.runbooks import open_incident, resolve_incident

    for _ in range(3):
        inc = await open_incident(UUID(oid), title="metric", source="manual", severity="major", auto_runbook=False)
        await resolve_incident(UUID(inc["id"]))

    metrics = await async_client.get("/api/v1/platform/ops/incidents/metrics", headers=plat)
    assert metrics.status_code == 200, metrics.text
    major = next(m for m in metrics.json()["by_severity"] if m["severity"] == "major")
    assert major["total"] >= 3
    assert major["resolved"] >= 3
    assert major["avg_mttr_seconds"] is not None
    assert major["avg_mttr_seconds"] >= 0
