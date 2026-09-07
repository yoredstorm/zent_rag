# =============================================================================
# Query Understanding — intención, entidades, conceptos, ambigüedad
# =============================================================================
# Identifica qué pide la pregunta ANTES de decidir estrategia. Nunca inventa
# definiciones empresariales: los conceptos detectados se resuelven contra el
# registro de definiciones aprobadas (business_definitions).
# =============================================================================
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from src.core.domain.intelligence import QueryUnderstanding
from src.intelligence.concept_classification import ConceptClassifier

_CLASSIFIER = ConceptClassifier()

_INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "business_metric",
        (
            r"\bcu[áa]nt", r"\btotal(es)?\b", r"\bsuma(s)?\b", r"\bsum\b",
            r"\bpromedio(s)?\b", r"\bmedia(s)?\b", r"\bm[ée]dio(s)?\b",
            r"\bventas", r"\bmargen(es)?\b",
            r"\bingresos", r"\bgastos", r"\bganancias", r"\bganancia",
            r"\brentable", r"\brentabilidad", r"\bproyecci[oó]n(es)?\b",
            r"\bestad[íi]sticas", r"\bporcentaje(s)?\b", r"\b%", r"\btop\b",
            r"\branking", r"\bfacturaci[oó]n", r"\bm[oó]dulo(s)?\b",
            r"\bcr[ée]dito(s)?\b", r"\bdeuda(s)?\b", r"\bvencimiento(s)?\b",
            r"\bcostos", r"\bcosto\b", r"\bprecio(s)?\b", r"\bflete(s)?\b",
            r"\bdemanda(s)?\b",
        ),
    ),
    (
        "operational_status",
        (
            r"\bestado(s)?\b", r"\bestatus\b", r"\bd[oó]nde est[áa]",
            r"\brastrear", r"\brastreo", r"\benv[íi]o(s)?\b", r"\bentrega(s)?\b",
            r"\bdirecci[oó]n de entrega", r"\bcu[áa]ndo llega", r"\bseguimiento(s)?\b",
            r"\btracking", r"\bdisponible(s)?\b", r"\bstock", r"\binventario(s)?\b",
            r"\bexistencia(s)?\b",
        ),
    ),
    (
        "document_policy",
        (
            r"\bpol[íi]tica(s)?\b", r"\bregla(s)?\b", r"\brequisito(s)?\b",
            r"\bqu[ée] dice", r"\bmanual(es)?\b", r"\bgu[íi]a(s)?\b",
            r"\bprocedimiento(s)?\b", r"\bcondicion(es)?\b",
            r"\bdevoluci[oó]n(es)?\b", r"\breembolso(s)?\b",
            r"\bgarant[íi]a(s)?\b", r"\bpermiso(s)?\b", r"\bprohibido(s)?\b",
            r"\bnormativa(s)?\b",
        ),
    ),
    (
        "concept_definition",
        (
            r"\bqu[ée] significa", r"\bqu[ée] es\b", r"\bqu[ée] se considera",
            r"\bdefinici[oó]n de", r"\bsignificado de", r"\bc[oó]mo se define",
            r"\bc[oó]mo definimos", r"\bqu[ée] entiende",
        ),
    ),
]

_INTENT_HINTS: dict[str, tuple[str, ...]] = {
    "business_metric": ("agregación", "métrica", "dimensión", "período"),
    "document_policy": ("política", "documento", "norma", "manual"),
    "operational_status": ("estado", "operación", "seguimiento"),
    "concept_definition": ("definición", "semántica"),
}

_CONCEPT_CANDIDATE_RE = re.compile(
    r"\b(?:cliente|clientes|venta|ventas|margen|stock|inventario|producto|"
    r"productos|pedido|pedidos|orden|ordenes|ordenes|empleado|empleados|"
    r"proveedor|proveedores|factura|facturas|ingreso|ingresos|gasto|gastos|"
    r"costo|costos|categoria|categor[ií]a|categor[ií]as|sucursal|sucursales|"
    r"canal|canales|region|regi[oó]n|regiones|marca|marcas|campa[ñn]a|"
    r"descuento|descuentos|devoluci[oó]n|devoluciones|subscription|"
    r"suscripci[oó]n|suscripciones|activo|activos|rentable|rentables|"
    r"corporativo|corporativos|prioridad|urgencia|estado|status)\b",
    re.IGNORECASE,
)

