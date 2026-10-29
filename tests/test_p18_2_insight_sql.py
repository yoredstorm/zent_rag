# =============================================================================
# P18.2-03 — Regresión SQL del cursor de objetos (asyncpg)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.session import get_async_session


@pytest.mark.asyncio
async def test_objects_cursor_query_has_no_ambiguous_parameter() -> None:
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.2 Cursor {uuid4().hex[:6]}"
    )
    source_id = uuid4()
    session = await get_async_session()
    try:
        # Primer página: cursor NULL ya no usa ":cursor IS NULL".
        first = (
            await session.execute(
                text(
                    "SELECT id FROM knowledge_canonical_objects "
                    "WHERE organization_id = :oid AND source_id = :sid "
                    "ORDER BY id ASC LIMIT 1000"
                ),
                {"oid": str(org.id), "sid": str(source_id)},
            )
        ).fetchall()
        assert first == []

        # Página siguiente: CAST explícito del cursor a uuid.
        cursor = str(uuid4())
        second = (
            await session.execute(
                text(
                    "SELECT id FROM knowledge_canonical_objects "
                    "WHERE organization_id = :oid AND source_id = :sid "
                    "AND id > CAST(:cursor AS uuid) "
                    "ORDER BY id ASC LIMIT 1000"
                ),
                {"oid": str(org.id), "sid": str(source_id), "cursor": cursor},
            )
        ).fetchall()
        assert second == []
    finally:
        await session.close()
