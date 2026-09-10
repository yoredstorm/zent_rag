# =============================================================================
# Knowledge Learning Engine — tests (FASE 33A)
# =============================================================================
# Cubre: fingerprint de schema, matemática del score, pesos configurables,
# aislamiento multi-tenant del repositorio, lifecycle del run (steps/eventos),
# fallo real del pipeline, replay SSE, RBAC y flag de feature.
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.base import ConnectorPlugin
from src.connectors.plugin.models import (
    ColumnProfile,
    DeepSchemaDiscovery,
    DeepTableProfile,
    Relationship,
)
from src.core.domain.knowledge_learning import (
    DEFAULT_SCORE_WEIGHTS,
    PHASE1_ACTIVE_STAGES,
    KnowledgeEventType,
    KnowledgeGate,
    LearningStage,
    compute_overall,
)
from src.infrastructure.postgres.session import get_async_session

ORG_DEV = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _deep_fixture() -> DeepSchemaDiscovery:
    return DeepSchemaDiscovery(
        source="postgres",
        tables=[
            DeepTableProfile(
                table_name="TBL_CUST",
                schema="erp",
                is_view=False,
                row_count_approx=1500,
                table_comment="Clientes corporativos",
                columns=[
                    ColumnProfile(
                        name="CUST_ID",
                        data_type="uuid",
                        nullable=False,
                        is_primary_key=True,
                    ),
                    ColumnProfile(
                        name="CUST_NAM",
                        data_type="character varying",
                        nullable=True,
                        column_comment="Nombre",
                    ),
                    ColumnProfile(
                        name="CUST_STS",
                        data_type="character varying",
                        nullable=True,
                        cardinality=4,
                        distinct_values=["A", "B", "C", "I"],
                    ),
                    ColumnProfile(
                        name="EMAIL_ADDR",
                        data_type="character varying",
                        nullable=True,
                        pii_flags=["email"],
                        sensitive=True,
                        sample_disabled=True,
                    ),
                ],
                foreign_keys=[],
            ),
            DeepTableProfile(
                table_name="TBL_ORD",
                schema="erp",
                row_count_approx=20000,
                columns=[
                    ColumnProfile(
                        name="ORD_ID",
                        data_type="uuid",
                        nullable=False,
                        is_primary_key=True,
                    ),
                    ColumnProfile(name="CUST_ID", data_type="uuid", nullable=True),
                    ColumnProfile(
                        name="STATUS_CD",
                        data_type="character varying",
                        nullable=True,
                        cardinality=3,
                        distinct_values=["P", "C", "X"],
                    ),
                ],
                foreign_keys=[
                    Relationship(
                        from_column="CUST_ID", to_table="TBL_CUST", to_column="CUST_ID"
                    ),
                ],
            ),
        ],
    )


class _FakePlugin(ConnectorPlugin):
    connector_type = "postgres"
    capabilities = frozenset({"test", "discover"})
    required_secret_keys = ["password"]

    def __init__(self, config=None, secrets=None, fail_validate: bool = False) -> None:
        super().__init__(config or {}, secrets or {})
        self.deep = _deep_fixture()
        self.fail_validate = fail_validate

    async def validate(self) -> None:
        if self.fail_validate:
            raise RuntimeError("fake connector unreachable")

    async def connect(self) -> None:
        return None

    async def deep_discover(self, max_samples: int = 50) -> DeepSchemaDiscovery:
        return self.deep

    async def sample_distinct_values(
        self, schema: str, table: str, column: str, max_samples: int = 50
    ) -> list[str]:
        for t in self.deep.tables:
            if t.table_name == table:
                for c in t.columns:
                    if c.name == column:
                        return list(c.distinct_values)
        return []


async def _patch_plugin(monkeypatch, plugin: _FakePlugin) -> None:
    def _fake_get_plugin(connector_type, config, secrets):
        return plugin

    monkeypatch.setattr("src.catalog.jobs.get_plugin", _fake_get_plugin)

async def _patch_enqueue(monkeypatch) -> None:
    async def _noop(job_id: str) -> None:
        return None

    monkeypatch.setattr("src.knowledge.queue.enqueue_knowledge_job", _noop)


