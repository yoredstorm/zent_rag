# =============================================================================
# Query Planner — elección de estrategia ANTES de ejecutar herramientas
# =============================================================================
# Text-to-SQL NO es siempre la primera estrategia. El planner decide:
#   SQL | RAG | SQL_RAG | API_TOOL | MULTI_SOURCE | CLARIFICATION | ABSTAIN
# Usa señales deterministas del understanding + disponibilidad de fuentes.
# =============================================================================
from __future__ import annotations

import re

from src.core.domain.intelligence import PlanStrategy, QueryPlan, QueryUnderstanding
from src.core.domain.semantic import SemanticCompileResult, SemanticGapCode

_CAUSAL_RE = re.compile(
    r"\bpor qu[ée]\b|\bcausa\b|\bmotivo\b|\ba qu[ée] se debe\b|"
    r"\bpor qu[ée] cay[oó]\b|\bexplica la ca[ií]da\b|\braz[oó]n\b",
    re.IGNORECASE,
)


class QueryPlanner:
    """Produce un plan estructurado antes de ejecutar cualquier herramienta."""

    def plan(
        self,
        understanding: QueryUnderstanding,
        *,
        query: str = "",
        sql_available: bool,
        router_score: float | None = None,
        sql_router_threshold: float = 0.5,
        kb_available: bool = True,
        tools_available: bool = False,
        compile_result: SemanticCompileResult | None = None,
    ) -> QueryPlan:
        rationale: list[str] = []
        limitations: list[str] = []

        # 1) Sin ninguna fuente disponible -> ABSTAIN
        if not sql_available and not kb_available and not tools_available:
            return QueryPlan(
                strategy=PlanStrategy.ABSTAIN,
                steps=["abstain"],
                rationale=["Ninguna fuente disponible para esta consulta"],
                limitations=["No hay SQL, ni knowledge base, ni tools configuradas"],
            )

        # 2) Ambigüedad: con fuentes se recopila evidencia y el Answerability
        #    Gate decide la aclaración post-evidencia (responder con datos
        #    gana a frictionar al usuario). Sin fuentes -> CLARIFICATION.
        if understanding.ambiguity:
            rationale.append(
                "Ambigüedad detectada: recopilar evidencia antes de decidir aclaración"
            )

        if compile_result is not None:
            unresolved = [
                str(u.get("name"))
                for u in compile_result.unresolved_objects
                if u.get("code") == SemanticGapCode.CONTEXT_MISSING.value
            ]
            rationale.append(
                "Semantic AST compiled "
                f"(query_type={compile_result.semantic_ast.query_type})"
            )
            if compile_result.has_blocking_gaps:
                limitations.append(
                    "Semantic compiler: essential objects unresolved — "
                    "refuse invented physical relationships"
                )
        else:
            unresolved = [
                c
                for c, defined in (understanding.resolved_concepts or {}).items()
                if not defined
            ]

        if understanding.intent == "business_metric":
            if sql_available and (
                understanding.requires_structured_data
                or (router_score is not None and router_score >= sql_router_threshold)
            ):
                router_desc = (
                    f"router={router_score:.2f}"
                    if router_score is not None
                    else "sin score de router"
                )
                rationale.append(f"Intento business_metric con señales SQL ({router_desc})")
                causal = bool(_CAUSAL_RE.search(query))
                needs_docs = understanding.requires_documents or causal
                if needs_docs and kb_available:
                    return QueryPlan(
                        strategy=PlanStrategy.SQL_RAG,
                        steps=["sql", "retrieval", "merge", "research_plan"],
                        needs_sql=True,
                        needs_retrieval=True,
                        needs_semantic_resolution=bool(unresolved),
                        rationale=rationale
                        + [
                            "Pregunta causal/explicativa: SQL para el dato y RAG para el contexto",
                            "Analytical Reasoning: build Research Plan (Phase 29)",
                        ],
                    )
                return QueryPlan(
                    strategy=PlanStrategy.SQL,
                    steps=["sql"],
                    needs_sql=True,
                    needs_semantic_resolution=bool(unresolved),
                    rationale=rationale + ["Métrica agregada: SQL-first"],
                    limitations=["Sin contexto documental si la consulta lo necesita"],
                )
            if kb_available:
                return QueryPlan(
                    strategy=PlanStrategy.RAG,
                    steps=["retrieval"],
                    needs_retrieval=True,
                    needs_semantic_resolution=bool(unresolved),
                    rationale=["Sin SQL disponible o intención débil: RAG"],
                )
            return QueryPlan(
                strategy=PlanStrategy.ABSTAIN,
                steps=["abstain"],
                rationale=["Métrica solicitada sin fuente estructurada"],
                limitations=["No hay SQL disponible para métricas"],
            )

        if understanding.intent == "concept_definition":
            return QueryPlan(
                strategy=PlanStrategy.RAG,
                steps=["retrieval", "semantic_resolution"],
                needs_retrieval=True,
                needs_semantic_resolution=True,
                rationale=["Definición de concepto: conocimiento semántico / RAG"],
            )

        if understanding.intent == "document_policy":
            return QueryPlan(
                strategy=PlanStrategy.RAG,
                steps=["retrieval"],
                needs_retrieval=True,
                rationale=["Política/norma: búsqueda documental"],
            )

        if understanding.intent == "operational_status":
            if tools_available:
                return QueryPlan(
                    strategy=PlanStrategy.API_TOOL,
                    steps=["tool"],
                    needs_tools=True,
                    rationale=["Estado operacional: API / tool dedicada"],
                )
            if sql_available:
                return QueryPlan(
                    strategy=PlanStrategy.SQL,
                    steps=["sql"],
                    needs_sql=True,
                    rationale=["Estado operacional sin tool: consulta estructurada"],
                )
            if kb_available:
                return QueryPlan(
                    strategy=PlanStrategy.RAG,
                    steps=["retrieval"],
                    needs_retrieval=True,
                    rationale=["Estado operacional: contexto documental"],
                )
            return QueryPlan(
                strategy=PlanStrategy.ABSTAIN,
                steps=["abstain"],
                rationale=["Estado operacional sin fuente disponible"],
            )

        # 3) Intento general: prioridad a RAG; SQL como refuerzo si hay señales
        if sql_available and router_score is not None and router_score >= sql_router_threshold:
            return QueryPlan(
                strategy=PlanStrategy.SQL_RAG,
                steps=["sql", "retrieval", "merge"],
                needs_sql=True,
                needs_retrieval=True,
                rationale=["Consulta general con señales SQL y contexto documental"],
            )
        return QueryPlan(
            strategy=PlanStrategy.RAG,
            steps=["retrieval"],
            needs_retrieval=True,
            rationale=["Consulta general: RAG"],
        )
