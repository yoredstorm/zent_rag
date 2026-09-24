"""Verificación determinista de fechas y años contra la evidencia."""

from src.intelligence.response.entities import (
    figures_note,
    stated_dates,
    ungrounded_figures,
)

# Evidencia real de la guía Cat31/33 que está en la KB del usuario.
EVIDENCIA = (
    "Implementation date 30 June 2024. Original ticket issue date 15 May 2024. "
    "NEW Category 31 system assumption in effect on 10 July 2024 applies. "
    "NEW Category 33 system assumption in effect on 01 August 2024 applies. "
    "Ticket refund request 10 August 2024."
)

RESPUESTA_ALUSINADA = (
    "A partir del 12 de julio de 2026, la suposición por defecto del sistema "
    "cambiará para la Categoría 31."
)


class TestStatedDates:
    def test_reconoce_los_formatos_reales(self) -> None:
        canonicos = {item.canonical for item in stated_dates(
            "12 de julio de 2026 · July 12, 2026 · 2026-07-12 · 12/07/2026"
        )}
        assert canonicos == {"2026-07-12"}

    def test_ignora_fechas_invalidas(self) -> None:
        assert stated_dates("32 de julio de 2026") == []

    def test_evidencia_real_del_usuario(self) -> None:
        canonicos = {item.canonical for item in stated_dates(EVIDENCIA)}
        assert "2024-07-10" in canonicos
        assert "2024-08-01" in canonicos


class TestUngroundedFigures:
    def test_fecha_inventada_se_marca(self) -> None:
        """Caso real: la guía dice 10 July 2024 y la respuesta dijo 12/07/2026."""
        figures = ungrounded_figures(RESPUESTA_ALUSINADA, EVIDENCIA)
        assert any("2026" in figure for figure in figures)

    def test_fecha_respaldada_no_se_marca(self) -> None:
        respuesta = "El cambio entra en vigor el 10 de julio de 2024."
        assert ungrounded_figures(respuesta, EVIDENCIA) == []

    def test_anio_respaldado_no_se_marca(self) -> None:
        respuesta = "La implementación fue en 2024 y afecta la Categoría 31."
        assert ungrounded_figures(respuesta, EVIDENCIA) == []

    def test_anio_del_usuario_no_se_marca(self) -> None:
        """Si el usuario nombra el año, repetirlo no es inventar."""
        figures = ungrounded_figures(
            "En 2026 todavía no aplica.", EVIDENCIA, "¿aplica en 2026?"
        )
        assert figures == []

    def test_sin_fechas_no_hay_nada_que_marcar(self) -> None:
        assert ungrounded_figures("La Categoría 31 controla los cambios.", EVIDENCIA) == []

    def test_iso_y_guiones(self) -> None:
        figures = ungrounded_figures("Vence el 2027-03-05.", EVIDENCIA)
        assert figures == ["2027-03-05"]

    def test_nota_de_correccion_menciona_las_figuras(self) -> None:
        figures = ungrounded_figures(RESPUESTA_ALUSINADA, EVIDENCIA)
        nota = figures_note(figures)
        assert "2026" in nota
        assert "no afirmes" in nota.lower()


class TestHelperDelCaminoRag:
    """El chat (`/query`) usa el mismo chequeo sobre las evidencias recuperadas."""

    def test_toma_el_contenido_de_las_evidencias(self) -> None:
        from dataclasses import dataclass

        from src.agents.runtime.orchestrator import _ungrounded_figures

        @dataclass
        class Item:
            content: str

        figures = _ungrounded_figures(
            "Aplica desde el 12 de julio de 2026.",
            [Item(content="NEW Category 31 system assumption in effect on 10 July 2024")],
            "¿desde cuándo aplica?",
        )
        assert any("2026" in figure for figure in figures)

    def test_respuesta_respaldada_no_marca_nada(self) -> None:
        from dataclasses import dataclass

        from src.agents.runtime.orchestrator import _ungrounded_figures

        @dataclass
        class Item:
            content: str

        assert (
            _ungrounded_figures(
                "Aplica desde el 10 de julio de 2024.",
                [Item(content="in effect on 10 July 2024")],
                "¿desde cuándo aplica?",
            )
            == []
        )
