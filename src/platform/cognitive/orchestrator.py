# =============================================================================
# Knowledge Cognitive Orchestrator — Phase 3 (planificación/delegación)
# =============================================================================
# Construye el CognitiveTaskGraph determinista a partir de la complejidad de la
# solicitud. NO ejecuta especialistas (eso llega en fases posteriores): produce
# tareas asignadas, dependencias y presupuesto validado, listas para ejecución.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from src.core.domain.cognitive import (
    CognitiveBudget,
    CognitiveRun,
    CognitiveRunStatus,
    CognitiveScope,
    CognitiveTask,
    CognitiveTaskGraph,
    ComplexityLevel,
    KnowledgeAgentDefinition,
    classify_complexity,
)
from src.platform.cognitive.registry import (
    KnowledgeAgentRegistry,
    default_registry,
)

# (key, agent_id, depends_on, description)
_TaskBlueprint = tuple[str, str, tuple[str, ...], str]

_TASK_BLUEPRINTS: dict[ComplexityLevel, tuple[_TaskBlueprint, ...]] = {
    ComplexityLevel.L0_DIRECT: (
        (
            "answer_direct",
            "librarian",
            (),
            "Resolver con definición/fact aprobado, sin retrieval abierto.",
        ),
    ),
    ComplexityLevel.L1_RETRIEVAL: (
        (
            "locate_sources",
            "librarian",
            (),
            "Localizar fuentes relevantes autorizadas (SourceSet).",
        ),
        (
            "retrieve",
            "retrieval_strategist",
            ("locate_sources",),
            "Ejecutar retrieval sobre el SourceSet con ACL pre-LLM.",
        ),
    ),
    ComplexityLevel.L2_ANALYSIS: (
        (
            "locate_sources",
            "librarian",
            (),
            "Localizar documentos autorizados y sus versiones.",
        ),
        (
            "retrieve",
            "retrieval_strategist",
            ("locate_sources",),
            "Recuperar secciones relevantes con citas.",
        ),
        (
            "analyze_sources",
            "document_analyst",
            ("retrieve",),
            "Analizar secciones/tablas y extraer hechos con locators.",
        ),
        (
            "synthesize",
            "synthesizer",
            ("analyze_sources",),
            "Sintetizar únicamente con la evidencia recolectada.",
        ),
    ),
    ComplexityLevel.L3_MULTI_SOURCE: (
        (
            "locate_sources",
            "librarian",
            (),
            "Localizar todas las fuentes implicadas y sus versiones.",
        ),
        (
            "retrieve",
            "retrieval_strategist",
            ("locate_sources",),
            "Recuperar evidencia por fuente.",
        ),
        (
            "analyze_sources",
            "document_analyst",
            ("retrieve",),
            "Analizar cada fuente y extraer hechos citables.",
        ),
        (
            "synthesize",
            "synthesizer",
            ("analyze_sources",),
            "Comparar y sintetizar con evidencia cruzada.",
        ),
        (
            "verify",
            "fact_checker",
            ("synthesize",),
            "Verificar cada claim contra su evidencia.",
        ),
    ),
    ComplexityLevel.L4_MULTI_SPECIALIST: (
        (
            "locate_sources",
            "librarian",
            (),
            "Localizar fuentes, versiones y autoridad.",
        ),
        (
            "retrieve",
            "retrieval_strategist",
            ("locate_sources",),
            "Recuperar evidencia multi-fuente.",
        ),
        (
            "analyze_sources",
            "document_analyst",
            ("retrieve",),
            "Extraer hechos y obligaciones con citas.",
        ),
        (
            "resolve_temporal",
            "temporal_analyst",
            ("retrieve",),
            "Resolver versiones vigentes y supersessiones.",
        ),
        (
            "analyze_policy",
            "policy_analyst",
            ("retrieve",),
            "Interpretar políticas/reglas aplicables.",
        ),
        (
            "detect_conflicts",
            "conflict_detector",
            ("analyze_sources", "resolve_temporal", "analyze_policy"),
            "Detectar contradicciones estructurales entre fuentes.",
        ),
        (
            "synthesize",
            "synthesizer",
            ("detect_conflicts",),
            "Sintetizar distinguiendo hechos, conflictos e incertidumbre.",
        ),
        (
            "critique",
            "critic",
            ("synthesize",),
            "Criticar la síntesis: citas débiles, saltos, fuentes omitidas.",
        ),
        (
            "verify",
            "fact_checker",
            ("critique",),
            "Verificar claims finales contra evidencia.",
        ),
    ),
    ComplexityLevel.L5_DEEP_INVESTIGATION: (
        (
            "locate_sources",
            "librarian",
            (),
            "Construir el SourceSet completo (histórico + vigente).",
        ),
        (
            "retrieve",
            "retrieval_strategist",
            ("locate_sources",),
            "Recuperar evidencia masiva con presupuesto acotado.",
        ),
        (
            "analyze_sources",
            "document_analyst",
            ("retrieve",),
            "Extraer hechos, obligaciones y cambios por documento.",
        ),
        (
            "resolve_temporal",
            "temporal_analyst",
            ("retrieve",),
            "Reconstruir la línea temporal y versiones vigentes.",
        ),
        (
            "analyze_policy",
            "policy_analyst",
            ("retrieve",),
            "Cruzar con políticas y reglas aprobadas.",
        ),
        (
            "analyze_relationships",
            "relationship_analyst",
            ("analyze_sources",),
            "Mapear relaciones entre documentos/entidades (modifies, supersedes).",
        ),
        (
            "analyze_data",
            "data_analyst",
            ("retrieve",),
            "Consultar datos estructurados relacionados (SQL con semantic guard).",
        ),
        (
            "detect_conflicts",
            "conflict_detector",
            (
                "analyze_sources",
                "resolve_temporal",
                "analyze_policy",
                "analyze_relationships",
            ),
            "Detectar contradicciones y desactualización.",
        ),
        (
            "synthesize",
            "synthesizer",
            ("detect_conflicts", "analyze_data"),
            "Sintetizar la investigación profunda con evidencia.",
        ),
        (
            "critique",
            "critic",
            ("synthesize",),
            "Crítica adversarial del resultado.",
        ),
        (
            "verify",
            "fact_checker",
            ("critique",),
            "Verificación final claim→evidencia.",
        ),
    ),
}

