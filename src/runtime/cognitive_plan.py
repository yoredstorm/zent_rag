# =============================================================================
# Cognitive Plan — qué tipo de conocimiento necesita la consulta (brief §2).
# =============================================================================
# Determinista y sin I/O. No ejecuta nada: declara capacidades con su razón.
# El runtime lo traza (shadow) y las fases siguientes lo usan para rutear
# retrieval, JEV y profundidad de razonamiento.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from src.core.domain.cognitive import ComplexityLevel, classify_complexity
from src.rag.retrieval.planner import RetrievalPlan, build_retrieval_plan


class KnowledgeNeed(StrEnum):
    """Capacidades de conocimiento del brief §2 (las que aplican al runtime)."""

    SEMANTIC_SEARCH = "semantic_search"
    EXACT_LOOKUP = "exact_lookup"
    STRUCTURED_QUERY = "structured_query"
    GRAPH_TRAVERSAL = "graph_traversal"
    TEMPORAL_LOOKUP = "temporal_lookup"
    CROSS_DOCUMENT_REASONING = "cross_document_reasoning"
    RULE_LOOKUP = "rule_lookup"
    CONFLICT_RESOLUTION = "conflict_resolution"
    COMPARISON = "comparison"
    AGGREGATION = "aggregation"
    CALCULATION = "calculation"
    EXTERNAL_TOOL = "external_tool"
    MEMORY = "memory"
    NO_RETRIEVAL = "no_retrieval"


@dataclass(frozen=True)
class PlanStep:
    need: KnowledgeNeed
    reason: str

    def to_public_dict(self) -> dict:
        return {"need": self.need.value, "reason": self.reason}


@dataclass(frozen=True)
class CognitivePlan:
    query: str
    complexity: ComplexityLevel
    needs: tuple[KnowledgeNeed, ...]
    steps: tuple[PlanStep, ...]

    @property
    def requires_knowledge(self) -> bool:
        return KnowledgeNeed.NO_RETRIEVAL not in self.needs

    def to_public_dict(self) -> dict:
        return {
            "complexity": self.complexity.value,
            "needs": [need.value for need in self.needs],
            "steps": [step.to_public_dict() for step in self.steps],
            "requires_knowledge": self.requires_knowledge,
        }


_GREETING = re.compile(
    r"^(hola|buenas|buenos d[ií]as|buenas tardes|buenas noches|hello|hi|hey|gracias)\b",
    flags=re.IGNORECASE,
)
_AGGREGATION = (
    "total",
    "suma",
    "sum",
    "average",
    "promedio",
    "cuántos",
    "cuantos",
    "count",
    "máximo",
    "maximo",
    "maximum",
    "mínimo",
    "minimo",
    "minimum",
)
_CALCULATION = ("calcula", "calculate", "porcentaje", "percent", "%")
_RULE = ("regla", "rule", "norma", "política", "politica", "policy", "aplica", "applies")
_CONFLICT = (
    "conflicto",
    "conflictos",
    "contradic",
    "contradice",
    "inconsistencia",
    "inconsistency",
)
_COMPARISON = (
    "compara",
    "comparar",
    "comparación",
    "comparacion",
    "versus",
    " vs ",
    "diferencia",
    "compare",
)
_CROSS_DOCUMENT = (
    "entre documentos",
    "cross-document",
    "todas las fuentes",
    "múltiples fuentes",
    "multiples fuentes",
)
_MEMORY = (
    "recuerda",
    "remember",
    "la vez pasada",
    "conversación anterior",
    "conversacion anterior",
    "mensajes anteriores",
)
_EXTERNAL_TOOL = (
    "envía",
    "envia",
    "send",
    "crea ",
    "create ",
    "actualiza ",
    "update ",
    "ejecuta",
    "ticket",
    "correo",
    "email",
)


def _first_marker(text: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in text:
            return marker
    return None


def build_cognitive_plan(
    query: str,
    *,
    retrieval_plan: RetrievalPlan | None = None,
) -> CognitivePlan:
    """Plan determinista de necesidades. Reglas explícitas, sin LLM."""
    text = " ".join((query or "").strip().split())
    lowered = text.lower()
    plan = retrieval_plan if retrieval_plan is not None else build_retrieval_plan(text)
    steps: list[PlanStep] = []

    def add(need: KnowledgeNeed, reason: str) -> None:
        if all(step.need is not need for step in steps):
            steps.append(PlanStep(need=need, reason=reason))

    if text and _GREETING.match(lowered) and "?" not in text and len(lowered.split()) <= 6:
        add(KnowledgeNeed.NO_RETRIEVAL, "saludo o cortesía sin consulta de conocimiento")
        return CognitivePlan(
            query=text,
            complexity=classify_complexity(text),
            needs=tuple(step.need for step in steps),
            steps=tuple(steps),
        )

    add(KnowledgeNeed.SEMANTIC_SEARCH, "búsqueda semántica base sobre el índice")
    if plan.includes("structured"):
        add(
            KnowledgeNeed.STRUCTURED_QUERY,
            f"la consulta pide datos estructurados ('{plan.structured_intent}')",
        )
    if plan.includes("exact"):
        literales = ", ".join(plan.exact_needles[:3])
        add(KnowledgeNeed.EXACT_LOOKUP, f"la consulta contiene literales exactos: {literales}")
    if plan.includes("temporal"):
        add(
            KnowledgeNeed.TEMPORAL_LOOKUP,
            f"la consulta es temporal ('{plan.temporal_intent}')",
        )
    if plan.includes("graph"):
        entidades = ", ".join(plan.entity_mentions[:3])
        add(KnowledgeNeed.GRAPH_TRAVERSAL, f"menciona entidades del grafo: {entidades}")

    comparison = _first_marker(lowered, _COMPARISON)
    if comparison:
        add(KnowledgeNeed.COMPARISON, f"la consulta pide comparar ('{comparison}')")
        add(
            KnowledgeNeed.CROSS_DOCUMENT_REASONING,
            "comparar exige relacionar más de una fuente",
        )
    cross = _first_marker(lowered, _CROSS_DOCUMENT)
    if cross:
        add(
            KnowledgeNeed.CROSS_DOCUMENT_REASONING,
            f"la consulta cruza documentos ('{cross}')",
        )
    rule = _first_marker(lowered, _RULE)
    if rule:
        add(KnowledgeNeed.RULE_LOOKUP, f"la consulta refiere a una regla ('{rule}')")
    conflict = _first_marker(lowered, _CONFLICT)
    if conflict:
        add(
            KnowledgeNeed.CONFLICT_RESOLUTION,
            f"la consulta menciona conflicto ('{conflict}')",
        )
    aggregation = _first_marker(lowered, _AGGREGATION)
    if aggregation:
        add(KnowledgeNeed.AGGREGATION, f"la consulta pide agregar valores ('{aggregation}')")
    calculation = _first_marker(lowered, _CALCULATION)
    if calculation:
        add(KnowledgeNeed.CALCULATION, f"la consulta pide un cálculo ('{calculation}')")
    tool = _first_marker(lowered, _EXTERNAL_TOOL)
    if tool:
        add(KnowledgeNeed.EXTERNAL_TOOL, f"la consulta pide una acción externa ('{tool}')")
    memory = _first_marker(lowered, _MEMORY)
    if memory:
        add(
            KnowledgeNeed.MEMORY,
            f"la consulta apela a memoria de conversación ('{memory}')",
        )

    return CognitivePlan(
        query=text,
        complexity=classify_complexity(text),
        needs=tuple(step.need for step in steps),
        steps=tuple(steps),
    )
