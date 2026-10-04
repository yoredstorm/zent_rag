# =============================================================================
# QueryRequirementGraph — qué conocimiento exige la pregunta (Fase 12)
# =============================================================================
# Reglas que se prueban:
#   - el grafo mapea requirements + payload fabric a nodos con estado real;
#   - dependencias (DEPENDS_ON/HAS_EXCEPTION/...) generan aristas y coverage;
#   - una dependencia sin evidencia queda MISSING y aparece en `missing`;
#   - fingerprint determinista y salida pública auditable.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.core.domain.entities import RetrievalChunk
from src.rag.longcontext.requirement_graph import (
    RequirementStatus,
    build_requirement_graph,
)


def _chunk(metadata: dict) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content="contenido", score=0.5, metadata=metadata
    )


def _requirement(state: str, description: str):
    return SimpleNamespace(state=state, description=description)


def test_graph_maps_requirements_and_dependencies() -> None:
    chunks = [
        _chunk(
            {
                "chunk_id": "c1",
                "rule_ids": ["r1"],
                "semantic_neighborhood": [
                    {
                        "node_id": "d1",
                        "node_type": "Definition",
                        "label": "FCLAS",
                        "relation": "DEPENDS_ON",
                        "activation": 0.7,
                    }
                ],
            }
        ),
        _chunk({"chunk_id": "c2", "definition_ids": ["d1"]}),
    ]
    graph = build_requirement_graph(
        question="¿FCLAS &&&F acepta X?",
        requirements=[
            _requirement("FOUND", "regla &&&F"),
            _requirement("MISSING", "excepción del carrier"),
        ],
        chunks=chunks,
    )
    nodes = {node.id: node for node in graph.nodes}
    assert nodes["r1"].status == RequirementStatus.FOUND.value
    assert nodes["d1"].status == RequirementStatus.FOUND.value
    assert ("r1", "DEPENDS_ON", "d1") in graph.edges
    assert graph.stats["dependency_coverage"] == 1.0
    assert any("excepción" in label for label in graph.missing)
    public = graph.to_public_dict()
    assert public["nodes"] >= 3
    assert public["dependency_coverage"] == 1.0
    assert public["by_type"]["Rule"] == 1
    assert public["by_status"][RequirementStatus.MISSING.value] >= 1


def test_missing_dependency_is_reported() -> None:
    chunks = [
        _chunk(
            {
                "chunk_id": "c1",
                "rule_ids": ["r1"],
                "semantic_neighborhood": [
                    {
                        "node_id": "d1",
                        "node_type": "Definition",
                        "label": "FCLAS",
                        "relation": "DEPENDS_ON",
                    }
                ],
            }
        )
    ]
    graph = build_requirement_graph(
        question="¿qué exige la regla?",
        requirements=[],
        chunks=chunks,
    )
    nodes = {node.id: node for node in graph.nodes}
    assert nodes["d1"].status == RequirementStatus.MISSING.value
    assert "FCLAS" in graph.missing
    assert graph.stats["dependency_coverage"] == 0.0
    assert graph.missing_by_type("Definition") == ("FCLAS",)


def test_graph_fingerprint_is_deterministic() -> None:
    chunks = [_chunk({"chunk_id": "c1", "symbol_ids": ["s1"]})]
    first = build_requirement_graph(
        question="q", requirements=[], chunks=chunks
    )
    second = build_requirement_graph(
        question="q", requirements=[], chunks=chunks
    )
    assert first.fingerprint == second.fingerprint
