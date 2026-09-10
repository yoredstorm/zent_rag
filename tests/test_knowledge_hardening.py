# =============================================================================
# Hardening — cancelación, notificaciones e isolación del run (FASH 33H)
# =============================================================================
# Cubre: cancelación vía API con RBAC y aislamiento multi-tenant, ejecución
# limpia de un job cancelado, notificación in-app de preguntas bloqueantes y
# consistencia de run/job tras cancelar.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.base import ConnectorPlugin
from src.connectors.plugin.models import (
    ColumnProfile,
    DeepSchemaDiscovery,
    DeepTableProfile,
)
from src.infrastructure.postgres.session import get_async_session


def _deep_fixture() -> DeepSchemaDiscovery:
    return DeepSchemaDiscovery(
        source="postgres",
        tables=[
            DeepTableProfile(
                table_name="TBL_CUST",
                schema="erp",
                table_comment="Clientes",
                columns=[
                    ColumnProfile(
                        name="CUST_ID", data_type="uuid", nullable=False,
                        is_primary_key=True,
                    ),
                    ColumnProfile(
                        name="STATUS_CD", data_type="character varying",
                        nullable=True, cardinality=2,
                        distinct_values=["A", "I"],
                    ),
                ],
            ),
        ],
    )


class _FakePlugin(ConnectorPlugin):
    connector_type = "postgres"
    capabilities = frozenset({"test", "discover"})
    required_secret_keys = ["password"]

    def __init__(self, config=None, secrets=None) -> None:
        super().__init__(config or {}, secrets or {})
        self.deep = _deep_fixture()

    async def validate(self) -> None:
        return None

    async def connect(self) -> None:
        return None

    async def deep_discover(self, max_samples: int = 50) -> DeepSchemaDiscovery:
        return self.deep

    async def sample_distinct_values(
        self, schema: str, table: str, column: str, max_samples: int = 50
    ) -> list[str]:
        return ["A", "I"]


async def _patch_plugin(monkeypatch, plugin: _FakePlugin) -> None:
    monkeypatch.setattr(
        "src.catalog.jobs.get_plugin",
        lambda connector_type, config, secrets: plugin,
    )


async def _patch_enqueue(monkeypatch) -> None:
    async def _noop(job_id: str) -> None:
        return None

    monkeypatch.setattr("src.knowledge.queue.enqueue_knowledge_job", _noop)


async def _create_org(prefix: str = "h") -> UUID:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name) "
                    "VALUES (uuid_generate_v4(), :name) RETURNING id"
                ),
                {"name": f"{prefix}-{uuid4().hex[:8]}"},
            )
        ).fetchone()
        await session.commit()
        return UUID(str(row.id))
    finally:
        await session.close()


async def _seed_source(org: UUID, name: str = "h-postgres") -> UUID:
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository

    connector_repo = PostgresConnectorRepository()
    await connector_repo.create_connector(org, name, "postgres", config_json={"host": "fake"})
    connectors = await connector_repo.list_connectors(org)
    connector = next(c for c in connectors if c.name == name)
    store = PostgresCatalogStore()
    await store.ensure_tables()
    source = await store.upsert_source(
        organization_id=org, connector_id=connector.id, engine="postgres"
    )
    source_id = source["id"]
    if not isinstance(source_id, UUID):
        source_id = UUID(str(source_id))
    return source_id


async def _build_engine(store: PostgresCatalogStore):
    from src.infrastructure.postgres.knowledge_repos import (
        PostgresIngestionJobRepository,
    )
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.intelligence.store import PostgresIntelligenceStore
    from src.platform.knowledge_learning.orchestrator import KnowledgeLearningEngine
    from src.platform.knowledge_learning.repository import (
        PostgresKnowledgeLearningRepository,
    )

    return KnowledgeLearningEngine(
        job_repo=PostgresIngestionJobRepository(),
        connector_repo=PostgresConnectorRepository(),
        catalog_store=store,
        intelligence_store=PostgresIntelligenceStore(),
        secret_store=None,
        llm_provider=None,
        repository=PostgresKnowledgeLearningRepository(),
    )


