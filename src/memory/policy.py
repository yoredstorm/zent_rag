# =============================================================================
# MemoryMaturityPolicy — única puerta de umbrales.
# =============================================================================
# Ningún otro módulo compara support_count contra un número mágico.
# ACTIVE nunca se alcanza aquí: sólo un admin, desde VALIDATED.
# =============================================================================
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping
from uuid import UUID

from src.core.domain.memory import (
    TERMINAL_STATUSES,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    ValidationPath,
)


class MemoryPolicyError(ValueError):
    """Transición o validación rechazada por política."""


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(raw)


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True, kw_only=True)
class MemoryMaturityPolicy:
    reinforce_min_support: int = 2
    pattern_min_support: int = 5
    pattern_min_confidence: float = 0.6
    validate_min_support: int = 20
    validate_min_success_rate: float = 0.9
    contradiction_ratio: float = 0.4
    contradiction_min_count: int = 2
    isolated_failure_min_occurrences: int = 3
    stale_after_days: int = 90
    recall_limit_default: int = 5
    recall_limit_max: int = 8

    def __post_init__(self) -> None:
        if self.reinforce_min_support < 2:
            raise ValueError("reinforce_min_support must be >= 2")
        if self.pattern_min_support < self.reinforce_min_support:
            raise ValueError("pattern_min_support must be >= reinforce_min_support")
        if self.recall_limit_max < 1:
            raise ValueError("recall_limit_max must be >= 1")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MemoryMaturityPolicy:
        source = env if env is not None else os.environ
        return cls(
            reinforce_min_support=_env_int(source, "MEMORY_REINFORCE_MIN_SUPPORT", 2),
            pattern_min_support=_env_int(source, "MEMORY_PATTERN_MIN_SUPPORT", 5),
            pattern_min_confidence=_env_float(source, "MEMORY_PATTERN_MIN_CONFIDENCE", 0.6),
            validate_min_support=_env_int(source, "MEMORY_VALIDATE_MIN_SUPPORT", 20),
            validate_min_success_rate=_env_float(source, "MEMORY_VALIDATE_MIN_SUCCESS_RATE", 0.9),
            contradiction_ratio=_env_float(source, "MEMORY_CONTRADICTION_RATIO", 0.4),
            contradiction_min_count=_env_int(source, "MEMORY_CONTRADICTION_MIN_COUNT", 2),
            isolated_failure_min_occurrences=_env_int(
                source, "MEMORY_ISOLATED_FAILURE_MIN_OCCURRENCES", 3
            ),
            stale_after_days=_env_int(source, "MEMORY_STALE_AFTER_DAYS", 90),
            recall_limit_default=_env_int(source, "MEMORY_RECALL_LIMIT", 5),
            recall_limit_max=_env_int(source, "MEMORY_RECALL_LIMIT_MAX", 8),
        )

    def blend_confidence(self, previous: float, observed: float, support_count: int) -> float:
        observed = min(1.0, max(0.0, float(observed)))
        if support_count <= 1:
            return observed
        blended = ((float(previous) * (support_count - 1)) + observed) / support_count
        return min(1.0, max(0.0, blended))

    def initial_status(self) -> MemoryStatus:
        return MemoryStatus.OBSERVED

    def status_after_support(
        self,
        record: MemoryRecord,
        *,
        has_knowledge_evidence: bool,
    ) -> MemoryStatus:
        """Promueve como máximo a PATTERN. Nunca VALIDATED ni ACTIVE."""
        if record.status in TERMINAL_STATUSES or record.status == MemoryStatus.CONTRADICTED:
            return record.status
        if record.status in {MemoryStatus.VALIDATED, MemoryStatus.ACTIVE}:
            return record.status
        if record.memory_type == MemoryType.CONVERSATION:
            if record.support_count >= self.reinforce_min_support:
                return MemoryStatus.REINFORCED
            return MemoryStatus.OBSERVED
        if record.memory_type == MemoryType.KNOWLEDGE and not has_knowledge_evidence:
            return MemoryStatus.OBSERVED
        if (
            record.support_count >= self.pattern_min_support
            and record.confidence >= self.pattern_min_confidence
            and record.memory_type in {MemoryType.OPERATIONAL, MemoryType.LEARNING, MemoryType.KNOWLEDGE}
        ):
            return MemoryStatus.PATTERN
        if record.support_count >= self.reinforce_min_support:
            return MemoryStatus.REINFORCED
        return MemoryStatus.OBSERVED

    def status_after_contradiction(self, record: MemoryRecord) -> MemoryStatus:
        if record.status in TERMINAL_STATUSES:
            return record.status
        if record.status in {MemoryStatus.ACTIVE, MemoryStatus.VALIDATED}:
            return MemoryStatus.CONTRADICTED
        ratio = record.contradiction_count / max(record.support_count, 1)
        if (
            record.contradiction_count >= self.contradiction_min_count
            and ratio >= self.contradiction_ratio
        ):
            return MemoryStatus.CONTRADICTED
        return record.status

    def validation_allowed(
        self,
        record: MemoryRecord,
        via: ValidationPath,
        *,
        has_knowledge_evidence: bool,
    ) -> None:
        if record.memory_type == MemoryType.CONVERSATION:
            raise MemoryPolicyError("conversation memory cannot be validated")
        if record.status in TERMINAL_STATUSES or record.status == MemoryStatus.CONTRADICTED:
            raise MemoryPolicyError(f"cannot validate status {record.status.value}")
        if record.memory_type == MemoryType.KNOWLEDGE and not has_knowledge_evidence:
            raise MemoryPolicyError("knowledge memory requires claim or evidence ledger")
        if via == ValidationPath.STATISTICAL:
            if record.support_count < self.validate_min_support:
                raise MemoryPolicyError("statistical validation requires more support")
            if record.success_rate < self.validate_min_success_rate:
                raise MemoryPolicyError("statistical validation requires a higher success rate")
            ratio = record.contradiction_count / max(record.support_count, 1)
            if ratio >= self.contradiction_ratio:
                raise MemoryPolicyError("statistical validation blocked by contradictions")
            return
        if via in {ValidationPath.EXPERIMENT, ValidationPath.GOLDEN_SET, ValidationPath.ADMIN}:
            return
        raise MemoryPolicyError(f"unknown validation path {via}")

    def activation_allowed(self, record: MemoryRecord) -> None:
        if record.status != MemoryStatus.VALIDATED:
            raise MemoryPolicyError("only validated memory can be activated")
        if record.memory_type == MemoryType.CONVERSATION:
            raise MemoryPolicyError("conversation memory cannot be activated")

    def restore_allowed(self, record: MemoryRecord) -> None:
        allowed = {
            MemoryStatus.REJECTED,
            MemoryStatus.EXPIRED,
            MemoryStatus.STALE,
            MemoryStatus.CONTRADICTED,
        }
        if record.status not in allowed:
            raise MemoryPolicyError(f"cannot restore status {record.status.value}")

    def is_stale(self, record: MemoryRecord, *, now: datetime | None = None) -> bool:
        if record.status == MemoryStatus.STALE:
            return True
        current = now or datetime.now(timezone.utc)
        last = record.last_observed_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return last < current - timedelta(days=self.stale_after_days)

    def recall_allowed(
        self,
        record: MemoryRecord,
        *,
        organization_id: UUID,
        conversation_id: UUID | None,
        now: datetime | None = None,
    ) -> bool:
        if record.organization_id != organization_id:
            return False
        if record.status != MemoryStatus.ACTIVE:
            return False
        if self.is_stale(record, now=now):
            return False
        if record.memory_type == MemoryType.CONVERSATION:
            return (
                conversation_id is not None
                and record.created_from_conversation_id == conversation_id
            )
        return True

    def clamp_limit(self, limit: int | None) -> int:
        if limit is None:
            return self.recall_limit_default
        return max(1, min(int(limit), self.recall_limit_max))
