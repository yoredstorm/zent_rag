# =============================================================================
# Knowledge Evaluation — auto-evaluación RAG (FASE 33G)
# =============================================================================
# Cubre: preguntas sintéticas justificadas por el catálogo, ejecución contra el
# RAG pipeline real (fake), persistencia en eval_runs, dimensión del score,
# etapa evaluating del run y API.
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
    Relationship,
)
from src.core.domain.entities import LLMResponse, QueryStatus, RAGQueryResult, RetrievalChunk, RetrievalContext
from src.infrastructure.postgres.session import get_async_session


def _deep_fixture() -> DeepSchemaDiscovery:
    return DeepSchemaDiscovery(
        source="postgres",
        tables=[
            DeepTableProfile(
                table_name="TBL_CUST",
                schema="erp",
                row_count_approx=1500,
                table_comment="Clientes",
                columns=[
                    ColumnProfile(
                        name="CUST_ID", data_type="character varying",
                        nullable=False, is_primary_key=True,
                    ),
                    ColumnProfile(
                        name="CUST_NAM", data_type="character varying",
                        nullable=True, column_comment="Nombre",
                    ),
                    ColumnProfile(
                        name="FEC_REG", data_type="timestamp",
                        nullable=True,
                    ),
                    ColumnProfile(
                        name="TOTAL_AMT", data_type="numeric",
                        nullable=True,
                    ),
                ],
            ),
            DeepTableProfile(
                table_name="TBL_ORD",
                schema="erp",
                row_count_approx=20000,
                columns=[
                    ColumnProfile(
                        name="ORD_ID", data_type="character varying",
                        nullable=False, is_primary_key=True,
                    ),
                    ColumnProfile(name="CUST_ID", data_type="character varying", nullable=True),
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
        return []


class _FakeOrchestrator:
    """Orquestador RAG falso con contrato real de RAGTarget."""

    def __init__(self, answer: str, chunk: str) -> None:
        self.answer = answer
        self.chunk = chunk
        self.calls: list[str] = []

    async def execute(
        self,
        *,
        organization_id,
        user_id,
        query,
        model=None,
        temperature=0.3,
        top_k=200,
        use_cache=True,
        role="admin",
    ):
        self.calls.append(query)
        chunk = RetrievalChunk(
            document_id=uuid4(),
            content=self.chunk,
            score=0.92,
            metadata={"source": "erp.TBL_CUST", "table": "TBL_CUST"},
        )
        return RAGQueryResult(
            organization_id=organization_id,
            user_id=user_id,
            query=query,
            status=QueryStatus.COMPLETED,
            retrieval_context=RetrievalContext(
                chunks=[chunk], retrieval_latency_ms=12.0
            ),
            llm_response=LLMResponse(
                content=self.answer,
                model=model or "fake-model",
                prompt_tokens=80,
                completion_tokens=40,
                total_tokens=120,
                latency_ms=30.0,
            ),
            total_latency_ms=45.0,
            method="rag",
        )


async def _patch_plugin(monkeypatch, plugin: _FakePlugin) -> None:
    monkeypatch.setattr(
        "src.catalog.jobs.get_plugin",
        lambda connector_type, config, secrets: plugin,
    )


async def _patch_enqueue(monkeypatch) -> None:
    async def _noop(job_id: str) -> None:
        return None

    monkeypatch.setattr("src.knowledge.queue.enqueue_knowledge_job", _noop)


async def _create_org(prefix: str = "ev") -> UUID:
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


async def _seed_source(org: UUID, name: str = "ev-postgres") -> UUID:
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


async def _build_engine(store: PostgresCatalogStore, *, llm=None, score_service=None):
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
        llm_provider=llm,
        repository=PostgresKnowledgeLearningRepository(),
        score_service=score_service,
    )


async def _seed_run(
    org: UUID, store: PostgresCatalogStore, monkeypatch
) -> tuple[UUID, dict]:
    """Corre un run 33A-33D (sin LLM/eval) para poblar el catálogo."""
    await _patch_plugin(monkeypatch, _FakePlugin())
    await _patch_enqueue(monkeypatch)
    engine = await _build_engine(store)
    source_id = await _seed_source(org)
    started = await engine.start_run(org, catalog_source_id=source_id)
    await engine.execute_job(UUID(started["job_id"]))
    run = await engine._repo.get_run(org, UUID(started["run"]["id"]))
    return source_id, run or {}


async def _cleanup_org(org: UUID) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM eval_runs WHERE organization_id = :oid"), {"oid": org}
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
# Preguntas sintéticas
# ---------------------------------------------------------------------------


class TestSyntheticQuestions:
    @pytest.mark.asyncio
    async def test_questions_are_justified_by_catalog(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.evaluation import (
            generate_synthetic_questions,
        )

        org = await _create_org("ev-gen")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            questions = await generate_synthetic_questions(
                store, org, source_id, limit=20
            )
            kinds = {q["kind"] for q in questions}
            assert {"count", "recent", "top"}.issubset(kinds)
            for question in questions:
                assert question["question"]
                assert question["evidence"]
                assert question["keywords"]
                assert question["entity_id"]
            capped = await generate_synthetic_questions(store, org, source_id, limit=2)
            assert len(capped) == 2
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_empty_catalog_has_no_questions(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.evaluation import (
            generate_synthetic_questions,
        )

        org = await _create_org("ev-empty")
        store = PostgresCatalogStore()
        try:
            source_id = await _seed_source(org, "ev-empty-src")
            questions = await generate_synthetic_questions(store, org, source_id, limit=10)
            assert questions == []
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Servicio de evaluación
# ---------------------------------------------------------------------------


class TestEvaluationService:
    @pytest.mark.asyncio
    async def test_run_persists_and_measures_score(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.evaluation import (
            KnowledgeEvaluationService,
        )
        from src.platform.knowledge_learning.knowledge_score import (
            KnowledgeScoreService,
        )
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("ev-run")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            fake = _FakeOrchestrator(
                answer="Los clientes con mayor Amount son los de la región norte.",
                chunk="Customer TotalAmount Amount es la medida de compras.",
            )
            service = KnowledgeEvaluationService(
                store, repo, orchestrator=fake
            )
            result = await service.run(org, source_id=source_id)
            assert result["status"] == "completed"
            assert result["questions"] >= 1
            assert (result["composite_score"] or 0) > 0.4
            assert (result["quality"] or {}).get("retrieval_precision") == 1.0
            assert fake.calls

            latest = await service.latest(org, source_id=source_id)
            assert latest is not None
            assert latest["dataset_name"].startswith("knowledge-auto")
            assert (latest["overall"] or 0) > 40

            from src.rag.evaluation.store import list_eval_runs

            runs = await list_eval_runs(org)
            assert any(r["dataset_name"].startswith("knowledge-auto") for r in runs)

            # La dimensión rag_evaluation ahora está medida y real.
            score = KnowledgeScoreService(store, repository=repo)
            result_score = await score.compute(
                org, source_id=source_id, persist=False, active_run={}
            )
            dimension = result_score.dimension("rag_evaluation")
            assert dimension is not None
            assert dimension.measured is True
            assert dimension.score > 40
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_skips_without_candidates(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.evaluation import (
            KnowledgeEvaluationService,
        )
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("ev-skip")
        store = PostgresCatalogStore()
        try:
            source_id = await _seed_source(org, "ev-skip-src")
            service = KnowledgeEvaluationService(
                store, PostgresKnowledgeLearningRepository()
            )
            result = await service.run(org, source_id=source_id)
            assert result["status"] == "skipped"
            assert result["reason"] == "no_synthetic_questions"
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Etapa evaluating del run
# ---------------------------------------------------------------------------


class TestEvaluationStage:
    @pytest.mark.asyncio
    async def test_stage_runs_with_fake_orchestrator(self, monkeypatch) -> None:
        import src.platform.knowledge_learning.evaluation as evaluation_module
        from src.core.config import get_settings
        from src.core.domain.knowledge_learning import KnowledgeEventType

        monkeypatch.setattr(
            get_settings(), "RAG_KNOWLEDGE_EVALUATION_ENABLED", True
        )
        fake = _FakeOrchestrator(
            answer="Los clientes con mayor Amount lideran las ventas.",
            chunk="Customer TotalAmount Amount compras de clientes.",
        )

        async def _fake_resolver():
            return fake

        monkeypatch.setattr(
            evaluation_module, "_resolve_orchestrator", _fake_resolver
        )
        org = await _create_org("ev-stage")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store)
        try:
            source_id = await _seed_source(org, "ev-stage-src")
            started = await engine.start_run(org, catalog_source_id=source_id)
            job = await engine.execute_job(UUID(started["job_id"]))
            assert job.status.value == "completed"
            run = await engine._repo.get_run(org, UUID(started["run"]["id"]))
            steps = {
                s["stage"]: s
                for s in await engine._repo.list_steps(org, UUID(started["run"]["id"]))
            }
            assert "evaluating" in steps
            evaluating = steps["evaluating"]
            assert evaluating["status"] == "completed"
            assert (evaluating["metrics"].get("composite_score") or 0) > 0.4
            events = await engine._repo.list_events(
                org, run_id=UUID(started["run"]["id"]), limit=1000
            )
            types = {e["event_type"] for e in events}
            assert KnowledgeEventType.EVALUATION_STARTED.value in types
            assert KnowledgeEventType.EVALUATION_COMPLETED.value in types
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class TestEvaluationApi:
    @pytest.mark.asyncio
    async def test_evaluation_endpoints_with_rbac(self, async_client, trial_auth) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = UUID(trial_auth["X-Organization-Id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await PostgresKnowledgeLearningRepository().ensure_tables()
        source_id = await _seed_source(org, "ev-api")

        latest = await async_client.get(
            "/api/v1/knowledge/learning/evaluation",
            params={"source_id": str(source_id)},
            headers=trial_auth,
        )
        assert latest.status_code == 200, latest.text
        body = latest.json()
        assert "enabled" in body and "latest" in body

        # Sin catálogo indexado: la auto-evaluación se omite con causa real.
        run = await async_client.post(
            "/api/v1/knowledge/learning/evaluation/run",
            json={"source_id": str(source_id)},
            headers=trial_auth,
        )
        assert run.status_code == 200, run.text
        assert run.json()["status"] in ("completed", "skipped")

        unauthenticated = await async_client.post(
            "/api/v1/knowledge/learning/evaluation/run",
            json={"source_id": str(source_id)},
        )
        assert unauthenticated.status_code in (401, 403)
