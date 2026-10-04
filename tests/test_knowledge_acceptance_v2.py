# =============================================================================
# Retrieval Acceptance V2 — ¿apareció el CONOCIMIENTO requerido? (Fase 14)
# =============================================================================
# Reglas que se prueban:
#   - probes V2 desde el fabric: tipos por nodo + dependencias (DEPENDS_ON);
#   - ids deterministas y límites por tipo;
#   - métricas por tipo, dependency_recall, semantic_coverage y orphans;
#   - conversión a RetrievalProbe válido (contrato acceptance);
#   - el engine persiste las métricas V2 en la evaluación del documento.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.knowledge.semantic.acceptance_v2 import (
    KNOWLEDGE_ACCEPTANCE_VERSION,
    build_knowledge_probes,
    evaluate_knowledge_acceptance,
    probe_payloads_to_objects,
)


def _node(node_id, node_type, label, block_ids=("b1",)):
    return {
        "id": str(node_id),
        "node_type": node_type,
        "label": label,
        "block_ids": list(block_ids),
        "unit_key": f"{node_type.lower()}:{label.lower()}",
    }


def _edge(relation, subject_id, object_id):
    return {
        "id": str(uuid4()),
        "relation_type": relation,
        "subject_id": str(subject_id),
        "object_id": str(object_id),
    }


def _document():
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        source_id=uuid4(),
    )


def test_build_knowledge_probes_from_fabric() -> None:
    document = _document()
    rule = _node(uuid4(), "Rule", "Fare rule")
    definition = _node(uuid4(), "Definition", "FCLAS")
    symbol = _node(uuid4(), "Symbol", "&&&F")
    nodes = [rule, definition, symbol, _node(uuid4(), "Evidence", "block")]
    edges = [_edge("DEPENDS_ON", rule["id"], definition["id"])]

    probes, stats = build_knowledge_probes(
        document=document, nodes=nodes, edges=edges, max_probes=12
    )
    types = {probe["query_type"] for probe in probes}
    assert "knowledge_rule" in types
    assert "knowledge_definition" in types
    assert "knowledge_symbol" in types
    assert "knowledge_dependency" in types
    dependency = next(
        probe for probe in probes if probe["query_type"] == "knowledge_dependency"
    )
    assert dependency["metadata"]["dependency_of"] == "Fare rule"
    assert dependency["metadata"]["node_type"] == "Definition"
    assert dependency["expected_unit_id"] == "b1"
    assert dependency["generated_by"] == "semantic_fabric"
    assert stats["candidates"] == 3
    assert stats["orphans"] == 0
    assert stats["dependencies"] == 1

    # Determinismo de ids.
    again, _ = build_knowledge_probes(
        document=document, nodes=nodes, edges=edges, max_probes=12
    )
    assert [probe["probe_id"] for probe in probes] == [
        probe["probe_id"] for probe in again
    ]


def test_probe_payloads_convert_to_retrieval_probe() -> None:
    document = _document()
    probes, _stats = build_knowledge_probes(
        document=document,
        nodes=[_node(uuid4(), "Definition", "FCLAS")],
        edges=[],
    )
    objects = probe_payloads_to_objects(probes)
    assert len(objects) == 1
    assert objects[0].query_type == "knowledge_definition"
    assert objects[0].expected_unit_id == "b1"


def test_evaluate_knowledge_acceptance_metrics() -> None:
    outcomes = [
        SimpleNamespace(query_type="knowledge_rule", passed=True),
        SimpleNamespace(query_type="knowledge_rule", passed=False),
        SimpleNamespace(query_type="knowledge_definition", passed=True),
        SimpleNamespace(query_type="knowledge_symbol", passed=False),
        SimpleNamespace(query_type="knowledge_dependency", passed=True),
    ]
    metrics = evaluate_knowledge_acceptance(
        outcomes, stats={"orphans": 2, "candidates": 5, "probed": 5}
    )
    assert metrics["version"] == KNOWLEDGE_ACCEPTANCE_VERSION
    assert metrics["rule_recall"] == 0.5
    assert metrics["definition_recall"] == 1.0
    assert metrics["symbol_recall"] == 0.0
    assert metrics["dependency_recall"] == 1.0
    assert metrics["exception_recall"] is None
    assert metrics["evidence_recall"] == 0.6
    # 3 tipos con pass de 4 tipos probados.
    assert metrics["semantic_coverage"] == 0.75
    assert metrics["orphans"] == 2


def test_evaluate_without_probes_is_honest() -> None:
    metrics = evaluate_knowledge_acceptance([], stats={})
    assert metrics["evidence_recall"] is None
    assert metrics["semantic_coverage"] is None
    assert metrics["probes"] == 0
