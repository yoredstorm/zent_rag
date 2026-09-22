# =============================================================================
# MemoryRecallService — sólo memorias del tenant, ACTIVE y no stale.
# No escribe. No manda el store completo al Judgment Fabric.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from src.core.domain.memory import MemoryRecord, MemoryType
from src.core.ports.memory import MemoryRepository
from src.memory.policy import MemoryMaturityPolicy
from src.memory.signature import PatternFeatures, pattern_signature


@dataclass(frozen=True, kw_only=True)
class RecallQuery:
    organization_id: UUID
    features: PatternFeatures
    memory_types: tuple[MemoryType, ...] = (MemoryType.OPERATIONAL, MemoryType.LEARNING)
    conversation_id: UUID | None = None
    limit: int | None = None


class MemoryRecallService:
    def __init__(
        self,
        repository: MemoryRepository,
        policy: MemoryMaturityPolicy | None = None,
    ) -> None:
        self._repo = repository
        self._policy = policy or MemoryMaturityPolicy()

    async def recall(self, query: RecallQuery) -> list[MemoryRecord]:
        features = query.features.normalized()
        signature = pattern_signature(features)
        if _is_blank(features):
            return []
        limit = self._policy.clamp_limit(query.limit)
        types = tuple(memory_type.value for memory_type in query.memory_types)
        candidates = await self._repo.recall_candidates(
            query.organization_id,
            signature=signature,
            intent_family=features.intent_family,
            source_type=features.source_type,
            retrieval_modality=features.retrieval_modality,
            tool_family=features.tool_family,
            failure_category=features.failure_category,
            memory_types=types,
            limit=limit,
        )
        now = datetime.now(timezone.utc)
        allowed: list[MemoryRecord] = []
        for record in candidates:
            if not self._policy.recall_allowed(
                record,
                organization_id=query.organization_id,
                conversation_id=query.conversation_id,
                now=now,
            ):
                continue
            allowed.append(record)
        return allowed[:limit]


def slim_pattern(record: MemoryRecord) -> dict:
    """Señal para JEV. Sin descripción libre ni chain-of-thought."""
    return {
        "memory_id": str(record.id),
        "pattern_key": record.pattern_key,
        "memory_type": record.memory_type.value,
        "success_rate": round(record.success_rate, 4),
        "support_count": record.support_count,
        "confidence": round(float(record.confidence), 4),
    }


def _is_blank(features: PatternFeatures) -> bool:
    return all(
        value in {"", "unknown_intent", "unknown_source", "unknown_retrieval", "none", "unclassified"}
        for value in (
            features.intent_family,
            features.source_type,
            features.retrieval_modality,
            features.tool_family,
            features.failure_category,
        )
    )
