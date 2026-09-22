# =============================================================================
# Composition root de memoria. Postgres en runtime. Tests inyectan el doble.
# =============================================================================
from __future__ import annotations

from src.memory.policy import MemoryMaturityPolicy
from src.memory.recall import MemoryRecallService
from src.memory.service import MemoryFoundationService


def memory_foundation_service() -> MemoryFoundationService:
    from src.infrastructure.postgres.memory_store import (
        LedgerKnowledgeChecker,
        PostgresMemoryRepository,
    )

    return MemoryFoundationService(
        PostgresMemoryRepository(),
        MemoryMaturityPolicy.from_env(),
        knowledge_checker=LedgerKnowledgeChecker(),
    )


def memory_recall_service() -> MemoryRecallService:
    from src.infrastructure.postgres.memory_store import PostgresMemoryRepository

    return MemoryRecallService(
        PostgresMemoryRepository(),
        MemoryMaturityPolicy.from_env(),
    )
