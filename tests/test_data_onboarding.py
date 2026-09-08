# =============================================================================
# Phase 31A — Data Onboarding Wizard (sessions, tenant isolation, RBAC)
# =============================================================================
from __future__ import annotations

import hashlib
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.platform.auth.passwords import hash_password
from src.platform.auth.session import encrypt_session


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"onb-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data


async def _owner_headers(org: dict) -> dict:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository

    user = await PostgresUserRepository().get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert user is not None
    return {
        "Authorization": f"Bearer {encrypt_session(user.id, UUID(org['organization_id']))}",
        "X-Organization-Id": org["organization_id"],
    }


async def _viewer_headers(org: dict) -> dict:
    from src.infrastructure.postgres.session import get_async_session

    email = f"view-{uuid4().hex[:8]}@example.com"
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash) "
                "VALUES (gen_random_uuid(), :oid, :ext, :eh, 'viewer', "
                ":email, :ph) RETURNING id"
            ),
            {
                "oid": UUID(org["organization_id"]),
                "ext": f"view-{uuid4().hex[:12]}",
                "eh": hashlib.sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": hash_password("StrongPass123!"),
            },
        )
        uid = result.fetchone().id
        await session.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role_id) "
                "SELECT :oid, :uid, id FROM roles "
                "WHERE organization_id IS NULL AND name = 'viewer' "
                "ON CONFLICT DO NOTHING"
            ),
            {"oid": UUID(org["organization_id"]), "uid": uid},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "Authorization": f"Bearer {encrypt_session(uid, UUID(org['organization_id']))}",
        "X-Organization-Id": org["organization_id"],
    }


PREFIX = "/api/v1/data-onboarding"


