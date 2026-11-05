# =============================================================================
# P20 - Demo conversacional: pedido paso a paso con waits durables.
# =============================================================================
from __future__ import annotations

from src.platform.commerce.conversational_order_demo import (
    CAPABILITIES,
    TEMPLATE_SLUG,
    build_graph,
    demo_conversation,
    demo_payload,
    template_row,
)
from src.platform.workflows.inventory_adapter import _product_search_sql, _search_terms
from src.platform.workflows.ir import WorkflowGraph, validate_graph


def test_conversational_graph_is_valid_and_acyclic() -> None:
    graph_dict = build_graph()
    graph = WorkflowGraph.from_dict(graph_dict)
    validate_graph(graph)

    assert graph.entrypoints == ["cliente"]
    assert graph_dict["workflow_version"] == 2
    assert graph_dict["metadata"]["template"] == TEMPLATE_SLUG


def test_conversational_graph_layout_has_no_overlaps() -> None:
    graph = build_graph()
    nodes = graph["nodes"]
    for index, first in enumerate(nodes):
        for second in nodes[index + 1 :]:
            ax = float(first["position"]["x"])
            ay = float(first["position"]["y"])
            bx = float(second["position"]["x"])
            by = float(second["position"]["y"])
            overlaps = abs(ax - bx) < 248 and abs(ay - by) < 112
            assert not overlaps, (first["id"], second["id"], first["position"], second["position"])


def test_conversational_graph_is_grouped_by_business_phases() -> None:
    graph = build_graph()
    phases = [item["id"] for item in graph["metadata"]["phases"]]
    assert phases == [
        "entrada",
        "producto",
        "cantidad",
        "stock",
        "entrega",
        "confirmacion",
        "pedido",
        "cierre",
        "fin",
    ]
    x_by_phase: dict[str, set[float]] = {}
    for node in graph["nodes"]:
        metadata = node["metadata"]
        assert metadata["phase"] in phases, node["id"]
        assert metadata["note"], node["id"]
        assert node["label"].startswith(f"{metadata['phase_label']} ·"), node["id"]
        x_by_phase.setdefault(metadata["phase"], set()).add(float(node["position"]["x"]))
    for phase in phases:
        assert len(x_by_phase[phase]) == 1, phase


def test_conversational_graph_waits_for_each_step() -> None:
    graph = build_graph()
    waits = [node for node in graph["nodes"] if node["type"] == "wait_event"]

    assert len(waits) == 5
    for node in waits:
        assert node["config"]["preset"] == "message"
        assert node["config"]["event_type"] == "conversation.message"
        assert node["config"]["on_timeout"] == "expire"
        assert node["config"]["correlation"] == {
            "order_number": "{{instance.state.order.order_number}}"
        }
        assert {port["name"] for port in node["output_ports"]} == {"out", "timeout"}


def test_conversational_graph_asks_before_every_wait() -> None:
    graph = build_graph()
    types = {node["id"]: node["type"] for node in graph["nodes"]}
    incoming: dict[str, str] = {}
    for edge in graph["edges"]:
        incoming.setdefault(edge["to_node"], edge["from_node"])

    for node_id, node_type in types.items():
        if node_type != "wait_event":
            continue
        assert types[incoming[node_id]] == "notify", node_id


def test_conversational_graph_has_product_fallback_without_order() -> None:
    graph = build_graph()
    types = {node["id"]: node["type"] for node in graph["nodes"]}
    edges = {(edge["from_node"], edge["to_node"]) for edge in graph["edges"]}

    assert types["sin_producto"] == "notify"
    assert ("encontrado", "sin_producto") in edges
    assert ("sin_producto", "fin_sin_producto") in edges
    # El fallback no puede llegar a crear pedido.
    reachable = {"sin_producto"}
    changed = True
    while changed:
        changed = False
        for source, target in edges:
            if source in reachable and target not in reachable:
                reachable.add(target)
                changed = True
    assert "crear_pedido" not in reachable


def test_not_found_message_is_natural_and_does_not_echo_the_question() -> None:
    graph = build_graph()
    node = next(item for item in graph["nodes"] if item["id"] == "sin_producto")
    message = str(node["config"]["message"])
    assert "{{trigger.text}}" not in message
    assert message.startswith("No encontré ese producto en el catálogo.")
    assert "¿Quieres que busque otro?" in message


def test_conversational_graph_keeps_state_across_messages() -> None:
    blob = str(build_graph())
    assert "{{instance.state.order.customer_ref}}" in blob
    assert "{{instance.state.order.sku}}" in blob
    assert "{{instance.state.order.quantity}}" in blob
    assert "{{instance.state.order.delivery_mode}}" in blob
    assert "{{variables.order" not in blob


def test_conversational_graph_declares_capabilities_and_event() -> None:
    row = template_row()
    declared = {
        item["ref"]
        for item in row["package"]["dependencies"]
        if item["kind"] == "capability"
    }
    events = {
        item["ref"]
        for item in row["package"]["dependencies"]
        if item["kind"] == "event"
    }
    assert set(CAPABILITIES) <= declared
    assert "conversation.message" in events
    assert row["trigger_config"] == {"event_type": "conversation.message"}


def test_conversational_graph_has_finite_canvas_positions() -> None:
    graph = build_graph()
    for node in graph["nodes"]:
        assert isinstance(node["position"]["x"], (int, float))
        assert isinstance(node["position"]["y"], (int, float))
    # El ciclo del loop no debe colapsar todo el grafo en una sola columna.
    assert len({node["position"]["x"] for node in graph["nodes"]}) >= 4


def test_conversational_demo_payload_and_script() -> None:
    payload = demo_payload(order_number="CONV-001")
    assert payload["text"] == "tienes arroz?"
    assert payload["customer_ref"] == "CUST-CONV"
    assert payload["order_number"] == "CONV-001"
    assert demo_payload()["order_number"].startswith("CONV-")

    script = demo_conversation()
    assert script[0] == "tienes arroz?"
    assert script[-1].lower() in ("si", "sí")


def test_search_terms_drop_question_words() -> None:
    assert _search_terms("tienes arroz?") == ["arroz"]
    assert _search_terms("quiero leche") == ["leche"]
    assert _search_terms("precio del aceite") == ["aceite"]
    assert _search_terms("tienes bicicleta en venta?") == ["bicicleta"]
    assert _search_terms("venden productos de limpieza") == ["limpieza"]
    assert _search_terms("BD-ARROZ-01") == ["bd-arroz-01"]
    assert _search_terms("   ") == []


def test_product_search_sql_is_one_statement_with_fixed_params() -> None:
    and_sql, or_sql, params = _product_search_sql(["arroz"], limit=2)

    for sql in (and_sql, or_sql):
        assert sql.lstrip().startswith("SELECT sku, name, unit, price, currency, available")
        assert sql.count("FROM bodega.product_catalog_v") == 1
        assert sql.count("SELECT") == 1
        assert "WHERE  AND" not in sql
        assert "WHERE  OR" not in sql
    assert params["q1"] == "%arroz%"
    assert params["q2"] is None
    assert params["limit"] == 2
