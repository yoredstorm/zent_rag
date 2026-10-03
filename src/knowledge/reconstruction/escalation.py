# =============================================================================
# Semantic Reconstruction Layer — escalamiento LLM (fase asíncrona)
# =============================================================================
# Corre SOLO sobre decisiones ambiguas que las reglas deterministas no
# resolvieron. Nunca reescribe toda la fuente. Aplica únicamente:
#   - CONTINUATION verificada carácter por carácter (sin contenido inventado),
#   - o cuarentena explícita (INCOMPLETE / REJECTED).
# No guarda chain-of-thought: solo resultado estructurado y señales.
# =============================================================================
from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.structure.base import content_hash, token_count

from .contracts import ReconstructionStatus
from .llm import (
    ReconstructionModelProvider,
    ReconstructionUsage,
    build_request,
    verify_continuation,
)

_MIN_LLM_CONFIDENCE = 0.6
_KNOWLEDGE_STATUSES = {
    ReconstructionStatus.VALID.value,
    ReconstructionStatus.RECONSTRUCTED.value,
}


async def escalate_reconstruction(
    document: StructuredDocument,
    provider: ReconstructionModelProvider | None,
    *,
    usage: ReconstructionUsage | None = None,
    max_calls: int = 8,
    model: str | None = None,
) -> tuple[StructuredDocument, ReconstructionUsage]:
    """Escala pendientes ambiguos al LLM. Best-effort: nunca rompe la ingesta."""
    counters = usage or ReconstructionUsage(model=model)
    payload = document.metadata.get("semantic_reconstruction")
    if provider is None or not isinstance(payload, dict):
        return document, counters
    pending = list(payload.get("pending_decisions") or [])
    if not pending:
        payload["llm"] = {
            "calls": 0,
            "repairs": 0,
            "rejected": 0,
            "assisted": True,
            "model": model,
        }
        return dataclasses.replace(
            document, metadata={**document.metadata, "semantic_reconstruction": payload}
        ), counters

    payload = _deepcopy_payload(payload)
    blocks = list(document.blocks)
    block_index = {block.id: position for position, block in enumerate(blocks)}
    unresolved: list[dict[str, Any]] = []

    for decision in pending:
        if counters.calls >= max_calls:
            unresolved.append(decision)
            continue
        if decision.get("kind") == "TABLE_HEADER":
            unresolved.append(decision)
            continue
        left_id = _as_uuid(decision.get("left_block_id"))
        right_id = _as_uuid(decision.get("right_block_id"))
        if left_id is None or right_id is None or left_id not in block_index or right_id not in block_index:
            unresolved.append(decision)
            continue
        if blocks[block_index[left_id]].metadata.get("superseded") or blocks[
            block_index[right_id]
        ].metadata.get("superseded"):
            unresolved.append(decision)
            continue
        request = build_request(
            source_kind=str(payload.get("source_kind") or ""),
            title=str(document.title or ""),
            left=str(decision.get("left_text") or ""),
            right=str(decision.get("right_text") or ""),
            context=f"heading={decision.get('reason') or ''}",
            candidate_kind=str(decision.get("kind") or "CONTINUATION"),
            confidence=float(decision.get("confidence") or 0.0),
        )
        try:
            response = await provider.reconstruct(request)
        except Exception:  # noqa: BLE001 — el escalamiento es best-effort
            unresolved.append(decision)
            continue
        counters.calls += 1
        counters.model = model or counters.model
        raw_response = response.get("_response") if isinstance(response, dict) else None
        if raw_response is not None:
            counters.add(raw_response)
        classification = str((response or {}).get("classification") or "UNKNOWN").upper()
        confidence = _confidence(response)
        candidate = str((response or {}).get("semantic_unit") or "")
        left_text = str(decision.get("left_text") or "")
        right_text = str(decision.get("right_text") or "")
        if (
            classification == "CONTINUATION"
            and confidence >= _MIN_LLM_CONFIDENCE
            and verify_continuation(left_text, right_text, candidate)
        ):
            blocks[block_index[left_id]] = _merge_block(
                blocks[block_index[left_id]], candidate, right_id, response
            )
            blocks[block_index[right_id]] = _quarantine_block(
                blocks[block_index[right_id]],
                ReconstructionStatus.DUPLICATE.value,
                into=left_id,
            )
            counters.repairs += 1
            payload.setdefault("continuations", []).append(
                {
                    "id": decision.get("decision_id"),
                    "kind": str(decision.get("kind") or "CONTINUATION"),
                    "left_id": str(left_id),
                    "right_id": str(right_id),
                    "merged_text": candidate[:400],
                    "confidence": round(confidence, 4),
                    "reason": "llm_verified_continuation",
                    "method": "llm",
                    "ambiguity": False,
                    "evidence": decision.get("evidence") or {},
                }
            )
            _update_units(payload, (left_id, right_id), ReconstructionStatus.RECONSTRUCTED.value, confidence)
        else:
            target_status = (
                ReconstructionStatus.INCOMPLETE.value
                if classification in {"TABLE_FRAGMENT", "HEADER_FOOTER"}
                else ReconstructionStatus.REJECTED.value
            )
            blocks[block_index[right_id]] = _quarantine_block(
                blocks[block_index[right_id]], target_status
            )
            counters.rejected += 1
            _update_units(payload, (right_id,), target_status, confidence)
            payload.setdefault("rejected_terms", [])

    payload["pending_decisions"] = unresolved
    payload["llm"] = {
        "calls": counters.calls,
        "repairs": counters.repairs,
        "rejected": counters.rejected,
        "assisted": True,
        "model": counters.model,
        "tokens": counters.total_tokens,
    }
    stats = payload.setdefault("stats", {})
    stats["llm_repairs"] = counters.repairs
    stats["deterministic_repairs"] = max(
        0, int(stats.get("deterministic_repairs") or 0)
    )
    stats["units_reconstructed"] = int(stats.get("units_reconstructed") or 0) + counters.repairs
    stats["ambiguous_units"] = len(payload["pending_decisions"])
    stats["rejected_units"] = int(stats.get("rejected_units") or 0) + counters.rejected
    payload["quality"] = _recompute_quality(payload)
    return dataclasses.replace(
        document,
        blocks=tuple(blocks),
        metadata={**document.metadata, "semantic_reconstruction": payload},
    ), counters


