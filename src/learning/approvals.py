# =============================================================================
# Approvals — registro gobernado de aprobaciones (who/when/why/versiones)
# =============================================================================
# Cada aprobación/rechazo de conocimiento registra: who, when, why, source
# evidence, previous version, new version. Los cambios críticos disparan
# Evaluation Replay (job durable) cuando la política lo requiere.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.learning import ApprovalAction, ApprovalRecord
from src.infrastructure.observability.logging_config import get_logger
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)

CRITICAL_KNOWLEDGE_TYPES = {"metric", "glossary", "authority"}


class ApprovalService:
    """Registro de aprobaciones + disparo de replays."""

    def __init__(
        self,
        store: PostgresLearningStore,
        replay_starter=None,
        replay_required: bool = True,
    ) -> None:
        self._store = store
        self._replay_starter = replay_starter
        self._replay_required = replay_required

    async def record(
        self,
        *,
        organization_id: UUID,
        knowledge_type: str,
        knowledge_id: str,
        action: ApprovalAction,
        acted_by: UUID | None = None,
        reason: str | None = None,
        source_evidence: list[str] | None = None,
        previous_version: dict | None = None,
        new_version: dict | None = None,
        replay_id: UUID | None = None,
    ) -> UUID:
        record = ApprovalRecord(
            organization_id=organization_id,
            knowledge_type=knowledge_type,
            knowledge_id=str(knowledge_id),
            action=action,
            acted_by=acted_by,
            reason=reason,
            source_evidence=source_evidence or [],
            previous_version=previous_version or {},
            new_version=new_version or {},
            replay_id=replay_id,
        )
        return await self._store.add_approval_record(record)

    async def record_and_maybe_replay(
        self,
        *,
        organization_id: UUID,
        knowledge_type: str,
        knowledge_id: str,
        acted_by: UUID | None = None,
        reason: str | None = None,
        source_evidence: list[str] | None = None,
        previous_version: dict | None = None,
        new_version: dict | None = None,
    ) -> UUID | None:
        """Registra la aprobación y encola replay si el tipo es crítico."""
        approval_id = await self.record(
            organization_id=organization_id,
            knowledge_type=knowledge_type,
            knowledge_id=knowledge_id,
            action=ApprovalAction.APPROVE,
            acted_by=acted_by,
            reason=reason,
            source_evidence=source_evidence,
            previous_version=previous_version,
            new_version=new_version,
        )
        replay_id = None
        if (
            self._replay_starter is not None
            and self._replay_required
            and knowledge_type in CRITICAL_KNOWLEDGE_TYPES
        ):
            try:
                replay_id = await self._replay_starter(
                    organization_id=organization_id,
                    knowledge_type=knowledge_type,
                    knowledge_id=knowledge_id,
                    trigger="auto",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto replay enqueue failed", error=str(exc)[:200])
        return replay_id or approval_id
