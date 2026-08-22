# =============================================================================
# Chunking Strategies — Estrategias de partición de texto para RAG
# =============================================================================
# Cada estrategia parte texto normalizado (idealmente Markdown) en chunks
# dentro de chunk_size con chunk_overlap de solape.
#
# - fixed:     ventana de caracteres con overlap (compat con _chunk_text)
# - recursive: markdown-aware — parte por headings (#/##/###), trata tablas
#              y bloques de código como unidades atómicas, luego párrafos y
#              oraciones hasta encajar en chunk_size
# - sentence:  agrupa oraciones hasta chunk_size
# =============================================================================
from __future__ import annotations

import re
from abc import ABC, abstractmethod


class ChunkingStrategy(ABC):
    """Contrato para estrategias de chunking."""

    def __init__(self, chunk_size: int = 1200, chunk_overlap: int = 150) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be >= 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be < chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @abstractmethod
    def chunk(self, text: str) -> list[str]: ...


# -----------------------------------------------------------------------------
# Utilidades compartidas
# -----------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Partición simple por oraciones (sin NLP pesado)."""
    parts = [p.strip() for p in _SENTENCE_RE.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def merge_pieces(pieces: list[str], max_size: int, overlap: int) -> list[str]:
    """Agrupa piezas en chunks de max_size caracteres con overlap."""
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        if not current:
            current = piece
            continue
        candidate = f"{current}\n\n{piece}"
        if len(candidate) <= max_size:
            current = candidate
        else:
            chunks.append(current)
            # overlap: arrastrar la cola del chunk anterior
            if overlap > 0:
                tail = current[-overlap:]
                current = f"{tail}\n\n{piece}" if len(piece) + overlap <= max_size else piece
            else:
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _slice_with_overlap(text: str, max_size: int, overlap: int) -> list[str]:
    """Ventana fija de caracteres con overlap (estrategia 'fixed')."""
    if not text:
        return []
    if len(text) <= max_size:
        return [text]
    chunks: list[str] = []
    step = max_size - overlap
    start = 0
    while start < len(text):
        end = min(start + max_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += step
    return chunks
