# =============================================================================
# Chunking Registry — fábrica de estrategias por nombre
# =============================================================================
from __future__ import annotations

from src.rag.chunking.base import ChunkingStrategy
from src.rag.chunking.fixed import FixedSizeChunker
from src.rag.chunking.recursive import RecursiveChunker
from src.rag.chunking.sentence import SentenceChunker

_STRATEGIES: dict[str, type[ChunkingStrategy]] = {
    "fixed": FixedSizeChunker,
    "recursive": RecursiveChunker,
    "sentence": SentenceChunker,
}

DEFAULT_STRATEGY = "fixed"


def available_strategies() -> list[str]:
    return sorted(_STRATEGIES)


def register_strategy(name: str, cls: type[ChunkingStrategy]) -> None:
    _STRATEGIES[name] = cls


def get_chunker(
    strategy: str | None, chunk_size: int = 1200, chunk_overlap: int = 150
) -> ChunkingStrategy:
    name = (strategy or DEFAULT_STRATEGY).strip().lower()
    cls = _STRATEGIES.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown chunking strategy '{name}'. "
            f"Available: {available_strategies()}"
        )
    return cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
