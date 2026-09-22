# =============================================================================
# Pattern signature — determinística. No usa el texto del prompt.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

_SLUG = re.compile(r"[^a-z0-9._]+")
_MAX_PART = 64

_FIELD_MARKERS = (
    "posición",
    "posicion",
    "columna",
    "campo",
    "cell ",
    "field position",
    "column ",
)
_DEFINITION_MARKERS = (
    "qué es",
    "que es",
    "qué significa",
    "definic",
    "what is",
    "what does",
)
_AGG_MARKERS = (
    "suma",
    "total",
    "promedio",
    "count",
    "agrupa",
    "group by",
    "cuántos",
    "cuantos",
)
_ID_MARKERS = ("sku", "código", "codigo", "identifier", "id exacto")


@dataclass(frozen=True, kw_only=True)
class PatternFeatures:
    """Dimensiones normalizadas. Un prompt largo no es una dimensión."""

    intent_family: str = ""
    source_type: str = ""
    retrieval_modality: str = ""
    tool_family: str = ""
    failure_category: str = ""

    def normalized(self) -> PatternFeatures:
        return PatternFeatures(
            intent_family=_slug(self.intent_family, empty="unknown_intent"),
            source_type=_slug(self.source_type, empty="unknown_source"),
            retrieval_modality=_slug(self.retrieval_modality, empty="unknown_retrieval"),
            tool_family=_slug(self.tool_family, empty="none"),
            failure_category=_slug(self.failure_category, empty="none"),
        )


def _slug(value: str, *, empty: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return empty
    # Un prompt no puede colarse como firma: frases largas caen a unclassified.
    if len(text) > _MAX_PART or text.count(" ") >= 4:
        return "unclassified"
    cleaned = _SLUG.sub("_", text).strip("_")
    if not cleaned or len(cleaned) > _MAX_PART:
        return "unclassified"
    return cleaned


def pattern_signature(features: PatternFeatures) -> str:
    item = features.normalized()
    return "|".join(
        (
            item.intent_family,
            item.source_type,
            item.retrieval_modality,
            item.tool_family,
            item.failure_category,
        )
    )


def pattern_key(features: PatternFeatures) -> str:
    item = features.normalized()
    if item.failure_category == "sql.schema_mismatch" and item.tool_family not in {"", "none"}:
        return "agent_tool_retry_schema_error"
    if item.intent_family not in {"", "unknown_intent", "unclassified"}:
        return item.intent_family
    if item.failure_category not in {"", "none", "unclassified"}:
        return item.failure_category.replace(".", "_")
    return "unspecified_pattern"


def infer_pattern_features(
    text: str,
    *,
    sql_enabled: bool = False,
    tool_family: str = "",
    failure_category: str = "",
) -> PatternFeatures:
    """Señales léxicas cortas. El texto completo no entra en la firma."""
    lowered = (text or "").lower()
    intent = ""
    source = ""
    retrieval = ""
    if any(marker in lowered for marker in _FIELD_MARKERS):
        intent, source, retrieval = "structured_field_lookup", "tabular", "structured_exact"
    elif any(marker in lowered for marker in _DEFINITION_MARKERS):
        intent, source, retrieval = "knowledge_definition", "knowledge", "hybrid"
    elif any(marker in lowered for marker in _AGG_MARKERS):
        intent, source, retrieval = "database_aggregation", "database", "structured_exact"
    elif any(marker in lowered for marker in _ID_MARKERS):
        intent, source, retrieval = "exact_identifier_query", "database", "structured_exact"
    elif sql_enabled:
        source = "database"
    return PatternFeatures(
        intent_family=intent,
        source_type=source,
        retrieval_modality=retrieval,
        tool_family=tool_family,
        failure_category=failure_category,
    )
