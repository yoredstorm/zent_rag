# =============================================================================
# ContextBuilder — recorte del contexto al presupuesto de tokens
# =============================================================================
from __future__ import annotations

from src.core.domain.entities import RetrievalChunk

# Aproximación conservadora de caracteres por token usada históricamente
# en el orchestrator para el presupuesto de contexto.
_CHARS_PER_TOKEN = 4


class ContextBuilder:
    """Ensambla el contexto final respetando RAG_MAX_CONTEXT_TOKENS."""

    def __init__(self, max_context_tokens: int) -> None:
        self._max_context_tokens = max_context_tokens

    def fit_budget(self, chunks: list[RetrievalChunk]) -> list[RetrievalChunk]:
        """Mantiene los chunks de mayor score dentro del presupuesto.

        Conserva el orden relativo original entre los seleccionados
        (mismo comportamiento que el orchestrator original).
        """
        if not chunks:
            return chunks
        budget_chars = max(int(self._max_context_tokens * _CHARS_PER_TOKEN), 1000)
        ordered = sorted(chunks, key=lambda c: c.score, reverse=True)
        selected: list[RetrievalChunk] = []
        used = 0
        for chunk in ordered:
            cost = len(chunk.content or "")
            if selected and used + cost > budget_chars:
                continue
            selected.append(chunk)
            used += cost
            if used >= budget_chars:
                break
        selected_ids = {c.document_id for c in selected}
        return [c for c in chunks if c.document_id in selected_ids]
