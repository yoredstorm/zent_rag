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
_decision_engine = None
_decision_hook = None
_adaptive_hook = None
_preflight_hook = None
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


_canonical_repo: object | None = None


def get_canonical_repo():
    """Repo de identidad canónica (Phase 1) — org-scoped, sin consumidores aún."""
    global _canonical_repo
    if _canonical_repo is None:
        from src.infrastructure.postgres.canonical import (
            PostgresCanonicalKnowledgeRepository,
        )

        _canonical_repo = PostgresCanonicalKnowledgeRepository()
    return _canonical_repo


_evidence_ledger_repo: object | None = None


def get_evidence_ledger_repo():
    """Repo del ledger de evidencia (Phase 2) — append-only, org-scoped."""
    global _evidence_ledger_repo
    if _evidence_ledger_repo is None:
        from src.infrastructure.postgres.evidence_ledger import (
            PostgresEvidenceLedgerRepository,
        )

        _evidence_ledger_repo = PostgresEvidenceLedgerRepository()
    return _evidence_ledger_repo


_claim_ledger_repo: object | None = None


def get_claim_ledger_repo():
    """Repo del ledger de claims (Phase 2) — verificación + conflicto, org-scoped."""
    global _claim_ledger_repo
    if _claim_ledger_repo is None:
        from src.infrastructure.postgres.evidence_ledger import (
            PostgresClaimLedgerRepository,
        )

        _claim_ledger_repo = PostgresClaimLedgerRepository()
    return _claim_ledger_repo


_cognitive_repo: object | None = None


def get_cognitive_repo():
    """Repo del Cognitive OS (Phase 3) — runs/tasks/mensajes, org-scoped."""
    global _cognitive_repo
    if _cognitive_repo is None:
        from src.infrastructure.postgres.cognitive import (
            PostgresCognitiveRepository,
        )

        _cognitive_repo = PostgresCognitiveRepository()
    return _cognitive_repo


_cognitive_service: object | None = None


def get_cognitive_service():
    """Servicio de planificación cognitiva (Phase 3) — sin ejecución aún."""
    global _cognitive_service
    if _cognitive_service is None:
        from src.platform.cognitive.service import CognitivePlanningService

        _cognitive_service = CognitivePlanningService(get_cognitive_repo())
    return _cognitive_service


_cognitive_executor: object | None = None


def get_cognitive_executor():
    """Executor de especialistas (Phase 4) — retrieval + LLM + ledgers."""
    global _cognitive_executor
    if _cognitive_executor is None:
        from src.platform.cognitive.executor import (
            CognitiveExecutor,
            SpecialistDeps,
        )

        _cognitive_executor = CognitiveExecutor(
            get_cognitive_repo(),
            SpecialistDeps(
                llm=get_llm_provider(),
                embedding=get_embedding_provider(),
                retriever=get_retriever(),
                evidence_repo=get_evidence_ledger_repo(),
                claim_repo=get_claim_ledger_repo(),
            ),
        )
    return _cognitive_executor


_curator_repo: object | None = None


def get_curator_repo():
    """Repo de sugerencias del Knowledge Curator (Phase 7) — org-scoped."""
    global _curator_repo
    if _curator_repo is None:
        from src.infrastructure.postgres.curator import PostgresCuratorRepository

        _curator_repo = PostgresCuratorRepository()
    return _curator_repo


_knowledge_curator: object | None = None


def get_knowledge_curator():
    """Knowledge Curator (Phase 7): observaciones → sugerencias PROPOSED."""
    global _knowledge_curator
    if _knowledge_curator is None:
        from src.platform.cognitive.curator import KnowledgeCurator

        _knowledge_curator = KnowledgeCurator(
            get_curator_repo(), get_cognitive_repo()
        )
    return _knowledge_curator


_shadow_repo: object | None = None


def get_shadow_repo():
    """Repo de comparaciones shadow (Phase 8) — org-scoped."""
    global _shadow_repo
    if _shadow_repo is None:
        from src.infrastructure.postgres.shadow import PostgresShadowRepository

        _shadow_repo = PostgresShadowRepository()
    return _shadow_repo


_shadow_evaluator: object | None = None


def get_shadow_evaluator():
    """Evaluador shadow baseline vs cognitive (Phase 8)."""
    global _shadow_evaluator
    if _shadow_evaluator is None:
        from src.platform.cognitive.shadow import ShadowEvaluator

        _shadow_evaluator = ShadowEvaluator(
            get_shadow_repo(), get_cognitive_repo(), get_cognitive_executor()
        )
    return _shadow_evaluator