_LEVEL_BUDGETS: dict[ComplexityLevel, CognitiveBudget] = {
    ComplexityLevel.L0_DIRECT: CognitiveBudget(
        max_agents=1, max_llm_calls=2, max_tokens=4000, max_cost_usd=0.05,
        max_seconds=20, max_tool_calls=2,
    ),
    ComplexityLevel.L1_RETRIEVAL: CognitiveBudget(
        max_agents=2, max_llm_calls=4, max_tokens=8000, max_cost_usd=0.15,
        max_seconds=45, max_tool_calls=6,
    ),
    ComplexityLevel.L2_ANALYSIS: CognitiveBudget(
        max_agents=4, max_llm_calls=8, max_tokens=16000, max_cost_usd=0.5,
        max_seconds=90, max_tool_calls=12,
    ),
    ComplexityLevel.L3_MULTI_SOURCE: CognitiveBudget(
        max_agents=5, max_llm_calls=10, max_tokens=24000, max_cost_usd=0.9,
        max_seconds=120, max_tool_calls=16,
    ),
    ComplexityLevel.L4_MULTI_SPECIALIST: CognitiveBudget(
        max_agents=9, max_llm_calls=20, max_tokens=48000, max_cost_usd=2.0,
        max_seconds=240, max_tool_calls=30,
    ),
    ComplexityLevel.L5_DEEP_INVESTIGATION: CognitiveBudget(
        max_agents=11, max_llm_calls=30, max_tokens=72000, max_cost_usd=3.0,
        max_seconds=360, max_tool_calls=45,
    ),
}


@dataclass(frozen=True, kw_only=True)
class CognitivePlan:
    run: CognitiveRun
    graph: CognitiveTaskGraph
    definitions: tuple[KnowledgeAgentDefinition, ...]
    budget: CognitiveBudget


class KnowledgeCognitiveOrchestrator:
    """Supervisor de planificación: complejidad → especialistas → DAG."""

    def __init__(self, registry: KnowledgeAgentRegistry | None = None) -> None:
        self._registry = registry or default_registry()

    def plan(
        self,
        *,
        query: str,
        scope: CognitiveScope,
        budget: CognitiveBudget | None = None,
        created_by: UUID | None = None,
    ) -> CognitivePlan:
        level = classify_complexity(query)
        effective = budget or _LEVEL_BUDGETS[level]
        blueprint = _TASK_BLUEPRINTS[level]

        agent_ids = sorted({agent_id for _, agent_id, _, _ in blueprint})
        if len(agent_ids) > effective.max_agents:
            raise ValueError(
                f"budget.max_agents={effective.max_agents} insufficient for "
                f"{level.value} ({len(agent_ids)} specialists)"
            )
        definitions: list[KnowledgeAgentDefinition] = []
        for agent_id in agent_ids:
            definition = self._registry.get(agent_id)
            if definition is None:
                raise ValueError(f"agent '{agent_id}' is not registered")
            definitions.append(definition)

        run_id: UUID = uuid4()
        tasks = tuple(
            CognitiveTask(
                run_id=run_id,
                key=key,
                description=description,
                agent_id=agent_id,
                depends_on=depends_on,
                position=position,
                budget=effective,
                input_scope=scope.to_dict(),
            )
            for position, (key, agent_id, depends_on, description) in enumerate(
                blueprint
            )
        )
        graph = CognitiveTaskGraph(tasks=tasks)

        run = CognitiveRun(
            id=run_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            query=query,
            complexity=level,
            status=CognitiveRunStatus.PLANNED,
            budget=effective,
            scope=scope.to_dict(),
            plan={
                "task_count": len(tasks),
                "agents": agent_ids,
                "topological_order": list(graph.topological_order()),
            },
            created_by=created_by,
        )
        return CognitivePlan(
            run=run,
            graph=graph,
            definitions=tuple(definitions),
            budget=effective,
        )
