# =============================================================================
# LLM Semantic Intelligence — tests (FASE 33B)
# =============================================================================
# Cubre: sanitización (PII/secretos/samples), validación Pydantic del JSON,
# invalid JSON, timeout del proveedor, fallback heurístico, cache por
# fingerprint+modelo, registro de usage/costos, quota y etapa LLM del run.
# =============================================================================
from __future__ import annotations

import json
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
from src.core.domain.entities import LLMResponse
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_learning.llm_analyzer import (
    PROMPT_VERSION,
    LLMAnalyzer,
    parse_llm_analysis,
    sanitize_llm_context,
)

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
                        name="CUST_ID", data_type="uuid", nullable=False,
                        is_primary_key=True,
                    ),
                    ColumnProfile(
                        name="CUST_NAM", data_type="character varying",
                        nullable=True, column_comment="Nombre",
                    ),
                    ColumnProfile(
                        name="CUST_STS", data_type="character varying",
                        nullable=True, cardinality=4,
                        distinct_values=["A", "B", "C", "I"],
                    ),
                    ColumnProfile(
                        name="EMAIL_ADDR", data_type="character varying",
                        nullable=True, pii_flags=["email"], sensitive=True,
                        sample_disabled=True,
                    ),
                    ColumnProfile(
                        name="API_KEY_HASH", data_type="character varying",
                        nullable=True,
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
                        name="ORD_ID", data_type="uuid", nullable=False,
                        is_primary_key=True,
                    ),
                    ColumnProfile(name="CUST_ID", data_type="uuid", nullable=True),
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
        for t in self.deep.tables:
            if t.table_name == table:
                for c in t.columns:
                    if c.name == column:
                        return list(c.distinct_values)
        return []


