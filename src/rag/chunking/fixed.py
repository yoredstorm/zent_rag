# =============================================================================
# FixedSizeChunker — ventana de caracteres con overlap
# =============================================================================
from __future__ import annotations

from src.rag.chunking.base import ChunkingStrategy, _slice_with_overlap


class FixedSizeChunker(ChunkingStrategy):
    """Chunking por tamaño fijo de caracteres (semántica de _chunk_text)."""

    def chunk(self, text: str) -> list[str]:
        return _slice_with_overlap(text or "", self.chunk_size, self.chunk_overlap)
