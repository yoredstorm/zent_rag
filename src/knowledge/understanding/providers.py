# =============================================================================
# Document Understanding — interfaces opcionales
# =============================================================================
# El parseo básico es determinista. OCR y un modelo de comprensión solo entran
# si alguien inyecta un provider. Ningún proveedor concreto vive aquí.
# =============================================================================
from __future__ import annotations

from typing import Protocol


class PageOcrProvider(Protocol):
    """Reconoce UNA página sin text layer. No se llama para páginas digitales."""

    def recognize_page(
        self,
        *,
        page_number: int,
        page_text: str,
        image: bytes | None = None,
    ) -> str: ...


class DocumentUnderstandingProvider(Protocol):
    """Corrección estructural opcional. No es el parser por defecto.

    Debe devolver solo correcciones. `derived_by` queda en `model` y la
    provenance de esas correcciones es INFERRED, nunca EXTRACTED.
    """

    name: str

    def correct(
        self,
        *,
        raw_text: str,
        layout_blocks: list[dict],
        page_image: bytes | None = None,
    ) -> dict: ...


class ParserProvider(Protocol):
    """Parser intercambiable. El pipeline elige uno y escala solo si la calidad cae."""

    name: str

    def supports(self, mime_type: str) -> bool: ...
