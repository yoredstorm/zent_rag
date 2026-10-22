# =============================================================================
# Session references — three different lifecycles, never one merged table.
#
# conversation: final-user chat turn stream (chat_events / conversation_id)
# design:       workflow_design_sessions (human designing, not executing)
# workflow:     workflow_instances (durable business process, not chat)
# =============================================================================
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def resolve_session(
    organization_id: UUID,
    session_id: UUID,
    kind: Literal["conversation", "design", "workflow_instance"],
) -> dict[str, Any]:
    session = await get_async_session()
    try:
        if kind == "design":
            row = (
                await session.execute(
                    text(
                        "SELECT id, status, workflow_id, created_at FROM workflow_design_sessions "
                        "WHERE id = :sid AND organization_id = :oid"
                    ),
                    {"sid": session_id, "oid": organization_id},
                )
            ).fetchone()
            if row is None:
                return {
                    "schema": "zent.session.ref/v1",
                    "kind": kind,
                    "session_id": str(session_id),
                    "exists": False,
                }
            return {
                "schema": "zent.session.ref/v1",
                "kind": kind,
                "session_id": str(row.id),
                "design_session_id": str(row.id),
                "status": str(row.status),
                "workflow_id": str(row.workflow_id) if row.workflow_id else None,
                "exists": True,
            }

        if kind == "workflow_instance":
            row = (
                await session.execute(
                    text(
                        "SELECT id, status, workflow_id, conversation_id, updated_at "
                        "FROM workflow_instances WHERE id = :sid AND organization_id = :oid"
                    ),
                    {"sid": session_id, "oid": organization_id},
                )
            ).fetchone()
            if row is None:
                return {
                    "schema": "zent.session.ref/v1",
                    "kind": kind,
                    "session_id": str(session_id),
                    "exists": False,
                }
            return {
                "schema": "zent.session.ref/v1",
                "kind": kind,
                "session_id": str(row.id),
                "workflow_instance_id": str(row.id),
                "conversation_id": str(row.conversation_id) if row.conversation_id else None,
                "workflow_id": str(row.workflow_id) if row.workflow_id else None,
                "status": str(row.status),
                "exists": True,
            }

        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS events, MIN(created_at) AS first_at, MAX(created_at) AS last_at "
                    "FROM chat_events WHERE organization_id = :oid AND session_id = :sid"
                ),
                {"sid": session_id, "oid": organization_id},
            )
        ).fetchone()
        instance = (
            await session.execute(
                text(
                    "SELECT id, status FROM workflow_instances "
                    "WHERE organization_id = :oid AND conversation_id = :sid "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"sid": session_id, "oid": organization_id},
            )
        ).fetchone()
        events = int(row.events or 0) if row else 0
        return {
            "schema": "zent.session.ref/v1",
            "kind": kind,
            "session_id": str(session_id),
            "conversation_id": str(session_id),
            "workflow_instance_id": str(instance.id) if instance else None,
            "status": str(instance.status) if instance else ("active" if events else "empty"),
            "events": events,
            "first_at": row.first_at.isoformat() if row and row.first_at else None,
            "last_at": row.last_at.isoformat() if row and row.last_at else None,
            "exists": bool(events or instance),
        }
    finally:
        await session.close()


__all__ = ["resolve_session"]
