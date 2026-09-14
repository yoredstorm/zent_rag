# =============================================================================
# Workflow Semantic Core — Fase 3: metadata semántica de nodos.
#
# Invariantes del catálogo backend: cobertura del registry, contratos de
# contexto declarados, flags de capability, alineación con las Business Schemas
# y estricta validación del merge cuando un nodo declara context_writes vacío.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

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
    metadata_for,
)
from src.platform.workflows.nodes import registry
from src.platform.workflows.parameters import NODE_BUSINESS_SCHEMAS

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
