# =============================================================================
# Workflow Semantic Core — Fase 3: metadata semántica de nodos.
#
# Invariantes del catálogo backend: cobertura del registry, contratos de
# contexto declarados, flags de capability, alineación con las Business Schemas
# y estricta validación del merge cuando un nodo declara context_writes vacío.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.context import (
    CONTEXT_SECTIONS,
    WRITABLE_SECTIONS,
    TriggerSnapshot,
    WorkflowContext,
    WorkflowIdentity,
    normalize_section,
)
from src.platform.workflows.contributions import ContextMerger, ContextWrite, NodeContribution
from src.platform.workflows.node_catalog import (
    CATEGORIES,
    NODE_METADATA,
    REQUIREMENT_TOKENS,
    catalog_availability,
    metadata_for,
)
from src.platform.workflows.nodes import registry
from src.platform.workflows.parameters import NODE_BUSINESS_SCHEMAS
from tests.test_workflows import _create_org, _headers, _owner_session

# Contribuciones que los handlers emiten hoy (deben estar declaradas).
EXPECTED_CONTRIBUTIONS: dict[str, set[str]] = {
    "kb_query": {"knowledge"},
    "query_business_data": {"data"},
    "api_call": {"data"},
    "marketplace_action": {"data", "evidence"},
    "business_node": {"data", "evidence"},
    "business_result": {"artifacts"},
    "llm": {"decisions", "findings"},
}


def test_registry_and_metadata_cover_each_other() -> None:
    registered = {node_def.node_type for node_def in registry.all()}
    assert registered == set(NODE_METADATA), registered ^ set(NODE_METADATA)


def test_every_node_has_business_copy() -> None:
    for node_def in registry.all():
        assert node_def.business_name, node_def.node_type
        assert node_def.short_description, node_def.node_type
        assert node_def.long_description, node_def.node_type


def test_context_declarations_are_valid() -> None:
    for node_def in registry.all():
        for section in node_def.context_reads:
            assert normalize_section(section) in CONTEXT_SECTIONS, (node_def.node_type, section)
        for section in node_def.context_writes:
            assert normalize_section(section) in WRITABLE_SECTIONS, (node_def.node_type, section)
        for requirement in node_def.requires:
            assert requirement in REQUIREMENT_TOKENS, (node_def.node_type, requirement)


def test_declared_writes_cover_handler_contributions() -> None:
    for node_type, expected in EXPECTED_CONTRIBUTIONS.items():
        node_def = registry.get(node_type)
        assert node_def is not None, node_type
        declared = {normalize_section(section) for section in node_def.context_writes}
        expected_sections = {normalize_section(section) for section in expected}
        assert expected_sections <= declared, (node_type, expected_sections - declared)


def test_supports_flags_are_explicit() -> None:
    assert registry.require("llm").supports_agent is True
    assert registry.require("kb_query").supports_knowledge is True
    assert registry.require("query_business_data").supports_knowledge is True
    for node_def in registry.all():
        if node_def.node_type == "llm":
            continue
        assert node_def.supports_agent is False, node_def.node_type


def test_simulation_supported_flags() -> None:
    expected_true = {
        "notify",
        "api_call",
        "marketplace_action",
        "business_result",
        "business_node",
        "human_approval",
    }
    for node_def in registry.all():
        if node_def.node_type in expected_true:
            assert node_def.simulation_supported is True, node_def.node_type
        else:
            assert node_def.simulation_supported is False, node_def.node_type


def test_business_name_and_category_align_with_business_schemas() -> None:
    for node_type, schema in NODE_BUSINESS_SCHEMAS.items():
        node_def = registry.get(node_type)
        assert node_def is not None, node_type
        assert node_def.business_name == schema.label, (node_type, node_def.business_name, schema.label)
        assert node_def.category == schema.category, (node_type, node_def.category, schema.category)


def test_categories_are_unique_and_ordered() -> None:
    ids = [category["id"] for category in CATEGORIES]
    orders = [category["order"] for category in CATEGORIES]
    assert len(ids) == len(set(ids))
    assert orders == sorted(orders)


def test_metadata_for_returns_copy() -> None:
    first = metadata_for("llm")
    first["business_name"] = "mutado"
    assert metadata_for("llm")["business_name"] == "Preguntar a un agente"
    assert metadata_for("no_existe") == {}


