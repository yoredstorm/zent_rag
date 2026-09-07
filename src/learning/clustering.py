# =============================================================================
# Learning from unanswered questions — clustering semántico determinista
# =============================================================================
# "cliente rentable" / "clientes con rentabilidad" / "cuentas rentables" ->
# mismo gap. Jaccard sobre tokens normalizados (sin diacríticos + stopwords).
# NUNCA crea business concepts automáticamente: genera una sugerencia que va
# a revisión (improvement item IN_REVIEW).
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.learning.improvements import ImprovementQueue

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "que", "con", "para", "por",
    "en", "un", "una", "cuantos", "cuantas", "cual", "cuales", "como",
    "estado", "actual", "tenemos", "hay", "nuestros", "nuestro", "sobre",
    "what", "the", "and", "for", "our", "current", "how", "many", "which",
    "is", "are", "of", "to", "in", "with", "total", "me",
}

_PREFIX_LEN = 5


def _stem_key(token: str) -> str:
    """Clave morfológica: prefijo estable (cliente/clientes/rentable/rentabilidad)."""
    return token[:_PREFIX_LEN] if len(token) > _PREFIX_LEN else token


def normalize_question(question: str) -> str:
    text = unicodedata.normalize("NFKD", question or "").lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    tokens = [
        _stem_key(t)
        for t in _TOKEN_RE.findall(text)
        if t not in _STOPWORDS and len(t) > 1
    ]
    return " ".join(sorted(set(tokens)))


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def overlap_coefficient(a: set[str], b: set[str]) -> float:
    """|a∩b| / min(|a|,|b|): tolera variación morfológica (rentable/rentabilidad)."""
    smaller = min(len(a), len(b))
    if smaller == 0:
        return 0.0
    return len(a & b) / smaller


class UnansweredClusterer:
    """Agrupa preguntas no contestadas por similitud semántica (stem + overlap)."""

    def __init__(
        self,
        improvements: ImprovementQueue,
        threshold: float = 0.45,
        min_size: int = 3,
    ) -> None:
        self._improvements = improvements
        self._threshold = threshold
        self._min_size = min_size

    def cluster(
        self, questions: list[dict]
    ) -> list[dict]:
        """questions: [{question, query_id, created_at}] -> clusters."""
        clusters: list[dict] = []
        for q in questions:
            tokens = set(normalize_question(q["question"]).split())
            if not tokens:
                continue
            placed = False
            for cluster in clusters:
                # Comparación contra el representante del cluster (primer
                # miembro): el union crece y diluiría la similitud.
                if (
                    overlap_coefficient(tokens, cluster["representative"])
                    >= self._threshold
                ):
                    cluster["questions"].append(q)
                    cluster["tokens"] |= tokens
                    placed = True
                    break
            if not placed:
                clusters.append(
                    {
                        "tokens": tokens,
                        "representative": set(tokens),
                        "questions": [q],
                    }
                )
        return [
            {
                "questions": c["questions"],
                "size": len(c["questions"]),
                "samples": [x["question"] for x in c["questions"][:5]],
            }
            for c in clusters
            if len(c["questions"]) >= self._min_size
        ]

    async def run(
        self,
        organization_id: UUID,
        questions: list[dict],
    ) -> list[dict]:
        """Clusteriza y crea improvement items IN_REVIEW (sugerencias)."""
        found: list[dict] = []
        for cluster in self.cluster(questions):
            key = _cluster_key(cluster["samples"][0])
            await self._improvements.sync_from_cluster(
                organization_id=organization_id,
                cluster_key=key,
                title=(
                    f"Sugerido: '{cluster['samples'][0][:80]}' representa un "
                    f"concepto sin resolver ({cluster['size']} preguntas)"
                ),
                questions=[x["question"] for x in cluster["questions"]],
                concept_hint=cluster["samples"][0][:120],
            )
            found.append(
                {
                    "cluster_key": key,
                    "size": cluster["size"],
                    "samples": cluster["samples"],
                }
            )
        return found


def _cluster_key(sample: str) -> str:
    import hashlib

    normalized = normalize_question(sample)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
