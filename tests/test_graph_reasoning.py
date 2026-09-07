"""Phase 29D — Graph reasoning bounded traversal."""
from __future__ import annotations

from src.intelligence.graph_reasoning import GraphReasoningEngine


def test_bounded_traversal_and_explanation() -> None:
    engine = GraphReasoningEngine()
    edges = [
        {
            "upstream_id": "Profitable Customer",
            "downstream_id": "Gross Margin",
            "relation": "DEPENDS_ON",
        },
        {
            "upstream_id": "Gross Margin",
            "downstream_id": "COGS",
            "relation": "DEPENDS_ON",
        },
        {
            "upstream_id": "COGS",
            "downstream_id": "material_cost",
            "relation": "MAPS_TO",
        },
        {
            "upstream_id": "material_cost",
            "downstream_id": "ERP",
            "relation": "SOURCE_OF",
        },
        {
            "upstream_id": "Gross Margin",
            "downstream_id": "secret_node",
            "relation": "USES",
        },
    ]
    result = engine.traverse(
        "Gross Margin",
        edges,
        max_depth=3,
        max_nodes=20,
        allowed_edge_types={"DEPENDS_ON", "MAPS_TO", "SOURCE_OF"},
    )
    assert result.nodes_visited >= 2
    assert result.truncated is False
    assert any("COGS" in e for e in result.explanation)
    assert all("secret_node" not in e for e in result.explanation)
    expl = engine.path_explanation(result.paths[0], start="Gross Margin")
    assert "DEPENDS_ON" in expl


def test_max_nodes_truncation() -> None:
    engine = GraphReasoningEngine()
    edges = [
        {"from": "A", "to": f"N{i}", "relation": "USES"} for i in range(10)
    ]
    result = engine.traverse("A", edges, max_depth=2, max_nodes=3, allowed_edge_types={"USES"})
    assert result.truncated is True
    assert result.nodes_visited <= 3