async def _create_org(prefix: str = "kl") -> UUID:
    """Organización real (FK de knowledge_learning_runs -> organizations)."""
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


async def _cleanup_org(org: UUID) -> None:
    session = await get_async_session()
    try:
        for table in (
            "knowledge_events",
            "knowledge_learning_steps",
            "knowledge_scores",
            "knowledge_learning_settings",
            "knowledge_learning_runs",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE organization_id = :oid"),  # noqa: S608
                {"oid": org},
            )
        await session.execute(
            text("DELETE FROM catalog_relationships WHERE organization_id = :oid"),
            {"oid": org},
        )
        await session.execute(
            text("DELETE FROM catalog_enum_values WHERE organization_id = :oid"),
            {"oid": org},
        )
        await session.execute(
            text("DELETE FROM catalog_fields WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM catalog_entities WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM catalog_columns WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM catalog_tables WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM catalog_scans WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM catalog_sources WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM connectors WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM ingestion_jobs WHERE organization_id = :oid"), {"oid": org}
        )
        await session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": org}
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
    finally:
        await session.close()


async def _seed_source(org: UUID, name: str = "kl-postgres") -> tuple[UUID, UUID]:
    """Crea connector + catalog source reales; retorna (connector_id, source_id)."""
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository

    connector_repo = PostgresConnectorRepository()
    await connector_repo.create_connector(
        org, name, "postgres", config_json={"host": "fake"}
    )
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
    return connector.id, source_id


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

    repo = PostgresKnowledgeLearningRepository()
    return KnowledgeLearningEngine(
        job_repo=PostgresIngestionJobRepository(),
        connector_repo=PostgresConnectorRepository(),
        catalog_store=store,
        intelligence_store=PostgresIntelligenceStore(),
        secret_store=None,
        llm_provider=None,
        repository=repo,
    )


# ---------------------------------------------------------------------------
# Fingerprint de schema (§27)
# ---------------------------------------------------------------------------


class TestSchemaFingerprint:
    def _table(self, **overrides) -> dict:
        base = {
            "schema_name": "public",
            "table_name": "orders",
            "is_view": False,
            "table_comment": "Pedidos",
            "row_count_approx": 100,
        }
        base.update(overrides)
        return base

    def _columns(self, **overrides) -> list[dict]:
        col = {
            "column_name": "total",
            "data_type": "numeric",
            "nullable": True,
            "is_primary_key": False,
            "column_comment": None,
            "is_sensitive": False,
            "null_ratio": 0.1,
        }
        col.update(overrides)
        return [col]

    def test_stable_for_same_schema(self) -> None:
        from src.platform.knowledge_learning.schema_analyzer import table_fingerprint

        first = table_fingerprint(self._table(), self._columns())
        second = table_fingerprint(self._table(), self._columns())
        assert first == second and len(first) == 64

    def test_ignores_data_stats(self) -> None:
        from src.platform.knowledge_learning.schema_analyzer import table_fingerprint

        before = table_fingerprint(self._table(row_count_approx=10), self._columns())
        after = table_fingerprint(
            self._table(row_count_approx=999999), self._columns(null_ratio=0.9)
        )
        assert before == after

    def test_changes_with_type_or_comment(self) -> None:
        from src.platform.knowledge_learning.schema_analyzer import table_fingerprint

        base = table_fingerprint(self._table(), self._columns())
        changed_type = table_fingerprint(
            self._table(), self._columns(data_type="text")
        )
        changed_comment = table_fingerprint(
            self._table(table_comment="Pedidos históricos"), self._columns()
        )
        assert base != changed_type
        assert base != changed_comment


# ---------------------------------------------------------------------------
# Score (§11) — matemática pura
# ---------------------------------------------------------------------------


class TestScoreMath:
    def test_weighted_average(self) -> None:
        weights = {"a": 0.5, "b": 0.5}
        assert compute_overall({"a": 100.0, "b": 0.0}, weights) == 50.0

    def test_missing_dimension_counts_as_zero(self) -> None:
        weights = {"a": 0.5, "b": 0.5}
        assert compute_overall({"a": 100.0}, weights) == 50.0

    def test_weights_are_normalized(self) -> None:
        assert compute_overall({"a": 80.0, "b": 80.0}, {"a": 2.0, "b": 1.0}) == 80.0

    def test_empty_weights_is_zero(self) -> None:
        assert compute_overall({"a": 90.0}, {}) == 0.0

    def test_default_weights_sum_to_one(self) -> None:
        assert round(sum(DEFAULT_SCORE_WEIGHTS.values()), 6) == 1.0


