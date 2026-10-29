# =============================================================================
# P18.2-04 — Género documental vs dominio vs semántica
# =============================================================================
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.core.domain.knowledge_v2 import (
    DocumentSection,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.understanding.views import source_profile

ROOT = Path(__file__).resolve().parent / "fixtures"
LABELS = json.loads((ROOT / "p18_2" / "labels.json").read_text(encoding="utf-8"))


def _document(text: str, *, title: str = "documento") -> StructuredDocument:
    blocks = tuple(
        StructuredBlock(kind=StructuredBlockKind.PARAGRAPH, text=line, order=index)
        for index, line in enumerate(text.splitlines())
        if line.strip()
    )
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id=f"{title}.txt",
        title=title,
        content_hash="hash",
        blocks=blocks,
    )


def _profile(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return source_profile(_document(text, title=path.stem), {}, {}, filename=path.name)


def test_annotated_matrix_matches_expected_genre_and_type() -> None:
    for name, expected in LABELS.items():
        path = ROOT / "p18_2" / name if (ROOT / "p18_2" / name).exists() else ROOT / "p18_1" / name
        profile = _profile(path)
        assert profile["document_genre"] == expected["genre"], name
        if expected.get("document_type"):
            assert profile["document_type"] == expected["document_type"], name


def test_narrative_with_numbers_questions_and_dialogue_is_not_technical() -> None:
    profile = _profile(ROOT / "p18_2" / "narrative_journey.txt")
    assert profile["document_genre"] == "narrative"
    assert profile["document_type"] != "technical_specification"
    assert profile["document_genre"] not in {"technical", "policy", "legal", "tabular"}
    for signal in profile["genre_evidence"]:
        assert signal["signal"] != "technical_layout"


def test_technical_manual_keeps_real_fields_and_masks() -> None:
    profile = _profile(ROOT / "p18_2" / "technical_manual.txt")
    assert profile["document_genre"] == "technical"
    assert profile["document_type"] == "technical_specification"
    assert profile["technical_shape"] >= 2
    signals = {item["signal"] for item in profile["genre_evidence"]}
    assert "technical_layout" in signals


def test_mixed_document_declares_segments_but_keeps_global_shape() -> None:
    text = (ROOT / "p18_2" / "mixed_policy_technical.txt").read_text(encoding="utf-8")
    document = _document(text, title="mixto")
    sections = []
    blocks = list(document.blocks)
    for index, heading in enumerate(["Política de control de registros", "Especificación del registro"]):
        section_id = uuid4()
        owned = [
            block
            for block in blocks
            if (index == 0 and block.text.startswith(("El ", "El responsable")))
            or (index == 1 and block.text.startswith(("Campo ", "El registro")))
        ]
        for block in owned:
            block.metadata["parent_section_id"] = str(section_id)
        sections.append(
            DocumentSection(
                id=section_id,
                document_id=document.id,
                organization_id=document.organization_id,
                section_path=(heading,),
                heading=heading,
                order=index,
                block_ids=tuple(block.id for block in owned),
                text="\n".join(block.text for block in owned),
            )
        )
    document = replace(document, sections=tuple(sections))
    profile = source_profile(document, {}, {}, filename="mixto.txt")

    assert profile["document_genre"] == "mixed"
    segments = {item["heading"]: item["genre"] for item in profile["genre_segments"]}
    assert segments["Política de control de registros"] == "policy"
    assert segments["Especificación del registro"] == "technical"


def test_noisy_or_empty_text_is_unknown_not_technical() -> None:
    for name in ("noisy_pdf_text.txt", "empty.txt"):
        profile = _profile(ROOT / "p18_1" / name)
        assert profile["document_genre"] == "unknown", name
        assert profile["document_type"] != "technical_specification", name
