# =============================================================================
# Quién decide el parseo PDF. El parser no lee flags.
# =============================================================================
from __future__ import annotations

from src.knowledge.structure.pdf_parser import PdfParseOptions


def production_pdf_options(settings: object) -> PdfParseOptions:
    """Shadow no enciende columnas en el documento que se indexa."""
    enabled = bool(getattr(settings, "DOCUMENT_UNDERSTANDING_ENABLED", False))
    layout = bool(getattr(settings, "DOCUMENT_UNDERSTANDING_LAYOUT", True))
    minimum = float(getattr(settings, "COLUMN_MIN_CONFIDENCE", 0.72) or 0.72)
    return PdfParseOptions(
        column_detection=bool(enabled and layout),
        column_min_confidence=minimum,
    )


def shadow_pdf_options(settings: object) -> PdfParseOptions:
    """Parseo de comparación. No se chunkear ni se embebe."""
    layout = bool(getattr(settings, "DOCUMENT_UNDERSTANDING_LAYOUT", True))
    minimum = float(getattr(settings, "COLUMN_MIN_CONFIDENCE", 0.72) or 0.72)
    return PdfParseOptions(column_detection=bool(layout), column_min_confidence=minimum)