def get_knowledge_engine():
    """Inyecta el motor de ingestion de la Knowledge Platform.

    El repo de documentos estructurados (Knowledge V2) se activa SOLO con
    RAG_KNOWLEDGE_V2_ENABLED=true; en su ausencia el motor queda idéntico a V1.
    """
    global _knowledge_engine
    if _knowledge_engine is None:
        from src.knowledge.engine.service import KnowledgeIngestionEngine

        structured_repo = None
        tabular_repo = None
        summarizer = None
        settings = get_settings()
        if settings.KNOWLEDGE_V2_ENABLED and settings.KNOWLEDGE_TABULAR_ENABLED:
            from src.infrastructure.postgres.tabular import (
                PostgresTabularRepository,
            )

            tabular_repo = PostgresTabularRepository()
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
            tabular_repo=tabular_repo,
            summarizer=summarizer,
            usage_tracker=usage_tracker,
            company_discovery=_company_discovery_hook(settings),
        )
    return _knowledge_engine


def _company_discovery_hook(settings):
    """Hook de ingesta -> descubrimiento de compañía (Fase 5B, fail-soft).

    Devuelve un objeto con `on_document_ingested`; el motor corre en background
    y solo propone candidatos. Si el flag está apagado, devuelve None y la
    ingesta no cambia en nada.
    """
    if not getattr(settings, "RAG_COMPANY_DISCOVERY_ENABLED", False):
        return None
    try:
        from src.company.discovery import jobs as discovery_jobs

        return discovery_jobs
    except Exception:  # noqa: BLE001 - descubrimiento no bloquea la ingesta
        return None


_tabular_query_service: object | None = None


def get_tabular_query_service():
    """Servicio SQL-first de Excel/CSV (Knowledge Tabular V2).

    Activo con RAG_KNOWLEDGE_V2_ENABLED + RAG_KNOWLEDGE_TABULAR_ENABLED.
    Incluye auto-ingesta al consultar si RAG_KNOWLEDGE_TABULAR_LAZY_ENABLED.
    """
    global _tabular_query_service
    if _tabular_query_service is None:
        settings = get_settings()
        if not (
            settings.KNOWLEDGE_V2_ENABLED and settings.KNOWLEDGE_TABULAR_ENABLED
        ):
            return None
        from src.infrastructure.postgres.tabular import PostgresTabularRepository
        from src.knowledge.tabular.lazy import TabularLazyIngestionService
        from src.knowledge.tabular.query import TabularQueryService

        repository = PostgresTabularRepository()
        lazy_service = (
            TabularLazyIngestionService(repository)
            if settings.KNOWLEDGE_TABULAR_LAZY_ENABLED
            else None
        )
        _tabular_query_service = TabularQueryService(
            repository,
            lazy_ingestion=lazy_service,
            max_lookup_rows=int(settings.KNOWLEDGE_TABULAR_LOOKUP_MAX_ROWS),
            min_confidence=float(settings.KNOWLEDGE_TABULAR_SQL_MIN_CONFIDENCE),
        )
    return _tabular_query_service


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
            tabular_query=(
                get_tabular_query_service()
                if settings.KNOWLEDGE_TABULAR_SQL_FIRST
                else None
            ),
            tabular_sql_first=bool(settings.KNOWLEDGE_TABULAR_SQL_FIRST),
            decision_hook=_decision_hook_or_none(),
            adaptive_hook=_adaptive_hook_or_none(),
            preflight_hook=_preflight_hook_or_none(),
        )
    return _orchestrator


_decision_configured = False


def get_decision_engine():
    """Decision Engine facade. Never exposes the JEV SDK to callers."""
    from src.decision.service import (
        configure_decision_engine,
        set_decision_engine,
    )
    from src.decision.service import (
        get_decision_engine as _get,
    )

    global _decision_configured, _decision_engine
    if not _decision_configured:
        # First API composition wins: DI engine with the LLM provider. Lower
        # layers import src.decision.service instead of this module.
        set_decision_engine(_build_decision_engine())
        configure_decision_engine(_build_decision_engine)
        _decision_configured = True
    _decision_engine = _get()
    return _decision_engine


def _build_decision_engine():
    from src.decision.factory import build_decision_engine

    return build_decision_engine(llm=get_llm_provider())


def _decision_hook_or_none():
    global _decision_hook
    if _decision_hook is None:
        from src.decision.hook import OrchestratorDecisionHook

        _decision_hook = OrchestratorDecisionHook(get_decision_engine())
    return _decision_hook


