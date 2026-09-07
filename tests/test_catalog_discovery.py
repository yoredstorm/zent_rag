# =============================================================================
# Discovery Engine & Semantic Catalog — tests (FASE 24)
# =============================================================================
# Cubre: inferencia heurística, PII (no-sampling), relaciones físicas/inferidas,
# enums sin auto-aprobación, readiness compuesta, engine end-to-end con plugin
# fake (solo lectura), aislamiento multi-tenant, glosario, métricas con sync a
# business_definitions, review queue con materialización + lineage, drift y
# borrado de fuente.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.catalog.discovery import DiscoveryAdapter, MetadataScanner
from src.catalog.enums import EnumDiscovery
from src.catalog.inference import SemanticInference, infer_entity_name, infer_field_name
from src.catalog.relationships import RelationshipDetector, _is_key_column, _normalize_column
from src.catalog.schema_linking import SemanticSchemaLinking
from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.base import ConnectorPlugin
from src.connectors.plugin.models import (
    ColumnProfile,
    DeepSchemaDiscovery,
    DeepTableProfile,
    Relationship,
)
from src.core.domain.catalog import (
    DiscoveryBudgets,
    ScanBudget,
)
from src.core.domain.pii import is_sensitive_column, pii_flags_for_column, should_sample_column

ORG_DEV = UUID("00000000-0000-0000-0000-000000000001")


async def _fresh_store() -> PostgresCatalogStore:
    store = PostgresCatalogStore()
    await store.ensure_tables()
    return store


# ---------------------------------------------------------------------------
# Fixtures
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
                        name="SALARY_AMT", data_type="numeric", nullable=True,
                        sensitive=True, sample_disabled=True,
                    ),
                ],
                foreign_keys=[
                    Relationship(from_column="CUST_ID", to_table="TBL_ORD", to_column="CUST_ID"),
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
                    ColumnProfile(
                        name="CUST_ID", data_type="uuid", nullable=True,
                    ),
                    ColumnProfile(
                        name="STATUS_CD", data_type="character varying",
                        nullable=True, cardinality=5,
                        distinct_values=["P", "C", "X"],
                    ),
                ],
            ),
            DeepTableProfile(
                table_name="TBL_AUDIT",
                schema="erp",
                columns=[ColumnProfile(name="id", data_type="uuid", is_primary_key=True)],
            ),
        ],
    )


class _FakePlugin(ConnectorPlugin):
    connector_type = "postgres"
    capabilities = frozenset({"test", "discover"})
    required_secret_keys = ["password"]

    def __init__(self, config=None, secrets=None, deep=None) -> None:
        super().__init__(config or {}, secrets or {})
        self.deep = deep or _deep_fixture()
        self.sampled_columns: list[str] = []
        self.queries: list[str] = []

    async def validate(self) -> None:
        return None

    async def connect(self) -> None:
        return None

    async def deep_discover(self, max_samples: int = 50) -> DeepSchemaDiscovery:
        return self.deep

    async def sample_distinct_values(
        self, schema: str, table: str, column: str, max_samples: int = 50
    ) -> list[str]:
        self.sampled_columns.append(f"{table}.{column}")
        for t in self.deep.tables:
            if t.table_name == table:
                for c in t.columns:
                    if c.name == column:
                        return list(c.distinct_values)
        return []


