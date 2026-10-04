# =============================================================================
# Knowledge Representation — fingerprint + parent semantic representation
# =============================================================================
# El fingerprint debe detectar cambios de REPRESENTACIÓN aunque el contenido
# no cambie (modelo de embeddings, enrichment version, chunking...). El padre
# nunca se embebe por truncamiento: se compone con señal semántica.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.knowledge.enrichment import enrich_document
from src.knowledge.representation import (
    RepresentationDecision,
    RepresentationDescriptor,
    build_parent_representation,
    change_reason,
    compute_fingerprint,
    descriptor_for_document,
    representation_decision,
)
from src.knowledge.representation.parent import PARENT_REPRESENTATION_VERSION
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding
from src.knowledge.understanding.units import chunks_for_document


def _understood_document(text: str, *, external_id: str = "manual.md"):
    parser = TextParser()
    document = parser.parse(
        text.encode("utf-8"),
        organization_id=uuid4(),
        external_id=external_id,
        source_id=uuid4(),
        source_name=external_id,
    )
    return apply_understanding(document, filename=external_id)


def _descriptor(**overrides) -> RepresentationDescriptor:
    base = dict(
        content_hash="hash-1",
        parser_version="parser-1",
        structure_schema_version="2",
        reconstruction_version="1.0",
        understanding_version="1.1",
        enrichment_version="1",
        chunking_version="semantic-units-1",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
    )
    base.update(overrides)
    return RepresentationDescriptor(**base)


def test_fingerprint_same_content_same_config_is_stable() -> None:
    assert compute_fingerprint(_descriptor()) == compute_fingerprint(_descriptor())
    assert _descriptor().fingerprint == _descriptor().fingerprint


def test_fingerprint_changes_with_embedding_model() -> None:
    assert compute_fingerprint(_descriptor()) != compute_fingerprint(
        _descriptor(embedding_model="text-embedding-3-large")
    )


def test_fingerprint_changes_with_embedding_dimensions() -> None:
    assert compute_fingerprint(_descriptor()) != compute_fingerprint(
        _descriptor(embedding_dimensions=3072)
    )


def test_fingerprint_changes_with_enrichment_version() -> None:
    assert compute_fingerprint(_descriptor()) != compute_fingerprint(
        _descriptor(enrichment_version="2")
    )


def test_fingerprint_changes_with_parent_representation_version() -> None:
    assert compute_fingerprint(_descriptor()) != compute_fingerprint(
        _descriptor(parent_representation_version="parent-semantic-2")
    )


def test_fingerprint_changes_with_content() -> None:
    assert compute_fingerprint(_descriptor()) != compute_fingerprint(
        _descriptor(content_hash="hash-2")
    )


def test_decision_matrix() -> None:
    current = "fp-current"
    assert (
        representation_decision(None, current, content_changed=False)
        is RepresentationDecision.CREATE
    )
    assert (
        representation_decision(current, current, content_changed=False)
        is RepresentationDecision.SKIP
    )
    assert (
        representation_decision("fp-old", current, content_changed=False)
        is RepresentationDecision.REINDEX
    )
    assert (
        representation_decision("fp-old", current, content_changed=True)
        is RepresentationDecision.UPDATE
    )


def test_change_reason_is_specific_and_bounded() -> None:
    base = _descriptor().to_payload()
    # Sin descriptor previo: missing_index (o manual si un operador invalidó).
    assert change_reason(None, base) == "missing_index"
    assert change_reason(None, base, invalidated_by="manual") == "manual"
    assert change_reason(None, base, invalidated_by="nutrition_action") == "nutrition_action"
    # Contenido distinto gana a cualquier versión.
    assert change_reason(base, _descriptor(content_hash="hash-2").to_payload()) == "content_changed"
    assert (
        change_reason(base, base, content_changed=True) == "content_changed"
    )
    # Modelo/dims.
    assert (
        change_reason(base, _descriptor(embedding_model="otro").to_payload())
        == "embedding_model_changed"
    )
    assert (
        change_reason(base, _descriptor(embedding_dimensions=999).to_payload())
        == "embedding_dimension_changed"
    )
    # Versiones de pipeline.
    assert (
        change_reason(base, _descriptor(enrichment_version="2").to_payload())
        == "enrichment_version_changed"
    )
    assert (
        change_reason(base, _descriptor(chunking_version="otro").to_payload())
        == "chunking_changed"
    )
    assert (
        change_reason(base, _descriptor(parser_version="otro").to_payload())
        == "parser_changed"
    )
    assert (
        change_reason(base, _descriptor(parent_representation_version="parent-semantic-2").to_payload())
        == "parent_representation_changed"
    )
    # Igual: unchanged.
    assert change_reason(base, base) == "unchanged"


