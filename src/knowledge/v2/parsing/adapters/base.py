# =============================================================================
# V2 adapter protocol
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.v2.parsing.context import ParseContext


class ParseError(Exception):
    """Structured parse failed (corrupt bytes, empty extract, missing extra)."""


class StructuredAdapter(ABC):
    """Bytes → StructuredDocument. V1 Normalizer.normalize() is unchanged."""

    name: str
    mime_type: str

    @abstractmethod
    def parse(self, ctx: ParseContext) -> StructuredDocument: ...