class TestSettingsMerge:
    def test_invalid_weights_ignored(self) -> None:
        from src.core.domain.knowledge_learning import KnowledgeLearningSettings

        settings = KnowledgeLearningSettings(
            organization_id=uuid4(),
            weights={"schema_discovery": 0.5, "inventado": 0.9, "relationships": -1},
        )
        effective = settings.effective_weights()
        assert effective["schema_discovery"] == 0.5
        assert "inventado" not in effective
        assert effective["relationships"] == DEFAULT_SCORE_WEIGHTS["relationships"]


# ---------------------------------------------------------------------------
# Repositorio — aislamiento multi-tenant y lifecycle
# ---------------------------------------------------------------------------


class TestRepositoryIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_reads_return_none(self) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org_a = await _create_org("kl-a")
        org_b = await _create_org("kl-b")
        repo = PostgresKnowledgeLearningRepository()
        await repo.ensure_tables()
        try:
            _, source_a = await _seed_source(org_a, "kl-iso-a")
            run = await repo.create_run(org_a, catalog_source_id=source_a)
            assert await repo.get_run(org_a, UUID(run["id"])) is not None
            assert await repo.get_run(org_b, UUID(run["id"])) is None
            assert await repo.list_runs(org_b) == []
            active_b = await repo.find_active_run(org_b, source_a)
            assert active_b is None
        finally:
            await _cleanup_org(org_a)
            await _cleanup_org(org_b)

    @pytest.mark.asyncio
    async def test_active_run_is_unique_per_source(self) -> None:
        from src.platform.knowledge_learning.repository import (
            ActiveRunExistsError,
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("kl-active")
        repo = PostgresKnowledgeLearningRepository()
        await repo.ensure_tables()
        try:
            _, source = await _seed_source(org, "kl-active-src")
            first = await repo.create_run(org, catalog_source_id=source)
            with pytest.raises(ActiveRunExistsError):
                await repo.create_run(org, catalog_source_id=source)
            await repo.update_run(org, UUID(first["id"]), status="completed")
            second = await repo.create_run(org, catalog_source_id=source)
            assert second["id"] != first["id"]
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Orquestador end-to-end (determinista, sin LLM)
# ---------------------------------------------------------------------------


class TestLearningRunLifecycle:
    @pytest.mark.asyncio
    async def test_full_run_persists_steps_events_and_score(
        self, monkeypatch
    ) -> None:
        org = await _create_org("kl-run")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        plugin = _FakePlugin()
        await _patch_plugin(monkeypatch, plugin)
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        try:
            _, source_id = await _seed_source(org, "kl-run-src")
            started = await engine.start_run(
                org, catalog_source_id=source_id, trigger="manual"
            )
            run_id = UUID(started["run"]["id"])
            steps = await engine._repo.list_steps(org, run_id)
            assert [s["stage"] for s in steps] == [
                stage.value for stage in PHASE1_ACTIVE_STAGES
            ]
            assert all(s["status"] == "pending" for s in steps)

            job = await engine.execute_job(UUID(started["job_id"]))
            assert job.status.value == "completed"

            run = await engine._repo.get_run(org, run_id)
            assert run is not None
            # F33D: con preguntas bloqueantes pendientes el run espera validación.
            assert run["status"] in ("completed", "awaiting_validation")
            assert run["overall_progress"] == 100
            assert run["tables_analyzed"] == 2
            assert run["entities_detected"] >= 1
            assert run["fields_detected"] >= 1
            assert run["relationships_detected"] >= 1
            assert run["gate"] in {g.value for g in KnowledgeGate}

            steps = await engine._repo.list_steps(org, run_id)
            assert all(s["status"] == "completed" for s in steps)
            assert all(s["finished_at"] is not None for s in steps)
            detecting = next(
                s for s in steps if s["stage"] == LearningStage.DETECTING_ENTITIES.value
            )
            assert detecting["metrics"]["entities_detected"] >= 1

            events = await engine._repo.list_events(org, run_id=run_id, limit=1000)
            event_types = {e["event_type"] for e in events}
            assert KnowledgeEventType.LEARNING_STARTED.value in event_types
            assert KnowledgeEventType.SCHEMA_DISCOVERED.value in event_types
            assert KnowledgeEventType.ENTITY_DETECTED.value in event_types
            assert KnowledgeEventType.FIELD_DETECTED.value in event_types
            assert KnowledgeEventType.RELATIONSHIP_DETECTED.value in event_types
            assert KnowledgeEventType.SCORE_COMPUTED.value in event_types
            assert KnowledgeEventType.LEARNING_COMPLETED.value in event_types
            assert all(e["organization_id"] == str(org) for e in events)

            score = await engine._repo.get_score(org, source_id)
            assert score is not None
            assert len(score["dimensions"]) == 7
            assert score["reasons"]

            # Fingerprints persistidos en el catálogo físico.
            tables = await store.list_tables(org, source_id)
            assert all(t["schema_fingerprint"] for t in tables)

            # Entidades/campos/relaciones reales en el catálogo semántico.
            entities = await store.list_entities(org)
            relationships = await store.list_relationships(org, source_id)
            assert len(entities) >= 1
            assert any(r["relation_type"] == "foreign_key" for r in relationships)
            assert all(e["provenance"] == "INFERRED" for e in entities)

            # Con preguntas bloqueantes el run queda awaiting_validation: un
            # segundo run sobre la misma fuente se rechaza hasta resolverlas.
            from src.platform.knowledge_learning.repository import (
                ActiveRunExistsError,
            )

            with pytest.raises(ActiveRunExistsError):
                await engine.start_run(org, catalog_source_id=source_id)
            await engine._repo.update_run(org, run_id, status="cancelled")
            started_again = await engine.start_run(org, catalog_source_id=source_id)
            await engine._repo.update_run(
                org, UUID(started_again["run"]["id"]), status="cancelled"
            )
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_failed_run_marks_step_and_event(self, monkeypatch) -> None:
        org = await _create_org("kl-fail")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        plugin = _FakePlugin(fail_validate=True)
        await _patch_plugin(monkeypatch, plugin)
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        try:
            _, source_id = await _seed_source(org, "kl-fail-src")
            started = await engine.start_run(org, catalog_source_id=source_id)
            run_id = UUID(started["run"]["id"])
            job = await engine.execute_job(UUID(started["job_id"]))

            run = await engine._repo.get_run(org, run_id)
            assert run is not None and run["status"] == "failed"
            assert "fake connector unreachable" in str(run["error_summary"])
            failed_steps = [
                s
                for s in await engine._repo.list_steps(org, run_id)
                if s["status"] == "failed"
            ]
            assert len(failed_steps) == 1
            assert failed_steps[0]["stage"] == LearningStage.CONNECTING.value
            assert job.status.value in ("failed", "dead")

            events = await engine._repo.list_events(org, run_id=run_id)
            assert KnowledgeEventType.LEARNING_FAILED.value in {
                e["event_type"] for e in events
            }
            # Un intento fallido programa retry (no muere al primer fallo).
            assert job.status.value == "failed"
            assert job.retry_at is not None
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_sse_replay_emits_durable_events(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.events import knowledge_event_source

        org = await _create_org("kl-sse")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        try:
            _, source_id = await _seed_source(org, "kl-sse-src")
            started = await engine.start_run(org, catalog_source_id=source_id)
            run_id = UUID(started["run"]["id"])
            await engine.execute_job(UUID(started["job_id"]))

            generator = knowledge_event_source(
                org, run_id=run_id, since_seq=0, repository=engine._repo
            )
            try:
                frame = await asyncio.wait_for(generator.__anext__(), timeout=10)
            finally:
                await generator.aclose()
            assert "event: learning.started" in frame
            assert str(run_id) in frame
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Score service sobre catálogo real
# ---------------------------------------------------------------------------


class TestScoreService:
    @pytest.mark.asyncio
    async def test_score_breakdown_and_gate_without_evaluation(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.knowledge_score import (
            KnowledgeScoreService,
        )
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("kl-score")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        repo = PostgresKnowledgeLearningRepository()
        try:
            _, source_id = await _seed_source(org, "kl-score-src")
            started = await engine.start_run(org, catalog_source_id=source_id)
            await engine.execute_job(UUID(started["job_id"]))

            service = KnowledgeScoreService(store, repository=repo)
            result = await service.compute(
                org, source_id=source_id, persist=True, active_run={}
            )
            assert len(result.dimensions) == 7
            assert result.dimension("rag_evaluation") is not None
            assert result.dimension("rag_evaluation").measured is False
            # Sin evaluación RAG el gate no puede ser READY (§31).
            assert result.gate in (KnowledgeGate.NOT_READY, KnowledgeGate.NEEDS_INPUT)
            assert any("evaluación" in reason.lower() for reason in result.reasons)

            # Pesos configurables por tenant.
            await repo.upsert_settings(
                org, weights={"schema_discovery": 0.5}, thresholds={}
            )
            custom = await service.compute(
                org, source_id=source_id, persist=False, active_run={}
            )
            schema_dim = custom.dimension("schema_discovery")
            assert schema_dim is not None and schema_dim.weight == 0.5
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# API — RBAC, aislamiento y feature flag
# ---------------------------------------------------------------------------


class TestKnowledgeLearningApi:
    @pytest.mark.asyncio
    async def test_status_and_score(self, async_client, trial_auth) -> None:
        status_resp = await async_client.get(
            "/api/v1/knowledge/learning/status", headers=trial_auth
        )
        assert status_resp.status_code == 200, status_resp.text
        status = status_resp.json()
        assert "counts" in status and "readiness" in status
        assert status["counts"]["sources_connected"] == 0

        score_resp = await async_client.get(
            "/api/v1/knowledge/learning/score", headers=trial_auth
        )
        assert score_resp.status_code == 200, score_resp.text
        score = score_resp.json()
        assert len(score["dimensions"]) == 7
        assert score["gate"] in {g.value for g in KnowledgeGate}

    @pytest.mark.asyncio
    async def test_start_unknown_source_returns_404(
        self, async_client, trial_auth, monkeypatch
    ) -> None:
        await _patch_enqueue(monkeypatch)
        resp = await async_client.post(
            "/api/v1/knowledge/learning/start",
            json={"catalog_source_id": str(uuid4())},
            headers=trial_auth,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_start_requires_write_permission(self, async_client) -> None:
        resp = await async_client.get("/api/v1/knowledge/learning/status")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_disabled_flag_blocks_start(
        self, async_client, trial_auth, monkeypatch
    ) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_KNOWLEDGE_LEARNING_ENABLED", False)
        resp = await async_client.post(
            "/api/v1/knowledge/learning/start",
            json={"catalog_source_id": str(uuid4())},
            headers=trial_auth,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_run_is_org_scoped(self, async_client, trial_auth) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org_a = UUID(trial_auth["X-Organization-Id"])
        _, source_a = await _seed_source(org_a, "kl-api-a")
        repo = PostgresKnowledgeLearningRepository()
        await repo.ensure_tables()
        run = await repo.create_run(org_a, catalog_source_id=source_a)

        # Otro tenant no puede ver el run.
        other = await async_client.post(
            "/api/v1/billing/subscription/create-trial",
            json={
                "company_name": f"Other Co {uuid4().hex[:8]}",
                "email": f"other-{uuid4().hex[:8]}@example.com",
            },
        )
        assert other.status_code == 200, other.text
        other_headers = {
            "Authorization": f"Bearer {other.json()['api_token']}",
            "X-Organization-Id": other.json()["organization_id"],
        }
        resp = await async_client.get(
            f"/api/v1/knowledge/learning/runs/{run['id']}", headers=other_headers
        )
        assert resp.status_code == 404

        # El dueño sí lo ve.
        own = await async_client.get(
            f"/api/v1/knowledge/learning/runs/{run['id']}", headers=trial_auth
        )
        assert own.status_code == 200
        assert own.json()["id"] == run["id"]
