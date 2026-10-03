# =============================================================================
# Knowledge OS — Calidad semántica
# =============================================================================
# Detección de fragmentos, artefactos de layout y trazabilidad de rechazos.
# =============================================================================
from src.knowledge.quality.fragments import (
    TextQuality,
    TextQualityStatus,
    analyze_text_quality,
    completeness_score,
    is_probable_fragment,
    repair_fragmented_parts,
)
from src.knowledge.quality.ingestion import (
    QualityCollector,
    QualityKind,
    severity_for,
)

__all__ = [
    "TextQuality",
    "TextQualityStatus",
    "analyze_text_quality",
    "completeness_score",
    "is_probable_fragment",
    "repair_fragmented_parts",
    "QualityCollector",
    "QualityKind",
    "severity_for",
]
