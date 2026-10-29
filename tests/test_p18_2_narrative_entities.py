# =============================================================================
# P18.2-05 — Narrativa no promueve secciones/diálogos a entidades canónicas
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.knowledge_v2 import StructuredBlock, StructuredBlockKind, StructuredDocument
from src.knowledge.compiler.entities import discover_entities
from src.knowledge.compiler.model import (
    EvidenceRef,
    SemanticUnit,
    SemanticUnitKind,
    SourceLocator,
)


def _document(genre: str) -> StructuredDocument:
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id="libro.txt",
        title="Libro",
        content_hash="hash",
        blocks=(
            StructuredBlock(
                kind=StructuredBlockKind.PARAGRAPH,
                text="—Adiós —dijo el principito.",
                order=0,
            ),
        ),
        metadata={
            "understanding": {
                "profile": {"document_genre": genre, "profile_version": "1.1"}
            }
        },
    )


def _unit(label: str, kind: str = SemanticUnitKind.SECTION.value) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{label}",
        label=label,
        text=label,
        confidence=0.8,
        evidence=EvidenceRef(
            locator=SourceLocator(page=1),
            excerpt=label,
            confidence=0.8,
        ),
    )


def test_narrative_sections_do_not_become_entities() -> None:
    entities = discover_entities(
        [
            _unit("Adiós"),
            _unit("Buenos días"),
            _unit("¿Ah sí?"),
            _unit("Acércate para que te vea mejor"),
        ],
        document=_document("narrative"),
    )
    assert entities == []


def test_technical_section_still_can_become_process() -> None:
    entities = discover_entities(
        [_unit("Validación de máscara")],
        document=_document("technical"),
    )
    assert entities
    assert entities[0].name == "Validación de máscara"