def test_merger_rejects_writes_when_context_writes_is_empty() -> None:
    context = WorkflowContext(
        identity=WorkflowIdentity(organization_id=uuid4(), workflow_id=uuid4(), run_id=uuid4()),
        trigger=TriggerSnapshot(source="manual"),
    )
    contribution = NodeContribution(
        writes=(ContextWrite(section="data", key="x", value={"a": 1}),)
    )
    report = ContextMerger().apply(
        context, node_id="n1", node_type="condition", contribution=contribution, allowed_sections=()
    )
    assert context.data == {}
    assert report.rejected == [{"index": 0, "section": "data", "reason": "section_not_declared"}]


# ---------------------------------------------------------------------------
# Fase 4 — disponibilidad y API del catálogo
# ---------------------------------------------------------------------------
def test_catalog_availability_checks_requirements() -> None:
    marketplace = registry.require("marketplace_action")
    available, reason = catalog_availability(marketplace, {}, permissions=None)
    assert available is False
    assert reason is not None and "integraciones" in reason

    available, reason = catalog_availability(
        marketplace, {"actions": {"peru.taxpayer.lookup": {}}}, permissions=None
    )
    assert available is True and reason is None

    kb = registry.require("kb_query")
    available, reason = catalog_availability(kb, {"knowledge_bases": {}}, permissions=None)
    assert available is False and reason is not None and "conocimiento" in reason


def test_catalog_availability_checks_permissions() -> None:
    llm = registry.require("llm")
    available, reason = catalog_availability(llm, {"agents": {"a": {}}}, permissions=frozenset())
    assert available is False
    assert reason is not None and "agents:execute" in reason

    available, reason = catalog_availability(
        llm, {"agents": {"a": {}}}, permissions=frozenset({"agents:execute"})
    )
    assert available is True and reason is None


@pytest.mark.asyncio
async def test_node_catalog_endpoint_returns_tenant_catalog(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Node Catalog")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    resp = await async_client.get("/api/v1/workflows/node-catalog", headers=_headers(org))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["catalog_version"] == 1
    assert body["generated_at"]
    assert {category["id"] for category in body["categories"]} >= {"trigger", "data", "ai", "logic"}

    by_type = {node["node_type"]: node for node in body["nodes"]}
    assert {"llm", "kb_query", "query_business_data", "condition", "notify", "end"} <= set(by_type)

    llm = by_type["llm"]
    assert llm["business_name"] == "Preguntar a un agente"
    assert llm["supports_agent"] is True
    assert llm["supports_knowledge"] is False
    assert llm["context_writes"] == ["findings", "decisions", "artifacts"]
    assert isinstance(llm["available"], bool)
    assert llm["when_to_use"]

    query_node = by_type["query_business_data"]
    assert query_node["business_name"] == "Consultar datos de negocio"
    assert any(parameter["key"] == "ask" for parameter in query_node["parameters"])
    assert {"rows", "columns", "answer"} <= {field["key"] for field in query_node["output_fields"]}

    for node in body["nodes"]:
        assert isinstance(node["available"], bool)
        if node["available"] is False:
            assert node["unavailable_reason"]


@pytest.mark.asyncio
async def test_node_catalog_covers_business_schemas(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Node Catalog Alias")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    headers = _headers(org)

    schemas_resp = await async_client.get("/api/v1/workflows/node-schemas", headers=headers)
    catalog_resp = await async_client.get("/api/v1/workflows/node-catalog", headers=headers)
    assert schemas_resp.status_code == 200, schemas_resp.text
    assert catalog_resp.status_code == 200, catalog_resp.text

    schema_types = {schema["node_type"] for schema in schemas_resp.json()["schemas"]}
    catalog_types = {node["node_type"] for node in catalog_resp.json()["nodes"]}
    assert schema_types <= catalog_types
    assert len(catalog_types) > len(schema_types)  # `end` no tiene Business Schema.


@pytest.mark.asyncio
async def test_node_catalog_requires_auth(async_client: AsyncClient) -> None:
    resp = await async_client.get("/api/v1/workflows/node-catalog")
    assert resp.status_code == 401
