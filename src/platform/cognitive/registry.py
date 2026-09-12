# =============================================================================
# Cognitive Agent Registry — declarative specialists (Phase 3)
# =============================================================================
# No hay if/elif gigantes: los especialistas son datos (KnowledgeAgentDefinition)
# y la selección por nivel es determinista. Los `allowed_tools` referencian
# tools YA existentes del Agent Runtime (search_knowledge, query_database,
# call_api); la ejecución real de especialistas llega en fases posteriores.
# =============================================================================
from __future__ import annotations

from src.core.domain.cognitive import ComplexityLevel, KnowledgeAgentDefinition

BUILTIN_DEFINITIONS: tuple[KnowledgeAgentDefinition, ...] = (
    KnowledgeAgentDefinition(
        id="librarian",
        name="Librarian / Source Curator",
        description="Localiza fuentes, versiones, autoridad y frescura; no interpreta a fondo.",
        capabilities=("source_lookup", "approved_definitions", "authority"),
        allowed_tools=("search_knowledge",),
        required_permissions=("rag:read",),
        supported_tasks=("locate_sources",),
        preferred_model_role="FAST_CLASSIFIER",
        max_steps=3,
        max_tokens=2000,
        max_cost_usd=0.05,
    ),
    KnowledgeAgentDefinition(
        id="retrieval_strategist",
        name="Retrieval Strategist",
        description="Elige estrategia de retrieval (dense/sparse/hybrid/section) y ejecuta búsquedas.",
        capabilities=("retrieval", "routing", "query_expansion"),
        allowed_tools=("search_knowledge",),
        required_permissions=("rag:read",),
        supported_tasks=("retrieve",),
        max_steps=4,
        max_tokens=3000,
        max_cost_usd=0.1,
    ),
    KnowledgeAgentDefinition(
        id="document_analyst",
        name="Document Analyst",
        description="Analiza StructuredDocument: secciones, tablas, cláusulas y hechos con citas.",
        capabilities=("document_analysis", "citations"),
        allowed_tools=("search_knowledge",),
        required_permissions=("rag:read",),
        supported_tasks=("analyze_sources",),
        max_steps=6,
        max_tokens=6000,
        max_cost_usd=0.3,
        can_delegate=False,
    ),
    KnowledgeAgentDefinition(
        id="data_analyst",
        name="Data Analyst",
        description="Consultas estructuradas vía SQL Expert con semantic guard; siempre con provenance.",
        capabilities=("data_query", "sql", "metrics"),
        allowed_tools=("query_database",),
        required_permissions=("rag:read",),
        supported_tasks=("analyze_data",),
        max_steps=6,
        max_tokens=6000,
        max_cost_usd=0.3,
    ),
    KnowledgeAgentDefinition(
        id="temporal_analyst",
        name="Temporal Specialist",
        description="Versiones, vigencia, effective_from/to, supersedes; evita mezclar versiones.",
        capabilities=("temporal", "versions", "validity"),
        allowed_tools=("search_knowledge",),
        required_permissions=("rag:read",),
        supported_tasks=("resolve_temporal",),
        max_steps=5,
        max_tokens=4000,
        max_cost_usd=0.2,
    ),
    KnowledgeAgentDefinition(
        id="policy_analyst",
        name="Policy / Compliance Specialist",
        description="Interpreta políticas y reglas de negocio aprobadas; NO aplica permisos del sistema.",
        capabilities=("policy", "rules", "compliance"),
        allowed_tools=("search_knowledge",),
        required_permissions=("rag:read",),
        supported_tasks=("analyze_policy",),
        max_steps=5,
        max_tokens=4000,
        max_cost_usd=0.2,
    ),
    KnowledgeAgentDefinition(
        id="relationship_analyst",
        name="Relationship Analyst",
        description="Relaciones entre entidades/fuentes (modifies, supersedes, references) con provenance.",
        capabilities=("relationships", "graph"),
        allowed_tools=(),
        supported_tasks=("analyze_relationships",),
        max_steps=4,
        max_tokens=3000,
        max_cost_usd=0.15,
    ),
    KnowledgeAgentDefinition(
        id="conflict_detector",
        name="Conflict Detector",
        description="Detecta contradicciones estructurales (mismo sujeto/predicado, objeto distinto).",
        capabilities=("conflict", "contradictions"),
        allowed_tools=(),
        supported_tasks=("detect_conflicts",),
        max_steps=4,
        max_tokens=3000,
        max_cost_usd=0.15,
    ),
    KnowledgeAgentDefinition(
        id="critic",
        name="Critic Agent",
        description="Busca errores en findings/claims: citas débiles, saltos lógicos, fuentes omitidas.",
        capabilities=("critique", "review"),
        allowed_tools=(),
        supported_tasks=("critique",),
        max_steps=5,
        max_tokens=4000,
        max_cost_usd=0.25,
        requires_verification=True,
    ),
    KnowledgeAgentDefinition(
        id="fact_checker",
        name="Fact Checker",
        description="Verifica claim→evidence (supported/partial/unsupported/conflicted/outdated).",
        capabilities=("verification", "evidence"),
        allowed_tools=("search_knowledge",),
        required_permissions=("rag:read",),
        supported_tasks=("verify",),
        max_steps=6,
        max_tokens=5000,
        max_cost_usd=0.3,
        requires_verification=True,
    ),
    KnowledgeAgentDefinition(
        id="synthesizer",
        name="Synthesizer",
        description="Sintetiza solo con evidencia suficiente; no agrega claims fuera de los inputs.",
        capabilities=("synthesis", "answer"),
        allowed_tools=(),
        supported_tasks=("synthesize",),
        preferred_model_role="SYNTHESIZER",
        max_steps=3,
        max_tokens=6000,
        max_cost_usd=0.35,
    ),
)