_LLM_UNDERSTAND_PROMPT = """Eres el módulo QueryUnderstanding de un sistema RAG empresarial.
Analiza la pregunta del usuario y responde SOLO con JSON válido (sin markdown):

{{
  "intent": "business_metric | document_policy | operational_status | concept_definition | general",
  "entities": ["nombres de entidades mencionadas (personas, productos, clientes, ...)"],
  "concepts": ["conceptos empresariales mencionados (en minúsculas, snake_case)"],
  "time_scope": "current | past | period | range | null",
  "requires_structured_data": true,
  "requires_documents": false,
  "requires_tools": false,
  "ambiguity": false,
  "clarifying_question": "pregunta que desambigüe en UNA pregunta, o null si no aplica"
}}

Pregunta del usuario:
{question}
"""


_CONCEPT_DEFINITION_MARKERS = _INTENT_PATTERNS[3][1]

# Marcadores FUERTES de policy (sustantivos inequívocos). "devolución",
# "reembolso", "garantía" son ambiguos (pueden ser métricas de negocio) y solo
# puntúan en la clasificación por score, no en el early-return.
_STRONG_DOCUMENT_POLICY_MARKERS = (
    r"\bpol[íi]tica(s)?\b",
    r"\bregla(s)?\b",
    r"\brequisito(s)?\b",
    r"\bqu[ée] dice\b",
    r"\bmanual(es)?\b",
    r"\bgu[íi]a(s)?\b",
    r"\bprocedimiento(s)?\b",
    r"\bnormativa(s)?\b",
    r"\bprohibido(s)?\b",
    r"\bpermiso(s)?\b",
    r"\bcondicion(es)? de\b",
)
_OPERATIONAL_STATUS_MARKERS = _INTENT_PATTERNS[1][1]


def _detect_intent(text: str) -> tuple[str, list[str]]:
    lowered = text.lower()
    # Marcadores fuertes de intención (definición/política): dominan siempre.
    if any(re.search(p, lowered) for p in _CONCEPT_DEFINITION_MARKERS):
        return "concept_definition", [p for p in _CONCEPT_DEFINITION_MARKERS if re.search(p, lowered)]
    if any(re.search(p, lowered) for p in _STRONG_DOCUMENT_POLICY_MARKERS):
        return "document_policy", [p for p in _STRONG_DOCUMENT_POLICY_MARKERS if re.search(p, lowered)]
    business_signals = [p for p in _INTENT_PATTERNS[0][1] if re.search(p, lowered)]
    operational_signals = [p for p in _OPERATIONAL_STATUS_MARKERS if re.search(p, lowered)]
    if operational_signals and not business_signals:
        return "operational_status", operational_signals
    signals: list[str] = []
    best_intent = "general"
    best_score = 0
    for intent, patterns in _INTENT_PATTERNS:
        score = sum(1 for p in patterns if re.search(p, lowered))
        if score > best_score:
            best_score = score
            best_intent = intent
            signals = [p for p in patterns if re.search(p, lowered)]
    if best_intent == "general" and re.search(r"\bcu[aá]l es\b|\bcu[aá]les son\b", lowered):
        best_intent = "business_metric"
    return best_intent, signals


def _detect_time_scope(text: str) -> str | None:
    lowered = text.lower()
    if re.search(
        r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
        r"octubre|noviembre|diciembre)\b|\bq[1-4]\b|\b20\d\d\b|\bmes pasado\b|"
        r"\b[úu]ltimo mes\b|\b[úu]ltimos? (d[ií]as|meses)\b|\bhoy\b|\bayer\b",
        lowered,
    ):
        return "past"
    if re.search(r"\bactualmente\b|\bhoy\b|\bactual\b|\bhasta ahora\b", lowered):
        return "current"
    if re.search(r"\bproyecci[oó]n\b|\bpr[oó]ximo\b|\bfuturo\b|\bestimaci[oó]n\b", lowered):
        return "future"
    return None


def _extract_candidate_concepts(text: str) -> list[str]:
    lowered = text.lower()
    found = [m.group(0).lower() for m in _CONCEPT_CANDIDATE_RE.finditer(lowered)]
    unique: list[str] = []
    for c in found:
        if c not in unique:
            unique.append(c)
    return unique


