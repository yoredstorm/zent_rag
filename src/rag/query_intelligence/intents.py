# =============================================================================
# Knowledge V2 — Query Intelligence (Phase F slice 1)
# =============================================================================
# Clasificación determinista de la intención de la consulta (brief §11) y
# QueryPlan estructurado (brief §12). La estrategia de retrieval cambia según
# intención; la expansión LLM controlada se añade en un slice posterior
# (nunca cambia la intención del usuario; las queries inventadas se rechazan).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Intenciones iniciales (brief §11)
INTENT_FACTUAL = "FACTUAL"
INTENT_SUMMARY = "SUMMARY"
INTENT_COMPARISON = "COMPARISON"
INTENT_MULTI_DOCUMENT = "MULTI_DOCUMENT"
INTENT_TEMPORAL = "TEMPORAL"
INTENT_EXPLANATION = "EXPLANATION"
INTENT_LIST = "LIST"
INTENT_DEFINITION = "DEFINITION"
INTENT_ANALYTICAL = "ANALYTICAL"
INTENT_NAVIGATION = "NAVIGATION"

KNOWLEDGE_INTENTS = (
    INTENT_FACTUAL,
    INTENT_SUMMARY,
    INTENT_COMPARISON,
    INTENT_MULTI_DOCUMENT,
    INTENT_TEMPORAL,
    INTENT_EXPLANATION,
    INTENT_LIST,
    INTENT_DEFINITION,
    INTENT_ANALYTICAL,
    INTENT_NAVIGATION,
)

# Orden = prioridad de matching (primera que gana).
_INTENT_RULES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        INTENT_NAVIGATION,
        (
            re.compile(r"\b(dónde|donde)\b", re.IGNORECASE),
            re.compile(
                r"\b(página|pagina|sección|seccion|párrafo|parrafo|indice|índice)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bnavigate\b|\blocate\b", re.IGNORECASE),
        ),
    ),
    (
        INTENT_COMPARISON,
        (
            re.compile(
                r"\b(compara|comparar|compare|comparison|diferencia[s]?|versus|vs\.?)\b",
                re.IGNORECASE,
            ),
            re.compile(r"(?<!por )qué cambió|cambios (entre|en)", re.IGNORECASE),
        ),
    ),
    (
        INTENT_MULTI_DOCUMENT,
        (
            re.compile(r"\b(contratos|adenda|versión|versiones|documentos)\b", re.IGNORECASE),
            re.compile(
                r"\bbetween .+ and\b|\bentre (el|la|los|las) .+ y (el|la|los|las)\b",
                re.IGNORECASE,
            ),
        ),
    ),
    (
        INTENT_TEMPORAL,
        (
            re.compile(
                r"\b(cuándo|cuando|fecha|vigente|vigencia|vence|vencim|"
                r"efectiv|válido|valido|temporal)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\b(19|20)\d{2}\b"),
            re.compile(r"\b(desde|hasta|prorrog|antig)\w*\b", re.IGNORECASE),
        ),
    ),
    (
        INTENT_DEFINITION,
        (
            re.compile(
                r"\b(qué es|que es|defini|definición|significa|se refiere)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bdefinition\b|\bmeaning\b|\bwhat is\b", re.IGNORECASE),
        ),
    ),
    (
        INTENT_EXPLANATION,
        (
            re.compile(
                r"\b(por qué|porque|explica|explicar|por qué motivo)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bexplain\b|\bwhy\b|\bhow does\b|\bcómo se\b|\bproceso de\b",
                re.IGNORECASE,
            ),
        ),
    ),
    (
        INTENT_LIST,
        (
            re.compile(r"\b(list[ao]|lista|enumera|cuáles son|cuales son)\b", re.IGNORECASE),
            re.compile(
                r"\b(list|enumerate|which (documents|clauses|obligations|requirements))\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bqué (obligaciones|cláusulas|requisitos|riesgos|fechas)\b", re.IGNORECASE),
        ),
    ),
    (
        INTENT_ANALYTICAL,
        (
            re.compile(
                r"\b(análisis|analiz|tendencia|métric|métricas|promedio|total de|forecast|proyección)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(average|trend|metric|total|percent|forecast)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\d+(\.\d+)?\s*%"),
        ),
    ),
    (
        INTENT_SUMMARY,
        (
            re.compile(r"\b(resume|resumen|resumir|sintetiza|resumido)\b", re.IGNORECASE),
            re.compile(r"\b(summa|synth|condensa)\w*\b", re.IGNORECASE),
            re.compile(
                r"\bde qué trata\b|\bquién está involucrado\b|\bquién firma\b",
                re.IGNORECASE,
            ),
        ),
    ),
)


@dataclass(frozen=True, kw_only=True)
class QueryPlan:
    """Plan estructurado de la consulta (brief §12)."""

    intent: str
    original_query: str
    search_queries: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    date_filters: dict = field(default_factory=dict)
    source_filters: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()

    @property
    def normalized_intent(self) -> str:
        return self.intent.upper()


def classify_intent(query: str) -> str:
    """Clasifica deterministamente la intención (FACTUAL por defecto)."""
    if not query or not query.strip():
        return INTENT_FACTUAL
    text = " " + query.strip() + " "
    for intent, patterns in _INTENT_RULES:
        if any(pattern.search(text) for pattern in patterns):
            return intent
    return INTENT_FACTUAL


def build_query_plan(query: str) -> QueryPlan:
    """Construye el QueryPlan determinista (sin expansión LLM en este slice).

    Regla: la expansión controlada (futuro) NUNCA modifica la intención del
    usuario ni ejecuta consultas inventadas sin límites.
    """
    intent = classify_intent(query)
    entities: list[str] = _extract_entities(query)
    date_filters = _extract_date_filters(query)
    return QueryPlan(
        intent=intent,
        original_query=query,
        search_queries=(query,),
        entities=tuple(entities),
        date_filters=date_filters,
        source_filters=(),
        required_evidence=("page", "section_path"),
    )


_ENTITY_CANDIDATES_RE = (
    re.compile(r"\b(contrato|adenda|pol[ií]tica|manual|gu[ií]a|reglamento)\b", re.IGNORECASE),
    re.compile(r"\b(\d{4})\b"),  # años como candidates temporales/entidades
)


def _extract_entities(query: str) -> list[str]:
    found: list[str] = []
    for pattern in _ENTITY_CANDIDATES_RE:
        found.extend(match.group(1).lower() for match in pattern.finditer(query))
    return list(dict.fromkeys(found))


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _extract_date_filters(query: str) -> dict:
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(query)]
    date_filters: dict = {}
    if years:
        date_filters["year"] = years[0]
    if re.search(r"\b(vigente|vigencia)\b", query, re.IGNORECASE):
        date_filters["temporal"] = "current"
    elif re.search(r"\b(históric|historia|anterior)\b", query, re.IGNORECASE):
        date_filters["temporal"] = "historical"
    return date_filters
