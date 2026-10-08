# =============================================================================
# Runtime Dependencies — composition root compartido entre API y runtime
# =============================================================================
# Las capas nuevas (decision/, runtime/) no importan src.api (guard de
# arquitectura). Este módulo es el punto único donde se instancian los
# adaptadores que ambas capas comparten; src.api.deps los re-exporta para
# FastAPI y el resto del código. Los imports de adaptadores son perezosos:
# el runtime no carga Qdrant/LiteLLM hasta que se piden.
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings
from src.core.ports import EmbeddingProvider, LLMProvider, VectorStore

# -----------------------------------------------------------------------------
# Singletons de infraestructura (inicialización lazy, thread-safe con FastAPI)
# -----------------------------------------------------------------------------
_vector_store: VectorStore | None = None
_llm_provider: LLMProvider | None = None
_embedding_provider: EmbeddingProvider | None = None
_structured_retriever: object | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        from src.infrastructure.qdrant.vector_store import QdrantVectorStore

        _vector_store = QdrantVectorStore()
    return _vector_store


def get_llm_provider() -> LLMProvider:
    global _llm_provider
    if _llm_provider is None:
        from src.infrastructure.llm.provider import LiteLLMProvider

        _llm_provider = LiteLLMProvider()
    return _llm_provider


def get_embedding_provider() -> EmbeddingProvider:
    global _embedding_provider
    if _embedding_provider is None:
        from src.infrastructure.llm.provider import LiteLLMProvider

        _embedding_provider = LiteLLMProvider()
    return _embedding_provider


def get_knowledge_retriever():
    """Retriever canónico del Knowledge OS.

    Búsqueda multi-representación sobre el MISMO índice (denso + léxico +
    híbrido) con reranker y ensamblado parent/child desde el árbol
    estructurado. Es el único camino de retrieval productivo.
    """
    global _structured_retriever
    if _structured_retriever is None:
        from src.rag.retrieval.builders import ContextBuilder
        from src.rag.retrieval.structured import StructuredRetriever

        settings = get_settings()
        vector_store = get_vector_store()
        reranker = None
        if settings.RAG_RERANK_ENABLED:
            from src.rag.reranking import base as rerank_base
            from src.rag.reranking.cross_encoder import CrossEncoderReranker  # noqa: F401 (register)
            from src.rag.reranking.reranker import LLMReranker  # noqa: F401 (register)

            reranker = rerank_base.get_reranker(
                settings.RAG_RERANKER or "llm",
                llm_provider=get_llm_provider(),
            )
        _structured_retriever = StructuredRetriever(
            vector_store=vector_store,
            lexical_store=vector_store,
            hybrid_store=vector_store,
            reranker=reranker,
            context_builder=ContextBuilder(max_context_tokens=8000),
        )
    return _structured_retriever


__all__ = [
    "get_embedding_provider",
    "get_knowledge_retriever",
    "get_llm_provider",
    "get_vector_store",
]
