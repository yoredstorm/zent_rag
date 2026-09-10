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
        f"{PREFIX}/sessions", headers=headers, json={"kind": "spreadsheets"}
    )
    sid = created.json()["id"]
    csv_bytes = b"codigo,descripcion,precio\nA1,Widget,12.5\nA2,Gadget,9.0\n"
    await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("productos.csv", BytesIO(csv_bytes), "text/csv")},
    )
    analyzed = await async_client.post(f"{PREFIX}/sessions/{sid}/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    skipped = await async_client.post(
        f"{PREFIX}/sessions/{sid}/skip/review", headers=headers
    )
    assert skipped.status_code == 200, skipped.text
    body = skipped.json()
    assert body["status"] == "NEEDS_ATTENTION"
    assert body["skipped_review"] is True
    assert body["usable"] is True
    warning = (body.get("warning") or "").lower()
    assert "campos" in warning, warning


_CONTRACT_TXT = """\
CONTRATO DE PRESTACIÓN DE SERVICIOS

Entre Acme SpA, RUT 76.123.456-7, en adelante "el Contratante", por una parte, \
y Consultora Beta Limitada, por la otra parte, se celebra el presente contrato.

PRIMERO: El presente contrato tiene vigencia desde el 15 de marzo de 2025 hasta el 14 de marzo de 2026.

SEGUNDO: El Contratante pagará un honorario mensual de CLP 1.500.000 a Consultora Beta Limitada.

TERCERO: Renovación. El contrato se renovará automáticamente por períodos de 12 meses salvo aviso de terminación con 30 días de anticipación.

CUARTO: Confidencialidad. Ambas partes mantendrán confidencial la información intercambiada durante la vigencia del contrato.
"""


def _tiny_pdf(text: str) -> bytes:
    """PDF mínimo de una página con texto (FlateDecode) para tests."""
    import zlib

    payload = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    stream = zlib.compress(payload)
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj"
        ),
        b"4 0 obj << /Length %d /Filter /FlateDecode >> stream\n" % len(stream)
        + stream
        + b"\nendstream endobj",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
    ]
    head = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    pos = len(head)
    for obj in objs:
        offsets.append(pos)
        body += obj + b"\n"
        pos += len(obj) + 1
    xref_pos = pos
    xref = (
        b"xref\n0 6\n0000000000 65535 f \n"
        + b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    )
    trailer = (
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return head + body + xref + trailer


@pytest.mark.asyncio
async def test_document_flow_extracts_facts_and_readiness(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Doc Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "documents"}
    )
    sid = created.json()["id"]
    uploaded = await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("contrato.txt", BytesIO(_CONTRACT_TXT.encode("utf-8")), "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    analyzed = await async_client.post(f"{PREFIX}/sessions/{sid}/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text

    understanding = await async_client.get(
        f"{PREFIX}/sessions/{sid}/understanding", headers=headers
    )
    assert understanding.status_code == 200, understanding.text
    body = understanding.json()
    facts = body.get("facts") or []
    assert facts, "document should produce extracted facts"
    types = {f.get("fact_type") for f in facts}
    assert "party" in types
    assert "date" in types
    assert "amount" in types
    suggestions = body.get("suggestions") or []
    assert suggestions, "facts should be reviewable"
    assert all(s["type"] == "document_fact" for s in suggestions)

    readiness = await async_client.get(
        f"{PREFIX}/sessions/{sid}/readiness", headers=headers
    )
    assert readiness.status_code == 200, readiness.text
    rbody = readiness.json()
    assert "Datos clave" in rbody["labels"].values()
    assert "Contenido extraído" in rbody["labels"].values()
    assert rbody["overall"] > 0
    assert rbody["pending_review_count"] == len(suggestions)

    first = suggestions[0]
    confirmed = await async_client.post(
        f"{PREFIX}/sessions/{sid}/review/{first['id']}",
        headers=headers,
        json={"action": "confirm"},
    )
    assert confirmed.status_code == 200, confirmed.text
    readiness2 = await async_client.get(
        f"{PREFIX}/sessions/{sid}/readiness", headers=headers
    )
    r2 = readiness2.json()
    assert r2["pending_review_count"] == len(suggestions) - 1
    assert r2["scores"]["key_facts"] > 0


@pytest.mark.asyncio
async def test_document_pdf_extracts_pages_and_facts(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Doc PDF Co")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "documents"}
    )
    sid = created.json()["id"]
    contract = (
        "Entre Acme SpA por una parte y Consultora Beta por la otra parte. "
        "Vigencia desde el 15 de marzo de 2025 hasta el 14 de marzo de 2026."
    )
    uploaded = await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("contrato.pdf", BytesIO(_tiny_pdf(contract)), "application/pdf")},
    )
    assert uploaded.status_code == 200, uploaded.text
    analyzed = await async_client.post(f"{PREFIX}/sessions/{sid}/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    understanding = await async_client.get(
        f"{PREFIX}/sessions/{sid}/understanding", headers=headers
    )
    assert understanding.status_code == 200, understanding.text
    body = understanding.json()
    assert body.get("pages") == 1
    fact_types = {f.get("fact_type") for f in (body.get("facts") or [])}
    assert "date" in fact_types


