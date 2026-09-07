# =============================================================================
# Governed Learning — tests de API (FASE 25)
# =============================================================================
# Gaps, improvements, advisor, clusters, replays, spider, source health,
# dependency impact, why/why-not, agent readiness, revocación y tenant isolation.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
    ConfidenceLevel,
)


async def _create_org(client: AsyncClient, name: str, email: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={"company_name": name, "email": email, "country": "CL"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return {"organization_id": data["organization_id"]}


async def _owner_headers(client: AsyncClient, org: dict) -> dict:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user_repo = PostgresUserRepository()
    user = await user_repo.get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert user is not None, "default-admin user missing"
    session = encrypt_session(user.id, UUID(org["organization_id"]))
    return {
        "Authorization": f"Bearer {session}",
        "X-Organization-Id": org["organization_id"],
    }


async def _seed_gap(org_id: UUID) -> str:
    """Registra un gap via el analyzer (DATO REAL, no fabricado)."""
    from src.intelligence.store import PostgresIntelligenceStore
    from src.learning.gaps import ContextGapAnalyzer
    from src.learning.store import PostgresLearningStore

    learning = PostgresLearningStore()
    intel = PostgresIntelligenceStore()
    await learning.ensure_tables()
    await intel.ensure_tables()
    decision = AnswerabilityDecision(
        status=AnswerabilityStatus.DATA_MISSING,
        answerable=False,
        confidence_level=ConfidenceLevel.INSUFFICIENT,
        reason_codes=["NO_SQL_RESULT"],
        missing_data=["costo de producto / COGS"],
        message="No tengo suficiente información.",
    )
    await ContextGapAnalyzer(learning, intelligence_store=intel).analyze_and_record(
        organization_id=org_id,
        user_id=None,
        question="¿Cuál es el margen bruto?",
        decision=decision,
    )
    gaps = await intel.list_gaps(org_id, gap_type="MISSING_TABLE", limit=1)
    return gaps[0]["id"] if gaps else ""


class TestGapsApi:
    @pytest.mark.asyncio
    async def test_list_and_resolve(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Gap Co", f"g-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        gap_id = await _seed_gap(UUID(org["organization_id"]))
        assert gap_id

        listed = await async_client.get(
            "/api/v1/learning/gaps?gap_type=MISSING_TABLE", headers=headers
        )
        assert listed.status_code == 200
        assert any(g["id"] == gap_id for g in listed.json())

        resolved = await async_client.post(
            f"/api/v1/learning/gaps/{gap_id}/resolve", headers=headers
        )
        assert resolved.status_code == 200
        after = await async_client.get(
            "/api/v1/learning/gaps?status=resolved", headers=headers
        )
        assert any(g["id"] == gap_id for g in after.json())


class TestAdvisorApi:
    @pytest.mark.asyncio
    async def test_advise_with_question(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Adv Co", f"a-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        resp = await async_client.get(
            "/api/v1/learning/advisor",
            headers=headers,
            params={"question": "¿Cuál es el margen bruto?", "concept": "margen"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "available" in body and "missing" in body and "recommendation" in body


class TestImprovementsApi:
    @pytest.mark.asyncio
    async def test_status_transition_and_owner(self, async_client: AsyncClient) -> None:
        from src.core.domain.learning import (
            ImprovementItem,
        )
        from src.learning.store import PostgresLearningStore

        org = await _create_org(async_client, "Imp Co", f"i-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        store = PostgresLearningStore()
        await store.ensure_tables()
        item = ImprovementItem(
            organization_id=UUID(org["organization_id"]),
            gap_type="MISSING_METRIC",
            title="margen (MISSING_METRIC)",
            cluster_key="margen",
            affected_queries=48,
        )
        item_id = await store.upsert_improvement(item)

        listed = await async_client.get(
            "/api/v1/learning/improvements?status=OPEN", headers=headers
        )
        assert listed.status_code == 200
        assert any(i["id"] == str(item_id) for i in listed.json())

        updated = await async_client.post(
            f"/api/v1/learning/improvements/{item_id}/status",
            headers=headers,
            json={"status": "IN_REVIEW", "owner": "Finance"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "IN_REVIEW"
        assert updated.json()["owner"] == "Finance"

        invalid = await async_client.post(
            f"/api/v1/learning/improvements/{item_id}/status",
            headers=headers,
            json={"status": "NOPE"},
        )
        assert invalid.status_code == 400


class TestClustersApi:
    @pytest.mark.asyncio
    async def test_clusters_create_improvements_in_review(
        self, async_client: AsyncClient
    ) -> None:
        from src.intelligence.store import PostgresIntelligenceStore

        org = await _create_org(async_client, "Clu Co", f"c-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = PostgresIntelligenceStore()
        await store.ensure_tables()

        from src.core.domain.intelligence import IntelligenceTrace

        for question in [
            "cliente rentable",
            "clientes con rentabilidad",
            "cuentas rentables",
            "clientes que generan margen",
        ]:
            await store.save_trace(
                IntelligenceTrace(
                    organization_id=org_id,
                    user_query=question,
                    status="DATA_MISSING",
                    decision={"status": "DATA_MISSING", "answerable": False},
                )
            )

        resp = await async_client.get(
            "/api/v1/learning/clusters?days=30", headers=headers
        )
        assert resp.status_code == 200, resp.text
        clusters = resp.json()
        assert any(c["size"] >= 3 for c in clusters)

        improvements = await async_client.get(
            "/api/v1/learning/improvements?status=IN_REVIEW", headers=headers
        )
        assert any(
            i["suggested_concept"] and "cliente" in i["suggested_concept"]
            for i in improvements.json()
        )


class TestReplayApi:
    @pytest.mark.asyncio
    async def test_start_replay_and_list(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Replay Co", f"r-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        started = await async_client.post(
            "/api/v1/learning/replay",
            headers=headers,
            json={"knowledge_type": "metric", "knowledge_id": "net_revenue"},
        )
        assert started.status_code == 201, started.text
        replay_id = started.json()["replay_id"]
        listed = await async_client.get("/api/v1/learning/replays", headers=headers)
        assert listed.status_code == 200
        assert any(r["id"] == replay_id for r in listed.json())


class TestSpiderApi:
    @pytest.mark.asyncio
    async def test_policy_crud_and_run(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Spider Co", f"s-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        created = await async_client.post(
            "/api/v1/learning/spider/policies",
            headers=headers,
            json={
                "name": "erp-daily",
                "schedule_hours": 24,
                "allowed_schemas": ["erp"],
                "profiling_level": "none",
                "pii_policy": "never",
            },
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["id"]
        assert created.json()["pii_policy"] == "never"

        listed = await async_client.get(
            "/api/v1/learning/spider/policies", headers=headers
        )
        assert any(p["id"] == policy_id for p in listed.json())

        invalid = await async_client.post(
            "/api/v1/learning/spider/policies",
            headers=headers,
            json={"name": "bad", "pii_policy": "always"},
        )
        assert invalid.status_code == 400


class TestSourceHealthAndImpact:
    @pytest.mark.asyncio
    async def test_health_and_dependency_impact(self, async_client: AsyncClient) -> None:
        from src.catalog.store import PostgresCatalogStore
        from src.infrastructure.postgres.relational_db import (
            PostgresConnectorRepository,
        )

        org = await _create_org(async_client, "Health Co", f"h-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()
        connector = await PostgresConnectorRepository().create_connector(
            org_id, f"c-{uuid4().hex[:8]}", "postgres", config_json={"host": "fake"}
        )
        src = await store.upsert_source(
            organization_id=org_id, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        table_id, _ = await store.upsert_table(
            organization_id=org_id, source_id=source_id,
            schema_name="erp", table_name="SALES",
        )
        await store.upsert_column(
            organization_id=org_id, table_id=table_id,
            column_name="net_revenue", data_type="numeric",
        )
        await store.update_source(org_id, source_id, phase="COMPLETED")

        health = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}/health", headers=headers
        )
        assert health.status_code == 200, health.text
        assert health.json()["connectivity"] == "healthy"

        impact = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}/dependency-impact", headers=headers
        )
        assert impact.status_code == 200
        assert impact.json()["tables"] >= 1

        deleted = await async_client.delete(
            f"/api/v1/connectors/{connector.id}", headers=headers
        )
        assert deleted.status_code == 200
        assert deleted.json()["revocation_impact"]["invalidated"] is True

        gone = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}/health", headers=headers
        )
        assert gone.status_code == 404


class TestWhyEndpoints:
    @pytest.mark.asyncio
    async def test_why_and_why_not(self, async_client: AsyncClient) -> None:
        from src.core.domain.intelligence import IntelligenceTrace
        from src.intelligence.store import PostgresIntelligenceStore

        org = await _create_org(async_client, "Why Co", f"w-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = PostgresIntelligenceStore()
        await store.ensure_tables()
        query_id = uuid4()
        await store.save_trace(
            IntelligenceTrace(
                organization_id=org_id,
                query_id=query_id,
                user_query="¿Cuál es la política de devolución?",
                status="CONTEXT_MISSING",
                answer="No tengo suficiente información.",
                decision={
                    "status": "CONTEXT_MISSING",
                    "answerable": False,
                    "confidence_level": "low",
                    "missing_context": ["Definition of cliente_activo"],
                    "missing_data": [],
                },
                understanding={"intent": "business_metric", "concepts": ["cliente_activo"]},
            )
        )
        why = await async_client.get(
            f"/api/v1/intelligence/why/{query_id}", headers=headers
        )
        assert why.status_code == 200, why.text
        assert why.json()["intent"] == "business_metric"

        why_not = await async_client.get(
            f"/api/v1/intelligence/why-not/{query_id}", headers=headers
        )
        assert why_not.status_code == 200
        assert why_not.json()["status"] == "CONTEXT_MISSING"
        assert why_not.json()["missing"]


class TestAgentReadinessApi:
    @pytest.mark.asyncio
    async def test_agent_intelligence_readiness(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Ready Co", f"rd-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        created = await async_client.post(
            "/api/v1/agents",
            headers=headers,
            json={
                "name": f"Agent {uuid4().hex[:6]}",
                "model": "gpt-4o-mini",
                "system_prompt": "Eres un asistente.",
            },
        )
        assert created.status_code in (200, 201), created.text
        agent_id = created.json().get("id")
        if not agent_id:
            pytest.skip("agent creation unavailable")
        resp = await async_client.get(
            f"/api/v1/agents/{agent_id}/intelligence-readiness", headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "dimensions" in body
        assert body["overall"] in ("HIGH", "MEDIUM", "LOW")


class TestLearningTenantIsolation:
    @pytest.mark.asyncio
    async def test_gaps_and_improvements_never_cross_tenant(
        self, async_client: AsyncClient
    ) -> None:
        org_a = await _create_org(async_client, "Iso A", f"ia-{uuid4().hex[:8]}@example.com")
        org_b = await _create_org(async_client, "Iso B", f"ib-{uuid4().hex[:8]}@example.com")
        headers_a = await _owner_headers(async_client, org_a)
        headers_b = await _owner_headers(async_client, org_b)
        gap_id = await _seed_gap(UUID(org_a["organization_id"]))
        assert gap_id

        gaps_b = await async_client.get("/api/v1/learning/gaps", headers=headers_b)
        assert gaps_b.status_code == 200
        assert all(g["id"] != gap_id for g in gaps_b.json())

        resolve_b = await async_client.post(
            f"/api/v1/learning/gaps/{gap_id}/resolve", headers=headers_b
        )
        assert resolve_b.status_code == 404
