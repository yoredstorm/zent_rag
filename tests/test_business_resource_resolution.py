# =============================================================================
# Prompt 05 — Business Resource Resolution.
#
# Seed real tenant rows in Semantic Catalog / Mapping Studio / Catalog Authority
# and verify dynamic discovery, fields, authority, bindings, agents and API.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import (
    CatalogAuthority,
    CatalogEntity,
    CatalogField,
    CatalogProvenance,
    FieldRole,
    MappingType,
)
from src.infrastructure.postgres.relational_db import PostgresAgentRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.bindings import upsert_binding
from src.platform.workflows.business_resources import BusinessResourceResolver
from tests.test_workflows import _create_org, _headers, _owner_session


async def _connector(organization_id: UUID, name: str) -> UUID:
    connector_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO connectors (id, organization_id, name, type, status) "
                "VALUES (:id, :oid, :name, 'sql', 'active')"
            ),
            {"id": connector_id, "oid": organization_id, "name": name[:255]},
        )
        await session.commit()
    finally:
        await session.close()
    return connector_id


async def _knowledge_base(organization_id: UUID, name: str) -> UUID:
    kb_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO knowledge_bases "
                "(id, organization_id, name, description, status, embedding_model, metadata_schema) "
                "VALUES (:id, :oid, :name, :description, 'active', 'test', "
                "CAST(:schema AS jsonb))"
            ),
            {
                "id": kb_id,
                "oid": organization_id,
                "name": name[:255],
                "description": "Base de conocimiento documental del tenant.",
                "schema": '{"type": "object", "properties": {"title": {"type": "string"}}}',
            },
        )
        await session.commit()
    finally:
        await session.close()
    return kb_id


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