@pytest.mark.asyncio
async def test_document_flow_does_not_create_fake_connector(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Doc NoFake")
    headers = await _owner_headers(org)
    created = await async_client.post(
        f"{PREFIX}/sessions", headers=headers, json={"kind": "documents"}
    )
    sid = created.json()["id"]
    await async_client.post(
        f"{PREFIX}/sessions/{sid}/connect/upload",
        headers={k: v for k, v in headers.items() if k != "Content-Type"},
        files={"file": ("contrato.txt", BytesIO(_CONTRACT_TXT.encode("utf-8")), "text/plain")},
    )
    analyzed = await async_client.post(f"{PREFIX}/sessions/{sid}/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    connectors = await async_client.get("/api/v1/connectors", headers=headers)
    assert connectors.status_code == 200, connectors.text
    names = [c.get("name", "") for c in connectors.json().get("connectors", [])]
    assert not any(name.startswith("file-") for name in names), names


@pytest.mark.asyncio
async def test_pending_review_scoped_to_session(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Scoped Co")
    headers = await _owner_headers(org)

    async def _upload_analyze(kind: str, filename: str, content: bytes) -> str:
        created = await async_client.post(
            f"{PREFIX}/sessions", headers=headers, json={"kind": kind}
        )
        sid = created.json()["id"]
        await async_client.post(
            f"{PREFIX}/sessions/{sid}/connect/upload",
            headers={k: v for k, v in headers.items() if k != "Content-Type"},
            files={"file": (filename, BytesIO(content), "text/csv")},
        )
        analyzed = await async_client.post(
            f"{PREFIX}/sessions/{sid}/analyze", headers=headers
        )
        assert analyzed.status_code == 200, analyzed.text
        return sid

    sid_a = await _upload_analyze("spreadsheets", "a.csv", b"sku,name\n1,Alpha\n")
    sid_b = await _upload_analyze("spreadsheets", "b.csv", b"fecha,venta\n2025-01-01,10\n")

    und_a = (await async_client.get(f"{PREFIX}/sessions/{sid_a}/understanding", headers=headers)).json()
    und_b = (await async_client.get(f"{PREFIX}/sessions/{sid_b}/understanding", headers=headers)).json()
    ids_a = {s["id"] for s in und_a.get("suggestions", [])}
    ids_b = {s["id"] for s in und_b.get("suggestions", [])}
    assert ids_a and ids_b
    assert ids_a.isdisjoint(ids_b)

    warning_a = (await async_client.get(f"{PREFIX}/sessions/{sid_a}", headers=headers)).json()
    assert warning_a["status"] in ("REVIEW_REQUIRED", "TESTING", "READY", "NEEDS_ATTENTION")


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
