# =============================================================================
# P18.2-05/06 — Comprensión por pasajes y resumen explicable
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.knowledge.understanding.explorer import build_explorer_insight
from src.knowledge.understanding.passages import build_passage_understanding

ROOT = Path(__file__).resolve().parent / "fixtures" / "p18_2"


def _blocks(name: str) -> list[dict]:
    text = (ROOT / name).read_text(encoding="utf-8")
    blocks = []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        kind = "section" if index == 0 else "paragraph"
        blocks.append(
            {
                "id": str(uuid4()),
                "kind": kind,
                "text": line.strip(),
                "heading": line.strip() if kind == "section" else None,
                "page_number": 1 + index // 4,
                "order_index": index,
                "section_path": [line.strip()] if kind == "section" else [],
                "metadata": {},
            }
        )
    return blocks


def _document(name: str, text: str) -> dict:
    return {
        "id": str(uuid4()),
        "title": name,
        "content_hash": "hash-narrative",
        "page_count": 3,
        "section_count": 1,
        "table_count": 0,
        "metadata": {
            "understanding": {
                "profile": {
                    "document_genre": "narrative",
                    "genre_confidence": 0.65,
                    "profile_version": "1.1",
                },
                "report": {"pages": 3, "sections": 1, "tables": 0},
            }
        },
    }


def test_narrative_participants_are_grounded_and_named_without_numbers() -> None:
    view = build_passage_understanding(
        document=None,
        blocks=_blocks("narrative_journey.txt"),
        genre="unknown",
    )
    names = {item["name"] for item in view["participants"]}
    assert {"lía", "tomás", "nara"} <= names
    assert "52" not in names
    assert "planeta?" not in names
    assert view["narrative_signal"] is True
    assert all(item["mentions"] >= 2 for item in view["participants"])
    assert all(item["excerpt"] for item in view["participants"])
    assert view["passages"]
    assert all(item["page"] for item in view["passages"])


def test_technical_manual_does_not_invent_characters() -> None:
    view = build_passage_understanding(
        document=None,
        blocks=_blocks("technical_manual.txt"),
        genre="technical",
    )
    assert view["narrative_signal"] is False
    assert view["participants"] == []
    assert view["themes"] == []
    assert view["relations"] == []


def test_narrative_signal_is_detected_even_with_stale_genre() -> None:
    view = build_passage_understanding(
        document=None,
        blocks=_blocks("narrative_journey.txt"),
        genre="unknown",
    )
    assert view["narrative_signal"] is True
    assert view["participants"]


def test_explorer_uses_passages_when_canonical_objects_are_zero() -> None:
    document = _document("narrative_journey.txt", "")
    result = build_explorer_insight(
        source={"id": "src-1", "name": "narrative_journey.txt", "type": "file"},
        document=document,
        objects=[],
        evidence=[],
        blocks=_blocks("narrative_journey.txt"),
    )

    assert result["counts"]["objects_visible"] == 0
    assert result["counts"]["proposals"] >= 3
    assert result["counts"]["proposed_participants"] >= 3
    assert any(topic["id"] == "passages" for topic in result["topics"])
    assert any(warning["code"] == "PROPOSALS_NOT_VERIFIED" for warning in result["warnings"])
    assert "no son hechos verificados" in result["summary"]
    assert result["limitations"]
    assert result["structure"]
    assert result["passages"]
    assert result["counts"]["passages_available"] >= len(result["passages"])
    assert any(
        "bloques estructurados" in item for item in result["limitations"]
    )
    assert result["narrative_proposals"]["relations"]
    assert all(
        "simboliza" not in item["claim_text"].lower() for topic in result["topics"] for item in topic["insights"]
    )
    # Nunca se publican como objetos canónicos.
    assert all(
        item["object_id"] is None
        for topic in result["topics"]
        if topic["id"] == "passages"
        for item in topic["insights"]
    )


def test_no_fabricated_quote_or_relation_without_passage() -> None:
    view = build_passage_understanding(
        document=None,
        blocks=_blocks("narrative_journey.txt"),
        genre="narrative",
    )
    block_texts = "\n".join(block["text"] for block in _blocks("narrative_journey.txt"))
    for relation in view["relations"]:
        assert relation["evidence_excerpt"]
        assert relation["evidence_excerpt"] in block_texts
        assert relation["status"] == "proposed"
        assert relation["claim_kind"] == "narrative_relation"