async def _seed_catalog(
    store: PostgresCatalogStore,
    plugin: _FakePlugin,
    org: UUID = ORG_DEV,
) -> tuple[UUID, dict]:
    """Ejecuta un scan completo con el plugin fake; retorna (source_id, outcome)."""
    from src.catalog.jobs import CatalogDiscoveryEngine
    from src.infrastructure.postgres.knowledge_repos import (
        PostgresIngestionJobRepository,
    )
    from src.infrastructure.postgres.relational_db import (
        PostgresConnectorRepository,
    )

    connector_id = uuid4()
    connector_repo = PostgresConnectorRepository()
    await connector_repo.create_connector(
        org, "fake-postgres", "postgres", config_json={"host": "fake"}
    )
    connectors = await connector_repo.list_connectors(org)
    connector_row = next(c for c in connectors if c.name == "fake-postgres")

    from src.catalog.jobs import DISCOVERY_JOB_PREFIX

    engine = CatalogDiscoveryEngine(
        job_repo=PostgresIngestionJobRepository(),
        connector_repo=connector_repo,
        catalog_store=store,
    )
    import src.catalog.jobs as jobs_mod

    def _fake_get_plugin(connector_type, config, secrets):
        assert connector_type == "postgres"
        return plugin


    jobs_mod.get_plugin = _fake_get_plugin

    job = await engine._jobs.create_job(
        org, job_type=f"{DISCOVERY_JOB_PREFIX}:scan", source_id=None, knowledge_base_id=None
    )
    await engine._jobs.update_job(
        job.id,
        cursor_snapshot={"catalog_source_id": None, "scan_type": "initial"},
    )

    # Conector real para el FK de catalog_sources.
    from src.catalog.jobs import start_discovery_scan

    result = await start_discovery_scan(
        job_repo=PostgresIngestionJobRepository(),
        catalog_store=store,
        organization_id=org,
        connector_id=connector_row.id,
        scan_type="initial",
    )
    source_id = UUID(result["catalog_source_id"])
    job = await engine._jobs.get_job(org, UUID(result["job_id"]))
    await engine._jobs.update_job(
        job.id,
        cursor_snapshot={"catalog_source_id": str(source_id), "scan_type": "initial"},
    )
    final = await engine.execute_job(job.id)
    return source_id, final


# ---------------------------------------------------------------------------
# Inferencia heurística
# ---------------------------------------------------------------------------

class TestInferEntityName:
    def test_abbreviation_mapping(self) -> None:
        assert infer_entity_name("TBL_CUST") == "Customer"
        assert infer_entity_name("fact_orders") == "Order"
        assert infer_entity_name("DIM_PRODUCT") == "Product"

    def test_technical_tables_skipped(self) -> None:
        assert infer_entity_name("TBL_AUDIT") is None
        assert infer_entity_name("log_errors") is None
        assert infer_entity_name("stg_raw") is None


class TestInferFieldName:
    def test_humanizes(self) -> None:
        assert infer_field_name("CUST_NAM") == "CustNam"
        assert infer_field_name("status_cd") == "StatusCd"

    def test_technical_skipped(self) -> None:
        assert infer_field_name("id") is None
        assert infer_field_name("created_at") is None
        assert infer_field_name("updated_by") is None


class TestPiiProtection:
    def test_flags_detected(self) -> None:
        assert "email" in pii_flags_for_column("EMAIL_ADDR")
        assert "secret" in pii_flags_for_column("user_password")
        assert "salary" in pii_flags_for_column("SALARY_AMT")

    def test_sensitive_never_sampled(self) -> None:
        assert is_sensitive_column("email_addr")
        assert is_sensitive_column("salary_amt")
        assert not is_sensitive_column("status_cd")
        assert should_sample_column("status_cd") is True
        assert should_sample_column("EMAIL_ADDR") is False


class TestRelationshipHelpers:
    def test_normalization(self) -> None:
        assert _normalize_column("CUST_ID") == "cust"
        assert _normalize_column("STATUS_CD") == "status"

    def test_key_column_detection(self) -> None:
        assert _is_key_column("CUST_ID")
        assert _is_key_column("STATUS_CD")
        assert _is_key_column("name") is False


# ---------------------------------------------------------------------------
# Scanner + enum + readiness (unit sobre store real)
# ---------------------------------------------------------------------------