async def _cleanup_org(org: UUID) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM eval_runs WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM tenant_notifications WHERE organization_id = :oid"),
            {"oid": org},
        )
        for table in (
            "knowledge_feedback",
            "knowledge_questions",
            "knowledge_business_rules",
            "knowledge_llm_analyses",
            "knowledge_events",
            "knowledge_learning_steps",
            "knowledge_scores",
            "knowledge_learning_settings",
            "knowledge_learning_runs",
            "usage_events",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE organization_id = :oid"),  # noqa: S608
                {"oid": org},
            )
        for table in (
            "catalog_lineage",
            "catalog_suggestions",
            "catalog_relationships",
            "catalog_enum_values",
            "catalog_fields",
            "catalog_entities",
            "catalog_columns",
            "catalog_tables",
            "catalog_scans",
            "catalog_sources",
            "connectors",
            "ingestion_jobs",
            "mapping_suggestions",
            "audit_logs",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE organization_id = :oid"),  # noqa: S608
                {"oid": org},
            )
        await session.execute(text("DELETE FROM organizations WHERE id = :oid"), {"oid": org})
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Cancelación vía API
# ---------------------------------------------------------------------------


class TestCancelRunApi:
    @pytest.mark.asyncio
    async def test_cancel_flow_with_rbac_and_isolation(
        self, async_client, trial_auth, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = UUID(trial_auth["X-Organization-Id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await PostgresKnowledgeLearningRepository().ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        source_id = await _seed_source(org, "h-api")
        started = await engine.start_run(org, catalog_source_id=source_id)
        run_id = started["run"]["id"]

        cancelled = await async_client.post(
            f"/api/v1/knowledge/learning/runs/{run_id}/cancel",
            headers=trial_auth,
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["cancelled"] == run_id

        run = await engine._repo.get_run(org, UUID(run_id))
        assert run is not None and run["status"] == "cancelled"
        assert run["finished_at"] is not None

        job = await engine._jobs.get_job(org, UUID(started["job_id"]))
        assert job is not None and job.status.value == "canceled"

        events = await engine._repo.list_events(org, run_id=UUID(run_id), limit=100)
        assert any(e["event_type"] == "learning.cancelled" for e in events)

        # Idempotencia: cancelar de nuevo da 409.
        again = await async_client.post(
            f"/api/v1/knowledge/learning/runs/{run_id}/cancel",
            headers=trial_auth,
        )
        assert again.status_code == 409

        # Otro tenant no puede cancelar ni ver.
        other = await async_client.post(
            "/api/v1/billing/subscription/create-trial",
            json={
                "company_name": f"H Co {uuid4().hex[:8]}",
                "email": f"h-{uuid4().hex[:8]}@example.com",
            },
        )
        assert other.status_code == 200, other.text
        other_headers = {
            "Authorization": f"Bearer {other.json()['api_token']}",
            "X-Organization-Id": other.json()["organization_id"],
        }
        cross = await async_client.post(
            f"/api/v1/knowledge/learning/runs/{run_id}/cancel",
            headers=other_headers,
        )
        assert cross.status_code == 404

        unauthenticated = await async_client.post(
            f"/api/v1/knowledge/learning/runs/{run_id}/cancel"
        )
        assert unauthenticated.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Ejecución limpia de job cancelado
# ---------------------------------------------------------------------------


class TestCancelledJobExecution:
    @pytest.mark.asyncio
    async def test_execute_job_after_cancel_is_clean(self, monkeypatch) -> None:
        org = await _create_org("h-exec")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        try:
            source_id = await _seed_source(org, "h-exec-src")
            started = await engine.start_run(org, catalog_source_id=source_id)
            run_id = UUID(started["run"]["id"])
            await engine._repo.update_run(
                org, run_id, status="cancelled", finished_at=None
            )
            job = await engine.execute_job(UUID(started["job_id"]))
            assert job.status.value == "canceled"
            run = await engine._repo.get_run(org, run_id)
            assert run is not None and run["status"] == "cancelled"
            # Sin steps ejecutados ni errores de run.
            assert run["error_summary"] == {}
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Notificación de preguntas bloqueantes
# ---------------------------------------------------------------------------


class TestPendingQuestionsNotification:
    @pytest.mark.asyncio
    async def test_awaiting_run_notifies_in_app(self, monkeypatch) -> None:
        org = await _create_org("h-notify")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        try:
            source_id = await _seed_source(org, "h-notify-src")
            started = await engine.start_run(org, catalog_source_id=source_id)
            await engine.execute_job(UUID(started["job_id"]))
            run = await engine._repo.get_run(org, UUID(started["run"]["id"]))
            assert run is not None and run["status"] == "awaiting_validation"

            session = await get_async_session()
            try:
                row = (
                    await session.execute(
                        text(
                            "SELECT event_type, title FROM tenant_notifications "
                            "WHERE organization_id = :oid "
                            "AND event_type = 'knowledge.questions_pending' "
                            "ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"oid": org},
                    )
                ).fetchone()
            finally:
                await session.close()
            assert row is not None
            assert "pregunta" in row.title.lower()
        finally:
            await _cleanup_org(org)