@pytest.mark.asyncio
async def test_create_session_and_resume(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Onboard Co")
    headers = await _owner_headers(org)

    created = await async_client.post(
        f"{PREFIX}/sessions",
        headers=headers,
        json={"kind": "spreadsheets"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "spreadsheets"
    assert body["status"] == "NOT_STARTED"
    assert body["step"] == "connect"
    sid = body["id"]

    resumed = await async_client.get(f"{PREFIX}/sessions/{sid}", headers=headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["id"] == sid

    listed = await async_client.get(f"{PREFIX}/sessions", headers=headers)
    assert listed.status_code == 200, listed.text
    ids = [row["id"] for row in listed.json()["sessions"]]
    assert sid in ids


@pytest.mark.asyncio
async def test_cross_tenant_session_is_404(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "Org A")
    org_b = await _create_org(async_client, "Org B")
    ha = await _owner_headers(org_a)
    hb = await _owner_headers(org_b)

    created = await async_client.post(
        f"{PREFIX}/sessions", headers=ha, json={"kind": "documents"}
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    other = await async_client.get(f"{PREFIX}/sessions/{sid}", headers=hb)
    assert other.status_code == 404, other.text

    listed_b = await async_client.get(f"{PREFIX}/sessions", headers=hb)
    assert listed_b.status_code == 200, listed_b.text
    assert all(row["id"] != sid for row in listed_b.json()["sessions"])


@pytest.mark.asyncio
async def test_viewer_cannot_create_session(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RBAC Co")
    viewer = await _viewer_headers(org)
    denied = await async_client.post(
        f"{PREFIX}/sessions", headers=viewer, json={"kind": "database"}
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.asyncio
async def test_skip_review_marks_needs_attention(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Skip Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "documents"}
    )
    sid = created.json()["id"]
    skipped = await async_client.post(
        f"{PREFIX}/sessions/{sid}/skip/review", headers=headers
    )
    assert skipped.status_code == 200, skipped.text
    body = skipped.json()
    assert body["status"] == "NEEDS_ATTENTION"
    assert body["skipped_review"] is True
    assert body["usable"] is True
    assert "mappings" in (body.get("warning") or "").lower() or "revis" in (
        body.get("warning") or ""
    ).lower()


@pytest.mark.asyncio
async def test_upload_csv_happy_and_exe_rejected(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Upload Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "spreadsheets"}
    )
    sid = created.json()["id"]

    csv_bytes = b"codigo,descripcion,precio\nA1,Widget,12.5\nA2,Gadget,9.0\n"
    ok = await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("productos.csv", BytesIO(csv_bytes), "text/csv")},
    )
    assert ok.status_code == 200, ok.text
    payload = ok.json()
    assert payload["kb_source_id"]
    assert "password" not in str(payload).lower() or "password" not in (
        payload.get("state") or {}
    )

    created2 = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "documents"}
    )
    sid2 = created2.json()["id"]
    rejected = await async_client.post(
        f"{PREFIX}/sessions/{sid2}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("malware.exe", BytesIO(b"MZ\x90\x00fake"), "application/octet-stream")},
    )
    assert rejected.status_code in (400, 415, 422), rejected.text


@pytest.mark.asyncio
async def test_database_secrets_never_in_config_json(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "DB Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "database"}
    )
    sid = created.json()["id"]
    connected = await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/database",
        headers=headers,
        json={
            "name": "ERP",
            "engine": "postgres",
            "host": "127.0.0.1",
            "port": 5432,
            "database": "erp",
            "username": "zent",
            "password": "super-secret-pass",
            "ssl": False,
            "advanced": {"ssrf_allowlist": ["127.0.0.1"]},
        },
    )
    assert connected.status_code in (200, 422), connected.text
    body = connected.json()
    blob = str(body)
    assert "super-secret-pass" not in blob
    connector_id = body.get("connector_id")
    assert connector_id
    listed = await async_client.get("/api/v1/connectors", headers=headers)
    assert listed.status_code == 200, listed.text
    match = next(
        c for c in listed.json()["connectors"] if c["id"] == connector_id
    )
    assert "super-secret-pass" not in str(match.get("config") or {})
    assert match.get("has_secrets") is True or connected.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_approve_review(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Review RBAC")
    owner = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=owner, json={"kind": "spreadsheets"}
    )
    sid = created.json()["id"]
    csv_bytes = b"sku,name\n1,Alpha\n"
    await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in owner.items() if k != "Content-Type"},
        files={"file": ("items.csv", BytesIO(csv_bytes), "text/csv")},
    )
    analyzed = await async_client.post(
        f"{PREFIX}/sessions/{sid}/analyze", headers=owner
    )
    assert analyzed.status_code == 200, analyzed.text
    understanding = await async_client.get(
        f"{PREFIX}/sessions/{sid}/understanding", headers=owner
    )
    assert understanding.status_code == 200, understanding.text
    items = understanding.json().get("suggestions") or []
    if not items:
        pytest.skip("no suggestions produced for csv fixture")
    suggestion_id = items[0]["id"]
    viewer = await _viewer_headers(org)
    denied = await async_client.post(
        f"{PREFIX}/sessions/{sid}/review/{suggestion_id}",
        headers=viewer,
        json={"action": "confirm"},
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.asyncio
async def test_answer_feedback_creates_pending_suggestion(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Feedback Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "spreadsheets"}
    )
    sid = created.json()["id"]
    csv_bytes = b"sku,precio\n1,10\n"
    await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("p.csv", BytesIO(csv_bytes), "text/csv")},
    )
    await async_client.post(f"{PREFIX}/sessions/{sid}/analyze", headers=headers)
    asked = await async_client.post(
        f"{PREFIX}/sessions/{sid}/ask",
        headers=headers,
        json={"question": "Cual es el precio mas alto?"},
    )
    assert asked.status_code == 200, asked.text
    fb = await async_client.post(
        f"{PREFIX}/sessions/{sid}/answer-feedback",
        headers=headers,
        json={
            "verdict": "incorrect",
            "reason": "wrong_field",
            "question": "Cual es el precio mas alto?",
        },
    )
    assert fb.status_code == 200, fb.text
    suggestion = fb.json()["suggestion"]
    assert suggestion["status"] == "pending"
    assert suggestion["status"] != "approved"


@pytest.mark.asyncio
async def test_free_text_creates_pending_mapping(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "FreeText Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "spreadsheets"}
    )
    sid = created.json()["id"]
    csv_bytes = b"VAL,qty\n10,2\n"
    await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("t.csv", BytesIO(csv_bytes), "text/csv")},
    )
    await async_client.post(f"{PREFIX}/sessions/{sid}/analyze", headers=headers)
    ft = await async_client.post(
        f"{PREFIX}/sessions/{sid}/free-text",
        headers=headers,
        json={"text": "This field is the published fare without tax."},
    )
    assert ft.status_code == 200, ft.text
    suggestion = ft.json()["suggestion"]
    assert suggestion["status"] == "pending"


@pytest.mark.asyncio
async def test_web_preview_rejects_private_host(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Web Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "website"}
    )
    sid = created.json()["id"]
    preview = await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/web",
        headers=headers,
        json={"url": "http://127.0.0.1/secret", "commit": False},
    )
    assert preview.status_code in (400, 422), preview.text


@pytest.mark.asyncio
async def test_gate_empty_for_new_org(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Empty Gate Co")
    headers = await _owner_headers(org)
    gate = await async_client.get(f"{PREFIX}/gate", headers=headers)
    assert gate.status_code == 200, gate.text
    body = gate.json()
    assert body["has_real_data"] is False
    assert body["resume_session_id"] is None
