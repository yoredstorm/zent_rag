# Retrieval Engine — motor híbrido de recuperación (sin infraestructura)
from src.rag.retrieval.base import Retriever  # noqa: F401
from src.rag.retrieval.builders import ContextBuilder  # noqa: F401
from src.rag.retrieval.classify import (  # noqa: F401
    classify_query,
    detect_language,
    normalize_query,
)
from src.rag.retrieval.config import (  # noqa: F401
    RetrievalConfig,
    resolve_retrieval_config,
)
from src.rag.retrieval.hybrid import HybridRetriever  # noqa: F401
from src.rag.retrieval.lexical_retriever import LexicalRetriever  # noqa: F401
from src.rag.retrieval.vector_retriever import VectorRetriever  # noqa: F401

__all__ = [
    "ContextBuilder",
    "HybridRetriever",
    "LexicalRetriever",
    "RetrievalConfig",
    "Retriever",
    "VectorRetriever",
    "classify_query",
    "detect_language",
    "normalize_query",
    "resolve_retrieval_config",
]
