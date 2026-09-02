# =============================================================================
# Tenant Audit & Compliance Reports v2 (PROMPT 38)
# =============================================================================
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"ar-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"ar-{uuid4().hex}",
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
async def test_generate_report_csv_pdf_with_chain(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AR Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    end = date.today()
    start = end - timedelta(days=30)

    r1 = await async_client.post(
        "/api/v1/audit/reports/generate",
        headers={**_headers(org), "Idempotency-Key": f"ar-g1-{uuid4().hex}"},
        json={"report_type": "activity", "period_start": start.isoformat(), "period_end": end.isoformat(), "format": "csv"},
    )
    assert r1.status_code == 200, r1.text
    report1 = r1.json()
    assert len(report1["integrity_hash"]) == 64
    assert report1["prev_hash"] is None  # raíz de la cadena

    r2 = await async_client.post(
        "/api/v1/audit/reports/generate",
        headers={**_headers(org), "Idempotency-Key": f"ar-g2-{uuid4().hex}"},
        json={"report_type": "full", "period_start": start.isoformat(), "period_end": end.isoformat(), "format": "pdf"},
    )
    assert r2.status_code == 200, r2.text
    report2 = r2.json()
    assert report2["prev_hash"] == report1["integrity_hash"]  # encadenado

    listed = await async_client.get("/api/v1/audit/reports", headers=h)
    assert listed.json()["count"] == 2

    # Descarga CSV.
    dl1 = await async_client.get(f"/api/v1/audit/reports/{report1['id']}/download", headers=h)
    assert dl1.status_code == 200, dl1.text
    assert dl1.headers["content-type"].startswith("text/csv")
    assert dl1.content.startswith(b"section")

    # Descarga PDF.
    dl2 = await async_client.get(f"/api/v1/audit/reports/{report2['id']}/download", headers=h)
    assert dl2.status_code == 200, dl2.text
    assert dl2.headers["content-type"].startswith("application/pdf")
    assert dl2.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_verify_integrity_and_detect_tampering(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AR Verify Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    end = date.today()
    start = end - timedelta(days=30)

    gen = await async_client.post(
        "/api/v1/audit/reports/generate",
        headers={**_headers(org), "Idempotency-Key": f"ar-v-{uuid4().hex}"},
        json={"report_type": "activity", "period_start": start.isoformat(), "period_end": end.isoformat(), "format": "csv"},
    )
    report_id = gen.json()["id"]

    ok = await async_client.get(f"/api/v1/audit/reports/{report_id}/verify", headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["verified"] is True
    assert ok.json()["chain_ok"] is True

    # Manipular el archivo → verificación falla.
    from src.platform.compliance.audit_reports import REPORT_DIR

    target = None
    for candidate in (REPORT_DIR / "reports" / str(UUID(org["organization_id"]))).glob("*.csv"):
        target = candidate
    assert target is not None
    target.write_bytes(target.read_bytes() + b"tampered")

    tampered = await async_client.get(f"/api/v1/audit/reports/{report_id}/verify", headers=h)
    assert tampered.json()["verified"] is False


@pytest.mark.asyncio
async def test_compliance_status_and_update(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AR Comp Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-arc-{uuid4().hex[:8]}@zent.example")

    status = await async_client.get("/api/v1/audit/compliance?framework=soc2", headers=h)
    assert status.status_code == 200, status.text
    body = status.json()
    assert len(body["controls"]) == 8
    assert body["counts"]["review"] == 8
    assert body["score"] == 0.0
    assert all(c["status"] == "review" for c in body["controls"])

    # Marcar controles pass/fail.
    updated = await async_client.put(
        "/api/v1/audit/compliance",
        headers={**_headers(org), "Idempotency-Key": f"ar-c-{uuid4().hex}"},
        json={"framework": "soc2", "control_id": "CC6.1", "status": "pass", "evidence": "SCIM + API keys"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["counts"]["pass"] == 1
    assert updated.json()["score"] == pytest.approx(12.5, abs=0.1)

    await async_client.put(
        "/api/v1/audit/compliance",
        headers={**_headers(org), "Idempotency-Key": f"ar-c2-{uuid4().hex}"},
        json={"framework": "soc2", "control_id": "CC7.2", "status": "pass"},
    )

    bad = await async_client.put(
        "/api/v1/audit/compliance",
        headers={**_headers(org), "Idempotency-Key": f"ar-c3-{uuid4().hex}"},
        json={"framework": "soc2", "control_id": "CC8.1", "status": "nope"},
    )
    assert bad.status_code == 422

    # Dashboard platform.
    dash = await async_client.get(
        f"/api/v1/platform/compliance/dashboard?organization_id={org['organization_id']}", headers=plat
    )
    assert dash.status_code == 200, dash.text
    soc2 = next(f for f in dash.json()["frameworks"] if f["framework"] == "soc2")
    assert soc2["pass"] == 2
    assert soc2["review"] == 6
    assert soc2["score"] == pytest.approx(25.0, abs=0.1)

    # Controles platform.
    controls = await async_client.get("/api/v1/platform/compliance/controls?framework=gdpr", headers=plat)
    assert controls.json()["controls"]  # 8 GDPR
    controls_all = await async_client.get("/api/v1/platform/compliance/controls", headers=plat)
    assert len(controls_all.json()["controls"]) == 24


@pytest.mark.asyncio
async def test_full_report_contains_sections(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AR Full Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    end = date.today()
    start = end - timedelta(days=30)

    gen = await async_client.post(
        "/api/v1/audit/reports/generate",
        headers={**_headers(org), "Idempotency-Key": f"ar-f-{uuid4().hex}"},
        json={"report_type": "full", "period_start": start.isoformat(), "period_end": end.isoformat(), "format": "csv"},
    )
    report_id = gen.json()["id"]

    dl = await async_client.get(f"/api/v1/audit/reports/{report_id}/download", headers=h)
    text = dl.content.decode()
    assert "config_changes" in text
    assert "incidents" in text
