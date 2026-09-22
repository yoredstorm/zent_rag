# =============================================================================
# Judgment Fabric integration.
# Recall ocurre ANTES de JEV. JEV no crea, no activa y no cambia memoria.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.memory import MemoryType
from src.infrastructure.observability.logging_config import get_logger
from src.memory.recall import RecallQuery, slim_pattern
from src.memory.signature import infer_pattern_features

logger = get_logger(__name__)


async def recall_for_decision(
    *,
    organization_id: UUID,
    query: str,
    sql_enabled: bool = False,
    conversation_id: UUID | None = None,
    limit: int = 5,
) -> list[dict]:
    """Patrones ACTIVE del tenant. Vacío si el store no está disponible."""
    try:
        from src.memory.wiring import memory_recall_service

        features = infer_pattern_features(query, sql_enabled=sql_enabled)
        records = await memory_recall_service().recall(
            RecallQuery(
                organization_id=organization_id,
                features=features,
                memory_types=(MemoryType.OPERATIONAL, MemoryType.LEARNING),
                conversation_id=conversation_id,
                limit=limit,
            )
        )
        return [slim_pattern(record) for record in records]
    except Exception as exc:  # noqa: BLE001 — recall nunca bloquea la decisión
        logger.warning("memory recall failed", error=str(exc)[:200])
        return []


async def record_memory_influence(
    *,
    organization_id: UUID,
    patterns: list[dict],
    request_id: UUID | None,
    conversation_id: UUID | None,
    run_id: UUID | None,
    capability: str,
    confidence: float,
) -> None:
    """Append memory.used. No muta status ni políticas."""
    if not patterns:
        return
    try:
        from src.memory.wiring import memory_foundation_service

        service = memory_foundation_service()
        for pattern in patterns:
            memory_id = pattern.get("memory_id")
            if not memory_id:
                continue
            idem = None
            if request_id is not None:
                idem = f"used:{request_id}:{memory_id}"
            await service.record_use(
                organization_id=organization_id,
                memory_id=UUID(str(memory_id)),
                source_component="decision.engine",
                phase="pre_retrieval",
                outcome=capability[:80] or "considered",
                conversation_id=conversation_id,
                run_id=run_id,
                request_id=request_id,
                idempotency_key=idem,
                metadata={
                    "route": capability[:80],
                    "confidence": round(float(confidence), 4),
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory influence record failed", error=str(exc)[:200])
