# =============================================================================
# Hybrid Semantic Catalog Search — ranking explicable (Phase 27B)
# =============================================================================
# Distinto de HybridRetriever documental (src/rag/retrieval/hybrid.py).
# Combina lexical, embedding, business mapping, verified query, graph,
# historical success y authority con pesos configurables + ranking_signals.
# =============================================================================
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

_TOKEN_RE = re.compile(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ0-9_]+")
_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "que", "con", "para", "por",
    "en", "un", "una", "the", "and", "for", "how", "many", "what",
}

DEFAULT_WEIGHTS: dict[str, float] = {
    "lexical": 0.20,
    "embedding": 0.25,
    "business_mapping": 0.15,
    "verified_query": 0.15,
    "graph_proximity": 0.10,
    "historical_success": 0.10,
    "authority": 0.05,
}

SIGNAL_KEYS = tuple(DEFAULT_WEIGHTS.keys())


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if t.lower() not in _STOPWORDS and len(t) > 1
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _clamp01(dot / (na * nb))


@dataclass
class HybridCatalogSearch:
    """Ranking híbrido de candidatos de catálogo con señales explicables."""

    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        merged = dict(DEFAULT_WEIGHTS)
        merged.update(self.weights or {})
        total = sum(merged.values()) or 1.0
        self.weights = {k: v / total for k, v in merged.items()}

    def _lexical_score(self, query: str, candidate: dict[str, Any]) -> float:
        q = _tokens(query)
        if not q:
            return 0.0
        hay = " ".join(
            str(candidate.get(k) or "")
            for k in (
                "name",
                "physical_name",
                "business_name",
                "description",
                "text",
                "qualified_name",
            )
        )
        c = _tokens(hay)
        if not c:
            return 0.0
        return _clamp01(len(q & c) / max(len(q), 1))

    def score(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        signals: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retorna candidatos rankeados con hybrid_score y ranking_signals."""
        signals = signals or {}
        query_vec = signals.get("query_vector")
        ranked: list[dict[str, Any]] = []

        for cand in candidates:
            cid = str(cand.get("object_id") or cand.get("id") or cand.get("name") or "")
            per_id = (signals.get("by_id") or {}).get(cid, {})
            ranking_signals = {
                "lexical": self._lexical_score(query, cand),
                "embedding": _clamp01(
                    float(
                        per_id.get(
                            "embedding",
                            cosine_similarity(query_vec or [], cand.get("vector") or [])
                            if query_vec
                            else cand.get("embedding_score", 0.0),
                        )
                    )
                ),
                "business_mapping": _clamp01(
                    float(per_id.get("business_mapping", cand.get("business_mapping", 0.0)))
                ),
                "verified_query": _clamp01(
                    float(per_id.get("verified_query", cand.get("verified_query", 0.0)))
                ),
                "graph_proximity": _clamp01(
                    float(per_id.get("graph_proximity", cand.get("graph_proximity", 0.0)))
                ),
                "historical_success": _clamp01(
                    float(
                        per_id.get(
                            "historical_success", cand.get("historical_success", 0.0)
                        )
                    )
                ),
                "authority": _clamp01(
                    float(per_id.get("authority", cand.get("authority", 0.0)))
                ),
            }
            hybrid = sum(
                ranking_signals[k] * self.weights.get(k, 0.0) for k in SIGNAL_KEYS
            )
            row = dict(cand)
            row["hybrid_score"] = round(hybrid, 6)
            row["ranking_signals"] = {k: round(v, 6) for k, v in ranking_signals.items()}
            ranked.append(row)

        ranked.sort(key=lambda r: r["hybrid_score"], reverse=True)
        return ranked