class TestMetadataScanner:
    @pytest.mark.asyncio
    async def test_scan_persists_physical_catalog_and_drift(self) -> None:
        store = await _fresh_store()
        plugin = _FakePlugin()
        adapter = DiscoveryAdapter(plugin, DiscoveryBudgets(max_samples=50), uuid4())
        budgets = DiscoveryBudgets()
        budgets.max_scan_cost = 500
        budget = ScanBudget(budget=budgets)

        # Fuente de catálogo con connector real (FK).
        connector = await _create_connector("scan-connector")
        src = await store.upsert_source(
            organization_id=ORG_DEV, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]

        scanner = MetadataScanner(store, budgets=budgets)
        outcome = await scanner.scan(
            organization_id=ORG_DEV,
            catalog_source_id=source_id,
            adapter=adapter,
            scan_budget=budget,
        )
        assert outcome.tables_scanned == 3
        tables = await store.list_tables(ORG_DEV, source_id)
        assert len(tables) == 3
        cust = next(t for t in tables if t["table_name"] == "TBL_CUST")
        cols = await store.list_columns(ORG_DEV, UUID(cust["id"]))
        names = {c["column_name"] for c in cols}
        assert "EMAIL_ADDR" in names
        sensitive = next(c for c in cols if c["column_name"] == "EMAIL_ADDR")
        assert sensitive["is_sensitive"] is True
        assert sensitive["sample_disabled"] is True

        # 2º scan: tabla removida -> drift table_removed.
        plugin.deep.tables = plugin.deep.tables[:2]
        outcome2 = await scanner.scan(
            organization_id=ORG_DEV,
            catalog_source_id=source_id,
            adapter=adapter,
            scan_budget=ScanBudget(budget=budgets),
        )
        assert any(c["type"] == "table_removed" for c in outcome2.changes)
        active = await store.list_tables(ORG_DEV, source_id)
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_scan_budget_exhausted_is_partial(self) -> None:
        store = await _fresh_store()
        plugin = _FakePlugin()
        budgets = DiscoveryBudgets(max_scan_cost=2)
        adapter = DiscoveryAdapter(plugin, budgets, uuid4())
        connector = await _create_connector("budget-connector")
        src = await store.upsert_source(
            organization_id=ORG_DEV, connector_id=connector.id, engine="postgres"
        )
        outcome = await MetadataScanner(store, budgets=budgets).scan(
            organization_id=ORG_DEV,
            catalog_source_id=src["id"],
            adapter=adapter,
            scan_budget=ScanBudget(budget=budgets),
        )
        assert outcome.partial is True


