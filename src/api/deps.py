# =============================================================================
# Dependency Injection — Wiring de Clean Architecture para FastAPI
# =============================================================================
# FastAPI usa Depends() para inyectar dependencias en los handlers.
# Cada dependencia retorna una implementación concreta de un puerto (ABC).
# Esto permite cambiar la infraestructura sin tocar el dominio ni la API.
#
# Ejemplo: Si mañana migramos de Qdrant a Pinecone, solo cambiamos
# get_vector_store(), el resto del código no se entera.
# =============================================================================
from __future__ import annotations

from src.application.orchestrator import RAGOrchestrator
from src.config import get_settings
from src.domain.ports import (
    CacheProvider,
    EmbeddingProvider,
    LLMProvider,
    TenantRepository,
    UserRepository,
    VectorStore,
)
from src.infrastructure.cache import RedisCache
from src.infrastructure.llm_provider import LiteLLMProvider
from src.infrastructure.relational_db import (
    PostgresTenantRepository,
    PostgresUserRepository,
)
from src.infrastructure.sql_expert import PostgresSqlExpert
from src.infrastructure.vector_store import QdrantVectorStore

# -----------------------------------------------------------------------------
# Singletons de infraestructura (inicialización lazy, thread-safe con FastAPI)
# -----------------------------------------------------------------------------
_tenant_repo: TenantRepository | None = None
_user_repo: UserRepository | None = None
_vector_store: VectorStore | None = None
_llm_provider: LLMProvider | None = None
_embedding_provider: EmbeddingProvider | None = None
_cache_provider: CacheProvider | None = None
_orchestrator: RAGOrchestrator | None = None


def get_tenant_repo() -> TenantRepository:
    global _tenant_repo
    if _tenant_repo is None:
        _tenant_repo = PostgresTenantRepository()
    return _tenant_repo


def get_user_repo() -> UserRepository:
    global _user_repo
    if _user_repo is None:
        _user_repo = PostgresUserRepository()
    return _user_repo


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = QdrantVectorStore()
    return _vector_store


def get_llm_provider() -> LLMProvider:
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LiteLLMProvider()
    return _llm_provider


def get_embedding_provider() -> EmbeddingProvider:
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = LiteLLMProvider()
    return _embedding_provider


def get_cache_provider() -> CacheProvider:
    global _cache_provider
    if _cache_provider is None:
        _cache_provider = RedisCache()
    return _cache_provider


def get_rag_orchestrator() -> RAGOrchestrator:
    """Inyecta el orquestador RAG con todas sus dependencias cableadas."""
    global _orchestrator
    if _orchestrator is None:
        settings = get_settings()
        sql_expert = None
        if settings.RAG_SQL_EXPERT_ENABLED:
            sql_expert = PostgresSqlExpert(llm_provider=get_llm_provider())
        _orchestrator = RAGOrchestrator(
            tenant_repo=get_tenant_repo(),
            vector_store=get_vector_store(),
            llm_provider=get_llm_provider(),
            embedding_provider=get_embedding_provider(),
            cache_provider=get_cache_provider(),
            score_threshold=settings.RAG_SCORE_THRESHOLD,
            conv_ttl_seconds=settings.RAG_CONVERSATION_TTL_SECONDS,
            sql_expert=sql_expert,
            # query_store=None,  # Se activará cuando la tabla de auditoría esté lista
        )
    return _orchestrator
