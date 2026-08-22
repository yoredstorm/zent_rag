# =============================================================================
# Retrieval Engine — Modelos de dominio (agnósticos de infraestructura)
# =============================================================================
# El motor de retrieval no conoce Qdrant, LiteLLM ni ningún adaptador.
# Solo puertos (ABCs) inyectados por DI y estructuras de datos puras.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

# Estrategias soportadas por el motor
STRATEGY_VECTOR = "vector"
STRATEGY_LEXICAL = "lexical"
STRATEGY_HYBRID = "hybrid"
RETRIEVAL_STRATEGIES = (STRATEGY_VECTOR, STRATEGY_LEXICAL, STRATEGY_HYBRID)

# Métodos de fusión soportados
FUSION_RRF = "rrf"
FUSION_WEIGHTED = "weighted"
FUSION_METHODS = (FUSION_RRF, FUSION_WEIGHTED)


@dataclass(kw_only=True)
class RetrievalQuery:
    """Query normalizada lista para ejecutar contra el motor.

    La construye la capa de aplicación (orchestrator) desde el request del
    usuario y la configuración del tenant. El motor no conoce la API.
    """

    query: str
    organization_id: UUID
    role: str = "admin"
    knowledge_base_id: UUID | None = None
    top_k: int = 200
    # Presupuesto total tras prioridad de doc_type (follow-ups recortan esto)
    effective_top_k: int | None = None
    rerank_top_k: int = 20
    score_threshold: float = 0.1
    strategy: str = STRATEGY_VECTOR
    fusion: str = FUSION_RRF
    rrf_k: int = 60
    lexical_weight: float = 0.3
    language: str | None = None
    filters: dict[str, str] = field(default_factory=dict)
    exclude_filters: dict[str, str] = field(default_factory=dict)
    # Tipos de documento que se priorizan en orden (comportamiento
    # "aggregated first" del pipeline original, generalizado).
    doc_type_priority: list[str] = field(default_factory=lambda: ["aggregated"])
    # Embedding de la query (lo calcula el llamador para reuso en ambas patas)
    query_embedding: list[float] | None = None


@dataclass(kw_only=True)
class QueryClassification:
    """Resultado de la clasificación heurística de la query."""

    kind: str  # "lexical" | "semantic" | "mixed"
    lexical_ratio: float  # 0.0 .. 1.0 — peso sugerido de la pata lexical
    language: str | None = None
