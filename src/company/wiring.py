# =============================================================================
# Company Intelligence — composition root (Postgres backend inicial).
# Para migrar a Neo4j: implementar Neo4jCompanyGraphRepository y cambiar
# company_graph_service() aquí. Ninguna capa superior cambia.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.company.service import CompanyAuthorityService, CompanyGraphService
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.company_discovery import (
    PostgresCompanyDiscoveryRepository,
)
from src.infrastructure.postgres.company_graph import (
    PostgresCompanyGraphRepository,
)

logger = get_logger(__name__)

_service: CompanyGraphService | None = None
_authority: CompanyAuthorityService | None = None
_discovery_repo: PostgresCompanyDiscoveryRepository | None = None
_discovery_engine = None
_context_compiler = None
_sources_registered = False


def company_graph_repository() -> PostgresCompanyGraphRepository:
    return PostgresCompanyGraphRepository()


def company_authority_service() -> CompanyAuthorityService:
    global _authority
    if _authority is None:
        _authority = CompanyAuthorityService()
    return _authority


def company_graph_service() -> CompanyGraphService:
    global _service
    if _service is None:
        _service = CompanyGraphService(
            company_graph_repository(), company_authority_service()
        )
    return _service


# -----------------------------------------------------------------------------
# Discovery Engine (Fase 5B)
# -----------------------------------------------------------------------------


def company_discovery_repository() -> PostgresCompanyDiscoveryRepository:
    global _discovery_repo
    if _discovery_repo is None:
        _discovery_repo = PostgresCompanyDiscoveryRepository()
    return _discovery_repo


def company_discovery_enabled() -> bool:
    try:
        from src.core.config import get_settings

        return bool(get_settings().RAG_COMPANY_DISCOVERY_ENABLED)
    except Exception:  # noqa: BLE001 - sin settings, descubrimiento off
        return False


def company_discovery_sources() -> list:
    """Fuentes builtin registradas (extensible: registrar y listo)."""
    global _sources_registered
    from src.company.discovery.source_base import (
        DiscoverySourceRegistry,
        register_default_sources,
    )

    if not _sources_registered or not DiscoverySourceRegistry.all():
        register_default_sources()
        _sources_registered = True
    return DiscoverySourceRegistry.all()


def company_discovery_engine():
    """Motor de descubrimiento. Postgres + Company Graph; storage-agnostic."""
    global _discovery_engine
    if _discovery_engine is None:
        from src.company.discovery.engine import CompanyDiscoveryEngine

        _discovery_engine = CompanyDiscoveryEngine(
            company_discovery_repository(),
            company_graph_service(),
            sources=company_discovery_sources(),
            authority_service=company_authority_service(),
        )
    return _discovery_engine


# -----------------------------------------------------------------------------
# Company Context Compiler (Fase 5B)
# -----------------------------------------------------------------------------


def company_context_compiler():
    """Compilador de contexto empresarial acotado para el runtime."""
    global _context_compiler
    if _context_compiler is None:
        from src.company.context import CompanyContextCompiler

        recall = None
        try:
            from src.memory.wiring import memory_recall_service

            recall = memory_recall_service()
        except Exception:  # noqa: BLE001 - memoria opcional
            recall = None
        _context_compiler = CompanyContextCompiler(
            company_graph_service(),
            memory_recall=recall,
            authority_service=company_authority_service(),
        )
    return _context_compiler


# -----------------------------------------------------------------------------
# Company Intelligence Studio (Fase 5C)
# -----------------------------------------------------------------------------

_studio = None
_ask = None


def company_studio_service():
    """Vistas compuestas: overview, map, detalle, impacto, gaps, cambios."""
    global _studio
    if _studio is None:
        from src.company.discovery.source_loaders import (
            load_document_versions,
            load_workflow_run_steps,
        )
        from src.company.studio import CompanyStudioService

        _studio = CompanyStudioService(
            company_graph_service(),
            discovery=_optional(company_discovery_repository),
            memory=_optional(_memory_service),
            learning=_optional(_learning_store),
            authority=company_authority_service(),
            run_steps_loader=load_workflow_run_steps,
            document_versions_loader=load_document_versions,
        )
    return _studio


def company_ask_service():
    """Exploración en lenguaje natural con evidencia del grafo."""
    global _ask
    if _ask is None:
        from src.company.ask import CompanyAskService

        _ask = CompanyAskService(
            company_graph_service(),
            company_studio_service(),
            compiler=company_context_compiler(),
            judge=_decision_judge,
            knowledge_search=_knowledge_search,
        )
    return _ask


def _optional(factory):
    """Colaborador opcional: si no está disponible, la vista pierde esa capa."""
    try:
        return factory()
    except Exception:  # noqa: BLE001 - la Studio nunca se cae por un optional
        return None


def _memory_service():
    from src.memory.wiring import memory_foundation_service

    return memory_foundation_service()


def _learning_store():
    from src.infrastructure.postgres.learning_cycle_store import (
        PostgresLearningCycleStore,
    )

    return PostgresLearningCycleStore()


async def _decision_judge(*, state: dict, questions: dict):
    """Juez del Judgment Fabric. Fail-soft: None si JEV no está configurado."""
    try:
        from src.decision.service import get_decision_engine

        engine = get_decision_engine()
    except Exception:  # noqa: BLE001
        return None
    if engine is None:
        return None
    return await engine.judge(state=state, questions=questions)


async def _knowledge_search(
    organization_id: UUID, query: str, *, limit: int = 5, role: str = "admin"
) -> list[dict]:
    """Fragmentos documentales como evidencia. Sin LLM: solo recuperación."""
    try:
        from src.api.deps import get_embedding_provider, get_retriever
        from src.rag.retrieval.models import RetrievalQuery

        retriever = get_retriever()
        embedder = get_embedding_provider()
        embedding = await embedder.embed(query)
        context = await retriever.retrieve(
            RetrievalQuery(
                query=query,
                organization_id=organization_id,
                role=role,
                top_k=limit,
                effective_top_k=limit,
                query_embedding=embedding,
            )
        )
    except Exception as exc:  # noqa: BLE001 - el ask nunca se cae
        logger.warning("company ask retrieval failed", error=str(exc)[:150])
        return []
    chunks = list(getattr(context, "chunks", None) or [])
    return [
        {
            "document_id": str(chunk.document_id),
            "title": (chunk.metadata or {}).get("title", ""),
            "content": chunk.content,
            "score": chunk.score,
        }
        for chunk in chunks[:limit]
    ]