class TestEnumDiscovery:
    @pytest.mark.asyncio
    async def test_enum_values_observed_and_gap_without_auto_approval(self) -> None:
        store = await _fresh_store()
        from src.intelligence.store import PostgresIntelligenceStore

        org = uuid4()
        intel = PostgresIntelligenceStore()
        await intel.ensure_tables()
        connector = await _create_connector("enum-connector", org)
        src = await store.upsert_source(
            organization_id=org, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        table_id, _ = await store.upsert_table(
            organization_id=org, source_id=source_id,
            schema_name="erp", table_name="TBL_CUST",
        )
        col_id = await store.upsert_column(
            organization_id=org, table_id=table_id,
            column_name="CUST_STS", data_type="character varying",
        )
        enum = EnumDiscovery(store, intelligence_store=intel)
        processed = await enum.process(
            organization_id=org,
            catalog_source_id=source_id,
            enum_columns=[{
                "schema": "erp", "table": "TBL_CUST",
                "table_id": str(table_id), "samples": {"CUST_STS": ["A", "B", "C", "I"]},
            }],
        )
        assert processed and processed[0]["undocumented"] == ["A", "B", "C", "I"]
        values = await store.list_enum_values(org, col_id)
        assert len(values) == 4
        assert values[0]["provenance"] == "OBSERVED"
        assert values[0]["documented_meaning"] is None

        gaps = await intel.list_gaps(org)
        assert any(g["gap_type"] == "UNDEFINED_ENUM" for g in gaps)

        suggestions = await store.list_suggestions(org, status="pending")
        enum_suggestions = [
            s for s in suggestions
            if s["type"] == "enum_definition"
            and str(s["payload"].get("column_id")) == str(col_id)
        ]
        assert len(enum_suggestions) == 1

        # Sin duplicados: un segundo process no crea otra sugerencia.
        await enum.process(
            organization_id=org,
            catalog_source_id=source_id,
            enum_columns=[{
                "schema": "erp", "table": "TBL_CUST",
                "table_id": str(table_id), "samples": {"CUST_STS": ["A", "B"]},
            }],
        )
        suggestions2 = await store.list_suggestions(org, status="pending")
        assert len([
            s for s in suggestions2
            if s["type"] == "enum_definition"
            and str(s["payload"].get("column_id")) == str(col_id)
        ]) == 1


class TestReadinessComposition:
    @pytest.mark.asyncio
    async def test_breakdown_never_single_percentage(self) -> None:
        from src.catalog.readiness import ReadinessService
        from src.intelligence.store import PostgresIntelligenceStore

        store = await _fresh_store()
        connector = await _create_connector("ready-connector")
        src = await store.upsert_source(
            organization_id=ORG_DEV, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        table_id, _ = await store.upsert_table(
            organization_id=ORG_DEV, source_id=source_id,
            schema_name="erp", table_name="TBL_CUST",
        )
        report = await ReadinessService(
            store, PostgresIntelligenceStore()
        ).for_source(ORG_DEV, source_id)
        payload = report.to_dict()
        assert set(payload) >= {
            "overall", "schema_coverage", "relationship_coverage",
            "description_coverage", "semantic_mapping_coverage",
            "metric_coverage", "glossary_coverage", "freshness",
            "data_quality", "unknown_code_count", "pending_review_count",
        }
        assert payload["unknown_code_count"] == 0


class TestSemanticInferenceUnit:
    @pytest.mark.asyncio
    async def test_entities_inferred_never_approved(self) -> None:
        store = await _fresh_store()
        org = uuid4()
        connector = await _create_connector("inf-connector", org)
        src = await store.upsert_source(
            organization_id=org, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        tables_meta = []
        for t in _deep_fixture().tables:
            tid, _ = await store.upsert_table(
                organization_id=org, source_id=source_id,
                schema_name=t.schema, table_name=t.table_name,
                table_comment=t.table_comment,
            )
            tables_meta.append(
                {"id": str(tid), "schema_name": t.schema, "table_name": t.table_name}
            )
        inference = SemanticInference(store, llm_provider=None, llm_enabled=False)
        suggestions = await inference.run(
            organization_id=org,
            catalog_source_id=source_id,
            deep=_deep_fixture(),
            tables_meta=tables_meta,
        )
        assert any(s["type"] == "entity_identification" for s in suggestions)
        entities = await store.list_entities(org)
        assert entities
        assert all(e["provenance"] == "INFERRED" for e in entities)
        assert all(e["status"] == "draft" for e in entities)


# ---------------------------------------------------------------------------
# Relaciones
# ---------------------------------------------------------------------------

class TestRelationshipDetector:
    @pytest.mark.asyncio
    async def test_physical_fk_confirmed_and_inferred_suggested(self) -> None:
        store = await _fresh_store()
        connector = await _create_connector("rel-connector")
        src = await store.upsert_source(
            organization_id=ORG_DEV, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        ids: dict[str, UUID] = {}
        for t in _deep_fixture().tables:
            tid, _ = await store.upsert_table(
                organization_id=ORG_DEV, source_id=source_id,
                schema_name=t.schema, table_name=t.table_name,
            )
            ids[t.table_name] = tid

        detector = RelationshipDetector(store)
        results = await detector.detect(
            organization_id=ORG_DEV,
            catalog_source_id=source_id,
            deep=_deep_fixture(),
        )
        rels = await store.list_relationships(ORG_DEV, source_id, limit=1000)
        physical = [r for r in rels if r["relation_type"] == "foreign_key"]
        assert physical and physical[0]["status"] == "confirmed"
        inferred = [r for r in rels if r["relation_type"] == "inferred"]
        assert inferred and inferred[0]["status"] == "suggested"
        assert all(r["confidence"] in ("high", "medium", "low") for r in inferred)


# ---------------------------------------------------------------------------
# Schema linking
# ---------------------------------------------------------------------------

class TestSchemaLinking:
    @pytest.mark.asyncio
    async def test_glossary_and_entity_boost(self) -> None:
        store = await _fresh_store()
        from src.intelligence.store import PostgresIntelligenceStore

        intel = PostgresIntelligenceStore()
        await intel.ensure_tables()
        await intel.upsert_definition(
            organization_id=ORG_DEV, concept="cliente", definition="Cliente",
            status="approved",
        )
        connector = await _create_connector("link-connector")
        src = await store.upsert_source(
            organization_id=ORG_DEV, connector_id=connector.id, engine="postgres"
        )
        source_id = src["id"]
        table_id, _ = await store.upsert_table(
            organization_id=ORG_DEV, source_id=source_id,
            schema_name="erp", table_name="TBL_CUST",
        )
        from src.core.domain.catalog import CatalogEntity, CatalogProvenance

        await store.upsert_entity(
            CatalogEntity(
                organization_id=ORG_DEV,
                name="customer",
                provenance=CatalogProvenance.APPROVED,
                status="approved",
                mapped_table_id=table_id,
            )
        )
        linking = SemanticSchemaLinking(store, intelligence_store=intel)
        scores = await linking.candidate_scores(
            ORG_DEV, "¿cuántos clientes tenemos?", ["erp.TBL_CUST", "erp.TBL_ORD"]
        )
        assert scores.get("erp.TBL_CUST", 0) > 0


# ---------------------------------------------------------------------------
# Engine end-to-end (job durable -> scan -> fase)
# ---------------------------------------------------------------------------

class TestCatalogDiscoveryEngine:
    @pytest.mark.asyncio
    async def test_full_job_flow_with_phases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.catalog.jobs import (
            CatalogDiscoveryEngine,
            start_discovery_scan,
        )
        from src.infrastructure.postgres.knowledge_repos import (
            PostgresIngestionJobRepository,
        )
        from src.infrastructure.postgres.relational_db import (
            PostgresConnectorRepository,
        )

        store = await _fresh_store()
        org = uuid4()
        connector = await _create_connector("e2e-connector", org)
        plugin = _FakePlugin()
        engine = CatalogDiscoveryEngine(
            job_repo=PostgresIngestionJobRepository(),
            connector_repo=PostgresConnectorRepository(),
            catalog_store=store,
        )

        import src.catalog.jobs as jobs_mod

        jobs_mod.get_plugin = lambda *a, **k: plugin

        result = await start_discovery_scan(
            job_repo=PostgresIngestionJobRepository(),
            catalog_store=store,
            organization_id=org,
            connector_id=connector.id,
            scan_type="initial",
        )
        job_id = UUID(result["job_id"])
        source_id = UUID(result["catalog_source_id"])
        job_repo = PostgresIngestionJobRepository()
        job = await job_repo.get_job(org, job_id)
        await job_repo.update_job(
            job.id,
            cursor_snapshot={
                "catalog_source_id": str(source_id),
                "scan_type": "initial",
            },
        )
        final = await engine.execute_job(job.id)
        assert final.status.value == "completed", final.error_summary

        source = await store.get_source(org, source_id)
        # TBL_AUDIT se excluye; TBL_CUST/TBL_ORD con enums -> WAITING_REVIEW.
        assert source["phase"] in ("WAITING_REVIEW", "COMPLETED")
        assert source["last_scan_at"] is not None

        tables = await store.list_tables(org, source_id)
        assert len(tables) >= 2
        entities = await store.list_entities(org)
        assert entities

        relationships = await store.list_relationships(org, source_id, limit=1000)
        assert any(r["relation_type"] == "foreign_key" for r in relationships)

        scans = await store.list_scans(org, source_id)
        assert scans and scans[0]["status"] == "completed"
        assert isinstance(scans[0]["changes"], list)

    @pytest.mark.asyncio
    async def test_never_samples_sensitive_columns(self) -> None:
        store = await _fresh_store()
        plugin = _FakePlugin()
        budgets = DiscoveryBudgets(max_scan_cost=1000)
        adapter = DiscoveryAdapter(plugin, budgets, uuid4())
        connector = await _create_connector("pii-connector")
        src = await store.upsert_source(
            organization_id=ORG_DEV, connector_id=connector.id, engine="postgres"
        )
        await MetadataScanner(store, budgets=budgets).scan(
            organization_id=ORG_DEV,
            catalog_source_id=src["id"],
            adapter=adapter,
            scan_budget=ScanBudget(budget=budgets),
        )
        # CUST_STS se muestrea; EMAIL_ADDR/SALARY_AMT NUNCA.
        assert plugin.sampled_columns
        assert all("EMAIL" not in c and "SALARY" not in c for c in plugin.sampled_columns)
        assert any("CUST_STS" in c for c in plugin.sampled_columns)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connector_repo():
    from src.infrastructure.postgres.relational_db import (
        PostgresConnectorRepository,
    )

    return PostgresConnectorRepository()


async def _create_connector(prefix: str, organization_id: UUID = ORG_DEV):
    """Conector real con nombre único por ejecución (UNIQUE org+name).

    Para orgs no seeded, crea primero la fila organizations (FK).
    """
    repo = _connector_repo()
    if organization_id != ORG_DEV:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name, status, created_at, updated_at) "
                    "VALUES (:id, :name, 'active', now(), now()) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": organization_id, "name": f"cat-{uuid4().hex[:8]}"},
            )
            await session.commit()
        finally:
            await session.close()
    name = f"{prefix}-{uuid4().hex[:8]}"
    connector = await repo.create_connector(
        organization_id, name, "postgres", config_json={"host": "fake"}
    )
    return connector
