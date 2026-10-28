# =============================================================================
# P18.1-09 — Read model del Explorador
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.knowledge.understanding.explorer import CONTRACT, build_explorer_insight


def _object(name, kind="concept", **overrides):
    return {
        "id": str(uuid4()),
        "name": name,
        "display_name": name,
        "kind": kind,
        "description": overrides.pop("description", f"Descripción de {name}"),
        "status": overrides.pop("status", "discovered"),
        "confidence": 0.7,
        "metadata": {},
        **overrides,
    }


def _evidence(canonical_id, excerpt="Pasaje real del documento."):
    return {
        "id": str(uuid4()),
        "canonical_id": canonical_id,
        "page": 12,
        "section_path": ["Capítulo 1"],
        "excerpt": excerpt,
        "locator": "document/doc/section/1/page/12",
        "evidence_type": "document",
        "strength": 0.85,
    }


def test_narrative_insight_hides_fragments_and_keeps_grounded_objects() -> None:
    good = _object("El principito")
    bad_question = _object("planeta?")
    bad_number = _object("52", kind="business_rule")
    evidence = [_evidence(str(good["id"]))]
    result = build_explorer_insight(
        source={"id": "src-1", "name": "el_principito.pdf", "type": "file", "status": "indexed"},
        document={
            "id": "doc-1",
            "content_hash": "hash-1",
            "metadata": {
                "understanding": {
                    "profile": {
                        "document_genre": "narrative",
                        "genre_confidence": 0.71,
                        "profile_version": "1.1",
                    },
                    "report": {"pages": 104, "sections": 8, "tables": 0},
                }
            },
        },
        objects=[good, bad_question, bad_number],
        evidence=evidence,
    )
    assert result["contract"] == CONTRACT
    assert result["counts"]["objects_visible"] == 1
    assert result["counts"]["objects_hidden"] == 2
    assert result["topics"][0]["label"] == "Personajes, temas y elementos"
    insight = result["topics"][0]["insights"][0]
    assert insight["name"] == "El principito"
    assert insight["grounded_excerpt"] == "Pasaje real del documento."
    assert insight["evidence_ids"]
    assert insight["source_locator"]["page"] == 12
    assert insight["verification_state"] == "discovered"
    assert insight["uncertainty"] == "media"


def test_no_evidence_is_stated_honestly() -> None:
    obj = _object("Concepto")
    result = build_explorer_insight(
        source={"id": "src-1", "name": "doc.pdf", "type": "file", "status": "indexed"},
        document={
            "id": "doc-1",
            "metadata": {
                "understanding": {
                    "profile": {"document_genre": "unknown"},
                    "report": {"pages": 1, "sections": 0},
                }
            },
        },
        objects=[obj],
        evidence=[],
    )
    assert result["insights"][0]["grounded_excerpt"] is None
    assert result["insights"][0]["uncertainty"] == "alta"
    assert any(item["code"] == "NO_OPENABLE_EVIDENCE" for item in result["warnings"])


def test_hidden_metadata_is_respected() -> None:
    obj = _object("Concepto", metadata={"explorer_visibility": "hidden"})
    result = build_explorer_insight(
        source={"id": "s"},
        document=None,
        objects=[obj],
        evidence=[],
    )
    assert result["counts"]["objects_visible"] == 0
    assert any(item["code"] == "HIDDEN_CANDIDATES" for item in result["warnings"])