async def _seed_catalog(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    duplicate_stock: bool = False,
    authority: bool = True,
    bind_product_search: bool = True,
    bind_payment: bool = True,
    seed_agent: bool = True,
    seed_kb: bool = True,
) -> dict:
    store = PostgresCatalogStore()
    await store.ensure_tables()
    kb_id = (
        await _knowledge_base(organization_id, f"Productos KB {uuid4().hex[:8]}")
        if seed_kb
        else None
    )
    products_connector = await _connector(organization_id, f"products-{uuid4().hex[:8]}")
    inventory_connector = await _connector(organization_id, f"inventory-{uuid4().hex[:8]}")
    products_source = await store.upsert_source(
        organization_id=organization_id,
        connector_id=products_connector,
        workspace_id=workspace_id,
        engine="postgres",
    )
    inventory_source = await store.upsert_source(
        organization_id=organization_id,
        connector_id=inventory_connector,
        workspace_id=workspace_id,
        engine="postgres",
    )
    await store.update_source(
        organization_id, _as_uuid(products_source["id"]), phase="COMPLETED"
    )
    await store.update_source(
        organization_id, _as_uuid(inventory_source["id"]), phase="COMPLETED"
    )
    products_table, _ = await store.upsert_table(
        organization_id=organization_id,
        source_id=_as_uuid(products_source["id"]),
        schema_name="commerce",
        table_name="products",
        row_count_approx=120,
        table_comment="Catálogo real de productos",
    )
    inventory_table, _ = await store.upsert_table(
        organization_id=organization_id,
        source_id=_as_uuid(inventory_source["id"]),
        schema_name="inventory",
        table_name="stock",
        row_count_approx=500,
        table_comment="Stock transaccional por SKU",
    )
    column_ids: dict[str, UUID] = {}
    for index, (name, data_type, nullable, pk) in enumerate(
        [
            ("product_id", "uuid", False, True),
            ("name", "text", False, False),
            ("price", "numeric", False, False),
            ("currency", "text", False, False),
            ("stock", "integer", False, False),
            ("brand", "text", True, False),
        ]
    ):
        column_ids[name] = await store.upsert_column(
            organization_id=organization_id,
            table_id=products_table,
            column_name=name,
            ordinal_position=index,
            data_type=data_type,
            nullable=nullable,
            is_primary_key=pk,
        )
    stock_column = await store.upsert_column(
        organization_id=organization_id,
        table_id=inventory_table,
        column_name="stock",
        ordinal_position=0,
        data_type="integer",
        nullable=False,
    )
    if duplicate_stock:
        legacy_connector = await _connector(
            organization_id, f"legacy-{uuid4().hex[:8]}"
        )
        legacy_source = await store.upsert_source(
            organization_id=organization_id,
            connector_id=legacy_connector,
            workspace_id=workspace_id,
            engine="postgres",
        )
        legacy_table, _ = await store.upsert_table(
            organization_id=organization_id,
            source_id=_as_uuid(legacy_source["id"]),
            schema_name="legacy",
            table_name="stock_old",
            table_comment="Stock legado no autoritativo",
        )
        await store.upsert_column(
            organization_id=organization_id,
            table_id=legacy_table,
            column_name="stock",
            ordinal_position=0,
            data_type="integer",
            nullable=False,
        )

    entity = CatalogEntity(
        organization_id=organization_id,
        name="Product",
        display_name="Producto",
        description="Producto vendible del catálogo",
        provenance=CatalogProvenance.APPROVED,
        confidence="high",
        mapped_table_id=products_table,
        status="approved",
    )
    await store.upsert_entity(entity)
    for field_name, role, unit, currency in [
        ("product_id", FieldRole.IDENTIFIER.value, None, None),
        ("name", FieldRole.DESCRIPTION.value, None, None),
        ("price", FieldRole.MEASURE.value, "unit", "PEN"),
        ("currency", FieldRole.CATEGORY.value, None, None),
        ("stock", FieldRole.MEASURE.value, "unit", None),
        ("brand", FieldRole.CATEGORY.value, None, None),
    ]:
        await store.upsert_field(
            CatalogField(
                organization_id=organization_id,
                entity_id=entity.id,
                name=field_name,
                provenance=CatalogProvenance.APPROVED,
                confidence="high",
                mapped_column_id=column_ids[field_name],
                status="approved",
                role=role,
                mapping_type=MappingType.DIRECT.value,
                unit=unit,
                currency=currency,
            )
        )

    if authority:
        await store.upsert_authority(
            CatalogAuthority(
                organization_id=organization_id,
                domain="commerce",
                concept="stock",
                source_name="inventory-primary",
                source_type="connector",
                connector_id=inventory_connector,
                authority_level="authoritative",
                priority=10,
            )
        )
    if bind_product_search:
        await upsert_binding(
            organization_id,
            "catalog.products.search",
            "managed_db",
            workspace_id=workspace_id,
            config={"database_id": str(uuid4())},
            contract_input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
            contract_output_schema={
                "type": "object",
                "properties": {"products": {"type": "array"}},
            },
        )
    if bind_payment:
        await upsert_binding(
            organization_id,
            "payments.qr.create",
            "rest_api",
            workspace_id=workspace_id,
            config={"url": "https://sandbox-payments.example/qr", "purpose": "test"},
            contract_input_schema={
                "type": "object",
                "required": ["amount", "currency"],
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                },
            },
            contract_output_schema={
                "type": "object",
                "properties": {"qr_url": {"type": "string"}},
            },
        )
    if seed_agent:
        repository = PostgresAgentRepository()
        await repository.create_agent(
            organization_id,
            "Asistente de catálogo",
            description="Consulta productos, stock y alternativas de marca.",
            workspace_id=workspace_id,
            tools=["catalog_search", "stock_lookup"],
            config_json={
                "purpose": "Seleccionar productos disponibles y explicar alternativas",
                "tools": ["catalog_search", "stock_lookup"],
                "knowledge_base_ids": [],
                "budget": {"monthly_usd": 25},
                "version": 3,
            },
        )
    return {
        "products_table": str(products_table),
        "inventory_table": str(inventory_table),
        "stock_column": str(stock_column),
        "products_connector": str(products_connector),
        "inventory_connector": str(inventory_connector),
        "entity_id": str(entity.id),
        "kb_id": str(kb_id) if kb_id else None,
    }