def test_invalidation_graph_is_centralized_and_transitive() -> None:
    from src.knowledge.representation import (
        ArtifactKind,
        downstream_of,
        invalidation_plan,
        plan_for_reason,
    )

    # Cambiar enrichment invalida representación, embeddings y acceptance,
    # pero NO exige reparse ni recompilar evidencia.
    stale = downstream_of(ArtifactKind.ENRICHMENT)
    assert ArtifactKind.RETRIEVAL_REPRESENTATION in stale
    assert ArtifactKind.EMBEDDING in stale
    assert ArtifactKind.RETRIEVAL_ACCEPTANCE in stale
    assert ArtifactKind.PARSED_STRUCTURE not in stale
    plan = invalidation_plan("ENRICHMENT")
    assert "reenrich" in plan.actions
    assert "reindex" in plan.actions
    assert "reevaluate" in plan.actions
    assert plan.requires_reembedding is True
    assert plan.requires_reparse is False

    # Cambiar el retriever (acceptance) NO re-embebe: solo reevalúa.
    plan = invalidation_plan(ArtifactKind.RETRIEVAL_ACCEPTANCE)
    assert plan.actions == ("reevaluate",)
    assert plan.requires_reembedding is False

    # Cambiar reglas del compiler: recompila y refresca payload, sin re-embed.
    plan = invalidation_plan(ArtifactKind.COMPILATION)
    assert "recompile" in plan.actions
    assert "refresh_payload" in plan.actions
    assert plan.requires_reembedding is False

    # Razones del fingerprint mapean a planes; unchanged no genera plan.
    assert plan_for_reason("embedding_model_changed").requires_reembedding is True
    assert plan_for_reason("enrichment_version_changed").actions[0] == "reenrich"
    assert plan_for_reason("unchanged") is None
    assert plan_for_reason(None) is None


def test_descriptor_reads_real_versions_from_document() -> None:
    document = _understood_document("# Manual\n\nCategory 31 defines voluntary changes.\n")
    descriptor = descriptor_for_document(
        document,
        embedding_provider="test",
        embedding_model="model-a",
        embedding_dimensions=8,
    )
    assert descriptor.content_hash == document.content_hash
    assert descriptor.parser_version  # versión real del parser
    assert descriptor.understanding_version  # versión real del understanding
    understanding = document.metadata.get("understanding") or {}
    assert descriptor.reconstruction_version == str(
        document.metadata.get("semantic_reconstruction", {}).get("schema_version") or ""
    )
    assert understanding.get("parser_version") == descriptor.parser_version


def test_parent_representation_is_composed_not_truncated() -> None:
    text = (
        "# Category 31 - Voluntary Changes\n\n"
        "Category 31 (CAT31) covers exchange eligibility, penalties and waiver conditions. "
        "Field: Status Byte\nBytes: 105-105\nDescription: Byte 105 indicates the status.\n"
    )
    document = _understood_document(text)
    chunks = chunks_for_document(document)
    parents = [chunk for chunk in chunks if (chunk.metadata or {}).get("level") == "parent"]
    assert parents, "el documento debe producir al menos un parent de sección"

    # Parent enorme: 55k+ caracteres de evidencia real (sección entera).
    import dataclasses

    filler = " ".join(f"detail_{index}" for index in range(9000))
    parent = parents[0]
    parent = dataclasses.replace(
        parent,
        content=f"{parent.content}\n\n{filler}",
        token_count=parent.token_count + len(filler.split()),
    )
    assert len(parent.content) > 50000, "el padre real conserva todo el contenido"

    enrichment = enrich_document(document)
    representation = build_parent_representation(
        document, parent, enrichment=enrichment, max_chars=1500
    )
    assert representation.version == PARENT_REPRESENTATION_VERSION
    assert len(representation.text) <= 1500
    # No es un prefijo del texto del padre (eso sería truncamiento).
    assert representation.text != parent.content[:1500]
    assert "Category 31" in representation.text or "Category31" in representation.text
    assert "Title:" in representation.text
    assert "Section:" in representation.text
    assert "Concepts:" in representation.text
    # Sin compiler disponible la representación es preliminar y actualizable.
    assert representation.preliminary is True
    assert representation.metadata.get("preliminary") is True
    assert representation.source_unit_ids
    assert representation.metadata.get("derived") is True
    assert representation.metadata.get("canonical") is False
    # El contenido real del padre sigue intacto en el chunk (evidencia).
    assert len(parent.content) > len(representation.text)


def test_parent_representation_finds_concepts_at_the_end() -> None:
    """Conceptos importantes al final del parent: la composición no los pierde."""
    filler_paragraphs = "\n\n".join(
        f"Filler paragraph {index} with routine narrative text about operations."
        for index in range(120)
    )
    text = (
        "# Manual\n\n"
        f"{filler_paragraphs}\n\n"
        "Field: Status Byte\nBytes: 105-105\nDescription: Byte 105 indicates the status.\n"
    )
    document = _understood_document(text)
    enrichment = enrich_document(document)
    chunks = chunks_for_document(document)
    parent = next(chunk for chunk in chunks if chunk.metadata.get("level") == "parent")
    assert len(parent.content) > 5000, "el parent acumula toda la sección"

    representation = build_parent_representation(
        document, parent, enrichment=enrichment, max_chars=1600
    )
    # Los conceptos del final del documento están en la representación compacta.
    assert "Byte 105" in representation.text, representation.text
    assert "Status Byte" in representation.text, representation.text
    assert "Identifiers:" in representation.text
    # No secciones vacías.
    assert "Entities:" not in representation.text or representation.entity_names
    assert len(representation.text) <= 1600


def test_parent_representation_provenance_towards_children() -> None:
    text = (
        "# Section A\n\n"
        "Record 4 defines the exchange rule for voluntary changes.\n\n"
        "Record 5 defines the penalty waiver conditions.\n"
    )
    document = _understood_document(text)
    chunks = chunks_for_document(document)
    parent = next(
        chunk for chunk in chunks if chunk.metadata.get("level") == "parent"
    )
    children = [chunk for chunk in chunks if chunk.parent_id == parent.id]
    assert children
    representation = build_parent_representation(document, parent, children=children)
    assert representation.child_count == len(children)
    assert len(representation.child_ids) == len(children[:8])
    assert representation.metadata.get("derivation_method") == "deterministic_compose"
