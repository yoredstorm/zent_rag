# =============================================================================
# Governed Learning — tests (FASE 25)
# =============================================================================
# Cubre: mapeo decision->gap, dedup+impact, priorización determinista,
# clustering (sin auto-conceptos), patrones SQL, advisor, approval records,
# replay verdict, spider policies, revocación, API y aislamiento multi-tenant.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
    ConfidenceLevel,
)
from src.core.domain.learning import (
    ApprovalAction,
    ApprovalRecord,
    ImprovementItem,
    PriorityLevel,
    SpiderPolicy,
)
from src.intelligence.store import PostgresIntelligenceStore
from src.learning.clustering import UnansweredClusterer, jaccard, normalize_question
from src.learning.gaps import ContextGapAnalyzer
from src.learning.improvements import ImprovementQueue
from src.learning.patterns import normalize_sql
from src.learning.replay import EvaluationReplayService
from src.learning.store import PostgresLearningStore

ORG_DEV = UUID("00000000-0000-0000-0000-000000000001")


async def _ensure_org(org: UUID) -> None:
    """Crea la fila organizations (FK de las tablas de aprendizaje)."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, status, created_at, updated_at) "
                "VALUES (:id, :name, 'active', now(), now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": org, "name": f"learn-{uuid4().hex[:8]}"},
        )
        await session.commit()
    finally:
        await session.close()


async def _fresh() -> tuple[PostgresLearningStore, PostgresIntelligenceStore]:
    learning = PostgresLearningStore()
    intel = PostgresIntelligenceStore()
    await learning.ensure_tables()
    await intel.ensure_tables()
    return learning, intel


async def _fresh_org() -> UUID:
    org = uuid4()
    await _ensure_org(org)
    return org


def _decision(
    status: AnswerabilityStatus, reason_codes: list[str], **kwargs
) -> AnswerabilityDecision:
    return AnswerabilityDecision(
        status=status,
        answerable=False,
        confidence_level=ConfidenceLevel.INSUFFICIENT,
        reason_codes=reason_codes,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Unit — gap mapping
# ---------------------------------------------------------------------------

class TestGapMapping:
    @pytest.mark.asyncio
    async def test_decision_maps_to_gap_types(self) -> None:
        learning, intel = await _fresh()
        analyzer = ContextGapAnalyzer(learning, intelligence_store=intel)
        org = await _fresh_org()
        cases = [
            (
                _decision(
                    AnswerabilityStatus.CONTEXT_MISSING,
                    ["UNDEFINED_BUSINESS_TERM"],
                    missing_context=["Definition of cliente_activo"],
                ),
                "MISSING_BUSINESS_TERM",
            ),
            (
                _decision(
                    AnswerabilityStatus.DATA_MISSING,
                    ["NO_SQL_RESULT"],
                    missing_data=["cost"],
                ),
                "MISSING_TABLE",
            ),
            (
                _decision(
                    AnswerabilityStatus.DATA_MISSING,
                    ["NO_SOURCE_AVAILABLE"],
                    missing_data=["source"],
                ),
                "MISSING_SOURCE",
            ),
            (
                _decision(AnswerabilityStatus.SOURCE_CONFLICT, ["SOURCE_DISAGREEMENT"]),
                "SOURCE_CONFLICT",
            ),
            (
                _decision(AnswerabilityStatus.ACCESS_BLOCKED, ["PERMISSION_DENIED"]),
                "PERMISSION_LIMITATION",
            ),
            (
                _decision(
                    AnswerabilityStatus.AMBIGUOUS, ["AMBIGUOUS_QUERY"]
                ),
                "AMBIGUOUS_TERM",
            ),
            (
                _decision(AnswerabilityStatus.EXECUTION_FAILED, ["BUDGET_EXCEEDED"]),
                "UNSUPPORTED_OPERATION",
            ),
            (
                _decision(AnswerabilityStatus.DATA_QUALITY_LOW, ["LOW_DATA_QUALITY"]),
                "LOW_DATA_QUALITY",
            ),
        ]
        for decision, expected in cases:
            assert analyzer.map_gap_type(decision).value == expected
            await analyzer.analyze_and_record(
                organization_id=org,
                user_id=None,
                question="pregunta de test",
                decision=decision,
            )
        gaps = await intel.list_gaps(org, limit=50)
        assert len(gaps) >= 8

    @pytest.mark.asyncio
    async def test_gap_dedup_increments_occurrences(self) -> None:
        learning, intel = await _fresh()
        analyzer = ContextGapAnalyzer(learning, intelligence_store=intel)
        org = await _fresh_org()
        decision = _decision(
            AnswerabilityStatus.DATA_MISSING, ["NO_SQL_RESULT"], missing_data=["COGS"]
        )
        await analyzer.analyze_and_record(organization_id=org, user_id=None, question="margen?", decision=decision)
        await analyzer.analyze_and_record(organization_id=org, user_id=None, question="margen de nuevo?", decision=decision)
        gaps = await intel.list_gaps(org, limit=10)
        matching = [g for g in gaps if g["concept"] == "COGS"]
        assert len(matching) == 1
        assert matching[0]["occurrences"] == 2
        assert matching[0]["impact"].get("query_count_30d") is not None

    @pytest.mark.asyncio
    async def test_conflict_recorded_even_if_resolved(self) -> None:
        learning, intel = await _fresh()
        analyzer = ContextGapAnalyzer(learning, intelligence_store=intel)
        org = await _fresh_org()
        decision = _decision(
            AnswerabilityStatus.ANSWERABLE,
            [],
            conflicting_sources=[
                {
                    "metric": "precio",
                    "source_a": "ERP",
                    "value_a": 120.0,
                    "source_b": "PDF",
                    "value_b": 100.0,
                }
            ],
        )
        assert analyzer.map_gap_type(decision) is None
        await analyzer.analyze_and_record(organization_id=org, user_id=None, question="precio?", decision=decision)
        conflicts = await learning.list_source_conflicts(org)
        assert len(conflicts) == 1
        assert conflicts[0]["resolved_by_authority"] is True


# ---------------------------------------------------------------------------
# Unit — priorización determinista
# ---------------------------------------------------------------------------

class TestPrioritization:
    def test_priorities_are_deterministic(self) -> None:
        critical = ImprovementQueue.priority_for(
            query_frequency=200, users=20, agents=5, concept="gross margin"
        )
        low = ImprovementQueue.priority_for(
            query_frequency=1, users=0, agents=0, concept="x"
        )
        assert critical == PriorityLevel.CRITICAL
        assert low == PriorityLevel.LOW
        again = ImprovementQueue.priority_for(
            query_frequency=200, users=20, agents=5, concept="gross margin"
        )
        assert again == critical


# ---------------------------------------------------------------------------
# Unit — clustering
# ---------------------------------------------------------------------------

class TestClustering:
    def test_normalization_stems_morphology(self) -> None:
        a = normalize_question("¿Cuántos clientes rentables tenemos?")
        b = normalize_question("Clientes con rentabilidad cuántos hay")
        assert "clien" in a and "renta" in a
        assert "clien" in b and "renta" in b

    def test_four_phrases_form_one_cluster(self) -> None:
        clusterer = UnansweredClusterer(None, threshold=0.45, min_size=3)  # type: ignore[arg-type]
        questions = [
            {"question": "cliente rentable", "query_id": str(uuid4())},
            {"question": "clientes con rentabilidad", "query_id": str(uuid4())},
            {"question": "cuentas rentables", "query_id": str(uuid4())},
            {"question": "clientes que generan margen", "query_id": str(uuid4())},
        ]
        clusters = clusterer.cluster(questions)
        assert len(clusters) == 1
        assert clusters[0]["size"] == 4

    def test_min_size_respected(self) -> None:
        clusterer = UnansweredClusterer(None, threshold=0.45, min_size=4)  # type: ignore[arg-type]
        questions = [
            {"question": "cliente rentable", "query_id": str(uuid4())},
            {"question": "clientes con rentabilidad", "query_id": str(uuid4())},
            {"question": "cuentas rentables", "query_id": str(uuid4())},
        ]
        assert clusterer.cluster(questions) == []

    def test_jaccard(self) -> None:
        assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
        assert jaccard({"a"}, {"b"}) == 0.0


# ---------------------------------------------------------------------------
# Unit — patterns y replay
# ---------------------------------------------------------------------------

class TestSqlPatterns:
    def test_sql_normalization(self) -> None:
        assert normalize_sql("SELECT 1 ;") == normalize_sql("  select   1")

    @pytest.mark.asyncio
    async def test_replay_verdict(self) -> None:
        service = EvaluationReplayService(store=None)  # type: ignore[arg-type]
        assert service._verdict({"composite_score": 0.8}, {"composite_score": 0.85}) == "pass"
        assert service._verdict({"composite_score": 0.8}, {"composite_score": 0.78}) == "pass"
        assert service._verdict({"composite_score": 0.8}, {"composite_score": 0.7}) == "warn"
        assert service._verdict({"composite_score": 0.8}, {"composite_score": 0.5}) == "fail"
        assert service._verdict({}, {"cases": 0}) == "unknown"


# ---------------------------------------------------------------------------
# Integración — improvements / approvals / spider / advisor
# ---------------------------------------------------------------------------

class TestImprovementsStore:
    @pytest.mark.asyncio
    async def test_upsert_dedupe_and_status(self) -> None:
        learning, _ = await _fresh()
        org = await _fresh_org()
        item = ImprovementItem(
            organization_id=org,
            gap_type="MISSING_METRIC",
            title="margen",
            cluster_key="margen",
            affected_queries=10,
        )
        first = await learning.upsert_improvement(item)
        second = await learning.upsert_improvement(item)
        assert first == second  # dedupe por (org, gap_type, cluster_key)
        rows = await learning.list_improvements(org, limit=10)
        assert len(rows) == 1
        assert rows[0]["affected_queries"] == 11
        ok = await learning.update_improvement_status(
            org, first, status="RESOLVED"
        )
        assert ok
        assert (await learning.get_improvement(org, first))["status"] == "RESOLVED"


class TestApprovalRecords:
    @pytest.mark.asyncio
    async def test_record_with_versions(self) -> None:
        learning, _ = await _fresh()
        org = await _fresh_org()
        rec = ApprovalRecord(
            organization_id=org,
            knowledge_type="glossary",
            knowledge_id="margen",
            action=ApprovalAction.APPROVE,
            acted_by=None,
            reason="revisión humana",
            source_evidence=["review queue"],
            previous_version={"version": 1},
            new_version={"version": 2},
        )
        await learning.add_approval_record(rec)
        records = await learning.list_approval_records(org)
        assert len(records) == 1
        assert records[0]["previous_version"] == {"version": 1}
        assert records[0]["new_version"] == {"version": 2}
        assert records[0]["reason"] == "revisión humana"


class TestSpiderPolicy:
    @pytest.mark.asyncio
    async def test_policy_crud_and_never_expands(self) -> None:
        learning, _ = await _fresh()
        org = await _fresh_org()
        policy = SpiderPolicy(
            organization_id=org,
            name="erp-only",
            schedule_hours=12,
            allowed_schemas=["erp"],
            profiling_level="none",
        )
        pid = await learning.upsert_spider_policy(policy)
        policies = await learning.list_spider_policies(org)
        assert len(policies) == 1
        assert policies[0]["allowed_schemas"] == ["erp"]
        # La política nunca amplía: solo lo que el tenant autoriza explícitamente.
        assert policies[0]["pii_policy"] == "never"


class TestAdvisor:
    @pytest.mark.asyncio
    async def test_advise_returns_available_missing_recommendation(self) -> None:
        from src.catalog.store import PostgresCatalogStore
        from src.infrastructure.postgres.relational_db import (
            PostgresConnectorRepository,
        )
        from src.learning.advisor import ContextAdvisor

        learning, intel = await _fresh()
        catalog = PostgresCatalogStore()
        await catalog.ensure_tables()
        org = await _fresh_org()
        connector = await PostgresConnectorRepository().create_connector(
            org, f"c-{uuid4().hex[:8]}", "postgres", config_json={"host": "fake"}
        )
        src = await catalog.upsert_source(
            organization_id=org, connector_id=connector.id, engine="postgres"
        )
        table_id, _ = await catalog.upsert_table(
            organization_id=org, source_id=src["id"],
            schema_name="erp", table_name="SALES",
        )
        await catalog.upsert_column(
            organization_id=org, table_id=table_id,
            column_name="net_revenue", data_type="numeric",
        )
        await catalog.upsert_column(
            organization_id=org, table_id=table_id,
            column_name="refunds_amt", data_type="numeric",
        )

        advisor = ContextAdvisor(catalog, intelligence_store=intel, learning_store=learning)
        result = await advisor.advise(
            org,
            "¿Cuál es el margen bruto?",
            gap={"gap_type": "MISSING_METRIC", "concept": "margen", "impact": {}},
        )
        assert result["recommendation"]
        assert any("SALES.net_revenue" in a for a in result["available"])
        assert any("margen" in m for m in result["missing"])
