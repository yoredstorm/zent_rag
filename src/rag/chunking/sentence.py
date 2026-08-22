# =============================================================================
# SentenceChunker — agrupa oraciones hasta chunk_size
# =============================================================================
from __future__ import annotations

from src.rag.chunking.base import ChunkingStrategy, merge_pieces, split_sentences


class SentenceChunker(ChunkingStrategy):
    """Chunking por oraciones agrupadas hasta el tamaño máximo."""

    def chunk(self, text: str) -> list[str]:
        if not text:
            return []
        return merge_pieces(split_sentences(text), self.chunk_size, self.chunk_overlap)
