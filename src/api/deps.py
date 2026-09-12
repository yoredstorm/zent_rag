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

from uuid import UUID

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
from src.infrastructure.observability.logging_config import get_logger
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

logger = get_logger(__name__)

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
_knowledge_learning_repo = None
_knowledge_learning_engine = None
_knowledge_score_service = None
_knowledge_graph_service = None
_knowledge_validation_engine = None
_knowledge_evaluation_service = None


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


_corpus_repo: object | None = None


def get_corpus_repo():
    """Repo de KnowledgeCorpus (Phase D slice 2) — workspace-scoped."""
    global _corpus_repo
    if _corpus_repo is None:
        from src.infrastructure.postgres.knowledge_corpora import (
            PostgresKnowledgeCorpusRepository,
        )

        _corpus_repo = PostgresKnowledgeCorpusRepository()
    return _corpus_repo


def get_knowledge_engine():
    """Inyecta el motor de ingestion de la Knowledge Platform.

    El repo de documentos estructurados (Knowledge V2) se activa SOLO con
    RAG_KNOWLEDGE_V2_ENABLED=true; en su ausencia el motor queda idéntico a V1.
    """
    global _knowledge_engine
    if _knowledge_engine is None:
        from src.knowledge.engine.service import KnowledgeIngestionEngine

        structured_repo = None
        summarizer = None
        settings = get_settings()
        if settings.KNOWLEDGE_V2_ENABLED:
            from src.infrastructure.postgres.structured_documents import (
                PostgresStructuredDocumentRepository,
            )

            structured_repo = PostgresStructuredDocumentRepository()
        if settings.KNOWLEDGE_V2_ENABLED and settings.KNOWLEDGE_SUMMARY_MODE == "shadow":
            from src.knowledge.summarize.service import (
                DocumentSummarizer,
                SummarizerConfig,
            )

            summarizer = DocumentSummarizer(
                llm=get_llm_provider(),
                config=SummarizerConfig(
                    model=settings.KNOWLEDGE_SUMMARY_MODEL or None
                ),
            )

        usage_tracker = None
        if settings.KNOWLEDGE_V2_ENABLED:
            from src.knowledge.cost import KnowledgeUsageTracker

            usage_tracker = KnowledgeUsageTracker()

        _knowledge_engine = KnowledgeIngestionEngine(
            job_repo=get_job_repo(),
            sync_state_repo=get_sync_state_repo(),
            doc_registry_repo=get_doc_registry_repo(),
            kb_repo=get_kb_repo(),
            source_repo=get_source_repo(),
            vector_store=get_vector_store(),
            embedding_provider=get_embedding_provider(),
            structured_doc_repo=structured_repo,
            summarizer=summarizer,
            usage_tracker=usage_tracker,
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
_structured_retriever: object | None = None


def get_structured_retriever():
    """Retriever V2 (Knowledge V2, Phase F) — solo lectura, mismo collection.

    Reutiliza el vector/lexical/hybrid store + reranker existentes y el
    ContextBuilder con presupuesto de contexto V2.
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


_intelligence_engine: object | None = None
_intelligence_store: object | None = None
_business_definition_registry: object | None = None
_catalog_store: object | None = None
_catalog_discovery_engine: object | None = None
_semantic_schema_linking: object | None = None
_learning_store: object | None = None
_context_gap_analyzer: object | None = None
_context_advisor: object | None = None
_approval_service: object | None = None
_replay_engine: object | None = None
_spider_service: object | None = None
_revocation_service: object | None = None
_agent_readiness_service: object | None = None
_learning_analytics: object | None = None


def get_learning_store():
    """Store del ciclo gobernado (FASE 25)."""
    global _learning_store
    if _learning_store is None:
        from src.learning.store import PostgresLearningStore

        _learning_store = PostgresLearningStore()
    return _learning_store


def get_context_gap_analyzer():
    """ContextGapAnalyzer (convierte abstenciones en gaps estructurados)."""
    global _context_gap_analyzer
    if _context_gap_analyzer is None:
        from src.learning.gaps import ContextGapAnalyzer

        _context_gap_analyzer = ContextGapAnalyzer(
            get_learning_store(), intelligence_store=get_intelligence_store()
        )
    return _context_gap_analyzer


def get_context_advisor():
    """ContextAdvisor (recomendaciones accionables sobre gaps reales)."""
    global _context_advisor
    if _context_advisor is None:
        from src.learning.advisor import ContextAdvisor

        _context_advisor = ContextAdvisor(
            get_catalog_store(),
            intelligence_store=get_intelligence_store(),
            learning_store=get_learning_store(),
        )
    return _context_advisor


def get_replay_engine():
    """EvaluationReplayService (jobs eval_replay:*)."""
    global _replay_engine
    if _replay_engine is None:
        from src.learning.replay import EvaluationReplayService

        _replay_engine = EvaluationReplayService(
            store=get_learning_store(),
            job_repo=get_job_repo(),
            orchestrator=get_rag_orchestrator(),
        )
    return _replay_engine


def get_approval_service():
    """ApprovalService (registro + disparo de replays)."""
    global _approval_service
    if _approval_service is None:
        from src.core.config import get_settings as _settings
        from src.learning.approvals import ApprovalService

        _approval_service = ApprovalService(
            store=get_learning_store(),
            replay_starter=get_replay_engine().start,
            replay_required=_settings().RAG_LEARNING_REPLAY_REQUIRED,
        )
    return _approval_service


def get_spider_service():
    """Zent Spider (discovery continuo autorizado)."""
    global _spider_service
    if _spider_service is None:
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store
        from src.learning.spider import SpiderService

        _spider_service = SpiderService(
            store=get_learning_store(),
            catalog_store=get_catalog_store(),
            connector_repo=get_connector_repo(),
            secret_store=get_secret_store(),
            intelligence_store=get_intelligence_store(),
            job_repo=get_job_repo(),
        )
    return _spider_service


def get_revocation_service():
    """RevocationService (impacto + propagación de revocación)."""
    global _revocation_service
    if _revocation_service is None:
        from src.learning.revocation import RevocationService

        _revocation_service = RevocationService(
            get_catalog_store(), learning_store=get_learning_store()
        )
    return _revocation_service


def get_agent_readiness_service():
    """Agent Intelligence Readiness."""
    global _agent_readiness_service
    if _agent_readiness_service is None:
        from src.learning.readiness import AgentReadinessService

        _agent_readiness_service = AgentReadinessService(
            get_learning_store(),
            get_catalog_store(),
            intelligence_store=get_intelligence_store(),
        )
    return _agent_readiness_service


def get_learning_analytics():
    """LearningAnalytics (tendencias + continuous improvement)."""
    global _learning_analytics
    if _learning_analytics is None:
        from src.learning.analytics import LearningAnalytics

        _learning_analytics = LearningAnalytics(
            get_learning_store(),
            catalog_store=get_catalog_store(),
            intelligence_store=get_intelligence_store(),
        )
    return _learning_analytics


def get_catalog_store():
    """Store del Discovery Engine & Semantic Catalog (FASE 24)."""
    global _catalog_store
    if _catalog_store is None:
        from src.catalog.store import PostgresCatalogStore

        _catalog_store = PostgresCatalogStore()
    return _catalog_store


def get_catalog_discovery_engine():
    """Motor de discovery (jobs durables 'catalog_discovery:*')."""
    global _catalog_discovery_engine
    if _catalog_discovery_engine is None:
        from src.catalog.jobs import CatalogDiscoveryEngine
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        _catalog_discovery_engine = CatalogDiscoveryEngine(
            job_repo=get_job_repo(),
            connector_repo=get_connector_repo(),
            catalog_store=get_catalog_store(),
            intelligence_store=get_intelligence_store(),
            secret_store=get_secret_store(),
            llm_provider=get_llm_provider(),
        )
    return _catalog_discovery_engine


def get_knowledge_learning_repo():
    """Store del Knowledge Learning Engine (FASE 33)."""
    global _knowledge_learning_repo
    if _knowledge_learning_repo is None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        _knowledge_learning_repo = PostgresKnowledgeLearningRepository()
    return _knowledge_learning_repo


def get_knowledge_score_service():
    """Score de Knowledge Readiness (FASE 33A)."""
    global _knowledge_score_service
    if _knowledge_score_service is None:
        from src.platform.knowledge_learning.knowledge_score import (
            KnowledgeScoreService,
        )

        _knowledge_score_service = KnowledgeScoreService(
            get_catalog_store(), repository=get_knowledge_learning_repo()
        )
    return _knowledge_score_service


def get_knowledge_graph_service():
    """Knowledge Map, entidades aprendidas y gaps (FASE 33C)."""
    global _knowledge_graph_service
    if _knowledge_graph_service is None:
        from src.platform.knowledge_learning.knowledge_graph import (
            KnowledgeGraphService,
        )

        _knowledge_graph_service = KnowledgeGraphService(
            get_catalog_store(),
            intelligence_store=get_intelligence_store(),
            repository=get_knowledge_learning_repo(),
        )
    return _knowledge_graph_service


def get_knowledge_evaluation_service():
    """Auto-evaluación RAG del conocimiento aprendido (FASE 33G)."""
    global _knowledge_evaluation_service
    if _knowledge_evaluation_service is None:
        from src.platform.knowledge_learning.evaluation import (
            KnowledgeEvaluationService,
        )

        _knowledge_evaluation_service = KnowledgeEvaluationService(
            get_catalog_store(), get_knowledge_learning_repo()
        )
    return _knowledge_evaluation_service


def get_knowledge_validation_engine():
    """Validación humana: respuestas -> conocimiento (FASE 33D)."""
    global _knowledge_validation_engine
    if _knowledge_validation_engine is None:
        from src.platform.knowledge_learning.validation_engine import (
            KnowledgeValidationEngine,
        )

        _knowledge_validation_engine = KnowledgeValidationEngine(
            get_catalog_store(),
            get_knowledge_learning_repo(),
            score_service=get_knowledge_score_service(),
            intelligence_store=get_intelligence_store(),
        )
    return _knowledge_validation_engine


def get_knowledge_learning_engine():
    """Motor de aprendizaje (jobs durables 'knowledge_learning:*')."""
    global _knowledge_learning_engine
    if _knowledge_learning_engine is None:
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store
        from src.platform.knowledge_learning.orchestrator import (
            KnowledgeLearningEngine,
        )

        _knowledge_learning_engine = KnowledgeLearningEngine(
            job_repo=get_job_repo(),
            connector_repo=get_connector_repo(),
            catalog_store=get_catalog_store(),
            intelligence_store=get_intelligence_store(),
            secret_store=get_secret_store(),
            llm_provider=get_llm_provider(),
            repository=get_knowledge_learning_repo(),
            score_service=get_knowledge_score_service(),
        )
    return _knowledge_learning_engine


def get_semantic_schema_linking():
    """Ranking semántico del SQL Expert (schema linking del catálogo)."""
    global _semantic_schema_linking
    if _semantic_schema_linking is None:
        from src.catalog.schema_linking import SemanticSchemaLinking

        _semantic_schema_linking = SemanticSchemaLinking(
            get_catalog_store(), intelligence_store=get_intelligence_store()
        )
    return _semantic_schema_linking


async def _resolve_authoritative_source(
    organization_id: UUID, concepts: list[str]
) -> str | None:
    """Fuente autoritativa para conceptos vía catalog_authority (fail-soft)."""
    try:
        from src.catalog.authority import AuthorityService

        service = AuthorityService(get_catalog_store())
        return await service.authoritative_source(organization_id, concepts)
    except Exception:  # noqa: BLE001
        return None


def get_intelligence_store():
    """Store de la Intelligence Layer (traces, definiciones, gaps)."""
    global _intelligence_store
    if _intelligence_store is None:
        from src.intelligence.store import PostgresIntelligenceStore

        _intelligence_store = PostgresIntelligenceStore()
    return _intelligence_store


def get_business_definition_registry():
    """Registro de definiciones empresariales (con caché compartida)."""
    global _business_definition_registry
    if _business_definition_registry is None:
        from src.intelligence.definitions import BusinessDefinitionRegistry

        _business_definition_registry = BusinessDefinitionRegistry(
            store=get_intelligence_store(), cache=get_cache_provider()
        )
    return _business_definition_registry


async def _resolve_source_freshness(
    organization_id: UUID, source_ids: list[str]
) -> dict[str, str]:
    """Días desde la última sync exitosa por source (señal source_freshness)."""
    from datetime import datetime, timezone

    repo = get_sync_state_repo()
    out: dict[str, str] = {}
    for source_id in source_ids:
        try:
            state = await repo.get_state(UUID(source_id))
            if state is not None and state.last_success_at is not None:
                days = max(
                    int(
                        (
                            datetime.now(timezone.utc)
                            - state.last_success_at.replace(tzinfo=timezone.utc)
                        ).total_seconds()
                        // 86400
                    ),
                    0,
                )
                out[source_id] = str(days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Source freshness lookup failed", error=str(exc)[:200])
    return out


def get_intelligence_engine():
    """Engine de answerability (None si RAG_ANSWERABILITY_ENABLED=false)."""
    global _intelligence_engine
    settings = get_settings()
    if not settings.RAG_ANSWERABILITY_ENABLED:
        return None
    if _intelligence_engine is None:
        from src.intelligence.definitions import BusinessDefinitionRegistry
        from src.intelligence.engine import IntelligenceEngine
        from src.intelligence.store import PostgresIntelligenceStore

        store = PostgresIntelligenceStore()
        _intelligence_engine = IntelligenceEngine(
            llm_provider=get_llm_provider(),
            definition_registry=BusinessDefinitionRegistry(
                store=store, cache=get_cache_provider()
            ),
            store=store,
            cache=get_cache_provider(),
            min_meaningful_score=max(settings.RAG_SCORE_THRESHOLD, 0.1),
            min_score=settings.RAG_ANSWERABILITY_MIN_SCORE,
            coverage_min=settings.RAG_ANSWERABILITY_RETRIEVAL_COVERAGE_MIN,
            conflict_tolerance_pct=settings.RAG_ANSWERABILITY_CONFLICT_TOLERANCE_PCT,
            freshness_max_days=settings.RAG_ANSWERABILITY_FRESHNESS_MAX_DAYS,
            llm_critic_enabled=settings.RAG_ANSWERABILITY_LLM_CRITIC_ENABLED,
            concept_llm_enabled=settings.RAG_ANSWERABILITY_CONCEPT_LLM_ENABLED,
            sql_router_threshold=settings.RAG_SQL_ROUTER_THRESHOLD,
            freshness_resolver=_resolve_source_freshness,
            authority_resolver=(
                _resolve_authoritative_source
                if settings.RAG_CATALOG_ENABLED
                else None
            ),
        )
    return _intelligence_engine


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
            intelligence=get_intelligence_engine(),
            learning=(
                get_context_gap_analyzer()
                if settings.RAG_LEARNING_ENABLED
                else None
            ),
            structured_retriever=(
                get_structured_retriever()
                if settings.KNOWLEDGE_V2_ENABLED
                and (settings.KNOWLEDGE_V2_SHADOW or settings.KNOWLEDGE_V2_PROMOTE)
                else None
            ),
            promote_v2=(
                settings.KNOWLEDGE_V2_PROMOTE
                if settings.KNOWLEDGE_V2_ENABLED
                else False
            ),
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
            semantic_linking=(
                get_semantic_schema_linking()
                if settings.RAG_CATALOG_ENABLED
                else None
            ),
            verified_query_service=get_verified_query_service(),
        )
        _ = settings.RAG_SQL_EXPERT_ENABLED  # el singleton no depende del flag
    return _sql_expert


_verified_query_service: object | None = None


def get_verified_query_service():
    """Singleton Verified Query Repository (Phase 26C)."""
    global _verified_query_service
    if _verified_query_service is None:
        from src.intelligence.verified_queries import VerifiedQueryService
        from src.intelligence.verified_query_store import PostgresVerifiedQueryStore

        _verified_query_service = VerifiedQueryService(
            store=PostgresVerifiedQueryStore()
        )
    return _verified_query_service


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
