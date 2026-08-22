# =============================================================================
# RecursiveChunker — markdown-aware, parte por secciones semánticas
# =============================================================================
# Prioridad de partición:
#   1. Headings (#/##/###) → secciones (los chunks heredan el heading_path)
#   2. Tablas markdown y bloques de código fenced = unidades atómicas
#   3. Párrafos (líneas en blanco)
#   4. Oraciones
# Cada nivel mergea hasta chunk_size con overlap; si una unidad excede
# chunk_size, se particiona por caracteres (hard split).
# =============================================================================
from __future__ import annotations

import re

from src.rag.chunking.base import (
    ChunkingStrategy,
    _slice_with_overlap,
    merge_pieces,
    split_sentences,
)

_FENCE_RE = re.compile(r"^```", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def _is_table_line(line: str) -> bool:
    return bool(_TABLE_ROW_RE.match(line))


def _group_blocks(lines: list[str]) -> list[str]:
    """Agrupa líneas en bloques: tablas y fences atómicos; párrafos por línea en blanco."""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current:
            blocks.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            current.append(line.rstrip())
            if not in_fence:  # cierre del fence
                flush()
            continue
        if in_fence:
            current.append(line.rstrip())
            continue
        if not line.strip():
            flush()
            continue
        if _is_table_line(line):
            # acumular filas de tabla consecutivas como un bloque
            if current and not _is_table_line(current[-1]):
                flush()
            current.append(line.rstrip())
            continue
        current.append(line.rstrip())
    flush()
    return blocks


class RecursiveChunker(ChunkingStrategy):
    """Chunking recursivo markdown-aware con headings como fronteras."""

    def chunk(self, text: str) -> list[str]:
        if not text:
            return []
        sections = self._split_by_headings(text)
        chunks: list[str] = []
        for section in sections:
            chunks.extend(self._chunk_section(section))
        # Merge final con overlap entre secciones pequeñas
        return merge_pieces(chunks, self.chunk_size, self.chunk_overlap)

    @staticmethod
    def _split_by_headings(text: str) -> list[str]:
        """Parte el texto por headings markdown (##, ###...)."""
        lines = text.splitlines()
        sections: list[str] = []
        current: list[str] = []
        for line in lines:
            if re.match(r"^#{1,6}\s+", line):
                if current:
                    sections.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current))
        return [s for s in sections if s.strip()]

    def _chunk_section(self, section: str) -> list[str]:
        if len(section) <= self.chunk_size:
            return [section.strip()]
        blocks = _group_blocks(section.splitlines())
        # Partir por párrafos/bloques
        paragraphs: list[str] = []
        for block in blocks:
            if len(block) <= self.chunk_size:
                paragraphs.append(block)
            else:
                # Bloque gigante (tabla/fence largo): dividir por oraciones
                # y, si sigue excediendo, hard-split por caracteres.
                sentences = split_sentences(block)
                for sentence in sentences:
                    if len(sentence) > self.chunk_size:
                        paragraphs.extend(
                            _slice_with_overlap(
                                sentence, self.chunk_size, self.chunk_overlap
                            )
                        )
                    else:
                        paragraphs.append(sentence)
        return merge_pieces(paragraphs, self.chunk_size, self.chunk_overlap)
