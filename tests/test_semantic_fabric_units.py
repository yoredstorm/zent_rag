# =============================================================================
# Nutrient Retrieval Units desde el Fabric — Fase 9
# =============================================================================
# Reglas que se prueban:
#   - chunk_fields mapea nodos del fabric a ids por tipo (concept/entity/rule/
#     definition/exception/symbol/...) + dependency ids + vecindad semántica;
#   - mode off no enriquece; shadow solo payload; active agrega labels sparse;
#   - el representation fingerprint incluye la versión del fabric y la
#     invalidación reporta "fabric_changed" (reindex sin reprocesar fuente);
#   - el engine escribe los campos del fabric en el payload de Qdrant.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.knowledge.representation import (
    FABRIC_REPRESENTATION_VERSION,
    change_reason,
    descriptor_for_document,
)
from src.knowledge.semantic import (
    build_retrieval_context,
)
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding


def _node(node_id, node_type, label, block_ids, unit_key="", **attrs):
    return {
        "id": str(node_id),
        "node_key": f"{node_type}:{unit_key or label}",
        "node_type": node_type,
        "label": label,
        "unit_key": unit_key,
        "block_ids": list(block_ids),
        "windows": [0],
        "attributes": attrs,
    }


def _edge(edge_id, relation_type, subject_id, object_id):
    return {
        "id": str(edge_id),
        "edge_key": f"{relation_type}:{subject_id}->{object_id}",
        "relation_type": relation_type,
        "subject_id": str(subject_id),
        "object_id": str(object_id),
        "windows": [0],
    }


def test_build_retrieval_context_maps_ids_and_neighborhood() -> None:
    rule_id = uuid4()
    symbol_id = uuid4()
    definition_id = uuid4()
    exception_id = uuid4()
    nodes = [
        _node(rule_id, "Rule", "Fare rule", ["b1"], unit_key="rule:fare"),
        _node(symbol_id, "Symbol", "&&&F", ["b1"], unit_key="symbol:&&&F"),
        _node(definition_id, "Definition", "FCLAS", ["b2"], unit_key="definition:fclas"),
        _node(exception_id, "Exception", "unless carrier", ["b3"], unit_key="exception:1"),
    ]
    edges = [
        _edge(uuid4(), "DEPENDS_ON", rule_id, symbol_id),
        _edge(uuid4(), "USES", rule_id, symbol_id),
        _edge(uuid4(), "HAS_EXCEPTION", rule_id, exception_id),
    ]
    context = build_retrieval_context(
        nodes, edges, document_id=uuid4(), mode="shadow"
    )
    assert context.enabled

    fields = context.chunk_fields(["b1"])
    assert str(rule_id) in fields["rule_ids"]
    assert str(symbol_id) in fields["symbol_ids"]
    assert fields["fabric_dependency_ids"]
    assert fields["semantic_neighborhood"]
    assert fields["fabric_version"] == FABRIC_REPRESENTATION_VERSION
    assert fields["fabric_mode"] == "shadow"

    # Un chunk sin nodos no se contamina.
    assert context.chunk_fields(["nope"]) == {}

    # Vecindad limitada: el nodo de la definición (otro bloque) aparece.
    neighborhood_labels = {
        item["label"] for item in fields["semantic_neighborhood"]
    }
    assert "unless carrier" in neighborhood_labels


def test_mode_off_shadow_active_behavior() -> None:
    rule_id = uuid4()
    symbol_id = uuid4()
    nodes = [
        _node(rule_id, "Rule", "Fare rule", ["b1"], unit_key="rule:fare"),
        _node(symbol_id, "Symbol", "&&&F", ["b1"], unit_key="symbol:&&&F"),
    ]
    edges = [_edge(uuid4(), "USES", rule_id, symbol_id)]

    off = build_retrieval_context(nodes, edges, mode="off")
    assert off.enabled is False
    assert off.chunk_fields(["b1"]) == {}
    assert off.sparse_labels(["b1"]) == []

    shadow = build_retrieval_context(nodes, edges, mode="shadow")
    assert shadow.chunk_fields(["b1"])["fabric_labels"]
    assert shadow.sparse_labels(["b1"]) == []

    active = build_retrieval_context(nodes, edges, mode="active")
    labels = active.sparse_labels(["b1"])
    assert "Fare rule" in labels
    assert "&&&F" in labels


def test_representation_fingerprint_includes_fabric_version() -> None:
    document = TextParser().parse(
        b"# Manual\n\nFCLAS - fare class definition.",
        organization_id=uuid4(),
        external_id="fabric.md",
        source_id=uuid4(),
        source_name="fabric.md",
    )
    document = apply_understanding(document, filename="fabric.md")
    descriptor = descriptor_for_document(document)
    payload = descriptor.to_payload()
    assert payload["fabric_representation_version"] == FABRIC_REPRESENTATION_VERSION

    previous = dict(payload)
    previous["fabric_representation_version"] = "fabric-units-0"
    reason = change_reason(previous, payload, content_changed=False)
    assert reason == "fabric_changed"
