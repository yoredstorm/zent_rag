# =============================================================================
# Workflow Business Parameters (commit 2) — registro de parámetros de negocio
# por nodo y conversión desde JSON Schema de capabilities.
# =============================================================================
from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.platform.workflows.parameters import (
    NODE_BUSINESS_SCHEMAS,
    all_node_schemas,
    business_outputs_for,
    business_parameters_for,
    node_business_schema,
    output_contracts,
    parameters_from_json_schema,
)
from tests.test_workflows import _create_org, _headers, _owner_session


def test_registry_covers_business_nodes() -> None:
    for node_type in (
        "notify",
        "condition",
        "llm",
        "query_business_data",
        "kb_query",
        "api_call",
        "marketplace_action",
        "business_result",
        "trigger_schedule",
        "trigger_event",
    ):
        assert node_type in NODE_BUSINESS_SCHEMAS
    assert len(all_node_schemas()) == len(NODE_BUSINESS_SCHEMAS)


def test_notify_parameters_levels() -> None:
    simple = {p.key for p in business_parameters_for("notify", "simple")}
    assert {"channel", "title", "message"} <= simple
    assert "data" not in simple
    assert "data" in {p.key for p in business_parameters_for("notify", "advanced")}

    channel = next(p for p in business_parameters_for("notify", "simple") if p.key == "channel")
    labels = {o["label"] for o in channel.static_options}
    assert {"Zent", "Correo", "Webhook"} <= labels
    assert channel.required is True


def test_condition_uses_friendly_operator_labels() -> None:
    operator = next(p for p in business_parameters_for("condition", "simple") if p.key == "operator")
    labels = {o["value"]: o["label"] for o in operator.static_options}
    assert labels[">"] == "es mayor que"
    assert labels["<="] == "es como máximo"
    assert operator.default == ">"


def test_llm_agent_is_dynamic_required() -> None:
    agent = next(p for p in business_parameters_for("llm", "simple") if p.key == "agent_id")
    assert agent.type == "agent"
    assert agent.dynamic_options == "agents"
    assert agent.required is True


def test_outputs_declared_per_node() -> None:
    keys = {o.key for o in business_outputs_for("query_business_data")}
    assert {"rows", "columns", "answer", "evidence"} <= keys
    assert "text" in {o.key for o in business_outputs_for("llm")}
    assert business_outputs_for("trigger_schedule") == []

    contracts = output_contracts()
    assert contracts["query_business_data"]["source"] == "contract"
    assert contracts["query_business_data"]["sample"] == {}


def test_unknown_node_has_no_schema() -> None:
    assert node_business_schema("nope") is None
    assert business_parameters_for("nope") == []


# ---------------------------------------------------------------------------
# JSON Schema → BusinessParameterSchema (marketplace / capabilities)
# ---------------------------------------------------------------------------
def test_parameters_from_json_schema_basic() -> None:
    params = parameters_from_json_schema(
        {
            "type": "object",
            "required": ["to", "body"],
            "properties": {
                "to": {"type": "string", "format": "email", "description": "Destinatario"},
                "body": {"type": "string", "title": "Mensaje"},
                "count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 10},
                "urgent": {"type": "boolean", "x-business-level": "advanced"},
            },
        },
        prefix="inputs.",
    )
    by_key = {p.key: p for p in params}
    assert by_key["inputs.to"].type == "email"
    assert by_key["inputs.to"].required is True
    assert by_key["inputs.to"].description == "Destinatario"
    assert by_key["inputs.body"].label == "Mensaje"
    assert by_key["inputs.count"].type == "integer"
    assert by_key["inputs.count"].validation["minimum"] == 1
    assert by_key["inputs.urgent"].min_level == "advanced"
    assert by_key["inputs.urgent"].required is False


def test_parameters_from_json_schema_business_extensions() -> None:
    params = parameters_from_json_schema(
        {
            "type": "object",
            "properties": {
                "priority": {
                    "type": "string",
                    "enum": ["low", "high"],
                    "x-business-enum-labels": ["Baja", "Alta"],
                    "x-business-label": "Prioridad",
                    "x-business-level": "guided",
                    "x-business-help": "Qué tan urgente es",
                },
                "api_key": {"type": "string", "x-business-secret": True},
                "warehouse": {"type": "string", "x-business-options": "warehouses", "x-business-type": "database"},
            },
        }
    )
    by_key = {p.key: p for p in params}
    assert by_key["priority"].min_level == "guided"
    assert by_key["priority"].static_options == [
        {"value": "low", "label": "Baja"},
        {"value": "high", "label": "Alta"},
    ]
    assert by_key["priority"].help == "Qué tan urgente es"
    assert by_key["api_key"].secret is True
    assert by_key["warehouse"].type == "database"
    assert by_key["warehouse"].dynamic_options == "warehouses"


def test_parameters_from_json_schema_empty() -> None:
    assert parameters_from_json_schema(None) == []
    assert parameters_from_json_schema({}) == []
    assert parameters_from_json_schema({"properties": "nope"}) == []


# ---------------------------------------------------------------------------
# API: schemas por nodo y parámetros de acciones
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_node_schemas_endpoint(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Node Schemas")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    resp = await async_client.get("/api/v1/workflows/node-schemas", headers=_headers(org))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_type = {s["node_type"]: s for s in body["schemas"]}
    assert "notify" in by_type and "condition" in by_type and "llm" in by_type

    channel = next(p for p in by_type["notify"]["parameters"] if p["key"] == "channel")
    assert channel["type"] == "enum"
    assert {o["label"] for o in channel["validation"]["options"]} >= {"Zent", "Correo"}

    contracts = body["output_contracts"]
    assert {"rows", "columns", "answer"} <= {o["key"] for o in contracts["query_business_data"]["outputs"]}


@pytest.mark.asyncio
async def test_ports_for_action_includes_business_parameters(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Ports Params")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    resp = await async_client.get(
        "/api/v1/workflows/marketplace/ports/peru.taxpayer.lookup", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    params = {p["key"]: p for p in resp.json()["input_parameters"]}
    assert params["inputs.ruc"]["required"] is True
    assert params["inputs.ruc"]["type"] == "text"
