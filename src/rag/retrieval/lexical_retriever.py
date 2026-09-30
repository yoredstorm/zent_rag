# =============================================================================
# LexicalRetriever — búsqueda lexical pura (BM25 / sparse vectors)
# =============================================================================
from __future__ import annotations

from src.core.domain.entities import RetrievalContext
from src.core.ports import LexicalStore
from src.rag.retrieval.base import Retriever
from src.rag.retrieval.classify import normalize_query
from src.rag.retrieval.models import RetrievalQuery


class LexicalRetriever(Retriever):
    """Implementación lexical del Retriever sobre el puerto LexicalStore."""

    def __init__(self, lexical_store: LexicalStore) -> None:
        self._store = lexical_store

    async def retrieve(self, query: RetrievalQuery) -> RetrievalContext:
        # Términos de los canales (campos, valores, conceptos): suman señal a la
        # pata léxica; el tokenizador aguas abajo los normaliza.
        text = query.query or ""
        terms = [str(term).strip() for term in (query.lexical_terms or []) if str(term or "").strip()]
        if terms:
            text = " ".join([text, *terms[:16]])
        normalized = normalize_query(text)
        return await self._store.search_sparse(
            organization_id=query.organization_id,
            query_text=normalized,
            top_k=query.effective_top_k or query.top_k,
            filters=query.filters or None,
            exclude_filters=query.exclude_filters or None,
            score_threshold=query.score_threshold,
            role=query.role,
            user_id=query.user_id,
            groups=query.groups,
            knowledge_base_id=query.knowledge_base_id,
            workspace_id=query.workspace_id,
            source_ids=query.source_ids or None,
        )
