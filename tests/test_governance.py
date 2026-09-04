# =============================================================================
# AI Governance Board & Audit Trail v2 (PROMPT 50)
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
            "email": f"gov-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"gov-{uuid4().hex}",
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
async def test_policies_seeded_and_revision(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GOV Policies Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    policies = await async_client.get("/api/v1/governance/policies", headers=h)
    assert policies.status_code == 200, policies.text
    body = policies.json()
    assert len(body["policies"]) == 4
    types = {p["policy_type"] for p in body["policies"]}
    assert types == {"acceptable_use", "deployment", "incident_response", "data_handling"}
    assert all(p["version"] == 1 for p in body["policies"])

    # Revisión → v2 + decisión de cambio.
    dep_policy = next(p for p in body["policies"] if p["policy_type"] == "deployment")
    revised = await async_client.post(
        f"/api/v1/governance/policies/{dep_policy['id']}/revision",
        headers={**_headers(org), "Idempotency-Key": f"gov-r-{uuid4().hex}"},
        json={"content": "Ahora se requieren 3 aprobadores de la junta y revisión legal."},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == 2

    policies2 = await async_client.get("/api/v1/governance/policies", headers=h)
    dep2 = next(p for p in policies2.json()["policies"] if p["id"] == dep_policy["id"])
    assert dep2["version"] == 2
    assert "3 aprobadores" in dep2["content"]

    decisions = await async_client.get("/api/v1/governance/decisions", headers=h)
    assert any(d["decision_type"] == "policy_change" and d["status"] == "pending" for d in decisions.json()["decisions"])


@pytest.mark.asyncio
async def test_decisions_with_signatures(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GOV Decisions Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/governance/decisions",
        headers={**_headers(org), "Idempotency-Key": f"gov-d-{uuid4().hex}"},
        json={"decision_type": "deploy_approval", "title": "Aprobar despliegue del agente ventas en producción", "rationale": "Cumple políticas y evals"},
    )
    assert created.status_code == 200, created.text
    did = created.json()["decision_id"]

    # 1ª firma → sigue pending.
    d1 = await async_client.post(
        f"/api/v1/governance/decisions/{did}/decide",
        headers={**_headers(org), "Idempotency-Key": f"gov-a-{uuid4().hex}"},
        json={"approve": True},
    )
    assert d1.status_code == 200, d1.text
    assert d1.json()["status"] == "pending"
    assert d1.json()["approvals"] == 1

    # 2ª firma → approved con firmas en el JSONB.
    d2 = await async_client.post(
        f"/api/v1/governance/decisions/{did}/decide",
        headers={**_headers(org), "Idempotency-Key": f"gov-b-{uuid4().hex}"},
        json={"approve": True},
    )
    assert d2.json()["status"] == "approved"

    decisions = await async_client.get("/api/v1/governance/decisions?status=approved", headers=h)
    entry = next(d for d in decisions.json()["decisions"] if d["id"] == did)
    assert len(entry["approvers"]) == 2
    assert all(len(a["signature"]) == 32 for a in entry["approvers"])
    assert entry["decided_at"] is not None

    # Rechazo inmediato.
    created2 = await async_client.post(
        "/api/v1/governance/decisions",
        headers={**_headers(org), "Idempotency-Key": f"gov-d2-{uuid4().hex}"},
        json={"decision_type": "model_change", "title": "Cambiar a modelo experimental"},
    )
    r1 = await async_client.post(
        f"/api/v1/governance/decisions/{created2.json()['decision_id']}/decide",
        headers={**_headers(org), "Idempotency-Key": f"gov-c-{uuid4().hex}"},
        json={"approve": False},
    )
    assert r1.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_audit_trail_hash_chain_and_verify(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GOV Audit Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    # Genera acciones de auditoría (revisión + decisión + certificación).
    from src.platform.governance.board import add_certification, create_decision

    await create_decision(UUID(org["organization_id"]), "incident_review", "Revisar incidente #42", "PII leak")
    await add_certification(UUID(org["organization_id"]), "maria", "AI Ethics")

    trail = await async_client.get("/api/v1/governance/audit", headers=h)
    assert trail.status_code == 200, trail.text
    entries = trail.json()["entries"]
    assert len(entries) == 2  # decision.created + certification.issued
    assert entries[0]["hash"] != entries[1]["hash"]

    verify = await async_client.post("/api/v1/governance/audit/verify", headers={**_headers(org)})
    assert verify.status_code == 200, verify.text
    assert verify.json()["intact"] is True
    assert verify.json()["verified"] == len(entries)

    # Tampering: modificar un detalle → detectado.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        target = (
            await session.execute(
                text(
                    "SELECT id FROM governance_audit_log "
                    "WHERE organization_id = :oid ORDER BY created_at LIMIT 1"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
        await session.execute(
            text("UPDATE governance_audit_log SET detail = 'MODIFICADO' WHERE id = :eid"),
            {"eid": target},
        )
        await session.commit()
    finally:
        await session.close()

    verify2 = await async_client.post("/api/v1/governance/audit/verify", headers={**_headers(org)})
    assert verify2.json()["intact"] is False
    assert len(verify2.json()["tampered"]) == 1


@pytest.mark.asyncio
async def test_certifications_and_report(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GOV Certs Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    added = await async_client.post(
        "/api/v1/governance/certifications",
        headers={**_headers(org), "Idempotency-Key": f"gov-c-{uuid4().hex}"},
        json={"member_name": "juan", "certification": "Prompt Safety", "expires_in_days": 180},
    )
    assert added.status_code == 200, added.text

    certs = await async_client.get("/api/v1/governance/certifications", headers=h)
    assert len(certs.json()["certifications"]) == 1
    assert certs.json()["certifications"][0]["certification"] == "Prompt Safety"

    # Certificación inválida → 400.
    bad = await async_client.post(
        "/api/v1/governance/certifications",
        headers={**_headers(org), "Idempotency-Key": f"gov-b-{uuid4().hex}"},
        json={"member_name": "x", "certification": "Hacking"},
    )
    assert bad.status_code == 400

    # Reporte ejecutivo: políticas activas → governance 100.
    report = await async_client.get("/api/v1/governance/report", headers=h)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["pillars"]["governance"]["score"] == 100.0  # 4/4 activas
    assert 0 <= body["total_score"] <= 100


@pytest.mark.asyncio
async def test_governance_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GOV Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-gov-{uuid4().hex[:8]}@zent.example")

    from src.platform.governance.board import create_decision, decide

    decision = await create_decision(UUID(org["organization_id"]), "deploy_approval", "Aprobar bot legal")
    await decide(UUID(org["organization_id"]), UUID(decision["decision_id"]), True)
    await decide(UUID(org["organization_id"]), UUID(decision["decision_id"]), True)

    dash = await async_client.get("/api/v1/platform/governance/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["organizations_governing"] >= 1
    assert body["audit_entries"] >= 1
    assert any(d["status"] == "approved" for d in body["decisions_by_status"])
    assert any(e["action"] in ("decision.created", "approved") for e in body["recent_audit"])
