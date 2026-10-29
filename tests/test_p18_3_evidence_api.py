# =============================================================================
# P18.3-06 - API de evidencias paginadas (auth + corpus + cursor)
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def _tenant(client):
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": f"P18.3 Evidence API {uuid4().hex[:6]}",
            "email": f"p183-evidence-{uuid4().hex[:8]}@example.com",
            "password": "P183-evidence-password-123",
        },
    )
    assert response.status_code == 200, response.text
    auth = response.json()
    headers = {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Organization-Id": auth["organization_id"],
    }
    onboarding = await client.post(
        "/api/v1/onboarding/start-mode",
        headers=headers,
        json={"mode": "blank"},
    )
    assert onboarding.status_code == 200, onboarding.text
    headers["X-Workspace-Id"] = onboarding.json()["workspace_id"]
    corpus = await client.post(
        "/api/v1/knowledge/workspaces",
        headers=headers,
        json={"name": "Evidence API"},
    )
    assert corpus.status_code == 201, corpus.text
    upload = await client.post(
        f"/api/v1/sources/files/upload?corpus_id={corpus.json()['corpus']['id']}",
        headers=headers,
        files={"file": ("evidencia.txt", b"Contenido de prueba.", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    return auth, headers, corpus.json()["corpus"]["id"], upload.json()["id"]


@pytest.mark.asyncio
async def test_evidence_endpoint_walks_all_rows_without_ties_or_nulls_loss(
    async_client,
) -> None:
    auth, headers, corpus_id, source_id = await _tenant(async_client)
    created_at = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        ("alta", 0.9, created_at, uuid4()),
        ("nula-a", None, created_at, uuid4()),
        ("nula-b", None, created_at, uuid4()),
        ("baja", 0.2, created_at, uuid4()),
    ]
    session = await get_async_session()
    try:
        for excerpt, strength, when, evidence_id in rows:
            await session.execute(
                text(
                    "INSERT INTO evidence_ledger "
                    "(id, organization_id, source_id, excerpt, content_hash, strength, created_at) "
                    "VALUES (:id, :oid, :sid, :excerpt, :hash, :strength, :created_at)"
                ),
                {
                    "id": str(evidence_id),
                    "oid": auth["organization_id"],
                    "sid": source_id,
                    "excerpt": excerpt,
                    "hash": f"hash-{evidence_id}",
                    "strength": strength,
                    "created_at": when,
                },
            )
        await session.commit()
    finally:
        await session.close()

    collected: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = await async_client.get(
            f"/api/v1/knowledge/workspaces/{corpus_id}/sources/{source_id}/evidence",
            headers=headers,
            params=params,
        )
        assert page.status_code == 200, page.text
        payload = page.json()
        assert payload["contract"] == "evidence_page/v1"
        assert payload["read_scope"]["corpus_id"] == corpus_id
        assert payload["read_scope"]["source_id"] == source_id
        collected.extend(item["id"] for item in payload["items"])
        cursor = payload["next_cursor"]
        if not cursor:
            break
    assert len(collected) == len(rows)
    assert len(set(collected)) == len(rows)

    invalid = await async_client.get(
        f"/api/v1/knowledge/workspaces/{corpus_id}/sources/{source_id}/evidence",
        headers=headers,
        params={"cursor": "inventado"},
    )
    assert invalid.status_code == 400

    foreign = await async_client.get(
        f"/api/v1/knowledge/workspaces/{uuid4()}/sources/{source_id}/evidence",
        headers=headers,
    )
    assert foreign.status_code == 404
