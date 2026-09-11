# =============================================================================
# Knowledge V2 parsing — bytes → StructuredDocument (Phase B)
# =============================================================================
# Parallel to V1 Markdown normalizers. Not wired into KnowledgeIngestionEngine.
# Production callers use parse_structured_if_enabled (None when flag is off).
# =============================================================================
from src.knowledge.v2.parsing.api import (
    ParseError,
    parse_structured,
    parse_structured_if_enabled,
    supported_v2_extensions,
)

__all__ = [
    "ParseError",
    "parse_structured",
    "parse_structured_if_enabled",
    "supported_v2_extensions",
]
