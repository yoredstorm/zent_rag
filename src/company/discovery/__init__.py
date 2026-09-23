# =============================================================================
# Company Discovery Engine (Fase 5B)
# =============================================================================
# Descubre cómo habla y cómo funciona una organización a partir de evidencia
# que ya existe: documentos, schemas, consultas exitosas, workflows, agentes,
# eventos, memoria y claims.
#
# Ley: DISCOVER -> SUPPORT -> SUGGEST -> VALIDATE -> CONFIRM.
# Nada se convierte en verdad de la compañía por inferencia de un LLM.
# =============================================================================
from src.company.discovery.confidence import (
    SUGGEST_CONFIDENCE,
    VALIDATE_CONFIDENCE,
    mapping_confident,
    next_stage_for,
    score_candidate,
)
from src.company.discovery.engine import CompanyDiscoveryEngine, DiscoveryRunResult
from src.company.discovery.gaps import KnowledgeGapSource, find_process_divergences
from src.company.discovery.jobs import (
    company_discovery_worker_loop,
    enqueue_discovery,
    on_document_ingested,
    run_due_discovery,
    run_next_discovery_job,
)
from src.company.discovery.resolution import (
    EntityResolutionEngine,
    ResolutionOutcome,
    ResolutionStrategy,
    normalize_business_name,
)
from src.company.discovery.source_base import (
    DiscoverySource,
    DiscoverySourceRegistry,
    default_sources,
    register_default_sources,
)

__all__ = [
    "CompanyDiscoveryEngine",
    "DiscoveryRunResult",
    "DiscoverySource",
    "DiscoverySourceRegistry",
    "EntityResolutionEngine",
    "KnowledgeGapSource",
    "ResolutionOutcome",
    "ResolutionStrategy",
    "SUGGEST_CONFIDENCE",
    "VALIDATE_CONFIDENCE",
    "company_discovery_worker_loop",
    "default_sources",
    "enqueue_discovery",
    "find_process_divergences",
    "mapping_confident",
    "next_stage_for",
    "normalize_business_name",
    "on_document_ingested",
    "register_default_sources",
    "run_due_discovery",
    "run_next_discovery_job",
    "score_candidate",
]