def _deepcopy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(payload)


def _as_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _confidence(response: dict[str, Any] | None) -> float:
    try:
        return min(1.0, max(0.0, float((response or {}).get("confidence") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _merge_block(block, text: str, right_id: UUID, response: dict[str, Any]):
    meta = dict(block.metadata)
    meta["reconstruction_status"] = ReconstructionStatus.RECONSTRUCTED.value
    meta["reconstruction"] = {
        "stage": "llm_continuation_merged",
        "method": "llm",
        "confidence": _confidence(response),
        "merged_with": str(right_id),
        "classification": str((response or {}).get("classification") or ""),
        "reason": str((response or {}).get("reason") or "")[:400],
    }
    if meta.get("index_semantic") is False:
        meta.pop("index_semantic", None)
    return dataclasses.replace(
        block,
        text=text,
        token_count=token_count(text),
        content_hash=content_hash(text),
        metadata=meta,
    )


def _quarantine_block(block, status: str, *, into: UUID | None = None):
    meta = dict(block.metadata)
    meta["reconstruction_status"] = status
    meta["index_semantic"] = False
    reconstruction = {
        "stage": "llm_quarantine",
        "method": "llm",
        "classification": status,
    }
    if into is not None:
        reconstruction["superseded_into"] = str(into)
        meta["superseded"] = True
    meta["reconstruction"] = reconstruction
    return dataclasses.replace(block, metadata=meta)


def _update_units(
    payload: dict[str, Any],
    block_ids: tuple[UUID, ...],
    status: str,
    confidence: float,
) -> None:
    wanted = {str(value) for value in block_ids}
    for unit in payload.get("units") or []:
        provenance = unit.get("provenance") or {}
        if str(provenance.get("block_id") or "") not in wanted:
            continue
        unit["status"] = status
        unit["method"] = "llm"
        if status == ReconstructionStatus.RECONSTRUCTED.value:
            signals = unit.setdefault("confidence", {})
            signals["continuity_confidence"] = round(confidence, 4)
            signals["reconstruction_confidence"] = round(max(confidence, 0.55), 4)


def _recompute_quality(payload: dict[str, Any]) -> dict[str, Any]:
    units = payload.get("units") or []
    knowledge = [
        unit
        for unit in units
        if str(unit.get("status") or "") in _KNOWLEDGE_STATUSES
    ]
    distribution: dict[str, int] = {}
    for unit in units:
        status = str(unit.get("status") or "")
        distribution[status] = distribution.get(status, 0) + 1
    if not units:
        score = 1.0
    elif not knowledge:
        score = 0.0
    else:
        ratio = len(knowledge) / len(units)
        mean = sum(
            float((unit.get("confidence") or {}).get("reconstruction_confidence") or 0.0)
            for unit in knowledge
        ) / len(knowledge)
        score = round(0.6 * ratio + 0.4 * mean, 4)
    return {**(payload.get("quality") or {}), "score": score, "distribution": distribution}


__all__ = ["escalate_reconstruction"]
