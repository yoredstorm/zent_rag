# =============================================================================
# Phase 31B — Semantic Mapping Studio
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.catalog.physical_resolver import PhysicalResolver
from src.catalog.signals import infer_column, tokenize_physical
from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import (
    CatalogEntity,
    CatalogField,
    CatalogProvenance,
    CatalogSuggestion,
    SuggestionType,
)
from tests.test_catalog_api import _create_org, _owner_headers


def test_dsc_neighbors_varchar_is_description_high() -> None:
    result = infer_column(
        column_name="DSC",
        table_name="PRD01",
        data_type="VARCHAR(80)",
        neighbor_names=["CODPRD", "PRC"],
    )
    assert result.role == "DESCRIPTION"
    assert result.confidence == "high"
    assert "Description" in result.label or result.label == "Product Description"


def test_prc_ambiguous_vs_cost_no_auto_map() -> None:
    result = infer_column(column_name="PRC", data_type="numeric")
    assert result.auto_map is False
    assert result.conflicting is True
    assert result.alternatives


def test_a1672_tokenizes_to_ccust() -> None:
    assert tokenize_physical("A1672CCUST") == "CCUST"


async def _seed_source(org_id: UUID, table_name: str = "PRD01"):
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository

    store = PostgresCatalogStore()
    await store.ensure_tables()
    connector = await PostgresConnectorRepository().create_connector(
        org_id, f"c-{uuid4().hex[:8]}", "postgres", config_json={"host": "fake"}
    )
    src = await store.upsert_source(
        organization_id=org_id, connector_id=connector.id, engine="postgres"
    )
    source_id = UUID(str(src["id"]))
    table_id, _ = await store.upsert_table(
        organization_id=org_id,
        source_id=source_id,
        schema_name="",
        table_name=table_name,
    )
    return store, source_id, table_id


