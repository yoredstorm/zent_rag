# =============================================================================
# Evaluation Engine (PROMPT 04) — examples first-class, CSV, clasificación,
# promotion gate, failures
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.rag.evaluation.examples import normalize_example, parse_csv


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
    }


async def _create_dataset(client: AsyncClient, h: dict, name: str) -> str:
    resp = await client.post(
        "/api/v1/eval/datasets/import",
        headers=h,
        json={"name": name, "cases": [{"question": "seed", "expected_sources": ["catálogo"]}]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["dataset_id"]


class TestNormalize:
    def test_normalize_minimal(self) -> None:
        ex = normalize_example({"question": "¿Cuánto stock hay?"})
        assert ex["question"] == "¿Cuánto stock hay?"
        assert ex["expected_sources"] == []
        assert ex["must_cite"] is False

    def test_normalize_sources_string(self) -> None:
        ex = normalize_example(
            {"question": "q", "expected_sources": "inventory;products|sales"}
        )
        assert ex["expected_sources"] == ["inventory", "products", "sales"]

    def test_normalize_requires_question(self) -> None:
        with pytest.raises(ValueError):
            normalize_example({"expected_behavior": "x"})

    def test_parse_csv(self) -> None:
        rows = parse_csv(
            "question,expected_answer,expected_behavior,expected_sources,must_cite\n"
            "¿Stock del ABC?,42,inventory_query,inventory|products,true\n"
            "¿Qué es una receta?,receta retenida,policy_query,políticas,false\n"
        )
        assert len(rows) == 2
        assert rows[0]["question"] == "¿Stock del ABC?"
        assert rows[0]["expected_sources"] == ["inventory", "products"]
        assert rows[0]["must_cite"] is True
        assert rows[1]["expected_behavior"] == "policy_query"

    def test_parse_csv_skips_empty_questions(self) -> None:
        rows = parse_csv(
            "question,expected_sources\n"
            ",inventory\n"
            "¿Hay stock?,inventory\n"
        )
        assert len(rows) == 1
        assert rows[0]["question"] == "¿Hay stock?"


@pytest.mark.asyncio
async def test_examples_crud_and_materialize(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Eval CRUD")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    did = await _create_dataset(async_client, h, "CRUD Dataset")

    created = await async_client.post(
        f"/api/v1/eval/datasets/{did}/examples",
        headers=h,
        json={
            "examples": [
                {"question": "¿Cuál es el producto más vendido?", "expected_behavior": "product_query", "must_cite": True},
                {"question": "¿Cuánto stock queda del ABC?", "expected_behavior": "inventory_query"},
            ]
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["count"] == 2

    listing = await async_client.get(f"/api/v1/eval/datasets/{did}/examples", headers=h)
    assert listing.status_code == 200, listing.text
    examples = listing.json()["examples"]
    assert len(examples) == 3  # seed + 2
    first = next(e for e in examples if e["question"].startswith("¿Cuál es el producto"))
    assert first["expected_behavior"] == "product_query"
    assert first["must_cite"] is True

    deleted = await async_client.delete(
        f"/api/v1/eval/datasets/{did}/examples/{first['id']}", headers=h
    )
    assert deleted.status_code == 200, deleted.text
    listing2 = await async_client.get(f"/api/v1/eval/datasets/{did}/examples", headers=h)
    assert listing2.json()["count"] == 2

    # Aislamiento cross-org.
    org_b = await _create_org(async_client, "Eval B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    resp = await async_client.get(
        f"/api/v1/eval/datasets/{did}/examples", headers=_headers(org_b)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_csv_import(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Eval CSV")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    did = await _create_dataset(async_client, h, "CSV Dataset")

    resp = await async_client.post(
        f"/api/v1/eval/datasets/{did}/import-csv",
        headers=h,
        json={
            "csv": (
                "question,expected_answer,expected_behavior,expected_sources,must_cite\n"
                "¿Cuánto vendimos?,132,sales_query,sales|products,true\n"
                "¿Qué cubre Fonasa?,40%,policy_query,health_insurance,false\n"
            )
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["count"] == 2

    # CSV vacío → 400.
    bad = await async_client.post(
        f"/api/v1/eval/datasets/{did}/import-csv",
        headers=h,
        json={"csv": "question,expected_sources\n,\n"},
    )
    assert bad.status_code == 400, bad.text


class TestCompareClassification:
    def _summary(self, score: float, hallucination: float) -> dict:
        return {
            "run_id": str(uuid4()),
            "version_id": str(uuid4()),
            "quality": {
                "composite_score": score,
                "faithfulness": max(0.0, min(1.0, score / 100)),
                "hallucination_rate": hallucination,
            },
            "performance": {"latency": {"p95": 500}, "avg_cost": 0.01},
        }

    def test_improvement(self) -> None:
        from src.rag.evaluation.regression import compare_runs

        report = compare_runs(
            self._summary(92.0, 0.05), self._summary(85.0, 0.05)
        )
        assert report["classification"] == "improvement"

    def test_regression(self) -> None:
        from src.rag.evaluation.regression import compare_runs

        report = compare_runs(
            self._summary(70.0, 0.4), self._summary(90.0, 0.1)
        )
        assert report["classification"] == "regression"
        assert report["overall"] == "fail"

    def test_no_material_change(self) -> None:
        from src.rag.evaluation.regression import compare_runs

        report = compare_runs(
            self._summary(88.48, 0.1), self._summary(88.5, 0.09)
        )
        assert report["classification"] == "no_material_change"


@pytest.mark.asyncio
async def test_run_failures_endpoint(async_client: AsyncClient) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    org = await _create_org(async_client, "Eval Fail")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    oid = UUID(org["organization_id"])

    session = await get_async_session()
    try:
        run = (
            await session.execute(
                text(
                    "INSERT INTO eval_runs (id, organization_id, dataset_id, "
                    "target_type, status, summary) "
                    "VALUES (gen_random_uuid(), :oid, NULL, 'rag', 'completed', "
                    "CAST('{}' AS jsonb)) RETURNING id"
                ),
                {"oid": oid},
            )
        ).fetchone()
        run_id = run.id
        await session.execute(
            text(
                "INSERT INTO eval_case_results (run_id, case_id, question, answer, "
                "status, scores) VALUES (:rid, 'c1', 'buena', 'ok', 'completed', "
                "CAST('{\"quality\": {\"composite_score\": 85, \"hallucination_rate\": 0.05}}' AS jsonb)), "
                "(:rid, 'c2', 'mala', 'no se', 'completed', "
                "CAST('{\"quality\": {\"composite_score\": 40, \"hallucination_rate\": 0.5}}' AS jsonb))"
            ),
            {"rid": run_id},
        )
        await session.commit()
    finally:
        await session.close()

    resp = await async_client.get(
        f"/api/v1/eval/runs/{run_id}/failures", headers=h
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["failures"][0]["case_id"] == "c2"
    assert any("score" in r for r in body["failures"][0]["reasons"])

    # Cross-org → 404.
    org_b = await _create_org(async_client, "Eval Fail B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    resp = await async_client.get(
        f"/api/v1/eval/runs/{run_id}/failures", headers=_headers(org_b)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_promotion_gate_blocks_without_eval(async_client: AsyncClient) -> None:
    """Con el gate activo, promover sin evaluación completada → 409."""
    from src.core.config import get_settings

    settings = get_settings()
    settings.EVAL_PROMOTION_MIN_SCORE = 80.0

    org = await _create_org(async_client, "Eval Gate")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    agent = await async_client.post(
        "/api/v1/agents",
        headers=h,
        json={"name": "Gate Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
    )
    assert agent.status_code == 201, agent.text
    aid = agent.json()["id"]
    version = (
        await async_client.post(
            f"/api/v1/agents/{aid}/versions", headers=h, json={}
        )
    ).json()
    vid = version["id"]

    # Promover a ready OK; a production debe bloquearse (sin run evaluado).
    ready = await async_client.post(
        f"/api/v1/agents/{aid}/versions/{vid}/promote",
        headers=h,
        json={"status": "ready"},
    )
    assert ready.status_code == 200, ready.text

    prod = await async_client.post(
        f"/api/v1/agents/{aid}/versions/{vid}/promote",
        headers=h,
        json={"status": "production"},
    )
    assert prod.status_code == 409, prod.text
    assert "Promotion blocked" in prod.json()["message"]

    # Con un run evaluado por encima del umbral, la promotion pasa.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO eval_runs (id, organization_id, dataset_id, target_type, "
                "target_id, target_name, version_id, status, summary) "
                "VALUES (gen_random_uuid(), :oid, NULL, 'agent', :aid, 'Gate Agent', :vid, "
                "'completed', CAST('{\"quality\": {\"composite_score\": 95, "
                "\"hallucination_rate\": 0.02}}' AS jsonb))"
            ),
            {"oid": UUID(org["organization_id"]), "aid": aid, "vid": str(vid)},
        )
        await session.commit()
    finally:
        await session.close()

    prod2 = await async_client.post(
        f"/api/v1/agents/{aid}/versions/{vid}/promote",
        headers=h,
        json={"status": "production"},
    )
    assert prod2.status_code == 200, prod2.text

    settings.EVAL_PROMOTION_MIN_SCORE = 0.0  # restaurar gate off
