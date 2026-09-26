# =============================================================================
# Evidencia — el recorte por relevancia no es texto[:N]
# =============================================================================
# Caso real: el overview de la Categoría 31 son 157.856 chars; «Table 988» vive
# en el offset 5.470 y «Record 2» en el 6.896. El corte ciego a 4.000 los dejaba
# afuera y la respuesta decía «las fuentes no detallan Record 2/Record 3».
from __future__ import annotations

from src.core.domain.adaptive import EvidenceItem
from src.runtime.evidence import relevance_window, select_evidence


def test_la_ventana_conserva_el_tramo_del_final() -> None:
    texto = ("A" * 5000) + " TABLE 988 PROCESSING " + ("B" * 500)

    ventana = relevance_window(texto, ["table 988"], budget=1500)

    assert ventana.startswith("A" * 100), "el arranque siempre entra"
    assert "TABLE 988" in ventana, "el tramo pedido entra aunque esté al final"
    assert len(ventana) <= 1500


def test_la_ventana_sin_match_conserva_el_arranque() -> None:
    texto = "arranque " + ("Z" * 5000)

    assert relevance_window(texto, ["inexistente"], budget=200) == texto[:200]


def test_la_seccion_expandida_entra_completa_al_presupuesto() -> None:
    item = EvidenceItem(
        source_type="qdrant",
        content="X" * 9000,
        evidence_id="E1",
        retrieval_method="entity_section",
        entity_pin=True,
    )

    seleccion = select_evidence(
        [item], "cuéntame de la categoría 31 y el byte 105", budget_chars=12000
    )

    assert seleccion.chars == 9000, "la sección no se corta a 4.000"
    assert seleccion.matches[0].complete is True


def test_un_fragmento_grande_se_recorta_por_relevancia_no_por_posicion() -> None:
    contenido = "encabezado\n" + ("z" * 3000) + " byte 105 relevante\n" + ("w" * 3000)
    item = EvidenceItem(source_type="qdrant", content=contenido, evidence_id="E2")

    seleccion = select_evidence(
        [item], "¿qué dice el byte 105?", budget_chars=2000, max_item_chars=1000
    )

    assert "byte 105 relevante" in seleccion.matches[0].content
    assert seleccion.matches[0].complete is False