class TestStudioMaterialize:
    @pytest.mark.asyncio
    async def test_approve_field_mapping_materializes_and_versions(
        self, async_client: AsyncClient
    ) -> None:
        org = await _create_org(async_client, "Map Co", f"map-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store, source_id, table_id = await _seed_source(org_id)
        col_id = await store.upsert_column(
            organization_id=org_id,
            table_id=table_id,
            column_name="DSC",
            data_type="VARCHAR",
        )
        entity = CatalogEntity(
            organization_id=org_id,
            name="Product",
            display_name="Product",
            provenance=CatalogProvenance.INFERRED,
            status="draft",
            mapped_table_id=table_id,
        )
        await store.upsert_entity(entity)
        field = CatalogField(
            organization_id=org_id,
            entity_id=entity.id,
            name="Description",
            provenance=CatalogProvenance.INFERRED,
            confidence="high",
            mapped_column_id=col_id,
            status="draft",
            role="DESCRIPTION",
        )
        await store.upsert_field(field)
        suggestion_id = await store.create_suggestion(
            CatalogSuggestion(
                organization_id=org_id,
                type=SuggestionType.FIELD_MAPPING,
                title="DSC Description",
                payload={
                    "entity_id": str(entity.id),
                    "field_id": str(field.id),
                    "column_id": str(col_id),
                    "mapped_column_id": str(col_id),
                },
            )
        )
        approved = await async_client.post(
            f"/api/v1/catalog/suggestions/{suggestion_id}/approve",
            headers=headers,
            json={},
        )
        assert approved.status_code == 200, approved.text
        after = await store.get_field(org_id, field.id)
        assert after is not None
        assert after["status"] == "approved"
        assert after["provenance"] == "APPROVED"
        versions = await store.list_mapping_versions(org_id, field.id)
        assert versions

    @pytest.mark.asyncio
    async def test_tenant_b_studio_404(self, async_client: AsyncClient) -> None:
        org_a = await _create_org(async_client, "A Co", f"a-{uuid4().hex[:8]}@example.com")
        org_b = await _create_org(async_client, "B Co", f"b-{uuid4().hex[:8]}@example.com")
        headers_a = await _owner_headers(async_client, org_a)
        headers_b = await _owner_headers(async_client, org_b)
        org_id = UUID(org_a["organization_id"])
        _, source_id, _ = await _seed_source(org_id)
        ok = await async_client.get(
            f"/api/v1/catalog/studio/{source_id}", headers=headers_a
        )
        assert ok.status_code == 200, ok.text
        forbidden = await async_client.get(
            f"/api/v1/catalog/studio/{source_id}", headers=headers_b
        )
        assert forbidden.status_code == 404

    @pytest.mark.asyncio
    async def test_bulk_without_ids_400(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Bulk Co", f"bk-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        resp = await async_client.post(
            "/api/v1/catalog/studio/bulk",
            headers=headers,
            json={"suggestion_ids": [], "action": "approve"},
        )
        assert resp.status_code == 400


class TestLexiconIsolation:
    @pytest.mark.asyncio
    async def test_org_lexicon_isolated_and_a1672(self, async_client: AsyncClient) -> None:
        org_a = await _create_org(async_client, "Lex A", f"lx-a-{uuid4().hex[:8]}@example.com")
        org_b = await _create_org(async_client, "Lex B", f"lx-b-{uuid4().hex[:8]}@example.com")
        ha = await _owner_headers(async_client, org_a)
        hb = await _owner_headers(async_client, org_b)
        put = await async_client.put(
            "/api/v1/catalog/lexicon",
            headers=ha,
            json={
                "token": "CCUST",
                "meaning": "Customer Code",
                "role": "IDENTIFIER",
                "status": "approved",
            },
        )
        assert put.status_code == 200, put.text
        listed_a = await async_client.get("/api/v1/catalog/lexicon", headers=ha)
        assert any(r["token"] == "CCUST" for r in listed_a.json())
        listed_b = await async_client.get("/api/v1/catalog/lexicon", headers=hb)
        assert listed_b.json() == []
        store = PostgresCatalogStore()
        await store.ensure_tables()
        lex_a = store.lexicon_as_signals(await store.list_lexicon(UUID(org_a["organization_id"])))
        inferred_a = infer_column(column_name="A1672CCUST", org_lexicon=lex_a)
        assert "Customer" in inferred_a.label
        inferred_b = infer_column(
            column_name="A1672CCUST",
            org_lexicon={"CCUST": [("Warehouse Zone", "CATEGORY", 0.9)]},
        )
        assert inferred_b.label == "Warehouse Zone"


class TestEnumAndResolver:
    @pytest.mark.asyncio
    async def test_enum_not_auto_active_then_predicate(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Enum Co", f"en-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store, source_id, table_id = await _seed_source(org_id)
        col_id = await store.upsert_column(
            organization_id=org_id, table_id=table_id, column_name="EST", data_type="CHAR"
        )
        await store.upsert_enum_values(
            organization_id=org_id, column_id=col_id, values=["A", "I", "B"]
        )
        resolver = PhysicalResolver(store)
        before = await resolver.resolve_question(org_id, "productos activos", source_id=source_id)
        assert before.enum_predicates == []
        values = await store.list_enum_values(org_id, col_id)
        a_id = next(v["id"] for v in values if v["value"] == "A")
        put = await async_client.put(
            f"/api/v1/catalog/enums/{a_id}",
            headers=headers,
            json={"meaning": "Active"},
        )
        assert put.status_code == 200, put.text
        after = await resolver.resolve_question(org_id, "productos activos", source_id=source_id)
        assert any(p["value"] == "A" for p in after.enum_predicates)

    @pytest.mark.asyncio
    async def test_approve_override_and_reject_excluded(
        self, async_client: AsyncClient
    ) -> None:
        org = await _create_org(async_client, "Res Co", f"rs-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store, source_id, table_id = await _seed_source(org_id)
        prc = await store.upsert_column(
            organization_id=org_id, table_id=table_id, column_name="PRC", data_type="NUMERIC"
        )
        entity = CatalogEntity(
            organization_id=org_id, name="Product", provenance=CatalogProvenance.INFERRED
        )
        await store.upsert_entity(entity)
        price = CatalogField(
            organization_id=org_id,
            entity_id=entity.id,
            name="UnitPrice",
            provenance=CatalogProvenance.INFERRED,
            confidence="low",
            mapped_column_id=prc,
            status="draft",
            role="MEASURE",
            synonyms=["precio", "price"],
        )
        await store.upsert_field(price)
        sid = await store.create_suggestion(
            CatalogSuggestion(
                organization_id=org_id,
                type=SuggestionType.FIELD_MAPPING,
                title="PRC",
                payload={
                    "field_id": str(price.id),
                    "column_id": str(prc),
                    "mapped_column_id": str(prc),
                },
            )
        )
        await async_client.post(
            f"/api/v1/catalog/suggestions/{sid}/approve", headers=headers, json={}
        )
        resolved = await PhysicalResolver(store).resolve_question(
            org_id, "cuál es el precio del producto"
        )
        assert resolved.context_missing is False
        assert any("PRC" in cols for cols in resolved.allowlist.values())

        rejected = CatalogField(
            organization_id=org_id,
            entity_id=entity.id,
            name="UnitCost",
            provenance=CatalogProvenance.REJECTED,
            confidence="high",
            mapped_column_id=prc,
            status="draft",
            role="MEASURE",
            synonyms=["costo"],
        )
        await store.upsert_field(rejected)
        cost_q = await PhysicalResolver(store).resolve_question(org_id, "cuál es el costo")
        usable = [f for f in cost_q.mapped_fields if f.get("name") == "UnitCost"]
        assert usable == [] or cost_q.context_missing

    @pytest.mark.asyncio
    async def test_sql_context_missing_without_mapping(
        self, async_client: AsyncClient
    ) -> None:
        org = await _create_org(async_client, "Sql Co", f"sql-{uuid4().hex[:8]}@example.com")
        org_id = UUID(org["organization_id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()
        missing = await PhysicalResolver(store).resolve_question(
            org_id, "cuál es el precio"
        )
        assert missing.context_missing is True
        assert missing.studio_path.startswith("/knowledge/understanding")
        assert "precio" in missing.message.lower()

    @pytest.mark.asyncio
    async def test_readiness_labels_and_verified_draft(
        self, async_client: AsyncClient
    ) -> None:
        org = await _create_org(async_client, "Ready Co", f"rd-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        _, source_id, _ = await _seed_source(org_id)
        ready = await async_client.get(
            f"/api/v1/catalog/sources/{source_id}/readiness", headers=headers
        )
        assert ready.status_code == 200, ready.text
        body = ready.json()
        assert "labels" in body
        assert "structural" in body["labels"]
        assert "semantic" in body["labels"]
        assert "sql" in body["labels"]
        draft = await async_client.post(
            "/api/v1/catalog/studio/verified-query-draft",
            headers=headers,
            json={
                "question": "precio promedio",
                "sql": "SELECT PRC FROM PRD01 LIMIT 10",
            },
        )
        assert draft.status_code == 200, draft.text
        assert draft.json()["status"] == "DRAFT"

    @pytest.mark.asyncio
    async def test_free_text_stays_draft(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Ft Co", f"ft-{uuid4().hex[:8]}@example.com")
        headers = await _owner_headers(async_client, org)
        resp = await async_client.post(
            "/api/v1/catalog/studio/free-text",
            headers=headers,
            json={"text": "DSC es la descripción del producto"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["needs_confirm"] is True
        assert data["status"] == "draft"
