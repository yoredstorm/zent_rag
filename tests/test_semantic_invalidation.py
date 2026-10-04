# =============================================================================
# Invalidación incremental por etapa (Fase 15)
# =============================================================================
# Reglas que se prueban:
#   - el grafo de invalidación cubre las etapas semánticas (windows -> stitch
#     -> regional -> global -> fabric -> representación -> embedding);
#   - cambiar una etapa NO reprocesa la fuente: solo lo downstream;
#   - `fabric_changed` reindexa; `global_changed` resintetiza y reproyecta;
#   - stitch_fingerprint determinista.
# =============================================================================
from __future__ import annotations

from src.knowledge.representation import (
    ArtifactKind,
    invalidation_plan,
    plan_for_reason,
)
from src.knowledge.semantic import (
    SemanticStitcher,
    StitchOutcome,
    stitch_fingerprint,
)


def test_fabric_invalidation_reindexes_without_reparse() -> None:
    plan = invalidation_plan(ArtifactKind.FABRIC)
    assert ArtifactKind.RETRIEVAL_REPRESENTATION in plan.stale
    assert ArtifactKind.EMBEDDING in plan.stale
    assert ArtifactKind.RETRIEVAL_ACCEPTANCE in plan.stale
    assert plan.requires_reembedding is True
    assert plan.requires_reparse is False
    assert "reproject" in plan.actions
    assert "reindex" in plan.actions
    assert "reevaluate" in plan.actions


def test_global_change_reprojects_and_reindexes() -> None:
    plan = plan_for_reason("global_changed")
    assert plan is not None
    assert plan.changed == ArtifactKind.GLOBAL
    assert "resynthesize" in plan.actions
    assert "reproject" in plan.actions
    assert "reindex" in plan.actions
    assert ArtifactKind.FABRIC in plan.stale
    assert ArtifactKind.EMBEDDING in plan.stale


def test_stitch_change_downstream_only() -> None:
    plan = plan_for_reason("stitch_changed")
    assert plan is not None
    assert plan.changed == ArtifactKind.STITCH
    for kind in (
        ArtifactKind.REGIONAL,
        ArtifactKind.GLOBAL,
        ArtifactKind.FABRIC,
        ArtifactKind.RETRIEVAL_REPRESENTATION,
        ArtifactKind.EMBEDDING,
        ArtifactKind.RETRIEVAL_ACCEPTANCE,
    ):
        assert kind in plan.stale
    assert ArtifactKind.PARSED_STRUCTURE not in plan.stale
    assert ArtifactKind.SEMANTIC_WINDOWS not in plan.stale


def test_stitch_fingerprint_is_deterministic() -> None:
    outcome = SemanticStitcher().stitch(
        document=type("Doc", (), {"id": None})(),
        results=[],
        threads=[],
    )
    first = stitch_fingerprint(outcome)
    second = stitch_fingerprint(outcome)
    assert first == second
    assert isinstance(outcome, StitchOutcome)


def test_fingerprint_includes_semantic_pipeline_versions() -> None:
    """Fase 29: window/state/stitcher/regional/global entran al fingerprint."""
    from uuid import uuid4

    from src.knowledge.representation import change_reason, descriptor_for_document
    from src.knowledge.structure.text_parser import TextParser
    from src.knowledge.understanding.engine import apply_understanding

    parsed = TextParser().parse(
        b"# Manual\n\nFCLAS - fare class definition.",
        organization_id=uuid4(),
        external_id="fp.md",
        source_id=uuid4(),
        source_name="fp.md",
    )
    document = apply_understanding(parsed, filename="fp.md")
    payload = descriptor_for_document(document).to_payload()
    for key in (
        "semantic_window_policy",
        "semantic_state",
        "stitcher",
        "regional_model",
        "global_model",
        "fabric_representation_version",
    ):
        assert payload.get(key), f"falta {key} en el fingerprint"

    previous = dict(payload)
    previous["stitcher"] = "semantic-stitch-0"
    assert (
        change_reason(previous, payload, content_changed=False)
        == "semantic_pipeline_changed"
    )
