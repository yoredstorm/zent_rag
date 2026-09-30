# =============================================================================
# ContextBuilder — recorte del contexto al presupuesto de tokens
# =============================================================================
# Cambio 2026-09: la selección ya no es sólo por score. MUST_KEEP (evidencia
# exacta) entra siempre y no lo expulsa un cosine mayor; dentro del resto se
# mantiene el orden por score histórico. El presupuesto puede venir por request
# (`context_token_budget`); sin él se usa el del constructor.
# =============================================================================
from __future__ import annotations

from src.core.domain.entities import RetrievalChunk
from src.rag.longcontext.must_keep import is_must_keep

# Aproximación conservadora de caracteres por token usada históricamente
# en el orchestrator para el presupuesto de contexto.
_CHARS_PER_TOKEN = 4

#: Lo que se le sirve al modelo por chunk está acotado (el tool corta a ~1200
#: caracteres): contar el contenido completo de un chunk padre de una sección
#: entera hacía que UN solo chunk se comiera el presupuesto y expulsara al resto.
_COST_CAP_CHARS = 2000

#: MUST_KEEP se cuenta completo (hasta este tope duro): es la evidencia que
#: explica la pregunta, no puede entrar cortada ni expulsada.
_MUST_KEEP_COST_CAP_CHARS = 8000


class ContextBuilder:
    """Ensambla el contexto final respetando el presupuesto de tokens."""

    def __init__(self, max_context_tokens: int) -> None:
        self._max_context_tokens = max_context_tokens

    def fit_budget(
        self,
        chunks: list[RetrievalChunk],
        *,
        max_context_tokens: int | None = None,
    ) -> list[RetrievalChunk]:
        """Mantiene los chunks relevantes dentro del presupuesto.

        Prioridad 0: MUST_KEEP (entra siempre, cuenta casi completo).
        Resto: score descendente, con el cap histórico de 2000 chars por chunk.
        Conserva el orden relativo original entre los seleccionados.
        """
        if not chunks:
            return chunks
        budget = (
            int(max_context_tokens)
            if max_context_tokens is not None and int(max_context_tokens) > 0
            else int(self._max_context_tokens)
        )
        budget_chars = max(int(budget * _CHARS_PER_TOKEN), 200)
        selected_ids: set = set()
        used = 0
        for chunk in chunks:
            if not is_must_keep(chunk):
                continue
            cost = min(len(chunk.content or ""), _MUST_KEEP_COST_CAP_CHARS)
            selected_ids.add(chunk.document_id)
            used += cost
        ordered = sorted(
            (c for c in chunks if c.document_id not in selected_ids),
            key=lambda c: c.score,
            reverse=True,
        )
        if selected_ids and used >= budget_chars:
            # MUST_KEEP ya consumió el presupuesto: no se agrega nada más.
            return [c for c in chunks if c.document_id in selected_ids]
        added = 0
        for chunk in ordered:
            cost = min(len(chunk.content or ""), _COST_CAP_CHARS)
            if added and used + cost > budget_chars:
                continue
            selected_ids.add(chunk.document_id)
            used += cost
            added += 1
            if used >= budget_chars:
                break
        return [c for c in chunks if c.document_id in selected_ids]


__all__ = ["ContextBuilder"]
