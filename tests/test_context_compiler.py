# =============================================================================
# ContextCompiler — contexto estructurado (Fase 13)
# =============================================================================
# Reglas que se prueban:
#   - clasificación por payload fabric en secciones reales (rules/definitions/
#     exceptions/conditions/related_evidence/conflicts);
#   - citation map estable por chunk;
#   - unresolved requirements desde la autoridad canónica o el grafo;
#   - presupuesto: la evidencia genérica cae antes que reglas y excepciones;
#   - render estructurado y fingerprint determinista;
#   - el generation package expone el contexto compilado.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.core.domain.entities import RetrievalChunk
from src.rag.longcontext.context_compiler import (
    compile_context,
    render_compiled_context_block,
)
from src.rag.longcontext.package import build_generation_package
from src.rag.longcontext.requirement_graph import build_requirement_graph


def _chunk(metadata: dict, content: str = "contenido de la fuente") -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content=content, score=0.5, metadata=metadata
    )


def test_compile_classifies_sections_and_citations() -> None:
    chunks = [
        _chunk(
            {
                "chunk_id": "c1",
                "rule_ids": ["r1"],
                "fabric_labels": ["Fare rule"],
                "semantic_neighborhood": [
                    {
                        "node_id": "d1",
                        "node_type": "Definition",
                        "label": "FCLAS",
                        "relation": "CONTRADICTS",
                    }
                ],
            },
            content="The fare must match &&&F",
        ),
        _chunk({"chunk_id": "c2", "definition_ids": ["d2"]}, content="FCLAS definition"),
        _chunk({"chunk_id": "c3", "exception_ids": ["e1"]}, content="unless carrier"),
        _chunk({"chunk_id": "c4", "condition_ids": ["k1"]}, content="if validated"),
        _chunk({"chunk_id": "c5"}, content="texto de apoyo"),
    ]
    compiled = compile_context(
        question="¿FCLAS &&&F acepta X?",
        chunks=chunks,
        user_inputs=["QNNF0SME"],
    )
    assert compiled.rules and compiled.rules[0]["citation"] == 1
    assert compiled.definitions[0]["citation"] == 2
    assert compiled.exceptions[0]["citation"] == 3
    assert compiled.conditions[0]["citation"] == 4
    assert compiled.related_evidence[0]["citation"] == 5
    assert compiled.conflicts[0]["object_label"] == "FCLAS"
    assert len(compiled.citation_map) == 5
    assert compiled.user_inputs == ("QNNF0SME",)
    public = compiled.to_public_dict()
    assert public["rules"][0]["node_ids"] == ["r1"]
    assert public["stats"]["chunks"] == 5


def test_unresolved_requirements_from_canonical_state() -> None:
    state = SimpleNamespace(
        missing_documentable_evidence=lambda: ("excepción del carrier",)
    )
    compiled = compile_context(
        question="q",
        chunks=[_chunk({"chunk_id": "c1", "rule_ids": ["r1"]})],
        evidence_state=state,
    )
    assert compiled.unresolved_requirements == ("excepción del carrier",)

    graph = build_requirement_graph(
        question="q",
        requirements=[],
        chunks=[
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
        ],
    )
    compiled2 = compile_context(question="q", chunks=[], requirement_graph=graph)
    assert "FCLAS" in compiled2.unresolved_requirements


def test_trim_keeps_rules_and_exceptions_over_generic_evidence() -> None:
    chunks = [_chunk({"chunk_id": "c1", "rule_ids": ["r1"]}, content="regla")]
    chunks.append(
        _chunk({"chunk_id": "c2", "exception_ids": ["e1"]}, content="excepción")
    )
    for index in range(40):
        chunks.append(
            _chunk({"chunk_id": f"e{index}"}, content="evidencia " + "x" * 200)
        )
    compiled = compile_context(
        question="q", chunks=chunks, max_tokens=80
    )
    assert compiled.rules
    assert compiled.exceptions
    assert compiled.omitted["related_evidence"] > 0
    assert compiled.stats["trimmed"] == sum(compiled.omitted.values())


def test_render_block_and_package_expose_compiled_context() -> None:
    compiled = compile_context(
        question="¿qué exige la regla?",
        chunks=[
            _chunk(
                {"chunk_id": "c1", "rule_ids": ["r1"], "fabric_labels": ["Regla"]},
                content="The fare must match &&&F",
            )
        ],
        user_inputs=["QNNF0SME"],
    )
    rendered = render_compiled_context_block(compiled)
    assert "[CONTEXTO COMPILADO]" in rendered
    assert "Reglas:" in rendered
    assert "Datos del usuario: QNNF0SME" in rendered

    package = build_generation_package(
        question="q", compiled_context=compiled
    )
    public = package.to_public_dict()
    assert public["compiled_context"]["rules"][0]["node_ids"] == ["r1"]


def test_compiled_fingerprint_is_deterministic() -> None:
    chunks = [_chunk({"chunk_id": "c1", "rule_ids": ["r1"]})]
    first = compile_context(question="q", chunks=chunks)
    second = compile_context(question="q", chunks=chunks)
    assert first.fingerprint == second.fingerprint
