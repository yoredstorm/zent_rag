# =============================================================================
# diagnose_retrieval — resumen genérico de cobertura de un run de búsqueda
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.entities import RetrievalChunk
from src.scripts.diagnose_retrieval import summarize_coverage


def _chunk(texto: str, score: float = 0.5) -> RetrievalChunk:
    return RetrievalChunk(document_id=uuid4(), content=texto, score=score)


def test_cobertura_de_entidades_y_anchors() -> None:
    resumen = summarize_coverage(
        [_chunk("4.6.2 Fee Application (byte 105)\nValue | Definition")],
        "¿qué dice el byte 105 de la categoría 31?",
    )

    assert resumen["entities_covered"] == ["byte 105"]
    assert resumen["entities_missing"] == ["categoría 31"]
    assert resumen["anchors_covered"] == []


def test_un_anchor_cubierto_cuenta_como_cobertura() -> None:
    resumen = summarize_coverage(
        [_chunk("Data table 3200501059649 layout\n14-22 Field")],
        "interpreta 3200501059649",
    )

    assert resumen["anchors_missing"] == []
    assert resumen["anchors_covered"] == ["codigo 3200501059649"]


def test_sin_anchors_ni_entidades_el_resumen_queda_vacio() -> None:
    resumen = summarize_coverage([_chunk("texto general")], "¿cómo funciona?")

    assert resumen == {
        "entities_covered": [],
        "entities_missing": [],
        "anchors_covered": [],
        "anchors_missing": [],
    }
