from __future__ import annotations

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


@pytest.mark.asyncio
async def test_p13_schema_is_applied_and_pointers_are_complete() -> None:
    session = await get_async_session()
    try:
        version = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar()
        assert int(str(version)) >= 173

        columns = (
            await session.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND ("
                    "(table_name = 'workflows' AND column_name IN ("
                    "'published_version_id','published_graph_hash','deployment_generation',"
                    "'draft_revision','capability_scope','safety_profile')) OR "
                    "(table_name = 'workflow_versions' AND column_name IN ("
                    "'workspace_id','graph_hash','legacy_baseline','trigger_hash')) OR "
                    "(table_name = 'workflow_ingress_events' AND column_name IN ("
                    "'dedupe_key','payload_hash','lease_expires_at','dead_letter_at')) OR "
                    "(table_name = 'workflow_runs' AND column_name IN ("
                    "'definition_source','effective_policy','effective_scope_hash'))"
                    ")"
                )
            )
        ).fetchall()
        found = {(row.table_name, row.column_name) for row in columns}
        expected = {
            ("workflows", "published_version_id"),
            ("workflows", "published_graph_hash"),
            ("workflows", "deployment_generation"),
            ("workflows", "draft_revision"),
            ("workflows", "capability_scope"),
            ("workflows", "safety_profile"),
            ("workflow_versions", "workspace_id"),
            ("workflow_versions", "graph_hash"),
            ("workflow_versions", "legacy_baseline"),
            ("workflow_versions", "trigger_hash"),
            ("workflow_ingress_events", "dedupe_key"),
            ("workflow_ingress_events", "payload_hash"),
            ("workflow_ingress_events", "lease_expires_at"),
            ("workflow_ingress_events", "dead_letter_at"),
            ("workflow_runs", "definition_source"),
            ("workflow_runs", "effective_policy"),
            ("workflow_runs", "effective_scope_hash"),
        }
        assert expected <= found

        missing_pointer = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflows "
                    "WHERE status = 'active' AND published_version_id IS NULL"
                )
            )
        ).scalar()
        assert int(missing_pointer or 0) == 0

        duplicate_production = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT workflow_id FROM workflow_versions "
                    "WHERE status = 'production' GROUP BY workflow_id HAVING COUNT(*) > 1"
                    ") dup"
                )
            )
        ).scalar()
        assert int(duplicate_production or 0) == 0

        outbox = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN "
                    "('workflow_outbox','workflow_effect_intents','workflow_policy_revocations',"
                    "'workflow_verification_evidence')"
                )
            )
        ).scalar()
        assert int(outbox or 0) == 4
    finally:
        await session.close()
