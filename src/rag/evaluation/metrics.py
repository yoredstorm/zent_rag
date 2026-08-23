# =============================================================================
# Evaluation Metrics — métricas deterministas (sin LLM)
# =============================================================================
# retrieval_precision / retrieval_recall: chunks recuperados vs
#   expected_sources (match por contenido o metadata; fallback keyword).
# citation_accuracy: parsea citas [Doc: N] de la respuesta y verifica que
#   el chunk citado esté entre los recuperados y sea relevante.
# =============================================================================
from __future__ import annotations

import re
from collections.abc import Iterable
from statistics import mean

_CITE_RE = re.compile(r"\[Doc:\s*(\d+)\]")
_NUMERIC = (int, float)


def _chunk_searchable(chunk: dict) -> str:
    """Texto de búsqueda de un chunk: contenido + valores de metadata."""
    parts: list[str] = [str(chunk.get("content") or "")]
    metadata = chunk.get("metadata") or {}
    if isinstance(metadata, dict):
        parts.extend(str(v) for v in metadata.values())
    return "\n".join(parts).lower()


def _matches_source(chunk: dict, source: str) -> bool:
    needle = source.strip().lower()
    if not needle:
        return False
    return needle in _chunk_searchable(chunk)


def retrieval_precision(chunks: list[dict], expected_sources: list[str]) -> float:
    """Fracción de chunks recuperados que coincide con alguna fuente esperada."""
    if not chunks:
        return 0.0
    if not expected_sources:
        return 0.0
    hits = sum(1 for c in chunks if any(_matches_source(c, s) for s in expected_sources))
    return round(hits / len(chunks), 4)


def retrieval_recall(chunks: list[dict], expected_sources: list[str]) -> float:
    """Fracción de fuentes esperadas cubiertas por al menos un chunk recuperado."""
    if not expected_sources:
        return 0.0
    if not chunks:
        return 0.0
    covered = sum(
        1
        for s in expected_sources
        if any(_matches_source(c, s) for c in chunks)
    )
    return round(covered / len(expected_sources), 4)


def _parse_citations(answer: str) -> list[int]:
    """Índices 1-based de citas [Doc: N] presentes en la respuesta."""
    return [int(m.group(1)) for m in _CITE_RE.finditer(answer or "")]


def citation_stats(
    answer: str,
    chunks: list[dict],
    expected_sources: list[str] | None = None,
) -> dict:
    """Estadísticas de citas [Doc: N]: en rango, correctas y accuracy.

    accuracy es None si la respuesta no cita (no aplica, ej. saludos).
    Una cita es "correcta" si el chunk citado coincide con una fuente
    esperada; sin expected_sources, "correcto" = dentro de rango.
    """
    citations = _parse_citations(answer)
    grounded = [i for i in citations if 1 <= i <= len(chunks)]
    if expected_sources:
        correct = [
            i
            for i in grounded
            if any(_matches_source(chunks[i - 1], s) for s in expected_sources)
        ]
    else:
        correct = list(grounded)
    accuracy = round(len(correct) / len(citations), 4) if citations else None
    return {
        "citations_parsed": len(citations),
        "citations_grounded": len(grounded),
        "citations_correct": len(correct),
        "accuracy": accuracy,
    }


def answer_keyword_coverage(answer: str, keywords: list[str]) -> float | None:
    """Proxy determinista legacy: fracción de keywords presentes en la respuesta.

    Devuelve None si no hay keywords definidas en el caso.
    """
    if not keywords:
        return None
    lowered = (answer or "").lower()
    return round(
        sum(1 for kw in keywords if str(kw).lower() in lowered) / len(keywords), 4
    )


def percentile(values: Iterable[float], p: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    idx = min(len(ordered) - 1, max(0, int(p / 100 * len(ordered))))
    return ordered[idx]


def latency_summary(values: Iterable[float]) -> dict:
    vals = [float(v) for v in values]
    if not vals:
        return {"avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "count": 0}
    return {
        "avg_ms": round(mean(vals), 2),
        "p50_ms": round(percentile(vals, 50), 2),
        "p95_ms": round(percentile(vals, 95), 2),
        "count": len(vals),
    }


def mean_or(values: Iterable[float], fallback: float = 0.0) -> float:
    vals = [float(v) for v in values]
    return round(mean(vals), 4) if vals else fallback