_LEVEL_SPECIALISTS: dict[ComplexityLevel, tuple[str, ...]] = {
    ComplexityLevel.L0_DIRECT: ("librarian",),
    ComplexityLevel.L1_RETRIEVAL: ("librarian", "retrieval_strategist"),
    ComplexityLevel.L2_ANALYSIS: (
        "librarian",
        "retrieval_strategist",
        "document_analyst",
        "synthesizer",
    ),
    ComplexityLevel.L3_MULTI_SOURCE: (
        "librarian",
        "retrieval_strategist",
        "document_analyst",
        "synthesizer",
        "fact_checker",
    ),
    ComplexityLevel.L4_MULTI_SPECIALIST: (
        "librarian",
        "retrieval_strategist",
        "document_analyst",
        "temporal_analyst",
        "policy_analyst",
        "conflict_detector",
        "synthesizer",
        "critic",
        "fact_checker",
    ),
    ComplexityLevel.L5_DEEP_INVESTIGATION: (
        "librarian",
        "retrieval_strategist",
        "document_analyst",
        "data_analyst",
        "temporal_analyst",
        "policy_analyst",
        "relationship_analyst",
        "conflict_detector",
        "synthesizer",
        "critic",
        "fact_checker",
    ),
}


class KnowledgeAgentRegistry:
    """Registro declarativo de especialistas (brief §7)."""

    def __init__(self) -> None:
        self._definitions: dict[str, KnowledgeAgentDefinition] = {}

    def register(self, definition: KnowledgeAgentDefinition) -> None:
        if definition.id in self._definitions:
            raise ValueError(
                f"agent definition '{definition.id}' is already registered"
            )
        self._definitions[definition.id] = definition

    def get(self, agent_id: str) -> KnowledgeAgentDefinition | None:
        return self._definitions.get(agent_id)

    def list(self) -> tuple[KnowledgeAgentDefinition, ...]:
        return tuple(self._definitions.values())

    def by_capability(
        self, capability: str
    ) -> tuple[KnowledgeAgentDefinition, ...]:
        return tuple(
            definition
            for definition in self._definitions.values()
            if capability in definition.capabilities
        )

    def select_for_level(
        self, level: ComplexityLevel
    ) -> tuple[KnowledgeAgentDefinition, ...]:
        definitions: list[KnowledgeAgentDefinition] = []
        for agent_id in _LEVEL_SPECIALISTS.get(level, ()):
            definition = self._definitions.get(agent_id)
            if definition is not None:
                definitions.append(definition)
        return tuple(definitions)


_default_registry: KnowledgeAgentRegistry | None = None


def default_registry() -> KnowledgeAgentRegistry:
    """Registro con los especialistas built-in (singleton de proceso)."""
    global _default_registry
    if _default_registry is None:
        registry = KnowledgeAgentRegistry()
        for definition in BUILTIN_DEFINITIONS:
            registry.register(definition)
        _default_registry = registry
    return _default_registry
