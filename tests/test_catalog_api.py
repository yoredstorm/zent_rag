# =============================================================================
# Catalog API — tests de integración HTTP (FASE 24)
# =============================================================================
# Glosario, métricas (con sync a business_definitions), autoridad, review
# queue con materialización, readiness y aislamiento multi-tenant.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.catalog import (
    CatalogEntity,
    CatalogProvenance,
    CatalogSuggestion,
    SuggestionType,
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


class TestGlossaryApi:
    @pytest.mark.asyncio
    async def test_crud_approve_and_versioning(
        self, async_client: AsyncClient
    ) -> None:
        org = await _create_org(async_client, "Gloss Co", f"g-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)

        created = await async_client.post(
            "/api/v1/catalog/glossary",
            headers=headers,
            json={
                "concept": "Active Customer",
                "definition": "Cliente con compra en los últimos 90 días",
                "synonyms": ["cliente activo", "active account"],
                "owner": "Commercial",
                "status": "approved",
            },
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["concept"] == "active customer"
        assert payload["synonyms"] == ["cliente activo", "active account"]
        assert payload["owner"] == "Commercial"
        assert payload["provenance"] == "APPROVED"

        updated = await async_client.post(
            "/api/v1/catalog/glossary",
            headers=headers,
            json={
                "concept": "Active Customer",
                "definition": "Cliente con compra en los últimos 60 días",
                "status": "draft",
            },
        )
        assert updated.status_code == 201
        assert updated.json()["version"] == 2
        assert updated.json()["status"] == "draft"

        approved = await async_client.post(
            "/api/v1/catalog/glossary/active customer/approve",
            headers=headers,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert approved.json()["provenance"] == "APPROVED"

        listed = await async_client.get(
            "/api/v1/catalog/glossary", headers=headers
        )
        concepts = [d["concept"] for d in listed.json()]
        assert "active customer" in concepts

        deleted = await async_client.delete(
            "/api/v1/catalog/glossary/active customer", headers=headers
        )
        assert deleted.status_code == 200


class TestMetricsApi:
    @pytest.mark.asyncio
    async def test_approve_syncs_to_business_definitions(
        self, async_client: AsyncClient
    ) -> None:
        org = await _create_org(async_client, "Metrics Co", f"m-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)

        created = await async_client.post(
            "/api/v1/catalog/metrics",
            headers=headers,
            json={
                "metric_key": "net_revenue",
                "name": "Net Revenue",
                "definition": "Ingresos netos del período",
                "formula": "SUM(revenue) - SUM(refunds)",
                "time_semantics": "monthly",
                "currency_semantics": "USD",
                "owner": "Finance",
                "status": "draft",
            },
        )
        assert created.status_code == 201, created.text
        metric_id = created.json()["id"]
        assert created.json()["status"] == "draft"

        approved = await async_client.post(
            f"/api/v1/catalog/metrics/{metric_id}/approve", headers=headers
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        # Sync idempotente a business_definitions (Answerability Gate).
        definitions = await async_client.get(
            "/api/v1/intelligence/definitions", headers=headers
        )
        assert definitions.status_code == 200
        defs = {d["concept"]: d for d in definitions.json()}
        assert "net_revenue" in defs
        assert defs["net_revenue"]["data_type"] == "metric"
        assert defs["net_revenue"]["expression"] == "SUM(revenue) - SUM(refunds)"

        lineage = await async_client.get(
            "/api/v1/catalog/lineage?object_type=business_metric",
            headers=headers,
        )
        assert lineage.status_code == 200
        assert lineage.json()


class TestAuthorityApi:
    @pytest.mark.asyncio
    async def test_upsert_and_list(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Auth Co", f"a-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)

        created = await async_client.post(
            "/api/v1/catalog/authority",
            headers=headers,
            json={
                "domain": "pricing",
                "concept": "current price",
                "source_name": "ERP",
                "authority_level": "authoritative",
                "priority": 10,
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["source_name"] == "ERP"

        listed = await async_client.get("/api/v1/catalog/authority", headers=headers)
        assert listed.status_code == 200
        assert any(a["concept"] == "current price" for a in listed.json())


class TestReviewQueueApi:
    @pytest.mark.asyncio
    async def test_approve_entity_suggestion_materializes(
        self, async_client: AsyncClient
    ) -> None:
        from src.catalog.store import PostgresCatalogStore

        org = await _create_org(async_client, "Review Co", f"r-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()

        from src.infrastructure.postgres.relational_db import (
            PostgresConnectorRepository,
        )

        connector = await PostgresConnectorRepository().create_connector(
            org_id, f"c-{uuid4().hex[:8]}", "postgres", config_json={"host": "fake"}
        )
        src = await store.upsert_source(
            organization_id=org_id, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]

        entity = CatalogEntity(
            organization_id=org_id,
            name="customer",
            provenance=CatalogProvenance.INFERRED,
            confidence="medium",
            evidence=["column names"],
            status="draft",
        )
        await store.upsert_entity(entity)
        table_id, _ = await store.upsert_table(
            organization_id=org_id, source_id=source_id,
            schema_name="erp", table_name="TBL_CUST",
        )
        suggestion = CatalogSuggestion(
            organization_id=org_id,
            type=SuggestionType.ENTITY_IDENTIFICATION,
            title="'erp.TBL_CUST' probablemente representa Customer.",
            description="Sugerencia INFERRED",
            evidence=["table naming patterns"],
            confidence="medium",
            payload={
                "entity_id": str(entity.id),
                "entity_name": "customer",
                "table_id": str(table_id),
            },
        )
        suggestion_id = await store.create_suggestion(suggestion)

        listed = await async_client.get(
            "/api/v1/catalog/suggestions?status=pending", headers=headers
        )
        assert listed.status_code == 200
        assert any(s["id"] == str(suggestion_id) for s in listed.json())

        approved = await async_client.post(
            f"/api/v1/catalog/suggestions/{suggestion_id}/approve",
            headers=headers,
            json={"payload": None},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        entity_after = await store.get_entity(org_id, entity.id)
        assert entity_after["status"] == "approved"
        assert entity_after["provenance"] == "APPROVED"

        lineage = await store.list_lineage(org_id, limit=100)
        assert any(
            e["upstream_type"] == "business_entity"
            and e["upstream_id"] == str(entity.id)
            for e in lineage
        )

    @pytest.mark.asyncio
    async def test_reject_marks_rejected(self, async_client: AsyncClient) -> None:
        from src.catalog.store import PostgresCatalogStore

        org = await _create_org(async_client, "Rej Co", f"rj-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()

        suggestion = CatalogSuggestion(
            organization_id=org_id,
            type=SuggestionType.GLOSSARY_TERM,
            title="Propuesta de término",
            payload={"concept": "cliente activo", "definition": "x"},
        )
        suggestion_id = await store.create_suggestion(suggestion)

        rejected = await async_client.post(
            f"/api/v1/catalog/suggestions/{suggestion_id}/reject",
            headers=headers,
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["reviewed_by"] is not None


class TestReadinessApi:
    @pytest.mark.asyncio
    async def test_readiness_breakdown(self, async_client: AsyncClient) -> None:
        from src.catalog.store import PostgresCatalogStore

        org = await _create_org(async_client, "Ready Co", f"rd-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()

        from src.infrastructure.postgres.relational_db import (
            PostgresConnectorRepository,
        )

        connector = await PostgresConnectorRepository().create_connector(
            org_id, f"c-{uuid4().hex[:8]}", "postgres", config_json={"host": "fake"}
        )
        src = await store.upsert_source(
            organization_id=org_id, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        table_id, _ = await store.upsert_table(
            organization_id=org_id, source_id=source_id,
            schema_name="erp", table_name="TBL_CUST",
        )
        await store.upsert_column(
            organization_id=org_id, table_id=table_id,
            column_name="CUST_ID", data_type="uuid",
        )
        await store.update_source(org_id, source_id, phase="COMPLETED")

        resp = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}/readiness", headers=headers
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert "overall" in payload
        assert payload["schema_coverage"] > 0
        assert payload["pending_review_count"] >= 0


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_catalog_objects_never_cross_tenant(
        self, async_client: AsyncClient
    ) -> None:
        from src.catalog.store import PostgresCatalogStore

        org_a = await _create_org(async_client, "Iso A", f"ia-{uuid4().hex[:8]}@example.com")
        org_b = await _create_org(async_client, "Iso B", f"ib-{uuid4().hex[:8]}@example.com")
        headers_a = await _owner_headers(async_client, org_a)
        headers_b = await _owner_headers(async_client, org_b)
        store = PostgresCatalogStore()
        await store.ensure_tables()

        from src.infrastructure.postgres.relational_db import (
            PostgresConnectorRepository,
        )

        connector = await PostgresConnectorRepository().create_connector(
            UUID(org_a["organization_id"]), f"c-{uuid4().hex[:8]}", "postgres",
            config_json={"host": "fake"},
        )
        src = await store.upsert_source(
            organization_id=UUID(org_a["organization_id"]),
            connector_id=connector.id,
            engine="postgres",
        )
        source_id = src["id"]

        # B no ve la fuente de A: 404.
        resp_b = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}", headers=headers_b
        )
        assert resp_b.status_code == 404

        # A sí la ve.
        resp_a = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}", headers=headers_a
        )
        assert resp_a.status_code == 200

        # Glosario de A invisible para B.
        await async_client.post(
            "/api/v1/catalog/glossary",
            headers=headers_a,
            json={"concept": "margen", "definition": "Ventas - COGS"},
        )
        glossary_b = await async_client.get(
            "/api/v1/catalog/glossary", headers=headers_b
        )
        assert all(d["concept"] != "margen" for d in glossary_b.json())


class TestSourceDeletionCascade:
    @pytest.mark.asyncio
    async def test_delete_connector_cascades_catalog(self, async_client: AsyncClient) -> None:
        from src.catalog.store import PostgresCatalogStore

        org = await _create_org(async_client, "Del Co", f"d-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()

        from src.infrastructure.postgres.relational_db import (
            PostgresConnectorRepository,
        )

        connector_repo = PostgresConnectorRepository()
        connector = await connector_repo.create_connector(
            org_id, f"c-{uuid4().hex[:8]}", "postgres", config_json={"host": "fake"}
        )
        src = await store.upsert_source(
            organization_id=org_id, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        table_id, _ = await store.upsert_table(
            organization_id=org_id, source_id=source_id,
            schema_name="erp", table_name="TBL_CUST",
        )
        await store.upsert_column(
            organization_id=org_id, table_id=table_id,
            column_name="status_cd", data_type="character varying",
        )

        deleted = await async_client.delete(
            f"/api/v1/connectors/{connector.id}", headers=headers
        )
        assert deleted.status_code == 200

        # El catálogo se purgó en cascada.
        resp = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}", headers=headers
        )
        assert resp.status_code == 404
        assert await store.get_table(org_id, table_id) is None
