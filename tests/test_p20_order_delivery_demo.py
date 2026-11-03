# =============================================================================
# P20 - Demo de pedido, cliente y delivery.
# =============================================================================
from __future__ import annotations

from src.platform.commerce.order_delivery_demo import (
    CAPABILITIES,
    TEMPLATE_SLUG,
    build_graph,
    demo_payload,
    template_row,
)
from src.platform.workflows.ir import WorkflowGraph, validate_graph


def test_demo_graph_is_valid_and_acyclic() -> None:
    graph_dict = build_graph()
    graph = WorkflowGraph.from_dict(graph_dict)
    validate_graph(graph)

    assert graph.entrypoints == ["inicio"]
    assert graph_dict["workflow_version"] == 2
    assert graph_dict["metadata"]["template"] == TEMPLATE_SLUG


def test_demo_graph_has_the_business_decisions() -> None:
    graph = build_graph()
    node_types = {node["id"]: node["type"] for node in graph["nodes"]}

    assert node_types["stock_ok"] == "condition"
    assert node_types["guardar_pedido"] == "state_merge"
    assert node_types["recurrente"] == "condition"
    assert node_types["delivery_check"] == "condition"
    assert node_types["address_check"] == "condition"
    assert node_types["aprobacion"] == "human_approval"
    assert node_types["crear_pedido"] == "capability_call"
    assert node_types["resultado"] == "business_result"
    assert node_types["marcar_delivery"].startswith("state")
    assert node_types["marcar_recurrente"].startswith("state")


def test_demo_graph_edges_reference_existing_nodes() -> None:
    graph = build_graph()
    node_ids = {node["id"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["from_node"] in node_ids, edge
        assert edge["to_node"] in node_ids, edge


def test_demo_graph_declares_required_capabilities() -> None:
    row = template_row()
    declared = {
        item["ref"]
        for item in row["package"]["dependencies"]
        if item["kind"] == "capability"
    }
    assert set(CAPABILITIES) <= declared
    assert {
        "bodega.product.get",
        "p19.customer.orders",
        "bodega.order.create",
        "bodega.stock.reserve_batch",
        "bodega.stock.commit_batch",
        "bodega.stock.release_batch",
    } == declared


def test_demo_graph_uses_durable_state_across_approval() -> None:
    blob = str(build_graph())
    assert "{{instance.state.pedido.customer_ref}}" in blob
    assert "{{instance.state.delivery_mode}}" in blob
    assert "{{variables.delivery_mode}}" not in blob


def test_demo_payload_is_repeatable_and_has_backend_inputs() -> None:
    first = demo_payload(order_number="SIM-CUST-A-001")
    second = demo_payload(order_number="SIM-CUST-A-001")
    assert first == second
    assert first["customer_ref"] == "CUST-A"
    assert first["sku"] == "BD-ARROZ-01"
    assert first["quantity"] == 2
    assert first["delivery"] is True
    assert first["order_number"] == "SIM-CUST-A-001"
    assert demo_payload()["order_number"].startswith("SIM-CUST-A-")
    assert demo_payload()["order_number"] != demo_payload()["order_number"]
