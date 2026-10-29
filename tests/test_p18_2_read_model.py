# =============================================================================
# P18.2-03 — Completitud, paginación y calidad del read model
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.knowledge.understanding.explorer import CONTRACT, build_explorer_insight


def _object(index: int, kind: str = "entity") -> dict:
    return {
        "id": str(uuid4()),
        "name": f"Entidad {index}",
        "display_name": f"Entidad {index}",
        "kind": kind,
        "description": f"Descripción sustentada de la entidad {index}.",
        "status": "discovered",
        "confidence": 0.7,
        "metadata": {},
    }


def _evidence(canonical_id: str, *, strength: float, excerpt: str, page: int = 1) -> dict:
    return {
        "id": str(uuid4()),
        "canonical_id": canonical_id,
        "page": page,
        "section_path": ["Sección"],
        "excerpt": excerpt,
        "locator": f"page/{page}",
        "evidence_type": "document",
        "strength": strength,
        "created_at": "2026-10-01T00:00:00+00:00",
    }


def _document(document_id: str | None = None) -> dict:
    return {
        "id": document_id or str(uuid4()),
        "content_hash": "hash-1",
        "page_count": 10,
        "section_count": 3,
        "table_count": 0,
        "metadata": {
            "understanding": {
                "profile": {
                    "document_genre": "technical",
                    "genre_confidence": 0.8,
                    "profile_version": "1.1",
                },
                "report": {"pages": 10, "sections": 3, "tables": 0},
            }
        },
    }


def test_contract_is_v2_and_declares_evaluation_state() -> None:
    result = build_explorer_insight(
        source={"id": "src-1", "name": "doc.pdf"},
        document=_document(),
        objects=[],
        evidence=[],
    )
    assert CONTRACT == "knowledge_explorer_insight/v2"
    assert result["contract"] == CONTRACT
    assert result["provenance"]["evaluation_state"] == "not_evaluated"
    assert result["provenance"]["is_stale"] is False


def test_truncated_read_never_claims_total_was_read() -> None:
    objects = [_object(index) for index in range(1000)]
    result = build_explorer_insight(
        source={"id": "src-1", "name": "grande.pdf"},
        document=_document(),
        objects=objects,
        evidence=[],
        read_stats={
            "objects_total": 1001,
            "objects_truncated": True,
            "objects_next_cursor": objects[-1]["id"],
            "evidence_total": 0,
            "documents_total": 1,
        },
    )

    assert result["counts"]["objects_total"] == 1001
    assert result["counts"]["objects_returned"] == 1000
    assert result["counts"]["objects_not_evaluated"] == 1
    assert result["counts"]["truncated"] is True
    assert result["pagination"]["objects"]["next_cursor"] == objects[-1]["id"]
    assert any(item["code"] == "READ_TRUNCATED" for item in result["warnings"])


def test_strongest_evidence_wins_not_most_recent() -> None:
    obj = _object(1)
    weak = _evidence(obj["id"], strength=0.2, excerpt="Pasaje débil.", page=2)
    strong = _evidence(obj["id"], strength=0.95, excerpt="Pasaje fuerte.", page=9)
    result = build_explorer_insight(
        source={"id": "src-1", "name": "doc.pdf"},
        document=_document(),
        objects=[obj],
        evidence=[weak, strong],
    )
    insight = result["insights"][0]
    assert insight["grounded_excerpt"] == "Pasaje fuerte."
    assert insight["source_locator"]["page"] == 9


def test_multiple_documents_are_counted_not_silently_dropped() -> None:
    primary = _document()
    secondary = _document()
    secondary["title"] = "Anexo"
    result = build_explorer_insight(
        source={"id": "src-1", "name": "paquete.pdf"},
        document=primary,
        documents=[primary, secondary],
        objects=[],
        evidence=[],
        read_stats={"documents_total": 3, "documents_truncated": True},
    )
    assert result["counts"]["documents_total"] == 3
    assert result["pagination"]["documents"]["returned"] == 2
    assert result["pagination"]["documents"]["truncated"] is True
    assert result["documents"][0]["primary"] is True
    assert result["documents"][1]["primary"] is False


def test_stale_profile_is_flagged_without_mutating_document() -> None:
    document = _document()
    document["metadata"]["understanding"]["profile"].pop("document_genre")
    before = repr(document)
    result = build_explorer_insight(
        source={"id": "src-1", "name": "historico.pdf"},
        document=document,
        objects=[],
        evidence=[],
    )
    assert result["provenance"]["is_stale"] is True
    assert result["source"]["genre"] == "unknown"
    assert repr(document) == before
