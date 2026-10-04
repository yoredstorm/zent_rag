# =============================================================================
# Distant semantics, excepciones lejanas y CRITICAL TEST (Fases 20, 24, 26)
# =============================================================================
# Caso crítico:
#   Window 1: definición D
#   Window 10: regla R usa D
#   Window 15: excepción E modifica R
#   Query requiere R -> seed R -> dependency D -> exception E -> contexto.
# Si el resultado solo contiene la ventana 10: FAIL.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.core.domain.entities import RetrievalChunk
from src.knowledge.semantic import (
    SemanticStitcher,
    SemanticWindowResult,
    WindowItem,
)
from src.rag.longcontext.context_compiler import compile_context
from src.rag.longcontext.graph_activation import (
    chunks_for_activated_nodes,
    spreading_activation,
)
from src.rag.longcontext.information import compute_information_gain, snapshot
from src.rag.longcontext.requirement_graph import build_requirement_graph


def _chunk(metadata: dict, content: str, score: float = 0.5) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content=content, score=score, metadata=metadata
    )


def test_distant_definition_reachable_from_late_rule_seed() -> None:
    """Fase 24: definición en el 10% inicial, regla en el 10% final."""
    edges = [
        {
            "id": "e1",
            "relation_type": "DEPENDS_ON",
            "subject_id": "r1",
            "object_id": "d1",
            "confidence": 0.9,
        }
    ]
    activated = spreading_activation(["r1"], edges)
    chunks = [
        _chunk(
            {"chunk_id": "c1", "fabric_node_ids": ["d1"]},
            "definition D early",
            score=0.1,
        ),
        _chunk(
            {"chunk_id": "c2", "fabric_node_ids": ["r1"]},
            "Rule R uses D late",
            score=0.9,
        ),
    ]
    selected = chunks_for_activated_nodes(chunks, activated, limit=5)
    assert {chunk.content for chunk in selected} == {
        "definition D early",
        "Rule R uses D late",
    }


def test_distant_exception_reaches_final_context() -> None:
    """Fase 26: regla temprana, excepción lejana; el contexto final la incluye."""
    chunks = [
        _chunk(
            {
                "chunk_id": "c1",
                "rule_ids": ["r1"],
                "semantic_neighborhood": [
                    {
                        "node_id": "e1",
                        "node_type": "Exception",
                        "label": "unless carrier",
                        "relation": "HAS_EXCEPTION",
                    }
                ],
            },
            "The fare must match &&&F",
        ),
        _chunk(
            {"chunk_id": "c2", "exception_ids": ["e1"]},
            "unless the validating carrier applies",
            score=0.3,
        ),
    ]
    compiled = compile_context(question="¿aplica la regla?", chunks=chunks)
    assert compiled.rules
    assert compiled.exceptions
    assert compiled.exceptions[0]["key"] == "c2"


def test_critical_rule_dependency_exception_across_windows() -> None:
    document_id = uuid4()
    organization_id = uuid4()
    windows = [
        SemanticWindowResult(
            window_index=1,
            organization_id=organization_id,
            document_id=document_id,
            items=(
                WindowItem(
                    kind="definition",
                    key="definition:d",
                    label="D",
                    text="definition D",
                    confidence=0.85,
                    block_ids=("b1",),
                ),
            ),
        ),
        SemanticWindowResult(
            window_index=10,
            organization_id=organization_id,
            document_id=document_id,
            items=(
                WindowItem(
                    kind="rule",
                    key="rule:r",
                    label="R",
                    text="Rule R uses D",
                    confidence=0.85,
                    block_ids=("b10",),
                ),
            ),
        ),
        SemanticWindowResult(
            window_index=15,
            organization_id=organization_id,
            document_id=document_id,
            items=(
                WindowItem(
                    kind="exception",
                    key="exception:e",
                    label="E",
                    text="Exception E modifies R",
                    confidence=0.85,
                    block_ids=("b15",),
                ),
            ),
        ),
    ]
    stitch = SemanticStitcher().stitch(
        document=SimpleNamespace(id=document_id),
        results=windows,
        threads=[],
    )
    assert len(stitch.units) == 3

    chunks = [
        _chunk(
            {"chunk_id": "b1", "definition_ids": ["d1"], "fabric_node_ids": ["d1"]},
            "definition D",
            score=0.2,
        ),
        _chunk(
            {
                "chunk_id": "b10",
                "rule_ids": ["r1"],
                "fabric_node_ids": ["r1"],
                "semantic_neighborhood": [
                    {
                        "node_id": "d1",
                        "node_type": "Definition",
                        "label": "D",
                        "relation": "DEPENDS_ON",
                    },
                    {
                        "node_id": "e1",
                        "node_type": "Exception",
                        "label": "E",
                        "relation": "HAS_EXCEPTION",
                    },
                ],
            },
            "Rule R uses D",
            score=0.9,
        ),
        _chunk(
            {"chunk_id": "b15", "exception_ids": ["e1"], "fabric_node_ids": ["e1"]},
            "Exception E modifies R",
            score=0.3,
        ),
    ]

    graph = build_requirement_graph(
        question="escenario que requiere R", requirements=[], chunks=chunks
    )
    coverage = graph.stats["coverage"]
    assert coverage["rules_satisfied"] == 1
    assert coverage["definitions_satisfied"] == 1
    assert coverage["exceptions_satisfied"] == 1
    assert graph.missing == ()

    compiled = compile_context(
        question="escenario que requiere R",
        chunks=chunks,
        requirement_graph=graph,
    )
    assert compiled.rules and compiled.definitions and compiled.exceptions
    citation_keys = {item["key"] for item in compiled.citation_map}
    assert {"b1", "b10", "b15"} <= citation_keys

    # FAIL scenario: solo la ventana 10 (regla) no alcanza.
    graph_only_rule = build_requirement_graph(
        question="q", requirements=[], chunks=[chunks[1]]
    )
    assert "D" in graph_only_rule.missing
    assert "E" in graph_only_rule.missing
    compiled_only_rule = compile_context(
        question="q", chunks=[chunks[1]], requirement_graph=graph_only_rule
    )
    assert not compiled_only_rule.definitions
    assert not compiled_only_rule.exceptions
    assert compiled_only_rule.unresolved_requirements


def test_information_gain_counts_new_fabric_nodes() -> None:
    """Fase 20: cada expansión reporta nodos nuevos además de tokens."""
    before = snapshot([_chunk({"fabric_node_ids": ["n1"]}, "evidencia")])
    after = snapshot(
        [_chunk({"fabric_node_ids": ["n1", "n2"]}, "evidencia nueva")]
    )
    gain = compute_information_gain(before, after, added_tokens=100)
    assert gain.new_nodes == 1
    assert gain.to_public_dict()["new_nodes"] == 1
