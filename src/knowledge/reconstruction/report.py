# =============================================================================
# Semantic Reconstruction Layer — observabilidad y Live Learning
# =============================================================================
# Registra por ingesta: raw_elements, semantic_units_created, units_reconstructed,
# continuations_detected, fragments_rejected, tables_detected, schemas_inferred,
# ambiguous_units, LLM_repairs, deterministic_repairs, rejected_units y la
# distribución de calidad. Alimenta el Tech View y los mensajes humanos del
# Live Learning ("ZENT reconstruyó 18 bloques divididos por el formato").
# =============================================================================
from __future__ import annotations

from typing import Any

from src.core.domain.knowledge_v2 import StructuredDocument

from .engine import semantic_reconstruction_payload


def observe_reconstruction(document: StructuredDocument) -> None:
    """Prometheus best-effort: ninguna métrica rompe la ingesta."""
    payload = semantic_reconstruction_payload(document)
    if not payload:
        return
    stats = payload.get("stats") or {}
    quality = payload.get("quality") or {}
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_reconstruction_continuations_total,
            knowledge_reconstruction_fragments_total,
            knowledge_reconstruction_llm_calls_total,
            knowledge_reconstruction_seconds,
            knowledge_reconstruction_sources_total,
            knowledge_reconstruction_units_total,
        )
    except Exception:  # noqa: BLE001
        return
    try:
        source_kind = str(payload.get("source_kind") or "unknown")
        status = str(payload.get("status") or "unknown")
        knowledge_reconstruction_sources_total.labels(
            source_kind=source_kind, status=status
        ).inc()
        knowledge_reconstruction_seconds.labels(source_kind=source_kind).observe(
            float(stats.get("elapsed_ms") or 0.0) / 1000.0
        )
        for unit_status, count in (quality.get("distribution") or {}).items():
            knowledge_reconstruction_units_total.labels(status=str(unit_status)).inc(
                int(count)
            )
        knowledge_reconstruction_continuations_total.labels(
            kind="merged"
        ).inc(int(stats.get("merged_continuations") or 0))
        knowledge_reconstruction_continuations_total.labels(
            kind="ambiguous"
        ).inc(int(stats.get("ambiguous_units") or 0))
        knowledge_reconstruction_fragments_total.labels(
            status="rejected"
        ).inc(int(stats.get("fragments_rejected") or 0))
        knowledge_reconstruction_llm_calls_total.labels(outcome="repair").inc(
            int(stats.get("llm_repairs") or 0)
        )
        llm = payload.get("llm") or {}
        knowledge_reconstruction_llm_calls_total.labels(outcome="call").inc(
            int(llm.get("calls") or 0)
        )
    except Exception:  # noqa: BLE001 — la métrica nunca rompe el pipeline
        return


def tech_view(document: StructuredDocument) -> dict[str, Any]:
    """Bloque técnico de Semantic Reconstruction (spec §23)."""
    return tech_view_from_metadata(document.metadata)


def tech_view_from_metadata(metadata: dict | None) -> dict[str, Any]:
    payload = (
        metadata.get("semantic_reconstruction")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(payload, dict) or not payload:
        return {}
    stats = payload.get("stats") or {}
    llm = payload.get("llm") or {}
    return {
        "source_kind": payload.get("source_kind"),
        "adapter": payload.get("adapter"),
        "status": payload.get("status"),
        "raw_blocks": stats.get("raw_elements"),
        "semantic_units": stats.get("semantic_units"),
        "merged_continuations": stats.get("merged_continuations"),
        "rejected_fragments": stats.get("fragments_rejected"),
        "tables_detected": stats.get("tables_detected"),
        "tables_reconstructed": stats.get("tables_reconstructed"),
        "schemas_inferred": stats.get("schemas_inferred"),
        "sheets": stats.get("sheets"),
        "ambiguous": stats.get("ambiguous_units"),
        "llm_assisted": llm.get("repairs"),
        "deterministic": stats.get("deterministic_repairs"),
        "quality_score": (payload.get("quality") or {}).get("score"),
        "quality_distribution": (payload.get("quality") or {}).get("distribution"),
        "elapsed_ms": payload.get("elapsed_ms"),
        "llm_calls": llm.get("calls"),
        "llm_tokens": llm.get("tokens"),
        "llm_model": llm.get("model"),
        "warnings": payload.get("warnings") or [],
    }


def live_learning_messages(document: StructuredDocument) -> list[dict[str, Any]]:
    """Mensajes humanos reales para la experiencia de ingesta (spec §22)."""
    payload = semantic_reconstruction_payload(document)
    if not payload:
        return []
    stats = payload.get("stats") or {}
    messages: list[dict[str, Any]] = []
    merged = int(stats.get("merged_continuations") or 0)
    if merged:
        messages.append(
            {
                "event_type": "CONTINUATIONS_MERGED",
                "payload": {"count": merged},
                "message": (
                    f"ZENT reconstruyó {merged} bloques que estaban divididos "
                    "por el formato original."
                ),
            }
        )
    tables = int(stats.get("tables_detected") or 0)
    if tables:
        messages.append(
            {
                "event_type": "TABLE_DETECTED",
                "payload": {"count": tables},
                "message": f"ZENT detectó {tables} tablas.",
            }
        )
    schemas = int(stats.get("schemas_inferred") or 0)
    if schemas:
        messages.append(
            {
                "event_type": "SCHEMAS_INFERRED",
                "payload": {"count": schemas},
                "message": f"ZENT reconoció la estructura de {schemas} tablas u hojas.",
            }
        )
    sheets = int(stats.get("sheets") or 0)
    if sheets and str(payload.get("source_kind")) in {"spreadsheet", "csv"}:
        messages.append(
            {
                "event_type": "SCHEMAS_INFERRED",
                "payload": {"count": sheets, "unit": "sheets"},
                "message": f"ZENT reconoció la estructura de {sheets} hojas de cálculo.",
            }
        )
    rejected = int(stats.get("fragments_rejected") or 0)
    if rejected:
        messages.append(
            {
                "event_type": "FRAGMENTS_REJECTED",
                "payload": {"count": rejected},
                "message": f"ZENT descartó {rejected} fragmentos incompletos.",
            }
        )
    ambiguous = int(stats.get("ambiguous_units") or 0)
    llm_repairs = int(stats.get("llm_repairs") or 0)
    messages.append(
        {
            "event_type": "SEMANTIC_RECONSTRUCTED",
            "payload": {
                "count": int(stats.get("semantic_units") or 0),
                "raw_blocks": stats.get("raw_elements"),
                "reconstructed": stats.get("units_reconstructed"),
                "deterministic": stats.get("deterministic_repairs"),
                "ambiguous": ambiguous,
                "llm_assisted": llm_repairs,
                "source_kind": payload.get("source_kind"),
            },
            "message": (
                "ZENT reconstruyó el significado de la fuente antes de "
                "convertirla en conocimiento."
            ),
        }
    )
    return messages


__all__ = ["live_learning_messages", "observe_reconstruction", "tech_view"]