def _adaptive_hook_or_none():
    global _adaptive_hook
    if _adaptive_hook is None:
        from src.rag.adaptive.hook import OrchestratorAdaptiveHook
        from src.rag.adaptive.settings import settings_from_app

        cfg = settings_from_app()
        if not cfg.enabled():
            return None
        engine = get_decision_engine()
        try:
            claims_ledger = get_claim_ledger_repo()
        except Exception:  # noqa: BLE001 — ledger opcional (best-effort)
            claims_ledger = None
        _adaptive_hook = OrchestratorAdaptiveHook(
            cfg,
            # El engine (no el bound method) habilita `judge_phase`: batching,
            # cache request-scoped y rollout off/shadow/on. `call_judge` acepta
            # ambos, así los fakes y callers previos siguen funcionando.
            judge=engine if engine.settings.jev_configured else None,
            cache=get_cache_provider(),
            llm=get_llm_provider(),
            high_confidence=engine.settings.high_confidence,
            rewrite_model=engine.settings.fallback_model or None,
            claims_ledger=claims_ledger,
        )
    return _adaptive_hook


def _preflight_hook_or_none():
    """JEV Preflight: juicio barato antes de pagar generación cara.

    Sin judge configurado el hook se construye igual pero queda inerte
    (`enabled()` exige judge y modo distinto de off).
    """
    global _preflight_hook
    if _preflight_hook is None:
        from src.rag.preflight_hook import OrchestratorPreflightHook, settings_from_app

        cfg = settings_from_app()
        if not cfg.active:
            return None
        engine = get_decision_engine()
        _preflight_hook = OrchestratorPreflightHook(
            cfg,
            judge=engine if engine.settings.jev_configured else None,
            cache=getattr(engine, "batch_cache", None),
        )
    return _preflight_hook


def get_decision_hook():
    """Shared decision hook for callers that need the recommendation only."""
    return _decision_hook_or_none()


_dispatcher = None