@pytest.mark.asyncio
async def test_discovers_catalog_entity_fields_mapping_and_currency(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Catalog")
    org_id = UUID(org["organization_id"])
    seeded = await _seed_catalog(org_id)
    resolver = BusinessResourceResolver(
        org_id, permissions=frozenset({"workflows:read", "agents:execute"})
    )
    report = await resolver.resolve_need(
        "catálogo real de productos con precio y moneda",
        required_fields=[
            {"name": "name", "type": "string"},
            {"name": "price", "type": "number"},
            {"name": "currency", "type": "string"},
        ],
    )
    assert report.resolved is True, report.model_dump()
    assert report.selected is not None
    assert report.selected.resource_ref == f"catalog.entity.{seeded['entity_id']}"
    assert any(field.name == "price" and field.currency == "PEN" for field in report.selected.fields)
    assert any(field.name == "brand" for field in report.selected.fields)
    assert report.trace["catalog_tables"] >= 2
    assert report.trace["discovered_from"].startswith("tenant_catalog")


@pytest.mark.asyncio
async def test_authority_selects_inventory_and_does_not_pick_first(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Authority")
    org_id = UUID(org["organization_id"])
    seeded = await _seed_catalog(org_id, duplicate_stock=True)
    resolver = BusinessResourceResolver(org_id)
    report = await resolver.resolve_need(
        "stock transaccional por SKU",
        required_fields=[{"name": "stock", "type": "integer"}],
        concepts=["stock"],
        domain="commerce",
    )
    assert report.resolved is True, report.model_dump()
    assert report.selected is not None
    assert report.selected.resource_ref == f"catalog.table.{seeded['inventory_table']}"
    assert report.authority[0].status == "resolved"


@pytest.mark.asyncio
async def test_ambiguous_stock_without_authority_requires_confirmation(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Ambiguous")
    org_id = UUID(org["organization_id"])
    await _seed_catalog(org_id, duplicate_stock=True, authority=False)
    resolver = BusinessResourceResolver(org_id)
    report = await resolver.resolve_need(
        "stock transaccional por SKU",
        required_fields=[{"name": "stock", "type": "integer"}],
        concepts=["stock"],
        domain="commerce",
    )
    assert report.resolved is False
    assert report.selected is None
    codes = {item["code"] for item in report.ambiguities + report.unresolved}
    assert "RESOURCE_AMBIGUOUS" in codes or "RESOURCE_AUTHORITY_AMBIGUOUS" in codes
    guidance = {item.code for item in report.guided_configuration}
    assert "RESOURCE_CATALOG_REQUIRED" in guidance or "RESOURCE_AUTHORITY_MISSING" in guidance


@pytest.mark.asyncio
async def test_missing_required_field_is_explicit(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Missing Field")
    org_id = UUID(org["organization_id"])
    await _seed_catalog(org_id, authority=False)
    resolver = BusinessResourceResolver(org_id)
    report = await resolver.resolve_need(
        "catálogo de productos",
        required_fields=[{"name": "cost", "type": "number"}],
        kinds=["catalog_table", "catalog_entity"],
    )
    assert report.resolved is False
    assert any(
        item.get("code") == "RESOURCE_FIELD_MISSING"
        and "cost" in (item.get("fields") or [])
        for item in report.unresolved
    )
    assert any(item.code == "RESOURCE_CATALOG_REQUIRED" for item in report.guided_configuration)


@pytest.mark.asyncio
async def test_binding_is_resolved_by_logical_capability(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Binding")
    org_id = UUID(org["organization_id"])
    await _seed_catalog(org_id)
    resolver = BusinessResourceResolver(org_id)
    report = await resolver.resolve_need(
        "productos",
        capability_refs=[
            "catalog.products.search",
            "sales.cart.quote",
            "sales.order.create",
            "payments.checkout.create",
            "payments.qr.create",
        ],
    )
    reported_refs = {item.capability_ref for item in report.bindings}
    assert {
        "catalog.products.search",
        "sales.cart.quote",
        "sales.order.create",
        "payments.checkout.create",
        "payments.qr.create",
    } <= reported_refs
    binding = next(
        item for item in report.bindings if item.capability_ref == "catalog.products.search"
    )
    assert binding.binding_found is True
    assert binding.provider_kind == "managed_db"
    assert binding.binding_id
    missing_payment = next(
        item for item in report.bindings if item.capability_ref == "payments.checkout.create"
    )
    assert missing_payment.binding_found is False
    payment_qr = next(
        item for item in report.bindings if item.capability_ref == "payments.qr.create"
    )
    assert payment_qr.binding_found is True
    assert payment_qr.provider_kind == "rest_api"
    assert any(
        item.requirement
        in (
            "capability:payments.checkout.create",
            "permission:payments.checkout.create",
        )
        for item in report.guided_configuration
    ), [(item.requirement, item.code) for item in report.guided_configuration]
    dumped = binding.model_dump(mode="json")
    assert "config" not in dumped
    assert "credential" not in str(dumped.get("reasons") or "").lower()


@pytest.mark.asyncio
async def test_knowledge_is_distinguished_from_transactional_data(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Knowledge")
    org_id = UUID(org["organization_id"])
    seeded = await _seed_catalog(org_id)
    resolver = BusinessResourceResolver(org_id)
    report = await resolver.resolve_need(
        "políticas documentales de productos",
        kinds=["knowledge_base"],
    )
    assert report.selected is not None
    assert report.selected.resource_ref == f"resource.knowledge_base.{seeded['kb_id']}"
    assert report.selected.resource_class == "knowledge"


@pytest.mark.asyncio
async def test_agents_are_ranked_by_purpose_and_tools(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Agents")
    org_id = UUID(org["organization_id"])
    await _seed_catalog(org_id)
    resolver = BusinessResourceResolver(
        org_id, permissions=frozenset({"workflows:read", "agents:execute"})
    )
    report = await resolver.resolve_need(
        "elegir productos usando la herramienta stock_lookup",
        kinds=["agent"],
    )
    assert report.agent_candidates
    top = report.agent_candidates[0]
    assert top["agent_id"]
    assert "stock_lookup" in (top.get("tools") or [])
    assert top.get("budget", {}).get("monthly_usd") == 25
    assert top.get("version") == 3


@pytest.mark.asyncio
async def test_workspace_isolation_hides_other_workspace_tables(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource Workspace")
    org_id = UUID(org["organization_id"])
    workspace_a = uuid4()
    await _seed_catalog(org_id, workspace_id=workspace_a, seed_agent=False)
    resolver_b = BusinessResourceResolver(
        org_id, workspace_id=uuid4(), permissions=frozenset({"workflows:read"})
    )
    report = await resolver_b.resolve_need(
        "catálogo de productos", kinds=["catalog_table", "catalog_entity"]
    )
    assert report.selected is None
    assert not [item for item in report.candidates if item.resource_ref.startswith("catalog.")]


@pytest.mark.asyncio
async def test_resource_api_returns_governed_report(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Resource API")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    await _seed_catalog(UUID(org["organization_id"]))
    response = await async_client.post(
        "/api/v1/workflows/architect/resources/resolve",
        headers=_headers(org),
        json={
            "need": "catálogo real de productos con precio y moneda",
            "required_fields": [
                {"name": "name", "type": "string"},
                {"name": "price", "type": "number"},
                {"name": "currency", "type": "string"},
            ],
            "domain": "general",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_id"] == "zent.resource.resolution/v1"
    assert body["selected"] is not None
    assert body["trace"]["read_only"] is True
    assert body["trace"]["catalog_tables"] >= 2


@pytest.mark.asyncio
async def test_planner_resource_tool_returns_tenant_report(async_client: AsyncClient) -> None:
    from src.platform.workflows.capability_registry import build_capability_snapshot
    from src.platform.workflows.planner_tools import PlannerToolContext, dispatch_tool

    org = await _create_org(async_client, "Resource Planner Tool")
    org_id = UUID(org["organization_id"])
    await _seed_catalog(org_id)
    snapshot = await build_capability_snapshot(
        org_id, None, permissions=frozenset({"workflows:read", "agents:execute"})
    )
    observation = await dispatch_tool(
        "resource.resolve",
        {
            "need": "catálogo de productos con precio",
            "required_fields": ["name", "price"],
        },
        PlannerToolContext(
            organization_id=org_id,
            workspace_id=None,
            snapshot=snapshot,
            permissions=frozenset({"workflows:read", "agents:execute"}),
        ),
        session_id="resource-tool",
    )
    data = observation["observation"]["data"]
    assert data["resolved"] is True
    assert data["selected"]["resource_ref"].startswith("catalog.entity.")