def _parse_llm_json(content: str) -> dict[str, Any] | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


class QueryUnderstandingService:
    """Capa de comprensión de consultas (determinista + LLM opcional)."""

    def __init__(
        self,
        llm_provider: Any | None = None,
        concept_llm_enabled: bool = True,
    ) -> None:
        self._llm = llm_provider
        self._concept_llm_enabled = concept_llm_enabled

    def understand_deterministic(self, query: str) -> QueryUnderstanding:
        intent, signals = _detect_intent(query)
        concepts = _extract_candidate_concepts(query)
        concept_types, requires_definition = _CLASSIFIER.classify_many(
            concepts, intent=intent
        )
        time_scope = _detect_time_scope(query)
        requires_structured = intent == "business_metric"
        requires_documents = intent in ("document_policy", "concept_definition")
        requires_tools = intent == "operational_status"
        return QueryUnderstanding(
            intent=intent,
            entities=[],
            concepts=concepts,
            concept_types=concept_types,
            requires_definition=requires_definition,
            time_scope=time_scope,
            requires_structured_data=requires_structured,
            requires_documents=requires_documents,
            requires_tools=requires_tools,
            ambiguity=False,
            extraction_source="deterministic",
            raw={"signals": signals},
        )

    async def understand(
        self,
        query: str,
        resolve_concepts: Callable[[list[str]], Awaitable[dict[str, bool]]] | None = None,
        use_llm: bool = True,
    ) -> QueryUnderstanding:
        understanding = self.understand_deterministic(query)

        if (
            use_llm
            and self._llm is not None
            and self._concept_llm_enabled
        ):
            try:
                resp = await self._llm.generate(
                    prompt=_LLM_UNDERSTAND_PROMPT.format(question=query[:3000]),
                    max_tokens=256,
                    temperature=0.0,
                )
                parsed = _parse_llm_json(resp.content or "")
                if parsed:
                    understanding = self._merge_llm(understanding, parsed)
            except Exception:  # noqa: BLE001 — el fallback determinista nunca falla
                pass

        if resolve_concepts is not None and understanding.concepts:
            try:
                understanding.resolved_concepts = await resolve_concepts(
                    understanding.concepts
                )
            except Exception:  # noqa: BLE001
                understanding.resolved_concepts = {
                    c: False for c in understanding.concepts
                }
        return understanding

    @staticmethod
    def _merge_llm(
        base: QueryUnderstanding, parsed: dict[str, Any]
    ) -> QueryUnderstanding:
        intent = str(parsed.get("intent") or base.intent)
        if intent not in _INTENT_HINTS:
            intent = base.intent
        concepts = [str(c).strip().lower() for c in (parsed.get("concepts") or [])]
        concepts = [c for c in concepts if c and len(c) <= 160]
        concepts = concepts or list(base.concepts)
        entities = [str(e).strip() for e in (parsed.get("entities") or [])]
        entities = [e for e in entities if e]
        clarifying = parsed.get("clarifying_question")
        if clarifying is not None:
            clarifying = str(clarifying).strip()
            # El LLM a veces devuelve el literal "null"/"none" en vez de JSON null.
            if not clarifying or clarifying.lower() in ("null", "none", "n/a"):
                clarifying = None
        ambiguity = bool(parsed.get("ambiguity")) or (
            clarifying is not None
        )
        time_scope = parsed.get("time_scope")
        if not time_scope or str(time_scope).strip().lower() == "null":
            time_scope = base.time_scope
        # Classify after merge — never treat all LLM concepts as definitional.
        concept_types, requires_definition = _CLASSIFIER.classify_many(
            concepts, intent=intent
        )
        return QueryUnderstanding(
            intent=intent,
            entities=entities,
            concepts=concepts,
            concept_types=concept_types,
            requires_definition=requires_definition,
            time_scope=str(time_scope) if time_scope else None,
            requires_structured_data=bool(
                parsed.get("requires_structured_data", base.requires_structured_data)
            ),
            requires_documents=bool(
                parsed.get("requires_documents", base.requires_documents)
            ),
            requires_tools=bool(parsed.get("requires_tools", base.requires_tools)),
            ambiguity=ambiguity,
            clarifying_question=str(clarifying).strip() if clarifying else None,
            extraction_source="llm",
            raw=parsed,
        )
