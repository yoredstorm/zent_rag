# =============================================================================
# Retrieval — Knowledge Retrieval Planner
# =============================================================================
# El retrieval deja de ser "vector search y ya": el planner decide QUÉ
# representaciones consultar y POR QUÉ, con reglas deterministas y explicables.
#
#   VECTOR      similitud semántica sobre el índice denso/léxico (base)
#   EXACT       literales: códigos, bytes, identificadores, símbolos
#   STRUCTURED  datos exactos: tablas, columnas, filas, agregaciones
#   GRAPH       entidades y relaciones del Knowledge Graph
#   TEMPORAL    vigencias: "antes de", "en marzo de 2025", "vigente"
#
# Una consulta puede necesitar varias a la vez. El plan es evidencia para la
# traza ("Ver Flujo"), no una caja negra.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Representation(StrEnum):
    VECTOR = "vector"
    EXACT = "exact"
    STRUCTURED = "structured"
    GRAPH = "graph"
    TEMPORAL = "temporal"


@dataclass(kw_only=True)
class RetrievalPlan:
    """Representaciones a consultar, con la razón de cada elección."""

    query: str
    representations: tuple[str, ...]
    reasons: dict[str, str] = field(default_factory=dict)
    exact_needles: tuple[str, ...] = ()
    entity_mentions: tuple[str, ...] = ()
    temporal_intent: str | None = None
    structured_intent: str | None = None
    normalized: str = ""

    @property
    def primary(self) -> str:
        for candidate in (
            Representation.STRUCTURED.value,
            Representation.EXACT.value,
            Representation.TEMPORAL.value,
            Representation.GRAPH.value,
            Representation.VECTOR.value,
        ):
            if candidate in self.representations:
                return candidate
        return Representation.VECTOR.value

    def includes(self, representation: str) -> bool:
        return representation in self.representations

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "primary": self.primary,
            "representations": list(self.representations),
            "reasons": dict(self.reasons),
            "exact_needles": list(self.exact_needles),
            "entity_mentions": list(self.entity_mentions),
            "temporal_intent": self.temporal_intent,
            "structured_intent": self.structured_intent,
        }


_EXACT_LITERAL = re.compile(
    r"(&&&\w+|\bByte\s*\d{1,4}\b|\b[A-F0-9]{6,}\b|\b\d{1,3}\.\d{1,3}\b|"
    r"\b[A-Z]{2,}\d{2,}\b|\$\w+\b|%\w+\b)",
    flags=re.IGNORECASE,
)
_ENTITY_MENTION = re.compile(
    r"\b(?:Record|Registro|Category|Categor[ií]a|Cat|Byte|Table|Tabla|"
    r"Column|Columna|Section|Secci[oó]n)\s*[#nº°]?\s*(\d{1,4})\b",
    flags=re.IGNORECASE,
)
_TEMPORAL = re.compile(
    r"\b(before|after|until|since|as of|prior to|currently|current|"
    r"antes|despu[eé]s|hasta|desde|vigente|actualmente|en vigor|"
    r"cambi[oó]|reemplaz|supersed|derogad)\b",
    flags=re.IGNORECASE,
)
_STRUCTURED = re.compile(
    r"\b(total|sum|average|count|how many|maximum|minimum|list all|"
    r"total|suma|promedio|cu[aá]ntos|m[aá]ximo|m[ií]nimo|cu[aá]l es el valor|"
    r"columna|column|fila|row|hoja|sheet|tabla|table)\b",
    flags=re.IGNORECASE,
)
_CODE_LOOKUP = re.compile(r"\b[A-Z]{3,}\b")


def _needles(query: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _EXACT_LITERAL.finditer(query or ""):
        value = match.group(0).strip()
        if value and value not in found:
            found.append(value)
    if len(found) <= 4:
        for match in _CODE_LOOKUP.finditer(query or ""):
            value = match.group(0).strip()
            if len(value) >= 3 and value not in found:
                found.append(value)
            if len(found) >= 6:
                break
    return tuple(found[:6])


def build_retrieval_plan(query: str) -> RetrievalPlan:
    """Plan determinista y explicable para la consulta."""
    text = (query or "").strip()
    normalized = " ".join(text.lower().split())
    representations: list[str] = [Representation.VECTOR.value]
    reasons: dict[str, str] = {
        Representation.VECTOR.value: "similitud semántica sobre el índice base"
    }

    needles = _needles(text)
    if needles:
        representations.append(Representation.EXACT.value)
        reasons[Representation.EXACT.value] = (
            "la consulta contiene literales exactos: " + ", ".join(needles[:3])
        )

    mentions = tuple(
        dict.fromkeys(
            f"{match.group(0).strip()}" for match in _ENTITY_MENTION.finditer(text)
        )
    )
    if mentions:
        representations.append(Representation.GRAPH.value)
        reasons[Representation.GRAPH.value] = (
            "menciona entidades del grafo: " + ", ".join(mentions[:3])
        )

    temporal_intent = None
    temporal_match = _TEMPORAL.search(text)
    if temporal_match:
        temporal_intent = temporal_match.group(0).lower()
        representations.append(Representation.TEMPORAL.value)
        reasons[Representation.TEMPORAL.value] = (
            f"la consulta es temporal ('{temporal_intent}')"
        )

    structured_intent = None
    structured_match = _STRUCTURED.search(text)
    if structured_match:
        structured_intent = structured_match.group(0).lower()
        representations.append(Representation.STRUCTURED.value)
        reasons[Representation.STRUCTURED.value] = (
            f"la consulta pide datos exactos ('{structured_intent}')"
        )

    return RetrievalPlan(
        query=query,
        representations=tuple(dict.fromkeys(representations)),
        reasons=reasons,
        exact_needles=needles,
        entity_mentions=mentions,
        temporal_intent=temporal_intent,
        structured_intent=structured_intent,
        normalized=normalized,
    )


class KnowledgeRetrievalPlanner:
    """Fachada del planner para el pipeline de respuesta."""

    def plan(self, query: str) -> RetrievalPlan:
        return build_retrieval_plan(query)
