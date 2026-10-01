# =============================================================================
# Quién decide el parseo PDF. El parser no lee flags.
# =============================================================================
from __future__ import annotations

from src.knowledge.structure.pdf_parser import PdfParseOptions


def production_pdf_options(settings: object) -> PdfParseOptions:
    """Parseo productivo del documento que se indexa y se compila."""
    layout = bool(getattr(settings, "DOCUMENT_UNDERSTANDING_LAYOUT", True))
    minimum = float(getattr(settings, "COLUMN_MIN_CONFIDENCE", 0.72) or 0.72)
    return PdfParseOptions(
        column_detection=layout,
        column_min_confidence=minimum,
    )

