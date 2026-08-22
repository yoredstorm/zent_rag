# =============================================================================
# Query Normalization + Classification — heurísticas genéricas de idioma
# =============================================================================
# Sin dependencias de negocio vertical. Determina qué pata del retrieval
# debe dominar y opcionalmente el idioma para filtros metadata.language.
# =============================================================================
from __future__ import annotations

import re
import unicodedata

from src.rag.retrieval.models import QueryClassification

_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9]+")

# Stopwords funcionales mínimas ES/EN (no de negocio). Suficientes para
# detectar idioma y medir densidad lexical de la query.
_STOPWORDS_ES = {
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
    "que", "en", "a", "con", "para", "por", "es", "son", "del", "al", "se",
    "no", "si", "como", "su", "sus", "mi", "mis", "tu", "tus", "lo", "le",
    "me", "te", "nos", "hay", "fue", "ser", "estar", "está", "están",
    "cual", "cuál", "cuales", "cuáles", "qué", "cuando", "cuándo",
    "donde", "dónde", "quien", "quién", "quienes", "quiénes",
}
_STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "these", "those", "my", "your", "his", "her", "our", "their", "do",
    "does", "did", "not", "no", "what", "which", "who", "whom", "when",
    "where", "how", "at", "by", "from", "as", "if", "than", "then",
}
_ES_ACCENT_MARKERS = {"á", "é", "í", "ó", "ú", "ñ", "ü", "¿"}
_EN_MARKERS = {"w", "k"}

# Señales de query lexical-dominante: códigos, números, referencias internas.
_CODE_PATTERNS = (
    re.compile(r"\b[a-z]{1,4}[-\s]?\d{2,}\b", re.IGNORECASE),  # SKU-1234
    re.compile(r"\b\d{2,}\b"),  # cantidades / años / precios
    re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE),
)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def normalize_query(query: str) -> str:
    """Normaliza para la pata lexical: minúsculas, sin acentos, sin puntuación.

    La pata semántica SIEMPRE usa el texto original (el embedding necesita
    contexto y acentos). Esta normalización solo alimenta tokenización.
    """
    stripped = _strip_accents((query or "").lower())
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def detect_language(query: str) -> str | None:
    """Detecta idioma por stopwords y marcadores ortográficos (ES/EN).

    Devuelve "es", "en" o None si no hay señal suficiente. Nunca lanza.
    """
    text = (query or "").strip()
    if not text:
        return None
    lowered = text.lower()

    es_hits = sum(1 for m in _ES_ACCENT_MARKERS if m in text)
    if es_hits >= 2:
        return "es"

    tokens = _TOKEN_RE.findall(_strip_accents(lowered))
    if not tokens:
        return None
    es_stops = sum(1 for t in tokens if t in _STOPWORDS_ES)
    en_stops = sum(1 for t in tokens if t in _STOPWORDS_EN)
    if es_stops > en_stops and es_stops >= 1:
        return "es"
    if en_stops > es_stops and en_stops >= 1:
        return "en"
    if en_stops == 0 and es_stops == 0 and lowered[-1] == "?" and "¿" in text:
        return "es"
    return None


def classify_query(query: str) -> QueryClassification:
    """Clasifica la query para decidir el peso de cada pata.

    Heurística genérica (sin negocio):
      - Tokens tipo código/número → lexical-dominante.
      - Queries cortas sin stopwords → lexical-dominante.
      - Lenguaje natural con stopwords → semántica.
    """
    normalized = normalize_query(query)
    tokens = _TOKEN_RE.findall(normalized)
    if not tokens:
        return QueryClassification(kind="semantic", lexical_ratio=0.0,
                                   language=detect_language(query))

    code_hits = sum(1 for pattern in _CODE_PATTERNS if pattern.search(query))
    stop_hits = sum(
        1 for t in tokens if t in _STOPWORDS_ES or t in _STOPWORDS_EN
    )
    stop_ratio = stop_hits / len(tokens)

    lexical_signals = 0
    lexical_signals += min(code_hits, 2)
    if len(tokens) <= 3 and stop_ratio == 0.0:
        lexical_signals += 1

    if lexical_signals >= 2:
        ratio = 0.7
        kind = "lexical"
    elif lexical_signals == 1:
        ratio = 0.4
        kind = "mixed"
    else:
        ratio = 0.2
        kind = "semantic"

    return QueryClassification(
        kind=kind,
        lexical_ratio=ratio,
        language=detect_language(query),
    )
