"""Persiste el replay sin tocar rag_flows."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


async def persist_replay(organization_id: UUID, result: dict[str, Any]) -> None:
    """Best-effort. Un fallo de escritura no borra la comparación ya calculada."""
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO query_replays (
                    id, organization_id, source_query_id, replay_query_id, payload
                ) VALUES (
                    :id, :organization_id, :source_query_id, :replay_query_id, CAST(:payload AS jsonb)
                )
                """
            ),
            {
                "id": result["replay_id"],
                "organization_id": organization_id,
                "source_query_id": result["source_query_id"],
                "replay_query_id": result["replay_query_id"],
                "payload": json.dumps(result, default=str),
            },
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.warning("query replay persist failed", error=str(exc)[:200])
    finally:
        await session.close()
