# =============================================================================
# AI Quality & Evals v2 (PROMPT 25)
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
            "email": f"ev-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(organization_id: str) -> str:
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
        "Idempotency-Key": f"ev-{uuid4().hex}",
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


class _FakeRuntime:
    """Devuelve respuestas deterministas por pregunta."""

    def __init__(self, answers: dict[str, str] | None = None, fail: set[str] | None = None):
        self.answers = answers or {}
        self.fail = fail or set()

    async def run(self, request):
        from src.agents.runtime.agent_runtime import AgentRunResult

        q = request.message
        if q in self.fail:
            raise RuntimeError("llm down")
        answer = self.answers.get(q, "respuesta genérica del agente")
        return AgentRunResult(
            run_id=uuid4(),
            agent_id=request.agent.id,
            organization_id=request.agent.organization_id,
            status="completed",
            answer=answer,
            message=q,
            total_latency_ms=100.0,
            total_tokens=50,
            cost=0.001,
        )


@pytest.mark.asyncio
async def test_eval_dataset_versioning_and_run(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Evals Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-ev-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Dataset.
    ds = await async_client.post(
        "/api/v1/platform/evals/datasets",
        headers=plat,
        json={"organization_id": oid, "name": "QA Finanzas", "description": "d"},
    )
    assert ds.status_code == 201, ds.text
    dataset_id = ds.json()["id"]
    assert ds.json()["version"] == 1

    # Items (bump a v2).
    items = await async_client.post(
        f"/api/v1/platform/evals/datasets/{dataset_id}/items",
        headers=plat,
        json={"items": [
            {"question": "¿Cuál es el margen bruto?", "expected_answer": "El margen bruto es 35 por ciento"},
            {"question": "¿Cuántos clientes activos hay?", "expected_answer": "Hay 120 clientes activos"},
        ]},
    )
    assert items.status_code == 201, items.text
    assert items.json()["version"] == 2

    listed_items = await async_client.get(
        f"/api/v1/platform/evals/datasets/{dataset_id}/items", headers=plat
    )
    assert listed_items.status_code == 200, listed_items.text
    assert listed_items.json()["items"][0]["question"] == "¿Cuál es el margen bruto?"

    listed = await async_client.get(f"/api/v1/platform/evals/datasets?organization_id={oid}", headers=plat)
    mine = next(d for d in listed.json()["datasets"] if d["id"] == dataset_id)
    assert mine["version"] == 2
    assert mine["items"] == 2

    # Agente.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"ev-a-{uuid4().hex}"},
            json={"name": "Fin Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()

    # Run con runtime fake que responde bien (score alto → gate PASS).
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    good_runtime = _FakeRuntime(answers={
        "¿Cuál es el margen bruto?": "El margen bruto es 35 por ciento",
        "¿Cuántos clientes activos hay?": "Hay 120 clientes activos",
    })
    app.dependency_overrides[get_agent_runtime] = lambda: good_runtime

    run = await async_client.post(
        "/api/v1/platform/evals/runs",
        headers=plat,
        json={"organization_id": oid, "dataset_id": dataset_id, "agent_id": agent["id"]},
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["run_id"]

    import asyncio

    for _ in range(30):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/platform/evals/runs", headers=plat)).json()["runs"]
        r = next(x for x in runs if x["id"] == run_id)
        if r["status"] in ("completed", "failed"):
            break
    assert r["status"] == "completed", r
    assert r["score_overall"] > 90
    assert r["passed_gate"] is True
    assert r["regression"] is False
    assert r["hallucination_rate"] < 0.1

    # Detalle con items.
    detail = await async_client.get(f"/api/v1/platform/evals/runs/{run_id}", headers=plat)
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["items"]) == 2
    assert detail.json()["items"][0]["score"] > 80


@pytest.mark.asyncio
async def test_eval_gate_fail_and_regression(async_client: AsyncClient, monkeypatch) -> None:
    org = await _create_org(async_client, "Evals Gate Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-evg-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    ds = await async_client.post(
        "/api/v1/platform/evals/datasets",
        headers=plat,
        json={"organization_id": oid, "name": "Gate DS"},
    )
    dataset_id = ds.json()["id"]
    await async_client.post(
        f"/api/v1/platform/evals/datasets/{dataset_id}/items",
        headers=plat,
        json={"items": [{"question": "P1", "expected_answer": "respuesta exacta esperada uno"}]},
    )

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"ev-g-{uuid4().hex}"},
            json={"name": "Gate Agent", "system_prompt": "t", "model": "gpt-4o-mini"},
        )
    ).json()

    from src.api.deps import get_agent_runtime
    from src.api.main import app
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "EVAL_PROMOTION_MIN_SCORE", 80.0)
    monkeypatch.setattr(settings, "EVAL_PROMOTION_MAX_HALLUCINATION", 0.2)

    # Run 1: respuesta mala → gate FAIL.
    bad_runtime = _FakeRuntime(answers={"P1": "zzz completamente fuera de contexto qqq"})
    app.dependency_overrides[get_agent_runtime] = lambda: bad_runtime

    run1 = await async_client.post(
        "/api/v1/platform/evals/runs",
        headers=plat,
        json={"organization_id": oid, "dataset_id": dataset_id, "agent_id": agent["id"]},
    )
    run1_id = run1.json()["run_id"]

    import asyncio

    for _ in range(30):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/platform/evals/runs", headers=plat)).json()["runs"]
        r1 = next(x for x in runs if x["id"] == run1_id)
        if r1["status"] in ("completed", "failed"):
            break
    assert r1["status"] == "completed"
    assert r1["passed_gate"] is False
    assert r1["score_overall"] < 50
    assert r1["hallucination_rate"] > 0.5

    # Run 2: respuesta buena → score alto, pero REGRESIÓN no (no hay best previo del mismo agente en el mismo dataset... el best previo es el run1 malo → no regresión).
    good_runtime = _FakeRuntime(answers={"P1": "respuesta exacta esperada uno"})
    app.dependency_overrides[get_agent_runtime] = lambda: good_runtime
    run2 = await async_client.post(
        "/api/v1/platform/evals/runs",
        headers=plat,
        json={"organization_id": oid, "dataset_id": dataset_id, "agent_id": agent["id"]},
    )
    run2_id = run2.json()["run_id"]
    for _ in range(30):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/platform/evals/runs", headers=plat)).json()["runs"]
        r2 = next(x for x in runs if x["id"] == run2_id)
        if r2["status"] in ("completed", "failed"):
            break
    assert r2["status"] == "completed"
    assert r2["passed_gate"] is True
    assert r2["regression"] is False

    # Run 3: de nuevo mala → REGRESIÓN vs el run2 (score alto).
    app.dependency_overrides[get_agent_runtime] = lambda: bad_runtime
    run3 = await async_client.post(
        "/api/v1/platform/evals/runs",
        headers=plat,
        json={"organization_id": oid, "dataset_id": dataset_id, "agent_id": agent["id"]},
    )
    run3_id = run3.json()["run_id"]
    for _ in range(30):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/platform/evals/runs", headers=plat)).json()["runs"]
        r3 = next(x for x in runs if x["id"] == run3_id)
        if r3["status"] in ("completed", "failed"):
            break
    assert r3["status"] == "completed"
    assert r3["passed_gate"] is False
    assert r3["regression"] is True  # vs best (run2)


@pytest.mark.asyncio
async def test_eval_scoring_heuristic(async_client: AsyncClient) -> None:
    from src.platform.evals.evals import score_answer

    exact = score_answer("El margen es 35%", "El margen es 35%", None)
    assert exact["score"] == 100.0
    assert exact["hallucination_rate"] == 0.0

    partial = score_answer("el margen es alto", "El margen es 35 por ciento", "El margen bruto fue 35 por ciento este trimestre")
    assert partial["score"] > 30
    assert partial["faithfulness"] > 0.2

    empty = score_answer("", "El margen es 35%", None)
    assert empty["score"] == 0.0
    assert empty["hallucination_rate"] == 1.0
