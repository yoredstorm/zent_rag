# =============================================================================
# P18.5-05 — Una intención real, una llave, un run.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from tests.test_workflow_published_snapshot import _marker_graph
from tests.test_workflows import _create_org, _headers, _owner_session


async def _workflow(client: AsyncClient, name: str) -> tuple[dict, str]:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    created = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={
            "name": name,
            "trigger_type": "webhook",
            "graph": _marker_graph("A"),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    return org, created.json()["workflow_id"]


@pytest.mark.asyncio
async def test_same_intent_key_does_not_duplicate_real_run(
    async_client: AsyncClient,
) -> None:
    org, workflow_id = await _workflow(async_client, "P18.5 idempotent run")
    key = f"intent-{uuid4().hex}"
    headers = {**_headers(org), "Idempotency-Key": key}

    first = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers=headers,
        json={"payload": {"message": "cobrar 10"}, "simulate": False},
    )
    assert first.status_code == 200, first.text
    first_run = first.json().get("run_id") or (first.json().get("run") or {}).get(
        "run_id"
    )

    second = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers=headers,
        json={"payload": {"message": "cobrar 10"}, "simulate": False},
    )
    assert second.status_code == 200, second.text
    second_run = second.json().get("run_id") or (second.json().get("run") or {}).get(
        "run_id"
    )
    assert second_run == first_run
    assert second.headers.get("Idempotency-Replayed") == "true"

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflow_runs "
                    "WHERE workflow_id = :wid AND trigger = 'manual'"
                ),
                {"wid": workflow_id},
            )
        ).scalar()
    finally:
        await session.close()
    assert int(count) == 1

    conflict = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers=headers,
        json={"payload": {"message": "cobrar 999"}, "simulate": False},
    )
    assert conflict.status_code == 409, conflict.text
    assert "idempotency" in conflict.text.lower()

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflow_runs "
                    "WHERE workflow_id = :wid AND trigger = 'manual'"
                ),
                {"wid": workflow_id},
            )
        ).scalar()
    finally:
        await session.close()
    assert int(count) == 1


@pytest.mark.asyncio
async def test_distinct_keys_create_distinct_runs(async_client: AsyncClient) -> None:
    org, workflow_id = await _workflow(async_client, "P18.5 distinct intent")
    runs = []
    for index in range(2):
        response = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/run",
            headers={
                **_headers(org),
                "Idempotency-Key": f"intent-{index}-{uuid4().hex}",
            },
            json={"payload": {"message": f"intento {index}"}, "simulate": False},
        )
        assert response.status_code == 200, response.text
        runs.append(
            response.json().get("run_id")
            or (response.json().get("run") or {}).get("run_id")
        )
    assert runs[0] != runs[1]
