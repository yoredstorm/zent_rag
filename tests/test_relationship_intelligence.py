# =============================================================================
# Relationship Intelligence & Knowledge Graph — tests (FASE 33C)
# =============================================================================
# Cubre: señales/score/cardinalidad, provenance OBSERVED/INFERRED y no
# auto-aprobación, merge de hipótesis LLM, Review Queue (relationship +
# business_rule), grafo con evidencia, "What Zent Learned" y gaps reales.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
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
from src.core.domain.catalog import (
    CatalogSuggestion,
    RelationshipProvenance,
    SuggestionType,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_learning.relationship_analyzer import (
    RelationshipAnalyzer,
    _estimate_cardinality,
    _resolve_provenance,
    _resolve_score,
    evaluate_relationship_signals,
)


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
                        distinct_values=["A", "I"],
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


async def _create_org(prefix: str = "rel") -> UUID:
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


async def _seed_source(org: UUID, name: str = "rel-postgres") -> UUID:
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


async def _seed_learning(org: UUID, store: PostgresCatalogStore, monkeypatch) -> UUID:
    """Corre un run 33A (sin LLM) para poblar catálogo y relaciones."""
    from src.infrastructure.postgres.knowledge_repos import (
        PostgresIngestionJobRepository,
    )
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.intelligence.store import PostgresIntelligenceStore
    from src.platform.knowledge_learning.orchestrator import KnowledgeLearningEngine
    from src.platform.knowledge_learning.repository import (
        PostgresKnowledgeLearningRepository,
    )

    await _patch_plugin(monkeypatch, _FakePlugin())
    await _patch_enqueue(monkeypatch)
    engine = KnowledgeLearningEngine(
        job_repo=PostgresIngestionJobRepository(),
        connector_repo=PostgresConnectorRepository(),
        catalog_store=store,
        intelligence_store=PostgresIntelligenceStore(),
        secret_store=None,
        llm_provider=None,
        repository=PostgresKnowledgeLearningRepository(),
    )
    source_id = await _seed_source(org)
    started = await engine.start_run(org, catalog_source_id=source_id)
    await engine.execute_job(UUID(started["job_id"]))
    return source_id


async def _cleanup_org(org: UUID) -> None:
    session = await get_async_session()
    try:
        for table in (
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
# Señales puras
# ---------------------------------------------------------------------------


class TestRelationshipSignals:
    def _column(self, name: str, **overrides) -> dict:
        base = {
            "column_name": name,
            "data_type": "uuid",
            "is_primary_key": False,
            "nullable": True,
        }
        base.update(overrides)
        return base

    def test_full_signal_stack_scores_high_and_explains(self) -> None:
        result = evaluate_relationship_signals(
            from_column=self._column("CUST_ID"),
            to_column=self._column("CUST_ID", is_primary_key=True),
            from_table_name="TBL_ORD",
            to_table_name="TBL_CUST",
            declared_fk=True,
            approved_convention=True,
            llm_confidence=0.93,
        )
        assert result.score >= 0.9
        signals = {d["signal"] for d in result.evidence_detail}
        assert {
            "fk_declared",
            "types_compatible",
            "target_key",
            "naming_similarity",
            "llm_agreement",
        }.issubset(signals)
        assert any("FK física" in e for e in result.evidence)
        assert result.cardinality == "N:1"

    def test_low_signal_scores_low(self) -> None:
        result = evaluate_relationship_signals(
            from_column=self._column("X_COL", data_type="text"),
            to_column=self._column("Y_COL", data_type="numeric"),
            from_table_name="A",
            to_table_name="B",
            declared_fk=False,
            approved_convention=False,
            llm_confidence=None,
        )
        assert result.score < 0.4

    def test_cardinality_estimation(self) -> None:
        pk = self._column("ID", is_primary_key=True)
        fk = self._column("OTHER_ID")
        assert _estimate_cardinality(from_column=pk, to_column=pk) == "1:1"
        assert _estimate_cardinality(from_column=fk, to_column=pk) == "N:1"
        assert _estimate_cardinality(from_column=pk, to_column=fk) == "1:N"
        assert _estimate_cardinality(from_column=fk, to_column=fk) == "N:M"

    def test_provenance_never_promotes_inferred(self) -> None:
        assert (
            _resolve_provenance(existing="INFERRED", declared_fk=True) == "OBSERVED"
        )
        assert (
            _resolve_provenance(existing="APPROVED", declared_fk=False) == "APPROVED"
        )
        assert (
            _resolve_provenance(existing="REJECTED", declared_fk=True) == "REJECTED"
        )
        assert (
            _resolve_provenance(existing="INFERRED", declared_fk=False) == "INFERRED"
        )

    def test_score_floors_and_caps(self) -> None:
        observed = _resolve_score(provenance="OBSERVED", computed=0.61, existing=0.0)
        assert observed >= 0.95
        inferred = _resolve_score(provenance="INFERRED", computed=0.99, existing=0.0)
        assert inferred <= 0.92
        approved = _resolve_score(provenance="APPROVED", computed=0.5, existing=0.9)
        assert approved == 1.0


# ---------------------------------------------------------------------------
# Analyzer + persistencia
# ---------------------------------------------------------------------------


class TestRelationshipAnalyzerApply:
    @pytest.mark.asyncio
    async def test_apply_enriches_fk_and_adds_llm_hypothesis(
        self, monkeypatch
    ) -> None:
        org = await _create_org("rel-apply")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id = await _seed_learning(org, store, monkeypatch)
            tables = await store.list_tables(org, source_id)
            ord_table = next(t for t in tables if t["table_name"] == "TBL_ORD")
            llm_analyses = [
                {
                    "status": "completed",
                    "table_id": ord_table["id"],
                    "result": {
                        "relationships": [
                            {
                                "from_table": "erp.TBL_ORD",
                                "from_column": "CUST_ID",
                                "to_table": "erp.TBL_CUST",
                                "to_column": "CUST_ID",
                                "confidence": 0.93,
                                "business_verb": "places",
                                "evidence": ["fk declarada"],
                            },
                            {
                                "from_table": "erp.TBL_ORD",
                                "from_column": "ORD_ID",
                                "to_table": "erp.TBL_CUST",
                                "to_column": "CUST_ID",
                                "confidence": 0.8,
                                "business_verb": "belongs_to",
                                "evidence": ["hypothesis"],
                            },
                        ]
                    },
                }
            ]
            analyzer = RelationshipAnalyzer(store)
            metrics = await analyzer.apply(
                org, source_id, deep=_deep_fixture(), llm_analyses=llm_analyses
            )
            assert metrics["created"] >= 1
            assert metrics["enriched"] >= 1
            relationships = await store.list_relationships(org, source_id, limit=100)
            fk = next(r for r in relationships if r["relation_type"] == "foreign_key")
            assert fk["provenance"] == RelationshipProvenance.OBSERVED.value
            assert fk["confidence_score"] >= 0.95
            assert fk["cardinality"] == "N:1"
            assert fk["evidence_detail"]
            assert fk["status"] == "confirmed"

            llm_only = next(
                r
                for r in relationships
                if r["relation_type"] == "inferred"
                and r["from_column"] == "ORD_ID"
                and r["to_column"] == "CUST_ID"
            )
            assert llm_only["provenance"] == RelationshipProvenance.INFERRED.value
            assert llm_only["status"] == "suggested"
            assert 0.35 < llm_only["confidence_score"] <= 0.92
            assert any("LLM" in e for e in llm_only["evidence"])

            # Red de seguridad: nunca auto-aprobación.
            assert all(
                r["provenance"] != RelationshipProvenance.APPROVED.value
                for r in relationships
            )

            # Idempotencia: re-aplicar no duplica la hipótesis LLM.
            second = await analyzer.apply(
                org, source_id, deep=_deep_fixture(), llm_analyses=llm_analyses
            )
            assert second["created"] == 0
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Review Queue: aprobación/rechazo humano
# ---------------------------------------------------------------------------


class TestReviewQueueGovernance:
    @pytest.mark.asyncio
    async def test_relationship_approval_sets_approved_provenance(
        self, monkeypatch
    ) -> None:
        from src.catalog.suggestions import ReviewQueueService
        from src.core.domain.catalog import RelationshipStatus
        from src.intelligence.store import PostgresIntelligenceStore

        org = await _create_org("rel-rq")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id = await _seed_learning(org, store, monkeypatch)
            tables = await store.list_tables(org, source_id)
            cust = next(t for t in tables if t["table_name"] == "TBL_CUST")
            rel_id = await store.upsert_relationship(
                organization_id=org,
                source_id=source_id,
                from_table_id=UUID(cust["id"]),
                from_column="CUST_STS",
                to_table_id=UUID(cust["id"]),
                to_column="CUST_NAM",
                relation_type="inferred",
                confidence="medium",
                confidence_score=0.7,
                provenance="INFERRED",
                status=RelationshipStatus.SUGGESTED,
                evidence=["naming similarity"],
                evidence_detail=[
                    {"signal": "naming_similarity", "weight": 0.12, "detail": "demo"}
                ],
            )
            suggestion = CatalogSuggestion(
                organization_id=org,
                type=SuggestionType.RELATIONSHIP_CANDIDATE,
                title="Relación candidata demo",
                description="Revisar",
                evidence=["naming similarity"],
                confidence="medium",
                payload={"relationship_id": str(rel_id)},
                affected_sources=[str(source_id)],
            )
            await store.create_suggestion(suggestion)

            service = ReviewQueueService(
                store, intelligence_store=PostgresIntelligenceStore()
            )
            result = await service.approve(org, suggestion.id)
            assert result is not None and result["status"] == "approved"

            updated = await store.get_relationship(org, rel_id)
            assert updated is not None
            assert updated["provenance"] == RelationshipProvenance.APPROVED.value
            assert updated["status"] == "confirmed"
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_business_rule_approval_and_rejection_materialize(self) -> None:
        from src.catalog.suggestions import ReviewQueueService
        from src.intelligence.store import PostgresIntelligenceStore
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = await _create_org("rel-rules")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        repo = PostgresKnowledgeLearningRepository()
        await repo.ensure_tables()
        try:
            approved = CatalogSuggestion(
                organization_id=org,
                type=SuggestionType.BUSINESS_RULE,
                title="Cliente activo",
                description="Un cliente con estado A está activo.",
                evidence=["llm:kl-v1"],
                confidence="high",
                payload={
                    "rule": "Cliente activo",
                    "definition": "Un cliente con estado A está activo.",
                    "applies_to": ["CUST_STS"],
                    "source": "llm",
                },
            )
            rejected = CatalogSuggestion(
                organization_id=org,
                type=SuggestionType.BUSINESS_RULE,
                title="Regla dudosa",
                description="Interpretación dudosa.",
                evidence=["llm:kl-v1"],
                confidence="low",
                payload={
                    "rule": "Regla dudosa",
                    "definition": "Interpretación dudosa.",
                },
            )
            await store.create_suggestion(approved)
            await store.create_suggestion(rejected)
            service = ReviewQueueService(
                store, intelligence_store=PostgresIntelligenceStore()
            )
            await service.approve(org, approved.id)
            await service.reject(org, rejected.id)

            rules = await repo.list_business_rules(org)
            by_name = {r["name"]: r for r in rules}
            assert by_name["Cliente activo"]["provenance"] == "APPROVED"
            assert by_name["Cliente activo"]["applies_to"] == ["CUST_STS"]
            assert by_name["Regla dudosa"]["provenance"] == "REJECTED"
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# Knowledge Graph / What Zent Learned / Gaps
# ---------------------------------------------------------------------------


def _llm_analysis_for(ord_table_id: str) -> list[dict]:
    return [
        {
            "status": "completed",
            "table_id": ord_table_id,
            "result": {
                "relationships": [
                    {
                        "from_table": "erp.TBL_ORD",
                        "from_column": "CUST_ID",
                        "to_table": "erp.TBL_CUST",
                        "to_column": "CUST_ID",
                        "confidence": 0.95,
                        "business_verb": "places",
                        "evidence": ["fk declarada"],
                    },
                    {
                        "from_table": "erp.TBL_ORD",
                        "from_column": "ORD_ID",
                        "to_table": "erp.TBL_CUST",
                        "to_column": "CUST_ID",
                        "confidence": 0.9,
                        "business_verb": "belongs_to",
                        "evidence": ["hipótesis llm"],
                    },
                ]
            },
        }
    ]


async def _seed_graph(
    org: UUID, store: PostgresCatalogStore, monkeypatch
) -> tuple[UUID, Any]:
    from src.intelligence.store import PostgresIntelligenceStore
    from src.platform.knowledge_learning.knowledge_graph import KnowledgeGraphService
    from src.platform.knowledge_learning.repository import (
        PostgresKnowledgeLearningRepository,
    )

    source_id = await _seed_learning(org, store, monkeypatch)
    tables = await store.list_tables(org, source_id)
    ord_table = next(t for t in tables if t["table_name"] == "TBL_ORD")
    analyzer = RelationshipAnalyzer(store)
    await analyzer.apply(
        org,
        source_id,
        deep=_deep_fixture(),
        llm_analyses=_llm_analysis_for(ord_table["id"]),
    )
    repo = PostgresKnowledgeLearningRepository()
    service = KnowledgeGraphService(
        store,
        intelligence_store=PostgresIntelligenceStore(),
        repository=repo,
    )
    return source_id, service


class TestKnowledgeGraph:
    @pytest.mark.asyncio
    async def test_graph_nodes_edges_with_evidence_and_filters(
        self, monkeypatch
    ) -> None:
        org = await _create_org("rel-graph")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, service = await _seed_graph(org, store, monkeypatch)
            graph = await service.build(org, source_id=source_id)
            node_types = {n["type"] for n in graph["nodes"]}
            assert {"datasource", "entity", "field"}.issubset(node_types)
            rel_edges = [e for e in graph["edges"] if e["type"] == "relationship"]
            assert rel_edges
            fk_edge = next(
                e
                for e in rel_edges
                if e["provenance"] == RelationshipProvenance.OBSERVED.value
            )
            assert fk_edge["confidence"] >= 0.95
            assert fk_edge["cardinality"] == "N:1"
            assert fk_edge["evidence"]
            assert fk_edge["evidence_detail"]
            assert all(node["confidence"] >= 0 for node in graph["nodes"])

            only_entities = await service.build(
                org, source_id=source_id, node_types={"entity"}
            )
            assert only_entities["nodes"]
            assert all(n["type"] == "entity" for n in only_entities["nodes"])

            search = await service.build(org, source_id=source_id, q="TBL_CUST")
            assert search["nodes"]
            assert any(
                "TBL_CUST" in json.dumps(n["metadata"]) for n in search["nodes"]
            )
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_learned_entities_cards(self, monkeypatch) -> None:
        org = await _create_org("rel-learned")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, service = await _seed_graph(org, store, monkeypatch)
            learned = await service.learned_entities(org, source_id=source_id)
            assert learned
            customer = next(e for e in learned if e["name"] == "Customer")
            assert customer["fields_total"] >= 1
            assert customer["relationships_total"] >= 1
            assert customer["table"]
            assert customer["confidence"] > 0
        finally:
            await _cleanup_org(org)

    @pytest.mark.asyncio
    async def test_gaps_detect_unmapped_table_and_pending_relationship(
        self, monkeypatch
    ) -> None:
        org = await _create_org("rel-gaps")
        store = PostgresCatalogStore()
        await store.ensure_tables()
        try:
            source_id, service = await _seed_graph(org, store, monkeypatch)
            gaps = await service.gaps(org, source_id=source_id)
            types = {g["gap_type"] for g in gaps["gaps"]}
            assert "MISSING_TABLE" in types  # TBL_LOG_X sin entidad
            assert "MISSING_RELATIONSHIP" in types  # hipótesis LLM pendiente
            pending = next(
                g for g in gaps["gaps"] if g["gap_type"] == "MISSING_RELATIONSHIP"
            )
            assert pending["suggested_action"] == "confirm_relationship"
            assert pending["severity"] in ("high", "medium", "critical")
            assert gaps["by_severity"]
        finally:
            await _cleanup_org(org)


# ---------------------------------------------------------------------------
# API: entities / graph / gaps con aislamiento
# ---------------------------------------------------------------------------


class TestKnowledgeGraphApi:
    @pytest.mark.asyncio
    async def test_graph_endpoints_and_tenant_isolation(
        self, async_client, trial_auth, monkeypatch
    ) -> None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        org = UUID(trial_auth["X-Organization-Id"])
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await PostgresKnowledgeLearningRepository().ensure_tables()
        source_id, _ = await _seed_graph(org, store, monkeypatch)

        entities = await async_client.get(
            "/api/v1/knowledge/learning/entities", headers=trial_auth
        )
        assert entities.status_code == 200, entities.text
        assert entities.json()["count"] >= 1

        graph = await async_client.get(
            "/api/v1/knowledge/learning/graph",
            params={"source_id": str(source_id), "limit_nodes": 100},
            headers=trial_auth,
        )
        assert graph.status_code == 200, graph.text
        body = graph.json()
        assert body["counts"]["nodes"] >= 1
        assert any(n["type"] == "entity" for n in body["nodes"])

        invalid = await async_client.get(
            "/api/v1/knowledge/learning/graph",
            params={"node_types": "inventado"},
            headers=trial_auth,
        )
        assert invalid.status_code == 400

        gaps = await async_client.get(
            "/api/v1/knowledge/learning/gaps",
            params={"source_id": str(source_id)},
            headers=trial_auth,
        )
        assert gaps.status_code == 200, gaps.text
        assert gaps.json()["total"] >= 1

        # Otro tenant no ve nada.
        other = await async_client.post(
            "/api/v1/billing/subscription/create-trial",
            json={
                "company_name": f"Graph Co {uuid4().hex[:8]}",
                "email": f"graph-{uuid4().hex[:8]}@example.com",
            },
        )
        assert other.status_code == 200, other.text
        other_headers = {
            "Authorization": f"Bearer {other.json()['api_token']}",
            "X-Organization-Id": other.json()["organization_id"],
        }
        other_entities = await async_client.get(
            "/api/v1/knowledge/learning/entities", headers=other_headers
        )
        assert other_entities.status_code == 200
        assert other_entities.json()["count"] == 0