def get_capability_dispatcher():
    """Capability dispatcher with the handlers this process can execute.

    Registration lives here (composition root): the runtime layer stays free
    of api/agents/platform imports. knowledge/database/llm keep flowing through
    RAGOrchestrator; agent/workflow/tool get a real execution path.
    """
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher
    from src.runtime.dispatcher import CapabilityDispatcher, DispatchResult, denied

    dispatcher = CapabilityDispatcher()

    def _org_config(request) -> dict:
        return dict(request.org_config or {})

    async def _agent_handler(request, decision):
        from src.agents.runtime.trace_store import ensure_agent_runs_table, save_run
        from src.platform.auth.scopes import permission_satisfied

        if not permission_satisfied(request.permissions, "agents:execute"):
            return denied(decision.capability, handler="agent_runtime")
        agent = await get_agent_repo().get_agent(request.organization_id, request.agent_id)
        if agent is None:
            return DispatchResult(
                capability=decision.capability,
                handler="agent_runtime",
                status="failed",
                error="agent_not_found",
            )
        from src.agents.runtime.agent_runtime import AgentRunRequest

        run = await get_agent_runtime().run(
            AgentRunRequest(
                agent=agent,
                message=request.query,
                user_id=request.user_id,
                role=request.role,
                conversation_id=request.conversation_id,
                permissions=request.permissions,
                org_config=_org_config(request),
                trace_id=request.trace_id,
            )
        )
        try:
            await ensure_agent_runs_table()
            await save_run(run)
        except Exception:  # noqa: BLE001 — trace persistence is best-effort
            pass
        return DispatchResult(
            capability=decision.capability,
            handler="agent_runtime",
            status="completed" if run.status == "completed" else "failed",
            answer=run.answer,
            error=None if run.status == "completed" else run.status,
            tokens=run.total_tokens,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            cost=run.cost,
            run_id=str(run.run_id),
            data={
                "method": "agent",
                "agent_id": str(agent.id),
                "model": run.model,
                "steps": run.steps[-10:],
                "status": run.status,
            },
        )

    async def _workflow_handler(request, decision):
        from src.platform.auth.scopes import permission_satisfied
        from src.platform.workflows.engine import WorkflowAccessError, run_workflow

        if not permission_satisfied(request.permissions, "workflows:run"):
            return denied(decision.capability, handler="workflow_engine")
        try:
            result = await run_workflow(
                request.workflow_id,
                payload={"query": request.query},
                trigger="manual",
                organization_id=request.organization_id,
                workspace_id=request.workspace_id,
                actor_type="api",
                actor_id=request.user_id,
                permissions=request.permissions,
                correlation_id=request.trace_id,
                resume=decision.capability == "workflow.resume",
                run_id=request.run_id if decision.capability == "workflow.resume" else None,
            )
        except WorkflowAccessError as exc:
            return denied(
                decision.capability,
                handler="workflow_engine",
                reason=str(exc)[:200],
            )
        if result is None:
            return DispatchResult(
                capability=decision.capability,
                handler="workflow_engine",
                status="failed",
                error="workflow_not_found",
            )
        status = str(result.get("status") or "completed")
        answer = str(
            result.get("answer")
            or result.get("message")
            or f"Workflow {status}."
        )
        return DispatchResult(
            capability=decision.capability,
            handler="workflow_engine",
            status="completed" if status in {"completed", "ok", "simulated"} else "failed",
            answer=answer[:8000],
            error=None if status in {"completed", "ok", "simulated"} else status,
            run_id=str(result.get("run_id") or result.get("id") or "") or None,
            data={"method": "workflow", "workflow_id": str(request.workflow_id), "status": status},
        )

    async def _tool_handler(request, decision):
        from src.agents.tools.base import ToolContext
        from src.agents.tools.guards import ToolRateLimiter, execute_tool_guarded
        from src.agents.tools.registry import get_tool
        from src.platform.auth.scopes import permission_satisfied

        if not permission_satisfied(request.permissions, "agents:execute"):
            return denied(decision.capability, handler="tool_registry")
        tool_name = request.tool or str(decision.metadata.get("tool") or "")
        if not tool_name:
            return DispatchResult(
                capability=decision.capability,
                handler="tool_registry",
                status="needs_target",
                error="missing_target:tool",
            )
        get_agent_runtime()  # guarantees builtin tools are registered
        tool = get_tool(tool_name)
        if tool is None:
            return DispatchResult(
                capability=decision.capability,
                handler="tool_registry",
                status="failed",
                error=f"tool_not_found:{tool_name}",
            )
        if tool.permission and not permission_satisfied(request.permissions, tool.permission):
            return denied(
                decision.capability,
                handler="tool_registry",
                reason=f"missing_permission:{tool.permission}",
            )
        arguments = dict(request.tool_arguments or {})
        if not arguments and request.query:
            arguments = {"query": request.query}
        ctx = ToolContext(
            tenant_id=request.organization_id,
            user_id=request.user_id,
            role=request.role,
            permissions=request.permissions,
            conversation_id=request.conversation_id,
            org_config=_org_config(request),
        )
        tool_result = await execute_tool_guarded(
            tool, ctx, arguments, ToolRateLimiter(get_cache_provider())
        )
        try:
            from uuid import uuid4 as _uuid4

            from src.platform.usage.usage_engine import UsageEvent, record_event

            await record_event(
                UsageEvent(
                    request_id=_uuid4(),
                    organization_id=request.organization_id,
                    user_id=request.user_id,
                    event_type="tool",
                    model=tool_name[:120],
                    provider="tool_registry",
                    latency_ms=tool_result.latency_ms,
                    status="failed" if tool_result.error else "completed",
                    routing={"capability": decision.capability},
                    trace_id=request.trace_id,
                )
            )
        except Exception:  # noqa: BLE001 — metering is best-effort
            pass
        return DispatchResult(
            capability=decision.capability,
            handler="tool_registry",
            status="failed" if tool_result.error else "completed",
            answer=tool_result.output or "",
            error=tool_result.error,
            tokens=tool_result.tokens,
            data={"method": "tool", "tool": tool_name, "meta": tool_result.meta},
        )

    dispatcher.register("agent_runtime", _agent_handler)
    dispatcher.register("workflow_engine", _workflow_handler)
    dispatcher.register("tool_registry", _tool_handler)
    # Judgment Fabric: CandidateSet autorizado (tenant + RBAC + fuentes +
    # riesgo). El judge y el modo se resuelven acá (composition root).
    try:
        from src.core.config import get_settings
        from src.decision.service import get_decision_engine

        settings = get_settings()
        engine = get_decision_engine()
        dispatcher.configure_target_selection(
            candidates=_build_candidate_registry(),
            judge=engine if engine.settings.jev_configured else None,
            mode=settings.DECISION_TARGET_SELECTION,
            cache=getattr(engine, "batch_cache", None),
        )
    except Exception:  # noqa: BLE001 — sin selección automática el path previo manda
        pass
    _dispatcher = dispatcher
    return _dispatcher


