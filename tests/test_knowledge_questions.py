# =============================================================================
# AI Questions & Human Validation — tests (FASE 33D)
# =============================================================================
# Cubre: prioridad explicable, detección de ambigüedad real (enums, variantes,
# impuestos, conflicto), dedupe, respuesta que propaga conocimiento (enums,
# léxico, campos), skip/defer, run awaiting_validation, gate y API con RBAC.
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
from src.core.domain.knowledge_learning import (
    QuestionPriority,
    compute_question_priority,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_learning.validation_engine import (
    QuestionAlreadyResolvedError,
)


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
                        name="CUST_ID", data_type="uuid", nullable=False,
                        is_primary_key=True,
                    ),
                    ColumnProfile(
                        name="CUST_NAM", data_type="character varying",
                        nullable=True, column_comment="Nombre",
                    ),
                    ColumnProfile(
                        name="CUST_STS", data_type="character varying",
                        nullable=True, cardinality=2,
                        distinct_values=["A", "I"],
                    ),
                ],
            ),
            DeepTableProfile(
                table_name="TBL_CUST_HIST",
                schema="erp",
                row_count_approx=8000,
                columns=[
                    ColumnProfile(name="CUST_ID", data_type="uuid", nullable=False),
                    ColumnProfile(
                        name="CUST_STS", data_type="character varying",
                        nullable=True, cardinality=2,
                        distinct_values=["A", "I"],
                    ),
                ],
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
                    ColumnProfile(name="TOTAL_AMT", data_type="numeric", nullable=True),
                    ColumnProfile(name="TAX_AMT", data_type="numeric", nullable=True),
                ],
                foreign_keys=[
                    Relationship(
                        from_column="CUST_ID", to_table="TBL_CUST", to_column="CUST_ID"
                    ),
                ],
            ),
            DeepTableProfile(
                table_name="TBL_LOG_X",
                schema="erp",
                columns=[ColumnProfile(name="id", data_type="uuid")],
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


async def _patch_plugin(monkeypatch, plugin: _FakePlugin) -> None:
    monkeypatch.setattr(
        "src.catalog.jobs.get_plugin",
        lambda connector_type, config, secrets: plugin,
    )


async def _patch_enqueue(monkeypatch) -> None:
    async def _noop(job_id: str) -> None:
        return None

    monkeypatch.setattr("src.knowledge.queue.enqueue_knowledge_job", _noop)


async def _create_org(prefix: str = "q") -> UUID:
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


async def _seed_source(org: UUID, name: str = "q-postgres") -> UUID:
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


async def _build_engine(
    store: PostgresCatalogStore, *, llm=None, score_service=None
):
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
    """Ejecuta un run completo (33A+33D) y retorna (source_id, run)."""
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


async def _build_validation_engine(store: PostgresCatalogStore):
    from src.intelligence.store import PostgresIntelligenceStore
    from src.platform.knowledge_learning.knowledge_score import (
        KnowledgeScoreService,
    )
    from src.platform.knowledge_learning.repository import (
        PostgresKnowledgeLearningRepository,
    )
    from src.platform.knowledge_learning.validation_engine import (
        KnowledgeValidationEngine,
    )

    repo = PostgresKnowledgeLearningRepository()
    score = KnowledgeScoreService(store, repository=repo)
    return KnowledgeValidationEngine(
        store,
        repo,
        score_service=score,
        intelligence_store=PostgresIntelligenceStore(),
    )


# ---------------------------------------------------------------------------
# Prioridad (sección 8)
# ---------------------------------------------------------------------------


class TestQuestionPriority:
    def test_critical_for_high_ambiguity_and_impact(self) -> None:
        priority, score = compute_question_priority(
            ambiguity=1.0,
            business_impact=1.0,
            retrieval_impact=1.0,
            frequency=1.0,
            confidence=0.0,
            dependents=1.0,
        )
        assert priority == QuestionPriority.CRITICAL
        assert score == 1.0

    def test_low_for_minimal_signals(self) -> None:
        priority, score = compute_question_priority(
            ambiguity=0.1,
            business_impact=0.1,
            retrieval_impact=0.1,
            frequency=0.1,
            confidence=0.9,
            dependents=0.0,
        )
        assert priority == QuestionPriority.LOW
        assert score < 0.2

    def test_monotonic_in_ambiguity(self) -> None:
        low, low_score = compute_question_priority(
            ambiguity=0.2,
            business_impact=0.5,
            retrieval_impact=0.5,
            frequency=0.5,
            confidence=0.5,
            dependents=0.0,
        )
        high, high_score = compute_question_priority(
            ambiguity=0.9,
            business_impact=0.5,
            retrieval_impact=0.5,
            frequency=0.5,
            confidence=0.5,
            dependents=0.0,
        )
        assert high_score > low_score


# ---------------------------------------------------------------------------
# Generador
# ---------------------------------------------------------------------------


class TestQuestionGenerator:
    @pytest.mark.asyncio
    async def test_generates_enum_variant_and_tax_questions(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.question_generator import (
            QuestionGenerator,
        )
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("q-gen")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            generator = QuestionGenerator(store, repo)
            result = await generator.generate(
                org, source_id=source_id, run_id=UUID(run["id"])
            )
            types = {q["question_type"] for q in result["questions"]}
            assert "enum_meaning" in types
            assert "table_variant" in types
            assert "tax_inclusion" in types
            enum_q = next(
                q for q in result["questions"] if q["question_type"] == "enum_meaning"
            )
            assert enum_q["evidence"]
            assert enum_q["options"]
            assert enum_q["priority"] in {p.value for p in QuestionPriority}
            assert enum_q["priority_score"] > 0

            # Dedupe: segunda pasada actualiza, no duplica.
            again = await generator.generate(
                org, source_id=source_id, run_id=UUID(run["id"])
            )
            all_questions = await repo.list_questions(org, limit=200)
            assert len(all_questions) == len(result["questions"])
            assert again["generated"] == 0
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_field_conflict_generates_ambiguity_question(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.question_generator import (
            QuestionGenerator,
        )
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("q-conflict")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            entities = await store.list_entities(org)
            hist = next(e for e in entities if e["name"] == "CustomerHist")
            fields = await store.list_fields(org, UUID(hist["id"]))
            target = next(f for f in fields if f["mapped_column_id"])
            await store.update_field_semantics(
                org,
                UUID(target["id"]),
                signal_scores={"llm": 0.9, "llm_role_conflict": "MEASURE"},
            )
            generator = QuestionGenerator(
                store, PostgresKnowledgeLearningRepository()
            )
            result = await generator.generate(org, source_id=source_id)
            conflict = next(
                (
                    q
                    for q in result["questions"]
                    if q["question_type"] == "field_ambiguity"
                    and q["field_id"] == target["id"]
                ),
                None,
            )
            assert conflict is not None
            assert any("LLM" in e for e in conflict["evidence"])
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Validación: respuestas -> conocimiento
# ---------------------------------------------------------------------------


class TestValidationEngine:
    @pytest.mark.asyncio
    async def test_enum_answer_updates_catalog_and_lexicon(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("q-answer")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            questions = await repo.list_questions(
                org, source_id=source_id, status="pending", limit=200
            )
            enum_question = next(
                q for q in questions if q["question_type"] == "enum_meaning"
            )
            engine = await _build_validation_engine(store)
            result = await engine.answer(
                org,
                UUID(enum_question["id"]),
                answer_text="A es Activo e I es Inactivo",
                structured_answer={
                    "mapping": {"A": "Activo", "I": "Inactivo"},
                    "lexicon": {"CLI_COD": "Customer Code"},
                },
            )
            assert result is not None
            applied_kinds = {entry["kind"] for entry in result["applied_to"]}
            assert "enum_meaning" in applied_kinds
            assert "lexicon" in applied_kinds
            assert result["feedback"]["applied"] is True

            updated = await repo.get_question(org, UUID(enum_question["id"]))
            assert updated is not None and updated["status"] == "answered"
            assert updated["structured_answer"]["mapping"]["A"] == "Activo"

            column = await store.get_column(org, UUID(enum_question["column_id"]))
            values = await store.list_enum_values(org, UUID(enum_question["column_id"]))
            meanings = {
                v["value"]: v["documented_meaning"]
                for v in values
                if v.get("documented_meaning")
            }
            assert meanings.get("A") == "Activo"
            assert column is not None

            # Memoria de léxico aprobada (aprendizaje continuo por tenant).
            lexicon = await store.list_lexicon(org)
            cli = next(e for e in lexicon if e["token"] == "CLI_COD")
            assert cli["meaning"] == "Customer Code"
            assert cli["status"] == "approved"

            feedback = await repo.list_feedback(org, limit=20)
            assert feedback and feedback[0]["applied"] is True
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_tax_answer_creates_approved_business_rule(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("q-tax")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            questions = await repo.list_questions(
                org, source_id=source_id, status="pending", limit=200
            )
            tax_question = next(
                q for q in questions if q["question_type"] == "tax_inclusion"
            )
            engine = await _build_validation_engine(store)
            result = await engine.answer(
                org,
                UUID(tax_question["id"]),
                answer_text="TOTAL_AMT sí incluye impuestos",
                structured_answer={"includes_tax": True},
            )
            assert result is not None
            rules = await repo.list_business_rules(org)
            rule = next(r for r in rules if r["provenance"] == "APPROVED")
            assert "TOTAL_AMT" in rule["name"]
            assert rule["source"] == "human_question"
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_skip_and_defer_do_not_apply_knowledge(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("q-skip")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            repo = PostgresKnowledgeLearningRepository()
            questions = await repo.list_questions(
                org, source_id=source_id, status="pending", limit=200
            )
            assert len(questions) >= 2
            engine = await _build_validation_engine(store)
            skipped = await engine.skip(
                org, UUID(questions[0]["id"]), reason="no aplica"
            )
            deferred = await engine.defer(org, UUID(questions[1]["id"]))
            assert skipped is not None
            assert skipped["question"]["status"] == "skipped"
            assert deferred is not None
            assert deferred["question"]["status"] == "deferred"
            feedback = await repo.list_feedback(org, limit=20)
            assert all(f["applied"] is False for f in feedback)

            with pytest.raises(QuestionAlreadyResolvedError):
                await engine.answer(
                    org,
                    UUID(questions[0]["id"]),
                    answer_text="tarde",
                    structured_answer={},
                )
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Run awaiting_validation -> completed tras responder
# ---------------------------------------------------------------------------


class TestAwaitingValidationLifecycle:
    @pytest.mark.asyncio
    async def test_run_waits_then_completes_after_answers(
        self, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("q-run")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, run = await _seed_run(org, store, monkeypatch)
            assert run["status"] == "awaiting_validation"
            repo = PostgresKnowledgeLearningRepository()
            blocking = await repo.count_pending_questions(
                org, run_id=UUID(run["id"]), priorities=["critical", "high"]
            )
            assert blocking >= 1

            engine = await _build_validation_engine(store)
            while True:
                pending = await repo.list_questions(
                    org,
                    run_id=UUID(run["id"]),
                    status="pending",
                    limit=200,
                )
                blocking_questions = [
                    q for q in pending if q["priority"] in ("critical", "high")
                ]
                if not blocking_questions:
                    break
                question = blocking_questions[0]
                structured = _answer_for(question)
                await engine.answer(
                    org,
                    UUID(question["id"]),
                    answer_text=f"respuesta para {question['question_type']}",
                    structured_answer=structured,
                )
            final_run = await repo.get_run(org, UUID(run["id"]))
            assert final_run is not None
            assert final_run["status"] == "completed"
            assert final_run["finished_at"] is not None
            events = await repo.list_events(org, run_id=UUID(run["id"]), limit=1000)
            assert any(e["event_type"] == "knowledge.confirmed" for e in events)
        finally:
            await _cleanup_org(org)


def _answer_for(question: dict) -> dict:
    qtype = question.get("question_type")
    if qtype == "enum_meaning":
        values = (question.get("answer_schema") or {}).get("values") or []
        return {"mapping": {str(v): f"Significado {v}" for v in values}}
    if qtype == "tax_inclusion":
        return {"includes_tax": True}
    if qtype == "table_variant":
        return {"is_history": False}
    if qtype == "field_ambiguity":
        return {"role": "STATUS"}
    return {"concept": question.get("title", "concepto"), "definition": "definido"}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class TestQuestionsApi:
    @pytest.mark.asyncio
    async def test_questions_flow_and_isolation(
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
        source_id = await _seed_source(org, "q-api")
        started = await engine.start_run(org, catalog_source_id=source_id)
        await engine.execute_job(UUID(started["job_id"]))

        listing = await async_client.get(
            "/api/v1/knowledge/learning/questions", headers=trial_auth
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["count"] >= 1
        assert body["blocking"] >= 1
        question = body["questions"][0]

        answer = await async_client.post(
            f"/api/v1/knowledge/learning/questions/{question['id']}/answer",
            json={
                "answer": "A es Activo",
                "structured_answer": {"mapping": {"A": "Activo", "I": "Inactivo"}},
            },
            headers=trial_auth,
        )
        assert answer.status_code == 200, answer.text
        assert answer.json()["question"]["status"] == "answered"

        second = body["questions"][1] if body["count"] > 1 else None
        if second is not None and second["id"] != question["id"]:
            skip = await async_client.post(
                f"/api/v1/knowledge/learning/questions/{second['id']}/skip",
                json={"reason": "no aplica"},
                headers=trial_auth,
            )
            assert skip.status_code == 200
            assert skip.json()["question"]["status"] == "skipped"

        feedback = await async_client.get(
            "/api/v1/knowledge/learning/feedback", headers=trial_auth
        )
        assert feedback.status_code == 200
        assert feedback.json()["count"] >= 1

        # Otro tenant no ve la pregunta.
        other = await async_client.post(
            "/api/v1/billing/subscription/create-trial",
            json={
                "company_name": f"Q Co {uuid4().hex[:8]}",
                "email": f"q-{uuid4().hex[:8]}@example.com",
            },
        )
        assert other.status_code == 200, other.text
        other_headers = {
            "Authorization": f"Bearer {other.json()['api_token']}",
            "X-Organization-Id": other.json()["organization_id"],
        }
        cross = await async_client.get(
            f"/api/v1/knowledge/learning/questions/{question['id']}",
            headers=other_headers,
        )
        assert cross.status_code == 404

        unauthenticated = await async_client.get(
            "/api/v1/knowledge/learning/questions"
        )
        assert unauthenticated.status_code in (401, 403)
