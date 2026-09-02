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

# Connector Platform: registra plugins builtin + entry points al importar.
import src.connectors.plugin.plugins  # noqa: F401 (registro de builtins)
from src.agents.runtime.orchestrator import RAGOrchestrator
from src.agents.tools.sql_expert_postgres import PostgresSqlExpert
from src.connectors.plugin.registry import load_entry_points, load_plugin_modules
from src.core.config import get_settings
from src.core.ports import (
    AgentRepository,
    AgentVersionRepository,
    ApiKeyRepository,
    AuditLogRepository,
    CacheProvider,
    ConnectorRepository,
    DeploymentRepository,
    DocumentRegistryRepository,
    EmbeddingProvider,
    IngestionJobRepository,
    KnowledgeBaseRepository,
    LLMProvider,
    MembershipRepository,
    OrganizationRepository,
    ProjectRepository,
    SourceRepository,
    SyncStateRepository,
    UserRepository,
    VectorStore,
    WorkspaceRepository,
)
from src.infrastructure.postgres.knowledge_repos import (
    PostgresDocumentRegistryRepository,
    PostgresIngestionJobRepository,
    PostgresSourceRepository,
    PostgresSyncStateRepository,
)
from src.infrastructure.postgres.relational_db import (
    PostgresAgentRepository,
    PostgresAgentVersionRepository,
    PostgresApiKeyRepository,
    PostgresAuditLogRepository,
    PostgresConnectorRepository,
    PostgresDeploymentRepository,
    PostgresKnowledgeBaseRepository,
    PostgresMembershipRepository,
    PostgresOrganizationRepository,
    PostgresProjectRepository,
    PostgresUserRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.qdrant.vector_store import QdrantVectorStore
from src.infrastructure.redis.cache import RedisCache

load_entry_points()
load_plugin_modules()

# -----------------------------------------------------------------------------
# Singletons de infraestructura (inicialización lazy, thread-safe con FastAPI)
# -----------------------------------------------------------------------------
_organization_repo: OrganizationRepository | None = None
_user_repo: UserRepository | None = None
_membership_repo: MembershipRepository | None = None
_api_key_repo: ApiKeyRepository | None = None
_project_repo: ProjectRepository | None = None
_kb_repo: KnowledgeBaseRepository | None = None
_agent_repo: AgentRepository | None = None
_agent_version_repo: AgentVersionRepository | None = None
_deployment_repo: DeploymentRepository | None = None
_connector_repo: ConnectorRepository | None = None
_audit_repo: AuditLogRepository | None = None
_source_repo: SourceRepository | None = None
_job_repo: IngestionJobRepository | None = None
_sync_state_repo: SyncStateRepository | None = None
_doc_registry_repo: DocumentRegistryRepository | None = None
_workspace_repo: WorkspaceRepository | None = None
_vector_store: VectorStore | None = None
_llm_provider: LLMProvider | None = None
_embedding_provider: EmbeddingProvider | None = None
_cache_provider: CacheProvider | None = None
_orchestrator: RAGOrchestrator | None = None
_knowledge_engine = None


def get_organization_repo() -> OrganizationRepository:
    global _organization_repo
    if _organization_repo is None:
        _organization_repo = PostgresOrganizationRepository()
    return _organization_repo


def get_user_repo() -> UserRepository:
    global _user_repo
    if _user_repo is None:
        _user_repo = PostgresUserRepository()
    return _user_repo


def get_membership_repo() -> MembershipRepository:
    global _membership_repo
    if _membership_repo is None:
        _membership_repo = PostgresMembershipRepository()
    return _membership_repo


def get_api_key_repo() -> ApiKeyRepository:
    global _api_key_repo
    if _api_key_repo is None:
        _api_key_repo = PostgresApiKeyRepository()
    return _api_key_repo


def get_project_repo() -> ProjectRepository:
    global _project_repo
    if _project_repo is None:
        _project_repo = PostgresProjectRepository()
    return _project_repo


def get_kb_repo() -> KnowledgeBaseRepository:
    global _kb_repo
    if _kb_repo is None:
        _kb_repo = PostgresKnowledgeBaseRepository()
    return _kb_repo


def get_agent_repo() -> AgentRepository:
    global _agent_repo
    if _agent_repo is None:
        _agent_repo = PostgresAgentRepository()
    return _agent_repo


def get_agent_version_repo() -> AgentVersionRepository:
    global _agent_version_repo
    if _agent_version_repo is None:
        _agent_version_repo = PostgresAgentVersionRepository()
    return _agent_version_repo


def get_workspace_repo() -> WorkspaceRepository:
    global _workspace_repo
    if _workspace_repo is None:
        _workspace_repo = PostgresWorkspaceRepository()
    return _workspace_repo


def get_deployment_repo() -> DeploymentRepository:
    global _deployment_repo
    if _deployment_repo is None:
        _deployment_repo = PostgresDeploymentRepository()
    return _deployment_repo


def get_connector_repo() -> ConnectorRepository:
    global _connector_repo
    if _connector_repo is None:
        _connector_repo = PostgresConnectorRepository()
    return _connector_repo


def get_audit_repo() -> AuditLogRepository:
    global _audit_repo
    if _audit_repo is None:
        _audit_repo = PostgresAuditLogRepository()
    return _audit_repo


def get_source_repo() -> SourceRepository:
    global _source_repo
    if _source_repo is None:
        _source_repo = PostgresSourceRepository()
    return _source_repo


def get_job_repo() -> IngestionJobRepository:
    global _job_repo
    if _job_repo is None:
        _job_repo = PostgresIngestionJobRepository()
    return _job_repo


def get_sync_state_repo() -> SyncStateRepository:
    global _sync_state_repo
    if _sync_state_repo is None:
        _sync_state_repo = PostgresSyncStateRepository()
    return _sync_state_repo


def get_doc_registry_repo() -> DocumentRegistryRepository:
    global _doc_registry_repo
    if _doc_registry_repo is None:
        _doc_registry_repo = PostgresDocumentRegistryRepository()
    return _doc_registry_repo


def get_knowledge_engine():
    """Inyecta el motor de ingestion de la Knowledge Platform."""
    global _knowledge_engine
    if _knowledge_engine is None:
        from src.knowledge.engine.service import KnowledgeIngestionEngine

        _knowledge_engine = KnowledgeIngestionEngine(
            job_repo=get_job_repo(),
            sync_state_repo=get_sync_state_repo(),
            doc_registry_repo=get_doc_registry_repo(),
            kb_repo=get_kb_repo(),
            source_repo=get_source_repo(),
            vector_store=get_vector_store(),
            embedding_provider=get_embedding_provider(),
        )
    return _knowledge_engine


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
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


def get_cache_provider() -> CacheProvider:
    global _cache_provider
    if _cache_provider is None:
        _cache_provider = RedisCache()
    return _cache_provider


_retriever: object | None = None


def get_retriever():
    """Ensambla el motor de retrieval (HybridRetriever) con reranker por config.

    El QdrantVectorStore implementa VectorStore + LexicalStore + HybridStore;
    el motor decide la pata según la estrategia del tenant. RAG_RERANK_ENABLED
    es el interruptor maestro del reranker; RAG_RERANKER elige implementación
    (llm | cross_encoder; vacío = llm para preservar el comportamiento previo).
    """
    global _retriever
    if _retriever is None:
        settings = get_settings()
        from src.rag.retrieval.builders import ContextBuilder
        from src.rag.retrieval.hybrid import HybridRetriever

        vector_store = get_vector_store()

        reranker = None
        if settings.RAG_RERANK_ENABLED:
            from src.rag.reranking import base as rerank_base
            from src.rag.reranking.cross_encoder import CrossEncoderReranker  # noqa: F401 (register)
            from src.rag.reranking.reranker import LLMReranker  # noqa: F401 (register)

            name = settings.RAG_RERANKER or "llm"
            reranker = rerank_base.get_reranker(
                name, llm_provider=get_llm_provider()
            )

        _retriever = HybridRetriever(
            vector_store=vector_store,
            lexical_store=vector_store,
            hybrid_store=vector_store,
            reranker=reranker,
            context_builder=ContextBuilder(
                max_context_tokens=settings.RAG_MAX_CONTEXT_TOKENS
            ),
        )
    return _retriever


def get_rag_orchestrator() -> RAGOrchestrator:
    """Inyecta el orquestador RAG con todas sus dependencias cableadas."""
    global _orchestrator
    if _orchestrator is None:
        settings = get_settings()
        sql_expert = get_sql_expert()
        sql_router = None
        if settings.RAG_SQL_EXPERT_ENABLED:
            from src.agents.tools.sql_router import SqlIntentRouter

            sql_router = SqlIntentRouter(llm_provider=get_llm_provider())
        reranker = None
        if settings.RAG_RERANK_ENABLED:
            from src.rag.reranking.reranker import LLMReranker
            reranker = LLMReranker(llm_provider=get_llm_provider())
        lazy_ingestion = None
        if settings.RAG_LAZY_INGESTION_ENABLED:
            from src.connectors.sql.ingestion import PostgresIngestionService
            lazy_ingestion = PostgresIngestionService(
                get_vector_store(),
                get_embedding_provider(),
                get_cache_provider(),
            )
        _orchestrator = RAGOrchestrator(
            organization_repo=get_organization_repo(),
            vector_store=get_vector_store(),
            llm_provider=get_llm_provider(),
            embedding_provider=get_embedding_provider(),
            cache_provider=get_cache_provider(),
            score_threshold=settings.RAG_SCORE_THRESHOLD,
            conv_ttl_seconds=settings.RAG_CONVERSATION_TTL_SECONDS,
            sql_expert=sql_expert,
            max_context_tokens=settings.RAG_MAX_CONTEXT_TOKENS,
            reranker=reranker,
            rerank_top_n=settings.RAG_RERANK_TOP_N,
            lazy_ingestion=lazy_ingestion,
            retriever=get_retriever(),
            sql_router=sql_router,
        )
    return _orchestrator


_sql_expert: object | None = None


def get_sql_expert():
    """Singleton del SQL Expert (compartido por RAG orchestrator y Agent Runtime)."""
    global _sql_expert
    if _sql_expert is None:
        settings = get_settings()
        _sql_expert = PostgresSqlExpert(
            llm_provider=get_llm_provider(),
            cache=get_cache_provider(),
        )
        _ = settings.RAG_SQL_EXPERT_ENABLED  # el singleton no depende del flag
    return _sql_expert


_agent_runtime: object | None = None


def get_agent_runtime():
    """Ensambla el Agent Runtime con tools builtin + verticales cargadas."""
    global _agent_runtime
    if _agent_runtime is None:
        from src.agents.runtime.agent_runtime import AgentRuntime
        from src.agents.tools.registry import load_tool_modules
        from src.agents.tools.tools_builtin import register_builtin_tools

        register_builtin_tools(
            retriever=get_retriever(),
            sql_expert=get_sql_expert(),
        )
        load_tool_modules()
        _agent_runtime = AgentRuntime(
            llm_provider=get_llm_provider(),
            cache_provider=get_cache_provider(),
        )
    return _agent_runtime