def _build_candidate_registry():
    """Providers tenant-scoped para agent/workflow/tool. Sólo campos seguros."""
    from src.core.domain.decision import CostClass, RiskLevel
    from src.decision.candidates import Candidate, CandidateKind, CandidateRegistry

    registry = CandidateRegistry()

    def _risk(value) -> RiskLevel:
        raw = value.value if hasattr(value, "value") else str(value or "")
        for level in RiskLevel:
            if level.value == raw:
                return level
        return RiskLevel.MEDIUM

    async def _agent_candidates(organization_id, context=None):
        try:
            agents = await get_agent_repo().list_agents(organization_id)
        except Exception:  # noqa: BLE001
            return []
        out: list[Candidate] = []
        for agent in agents:
            status = str(getattr(agent.status, "value", agent.status) or "draft")
            enabled = bool(getattr(agent, "is_active", True)) and status not in {
                "draft",
                "archived",
            }
            config = dict(getattr(agent, "config_json", None) or {})
            out.append(
                Candidate(
                    id=str(agent.id),
                    kind=CandidateKind.AGENT.value,
                    name=str(getattr(agent, "name", "") or "")[:120],
                    description=str(getattr(agent, "description", "") or "")[:200],
                    capabilities=("agent.execute", "agent.reason", "agent.delegate"),
                    required_permission="agents:execute",
                    risk_level=_risk(config.get("risk_level") or "medium"),
                    cost_class=CostClass.EXPENSIVE,
                    enabled=enabled,
                    status="active" if enabled else status,
                    tenant_id=str(organization_id),
                    tags=tuple(str(t) for t in (config.get("tags") or ())[:8]),
                )
            )
        return out

    async def _workflow_candidates(organization_id, context=None):
        from src.platform.workflows.engine import list_workflows

        workspace_id = getattr(context, "workspace_id", None) if context is not None else None
        try:
            payload = await list_workflows(organization_id, workspace_id=workspace_id)
        except Exception:  # noqa: BLE001
            return []
        out: list[Candidate] = []
        for item in payload.get("workflows") or []:
            status = str(item.get("status") or "draft")
            enabled = status in {"active", "published", "ready", "simulated"}
            out.append(
                Candidate(
                    id=str(item.get("id") or ""),
                    kind=CandidateKind.WORKFLOW.value,
                    name=str(item.get("name") or "")[:120],
                    description=str(item.get("description") or "")[:200],
                    capabilities=("workflow.start", "workflow.execute"),
                    required_permission="workflows:run",
                    risk_level=RiskLevel.MEDIUM,
                    cost_class=CostClass.STANDARD,
                    enabled=enabled,
                    status="active" if enabled else status,
                    tenant_id=str(organization_id),
                    tags=(str(item.get("trigger_type") or "manual")[:32],),
                )
            )
        return out

    async def _tool_candidates(organization_id, context=None):
        from src.agents.tools.registry import list_tools

        try:
            get_agent_runtime()  # garantiza tools builtin registradas
            tools = list_tools()
        except Exception:  # noqa: BLE001
            return []
        source_map = {
            "query_database": ("sql",),
            "query_tabular_data": ("tabular",),
            "search_knowledge": ("knowledge",),
            "call_api": ("api",),
        }
        out: list[Candidate] = []
        for name, tool in tools.items():
            permission = str(getattr(tool, "permission", "") or "")
            out.append(
                Candidate(
                    id=str(name),
                    kind=CandidateKind.TOOL.value,
                    name=str(name)[:120],
                    description=str(getattr(tool, "description", "") or name)[:200],
                    capabilities=("tool.execute",),
                    required_sources=source_map.get(str(name), ()),
                    required_permission=permission,
                    risk_level=RiskLevel.HIGH if permission else RiskLevel.MEDIUM,
                    cost_class=CostClass.CHEAP,
                    enabled=True,
                    status="active",
                    tenant_id=str(organization_id),
                    tags=("tool",),
                )
            )
        return out

    registry.register(CandidateKind.AGENT.value, _agent_candidates)
    registry.register(CandidateKind.WORKFLOW.value, _workflow_candidates)
    registry.register(CandidateKind.TOOL.value, _tool_candidates)
    return registry


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
            embedder=get_embedding_provider(),
            tabular_query=get_tabular_query_service(),
        )
        load_tool_modules()
        _agent_runtime = AgentRuntime(
            llm_provider=get_llm_provider(),
            cache_provider=get_cache_provider(),
        )
    return _agent_runtime