class _FakeLLM:
    """Proveedor LLM falso con firma real de LLMProvider.generate."""

    def __init__(self, content: str = "", *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        self.calls.append({"prompt": prompt, "model": model, "system": system_prompt})
        if self.fail:
            raise TimeoutError("llm timeout")
        return LLMResponse(
            content=self.content,
            model=model or "fake-model",
            prompt_tokens=120,
            completion_tokens=80,
            total_tokens=200,
            latency_ms=12.5,
            finish_reason="stop",
        )


def _analysis_json() -> str:
    return json.dumps(
        {
            "entity": {
                "name": "Customer",
                "business_name": "Cliente",
                "description": "Personas u organizaciones que compran productos.",
                "business_purpose": "Gestionar la relación con clientes.",
                "confidence": 0.94,
                "reasoning_summary": "La tabla representa clientes por su PK y columnas.",
                "evidence": ["primary key CUST_ID", "comentario de tabla"],
            },
            "fields": [
                {
                    "physical_column": "CUST_NAM",
                    "business_name": "Nombre de Cliente",
                    "description": "Nombre completo del cliente.",
                    "role": "DESCRIPTION",
                    "confidence": 0.9,
                    "reasoning_summary": "Columna de texto con nombre.",
                    "evidence": ["tipo texto"],
                },
                {
                    "physical_column": "CUST_STS",
                    "business_name": "Estado",
                    "description": "Estado del cliente.",
                    "role": "STATUS",
                    "confidence": 0.82,
                    "reasoning_summary": "Valores categóricos A/B/C/I.",
                    "evidence": ["cardinalidad 4"],
                },
            ],
            "relationships": [],
            "business_rules": [
                {
                    "name": "Cliente activo",
                    "definition": "Un cliente con estado A está activo.",
                    "applies_to": ["CUST_STS"],
                    "confidence": 0.8,
                    "evidence": ["valores A/I"],
                }
            ],
            "possible_metrics": [
                {
                    "name": "Clientes activos",
                    "definition": "Conteo de clientes activos.",
                    "formula": "COUNT(*) WHERE estado = A",
                    "confidence": 0.75,
                    "evidence": ["CUST_STS"],
                }
            ],
            "dimensions": [],
            "questions": [
                {
                    "question": "¿A significa Activo e I Inactivo?",
                    "target": "CUST_STS",
                    "options": ["Activo", "Inactivo"],
                    "impact": "high",
                    "confidence": 0.6,
                    "evidence": ["valores A/I"],
                }
            ],
            "ambiguities": [],
        }
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


async def _create_org(prefix: str = "llm") -> UUID:
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


async def _seed_source(org: UUID, name: str = "llm-postgres") -> tuple[UUID, UUID]:
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
    return connector.id, source_id


async def _build_engine(store: PostgresCatalogStore, *, llm=None):
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
    )


async def _seed_catalog(org: UUID, store: PostgresCatalogStore, monkeypatch) -> UUID:
    """Corre un run FASE 33A (sin LLM) para poblar el catálogo físico/semántico."""
    await _patch_plugin(monkeypatch, _FakePlugin())
    await _patch_enqueue(monkeypatch)
    engine = await _build_engine(store)
    _, source_id = await _seed_source(org)
    started = await engine.start_run(org, catalog_source_id=source_id)
    await engine.execute_job(UUID(started["job_id"]))
    return source_id


# ---------------------------------------------------------------------------
# Sanitización (§28)
# ---------------------------------------------------------------------------


class TestSanitizeLLMContext:
    def _columns(self) -> list[dict]:
        return [
            {
                "id": "c1",
                "column_name": "CUST_NAM",
                "data_type": "character varying",
                "nullable": True,
                "is_primary_key": False,
                "column_comment": "Nombre",
                "cardinality_approx": 500,
                "is_sensitive": False,
                "sample_disabled": False,
            },
            {
                "id": "c2",
                "column_name": "CUST_STS",
                "data_type": "character varying",
                "nullable": True,
                "is_primary_key": False,
                "column_comment": "Estado",
                "cardinality_approx": 4,
                "is_sensitive": False,
                "sample_disabled": False,
            },
            {
                "id": "c3",
                "column_name": "EMAIL_ADDR",
                "data_type": "character varying",
                "nullable": True,
                "is_primary_key": False,
                "is_sensitive": True,
                "sample_disabled": True,
            },
            {
                "id": "c4",
                "column_name": "API_KEY_HASH",
                "data_type": "character varying",
                "nullable": True,
                "is_primary_key": False,
                "is_sensitive": False,
                "sample_disabled": False,
            },
            {
                "id": "c5",
                "column_name": "USER_PASSWORD",
                "data_type": "text",
                "nullable": True,
                "is_primary_key": False,
                "is_sensitive": False,
                "sample_disabled": False,
            },
        ]

    def test_omits_sensitive_and_secret_like_columns(self) -> None:
        result = sanitize_llm_context(
            table={"schema_name": "erp", "table_name": "TBL_CUST", "table_comment": "Clientes"},
            columns=self._columns(),
            enum_values={"CUST_STS": [{"value": "A"}, {"value": "I"}]},
        )
        names = {c["name"] for c in result.payload["columns"]}
        assert "CUST_NAM" in names
        assert "CUST_STS" in names
        assert "EMAIL_ADDR" not in names
        assert "API_KEY_HASH" not in names
        assert "USER_PASSWORD" not in names
        assert result.meta["columns_omitted_sensitive"] == 3

    def test_samples_only_for_safe_low_cardinality_columns(self) -> None:
        result = sanitize_llm_context(
            table={"schema_name": "erp", "table_name": "TBL_CUST"},
            columns=self._columns(),
            enum_values={
                "CUST_STS": [{"value": "A"}, {"value": "I"}],
                "EMAIL_ADDR": [{"value": "a@b.com"}],
                "CUST_NAM": [{"value": f"cliente {i}"} for i in range(50)],
            },
            max_samples=5,
        )
        by_name = {c["name"]: c for c in result.payload["columns"]}
        assert by_name["CUST_STS"]["sample_values"] == ["A", "I"]
        # cardinalidad alta: sin muestras
        assert "sample_values" not in by_name["CUST_NAM"]
        # sensible: columna ausente
        assert "EMAIL_ADDR" not in by_name

    def test_unsafe_sample_values_are_dropped(self) -> None:
        result = sanitize_llm_context(
            table={"schema_name": "erp", "table_name": "TBL_CUST"},
            columns=[self._columns()[1]],
            enum_values={
                "CUST_STS": [
                    {"value": "A"},
                    {"value": 'DROP TABLE "x";--'},
                    {"value": "I"},
                ]
            },
        )
        values = result.payload["columns"][0].get("sample_values", [])
        assert values == ["A", "I"]

    def test_includes_lexicon_and_approved_knowledge(self) -> None:
        result = sanitize_llm_context(
            table={"schema_name": "erp", "table_name": "TBL_CUST"},
            columns=[self._columns()[1]],
            lexicon=[{"token": "CLI", "meaning": "Cliente", "role": "IDENTIFIER"}],
            approved_entities=[{"name": "Customer", "display_name": "Cliente"}],
            approved_fields=[{"name": "CustomerCode", "role": "IDENTIFIER"}],
        )
        assert result.payload["organization_lexicon"][0]["token"] == "CLI"
        assert result.payload["existing_approved_knowledge"]
        assert result.meta["lexicon_terms"] == 1

    def test_digest_is_stable_and_sensitive_to_changes(self) -> None:
        table = {"schema_name": "erp", "table_name": "TBL_CUST", "table_comment": "Clientes"}
        first = sanitize_llm_context(table=table, columns=self._columns())
        second = sanitize_llm_context(table=table, columns=self._columns())
        assert first.digest == second.digest
        changed = sanitize_llm_context(
            table={**table, "table_comment": "Clientes históricos"},
            columns=self._columns(),
        )
        assert changed.digest != first.digest


# ---------------------------------------------------------------------------
# Parseo Pydantic (§4)
# ---------------------------------------------------------------------------


class TestParseLLMAnalysis:
    def test_valid_json(self) -> None:
        parsed = parse_llm_analysis(_analysis_json())
        assert parsed is not None
        assert parsed.entity is not None
        assert parsed.entity.business_name == "Cliente"
        assert len(parsed.fields) == 2
        assert parsed.business_rules[0].name == "Cliente activo"
        assert parsed.questions[0].impact == "high"

    def test_markdown_fenced_json(self) -> None:
        parsed = parse_llm_analysis(f"```json\n{_analysis_json()}\n```")
        assert parsed is not None
        assert parsed.entity is not None

    def test_invalid_json_returns_none(self) -> None:
        assert parse_llm_analysis("no soy json") is None
        assert parse_llm_analysis("") is None
        assert parse_llm_analysis("{incompleto") is None

    def test_wrong_types_rejected(self) -> None:
        assert parse_llm_analysis('{"entity": ["no", "objeto"]}') is None
        assert parse_llm_analysis('{"fields": "texto"}') is None

    def test_extra_keys_ignored_and_summary_truncated(self) -> None:
        payload = json.loads(_analysis_json())
        payload["chain_of_thought"] = "secreto interno"
        payload["entity"]["reasoning_summary"] = "x" * 5000
        parsed = parse_llm_analysis(json.dumps(payload))
        assert parsed is not None
        assert not hasattr(parsed, "chain_of_thought")
        assert len(parsed.entity.reasoning_summary) == 800


# ---------------------------------------------------------------------------
# Analyzer: cache, fallback, usage (§26, §37)
# ---------------------------------------------------------------------------


class TestLLMAnalyzer:
    @pytest.mark.asyncio
    async def test_cache_prevents_second_llm_call(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("llm-cache")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id = await _seed_catalog(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            provider = _FakeLLM(_analysis_json())
            analyzer = LLMAnalyzer(
                repository=repo, catalog_store=store, llm_provider=provider
            )
            index = await analyzer.build_source_index(org, source_id)
            table = next(t for t in index.tables if t["table_name"] == "TBL_CUST")
            context = await analyzer.build_table_context(
                org, source_id=source_id, table=table, index=index
            )
            first = await analyzer.analyze_table(
                org, source_id=source_id, context=context, model="fake-model"
            )
            second = await analyzer.analyze_table(
                org, source_id=source_id, context=context, model="fake-model"
            )
            assert first["status"] == "completed"
            assert second["status"] == "cached"
            assert len(provider.calls) == 1
            assert second["tokens_input"] == 0
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_provider_timeout_falls_back_and_persists_failed(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("llm-timeout")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id = await _seed_catalog(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            analyzer = LLMAnalyzer(
                repository=repo,
                catalog_store=store,
                llm_provider=_FakeLLM(_analysis_json(), fail=True),
            )
            index = await analyzer.build_source_index(org, source_id)
            table = next(t for t in index.tables if t["table_name"] == "TBL_CUST")
            context = await analyzer.build_table_context(
                org, source_id=source_id, table=table, index=index
            )
            result = await analyzer.analyze_table(
                org, source_id=source_id, context=context, model="fake-model"
            )
            assert result["status"] == "failed"
            assert result["analysis"] is None
            analyses = await repo.list_llm_analyses(org, source_id=source_id)
            assert any(a["status"] == "failed" for a in analyses)
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_invalid_json_persisted_as_failed(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("llm-invalid")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id = await _seed_catalog(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            analyzer = LLMAnalyzer(
                repository=repo,
                catalog_store=store,
                llm_provider=_FakeLLM("esto no es json"),
            )
            index = await analyzer.build_source_index(org, source_id)
            table = next(t for t in index.tables if t["table_name"] == "TBL_CUST")
            context = await analyzer.build_table_context(
                org, source_id=source_id, table=table, index=index
            )
            result = await analyzer.analyze_table(
                org, source_id=source_id, context=context, model="fake-model"
            )
            assert result["status"] == "failed"
            assert result["error"] == "invalid_json_schema"
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_usage_event_recorded(self, monkeypatch) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("llm-usage")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id = await _seed_catalog(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            analyzer = LLMAnalyzer(
                repository=repo,
                catalog_store=store,
                llm_provider=_FakeLLM(_analysis_json()),
            )
            index = await analyzer.build_source_index(org, source_id)
            table = next(t for t in index.tables if t["table_name"] == "TBL_CUST")
            context = await analyzer.build_table_context(
                org, source_id=source_id, table=table, index=index
            )
            result = await analyzer.analyze_table(
                org, source_id=source_id, context=context, model="fake-model"
            )
            assert result["status"] == "completed"
            session = await get_async_session()
            try:
                row = (
                    await session.execute(
                        text(
                            "SELECT prompt_tokens, completion_tokens, model, status "
                            "FROM usage_events WHERE organization_id = :oid "
                            "AND event_type = 'knowledge_llm_analysis'"
                        ),
                        {"oid": org},
                    )
                ).fetchone()
            finally:
                await session.close()
            assert row is not None
            assert int(row.prompt_tokens) == 120
            assert int(row.completion_tokens) == 80
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_quota_exceeded_skips_llm(self, monkeypatch) -> None:
        from src.platform.billing.quota_service import QuotaExceededError
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        async def _raise(*args, **kwargs):
            raise QuotaExceededError("monthly_tokens quota exceeded", quota_type="monthly_tokens")

        monkeypatch.setattr(
            "src.platform.billing.quota_service.check_preflight", _raise
        )
        org = await _create_org("llm-quota")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id = await _seed_catalog(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            provider = _FakeLLM(_analysis_json())
            analyzer = LLMAnalyzer(
                repository=repo, catalog_store=store, llm_provider=provider
            )
            index = await analyzer.build_source_index(org, source_id)
            table = next(t for t in index.tables if t["table_name"] == "TBL_CUST")
            context = await analyzer.build_table_context(
                org, source_id=source_id, table=table, index=index
            )
            result = await analyzer.analyze_table(
                org, source_id=source_id, context=context, model="fake-model"
            )
            assert result["status"] == "skipped"
            assert result["error"] == "quota_exceeded"
            assert provider.calls == []
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Orquestador con etapa LLM (§2, §26)
# ---------------------------------------------------------------------------


class TestOrchestratorLLMStage:
    @pytest.mark.asyncio
    async def test_llm_stage_enriches_catalog_and_run(self, monkeypatch) -> None:
        from src.core.config import get_settings
        from src.core.domain.knowledge_learning import KnowledgeEventType

        monkeypatch.setattr(
            get_settings(), "RAG_KNOWLEDGE_LLM_ANALYSIS_ENABLED", True
        )
        org = await _create_org("llm-run")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        provider = _FakeLLM(_analysis_json())
        engine = await _build_engine(store, llm=provider)
        try:
            _, source_id = await _seed_source(org)
            started = await engine.start_run(org, catalog_source_id=source_id)
            job = await engine.execute_job(UUID(started["job_id"]))
            assert job.status.value == "completed"

            run = await engine._repo.get_run(org, UUID(started["run"]["id"]))
            assert run is not None
            steps = {s["stage"]: s for s in await engine._repo.list_steps(
                org, UUID(started["run"]["id"])
            )}
            llm_step = steps["llm_reasoning"]
            assert llm_step["status"] == "completed"
            assert llm_step["metrics"]["completed"] >= 1
            assert llm_step["metrics"]["tokens_input"] >= 120
            assert run["metrics"]["llm"]["suggestions_created"] >= 1

            analyses = await engine._repo.list_llm_analyses(
                org, run_id=UUID(started["run"]["id"])
            )
            assert analyses
            assert all(a["status"] in ("completed", "cached") for a in analyses)
            assert all(a["context_digest"] for a in analyses)
            assert all(isinstance(a["context_meta"], dict) for a in analyses)
            assert any(
                a["context_meta"].get("columns_omitted_sensitive", 0) >= 1
                for a in analyses
            )

            events = await engine._repo.list_events(
                org, run_id=UUID(started["run"]["id"]), limit=1000
            )
            types = {e["event_type"] for e in events}
            assert KnowledgeEventType.LLM_ANALYSIS_STARTED.value in types
            assert KnowledgeEventType.LLM_ANALYSIS_COMPLETED.value in types

            # Enriquecimiento real del catálogo semántico (draft, nunca approved).
            entities = await store.list_entities(org)
            customer = next(e for e in entities if e["name"] == "Customer")
            fields = await store.list_fields(org, UUID(customer["id"]))
            enriched = [
                f for f in fields if (f.get("signal_scores") or {}).get("llm") is not None
            ]
            assert enriched
            assert all(f["status"] == "draft" for f in fields)

            suggestions = await store.list_suggestions(
                org, status="pending", limit=200
            )
            assert any(s["type"] == "business_rule" for s in suggestions)
            assert any(s["type"] == "metric_proposal" for s in suggestions)
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_break_run(self, monkeypatch) -> None:
        from src.core.config import get_settings

        monkeypatch.setattr(
            get_settings(), "RAG_KNOWLEDGE_LLM_ANALYSIS_ENABLED", True
        )
        org = await _create_org("llm-fail-run")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(
            store, llm=_FakeLLM(_analysis_json(), fail=True)
        )
        try:
            _, source_id = await _seed_source(org)
            started = await engine.start_run(org, catalog_source_id=source_id)
            job = await engine.execute_job(UUID(started["job_id"]))
            assert job.status.value == "completed"
            run = await engine._repo.get_run(org, UUID(started["run"]["id"]))
            assert run is not None
            assert run["status"] in ("completed", "awaiting_validation")
            steps = {s["stage"]: s for s in await engine._repo.list_steps(
                org, UUID(started["run"]["id"])
            )}
            assert steps["llm_reasoning"]["status"] == "completed"
            assert steps["llm_reasoning"]["metrics"]["failed"] >= 1
            assert steps["detecting_relationships"]["status"] == "completed"
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_flag_off_has_no_llm_stage(self, monkeypatch) -> None:
        org = await _create_org("llm-off")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await _patch_plugin(monkeypatch, _FakePlugin())
        await _patch_enqueue(monkeypatch)
        engine = await _build_engine(store, llm=_FakeLLM(_analysis_json()))
        try:
            _, source_id = await _seed_source(org)
            started = await engine.start_run(org, catalog_source_id=source_id)
            stages = [
                s["stage"]
                for s in await engine._repo.list_steps(org, UUID(started["run"]["id"]))
            ]
            assert "llm_reasoning" not in stages
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# API de transparencia
# ---------------------------------------------------------------------------


class TestLLMAnalysisApi:
    @pytest.mark.asyncio
    async def test_llm_analyses_endpoint_scoped_and_auditable(
        self, async_client, trial_auth
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = UUID(trial_auth["X-Organization-Id"])
        _, source_id = await _seed_source(org, "llm-api-src")
        repo = PostgresKnowledgeLearningRepository()
        await repo.ensure_tables()
        run = await repo.create_run(org, catalog_source_id=source_id)
        await repo.upsert_llm_analysis(
            org,
            source_id=source_id,
            run_id=UUID(run["id"]),
            table_id=None,
            schema_fingerprint="f" * 64,
            prompt_version=PROMPT_VERSION,
            model="fake-model",
            status="completed",
            context_digest="d" * 64,
            context_meta={"columns_included": 4, "columns_omitted_sensitive": 1},
            result={"entity": {"name": "Customer"}},
            reasoning_summary="La tabla representa clientes.",
            confidence=0.94,
            tokens_input=120,
            tokens_output=80,
            latency_ms=15.0,
            estimated_cost=0.0002,
        )
        try:
            resp = await async_client.get(
                f"/api/v1/knowledge/learning/runs/{run['id']}/llm-analyses",
                headers=trial_auth,
            )
            assert resp.status_code == 200, resp.text
            payload = resp.json()
            assert payload["count"] == 1
            item = payload["analyses"][0]
            assert item["context_digest"] == "d" * 64
            assert item["context_meta"]["columns_omitted_sensitive"] == 1
            assert item["result"]["entity"]["name"] == "Customer"

            without_result = await async_client.get(
                f"/api/v1/knowledge/learning/runs/{run['id']}/llm-analyses",
                params={"include_result": "false"},
                headers=trial_auth,
            )
            assert without_result.status_code == 200
            assert "result" not in without_result.json()["analyses"][0]

            audit = await repo.list_llm_analyses(org, run_id=UUID(run["id"]))
            assert audit[0]["prompt_version"] == PROMPT_VERSION
        finally:
            await _cleanup_org(org)
