# =============================================================================
# Anchors genéricos — tokens estructurados de la pregunta (sin dominio)
# =============================================================================
# Un «anchor» es un identificador que el texto denso no sabe buscar: runs de
# dígitos, códigos alfanuméricos, rangos. El core los extrae por forma; los
# providers de dominio (plugins) agregan semántica sin tocar el core.
from __future__ import annotations

import sys
import types

import pytest

from src.intelligence.response.anchors import (
    Anchor,
    anchor_covered,
    anchor_needles,
    clear_anchor_providers,
    dense_query_rewrite,
    extract_anchors,
    load_anchor_modules,
    register_anchor_provider,
)

TRAMA = "3200501059649 007D 00000000X 001D R007D03E000 000000000000000000000000000000"


@pytest.fixture(autouse=True)
def _sin_providers() -> None:
    clear_anchor_providers()
    yield
    clear_anchor_providers()


class TestExtractorGenerico:
    def test_run_largo_de_digitos_es_un_anchor(self) -> None:
        anchors = extract_anchors(f"interpreta esta trama {TRAMA}")

        codigos = [a for a in anchors if a.kind == "codigo"]
        assert any(a.value == "3200501059649" for a in codigos)

    def test_codigo_alfanumerico_es_un_anchor(self) -> None:
        anchors = extract_anchors("explicame R007D03E000")

        assert any(a.value == "R007D03E000" for a in anchors)

    def test_rango_de_posiciones_es_un_anchor(self) -> None:
        anchors = extract_anchors("que dice el rango 14-22 del layout")

        rangos = [a for a in anchors if a.kind == "rango"]
        assert rangos and rangos[0].value == "14-22"
        assert "14 22" in rangos[0].needles

    def test_pregunta_en_prosa_no_produce_anchors(self) -> None:
        assert extract_anchors("¿cuál es la política de reembolsos?") == []

    def test_los_anchors_no_se_repiten(self) -> None:
        anchors = extract_anchors("3200501059649 y de nuevo 3200501059649")

        assert len([a for a in anchors if a.value == "3200501059649"]) == 1

    def test_tope_de_anchors(self) -> None:
        anchors = extract_anchors("1111111 2222222 3333333 4444444 5555555 6666666")

        assert len(anchors) <= 4


class TestProviders:
    def test_un_provider_agrega_anchors_de_dominio(self) -> None:
        class _Provider:
            def extract(self, question: str):
                if "trama" not in question.lower():
                    return []
                return [
                    Anchor(
                        kind="trama",
                        value="3200501059649",
                        label="trama 3200501059649",
                        variants=("3200501059649",),
                        needles=("3200501059649",),
                        expansion_terms=("record layout bytes",),
                    )
                ]

        register_anchor_provider(_Provider())
        anchors = extract_anchors(f"interpreta la trama {TRAMA}")

        assert anchors and anchors[0].kind == "trama"
        assert anchors[0].expansion_terms == ("record layout bytes",)
        assert not any(a.kind == "codigo" and a.value == "3200501059649" for a in anchors), (
            "el token ya cubierto por el provider no se duplica como genérico"
        )

    def test_load_anchor_modules_importa_y_llama_register(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = types.ModuleType("_zent_anchor_test_module")
        calls: list[str] = []

        def register() -> None:
            calls.append("ok")

        module.register = register  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "_zent_anchor_test_module", module)

        load_anchor_modules(["_zent_anchor_test_module"])

        assert calls == ["ok"]

    def test_load_anchor_modules_no_rompe_con_modulo_inexistente(self) -> None:
        load_anchor_modules(["_zent_anchor_no_existe"])


class TestDenseRewrite:
    def test_los_tokens_opacos_salen_del_texto_denso(self) -> None:
        limpio = dense_query_rewrite(f"interpreta esta trama {TRAMA} de categoría 5")

        assert "3200501059649" not in limpio
        assert "R007D03E000" not in limpio
        assert "categoría 5" in limpio

    def test_si_no_queda_texto_se_conserva_la_pregunta(self) -> None:
        solo_tokens = "3200501059649 R007D03E000"

        assert dense_query_rewrite(solo_tokens) == solo_tokens

    def test_prosa_normal_no_cambia(self) -> None:
        pregunta = "¿cómo funciona la reemisión de boletos?"

        assert dense_query_rewrite(pregunta) == pregunta


class TestCoverage:
    def test_anchor_cubierto_por_la_evidencia(self) -> None:
        anchor = extract_anchors("el rango 14-22")[0]

        assert anchor_covered(anchor, "Field 14-22 Advance Reservation First")
        assert not anchor_covered(anchor, "Field 64-67 Exception Time")

    def test_anchor_needles_planas(self) -> None:
        anchors = extract_anchors("rango 14-22 y código R007D03E000")
        needles = anchor_needles(anchors)

        assert "14-22" in needles
        assert "R007D03E000" in needles


class TestAnchorsV2:
    """Siglas y máscaras: el caso FCLAS &&&F no tenía ninguna aguja."""

    def test_sigla_en_mayusculas_es_un_anchor(self) -> None:
        anchors = extract_anchors("qué significa FCLAS en el Record 2")

        assert any(a.kind == "sigla" and a.value == "FCLAS" for a in anchors)

    def test_siglas_tecnicas_no_son_anchors(self) -> None:
        anchors = extract_anchors("genera un PDF desde la API con JSON")

        assert not [a for a in anchors if a.kind == "sigla"]

    def test_mascara_con_comodines_es_un_anchor(self) -> None:
        anchors = extract_anchors("FCLAS &&&F exige que el fare basis cumpla")

        mascaras = [a for a in anchors if a.kind == "mascara"]
        assert mascaras and mascaras[0].value == "&&&F"

    def test_html_escapado_se_desescapa(self) -> None:
        anchors = extract_anchors("FCLAS &amp;&amp;&amp;F")

        assert any(a.kind == "mascara" and a.value == "&&&F" for a in anchors)

    def test_la_mascara_sale_del_denso_y_la_sigla_queda(self) -> None:
        limpio = dense_query_rewrite("FCLAS &&&F")

        assert "&&&F" not in limpio
        assert "FCLAS" in limpio

    def test_mascara_cubierta_por_la_evidencia(self) -> None:
        anchor = next(a for a in extract_anchors("FCLAS &&&F") if a.kind == "mascara")

        assert anchor_covered(anchor, "Fare Class &&&F matches the fourth character")
        assert not anchor_covered(anchor, "Fare Class *** matches")

    def test_pregunta_en_prosa_con_interrogacion_no_es_mascara(self) -> None:
        anchors = extract_anchors("¿qué significa esto?")

        assert not [a for a in anchors if a.kind == "mascara"]


class TestCoverageNoteConAnchors:
    def test_coverage_note_lista_anchors_faltantes(self) -> None:
        from src.intelligence.response.entities import coverage_note

        note = coverage_note("qué significa FCLAS &&&F", "texto sin nada relevante")

        assert "FCLAS" in note
        assert "&&&F" in note

    def test_coverage_note_vacia_si_la_evidencia_cubre(self) -> None:
        from src.intelligence.response.entities import coverage_note

        note = coverage_note(
            "qué significa FCLAS &&&F",
            "FCLAS es el campo de fare class. &&&F es un patrón posicional.",
        )

        assert note == ""
