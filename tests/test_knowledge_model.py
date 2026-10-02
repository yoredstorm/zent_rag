# =============================================================================
# Knowledge Operating System — tests (FASE 34)
# =============================================================================
# Cubre: dominio puro (confianza explicable, health sin medir != 0, prioridad
# de gaps, aliases), materialización real desde catalog_*, provenance/evidencia,
# aislamiento multi-tenant, error tipado (ERROR != ZERO) y verificación humana.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import text

import src.platform.knowledge_model.materializer as materializer_module
from src.core.domain.knowledge_events import KnowledgeEventType
from src.core.domain.knowledge_model import (
    ConfidenceSignals,
    GapImpact,
    GapType,
    HealthDimension,
    KnowledgeObjectStatus,
    aggregate_health,
    compute_confidence,
    compute_gap_priority,
    normalize_object_status,
    normalize_object_type,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_model.materializer import KnowledgeModelMaterializer
from src.platform.knowledge_model.repository import PostgresKnowledgeModelRepository
from src.platform.knowledge_model.service import KnowledgeModelUnavailable

# ---------------------------------------------------------------------------
# Dominio puro
# ---------------------------------------------------------------------------


def test_confidence_caps_without_evidence() -> None:
    score, detail = compute_confidence(
        ConfidenceSignals(
            source_reliability=1.0,
            evidence_strength=1.0,
            evidence_count=0,
            semantic_certainty=1.0,
            freshness=1.0,
        )
    )
    assert score <= 0.6
    assert detail["components"]["corroboration"] == 0.0
    assert "sin evidencia" in " ".join(detail["caps"])


def test_confidence_rejected_is_zero_and_verified_has_floor() -> None:
    rejected, _ = compute_confidence(
        ConfidenceSignals(validation=0.0, evidence_count=3, evidence_strength=0.9)
    )
    assert rejected == 0.0
    verified, _ = compute_confidence(
        ConfidenceSignals(
            validation=1.0,
            evidence_count=3,
            evidence_strength=1.0,
            source_reliability=1.0,
            semantic_certainty=1.0,
            freshness=1.0,
        )
    )
    assert verified >= 0.9


def test_confidence_evidence_beats_source_reliability() -> None:
    weak_evidence, _ = compute_confidence(
        ConfidenceSignals(
            source_reliability=1.0,
            evidence_strength=0.5,
            evidence_count=1,
            semantic_certainty=0.55,
        )
    )
    strong_evidence, _ = compute_confidence(
        ConfidenceSignals(
            source_reliability=0.5,
            evidence_strength=0.95,
            evidence_count=3,
            semantic_certainty=0.9,
        )
    )
    assert strong_evidence > weak_evidence


def test_health_excludes_unmeasured_dimensions() -> None:
    dimensions = [
        HealthDimension(
            key="coverage", label="Cobertura", score=80.0, weight=0.5, measured=True
        ),
        HealthDimension(
            key="retrieval",
            label="Retrieval",
            score=None,
            weight=0.5,
            measured=False,
            reason="sin evaluación",
        ),
    ]
    overall, measured = aggregate_health(dimensions)
    assert measured == 1
    assert overall == 80.0  # la dimensión no medida NO cuenta como 0


def test_health_all_unmeasured_is_none_not_zero() -> None:
    overall, measured = aggregate_health(
        [
            HealthDimension(
                key="retrieval",
                label="Retrieval",
                score=None,
                weight=1.0,
                measured=False,
            )
        ]
    )
    assert overall is None
    assert measured == 0


def test_gap_priority_prefers_business_impact() -> None:
    low, low_score = compute_gap_priority(
        impact=GapImpact(affected_objects=1, business_impact=0.1, retrieval_impact=0.1),
        confidence=0.9,
        ambiguity=0.2,
        dependents=0.0,
    )
    high, high_score = compute_gap_priority(
        impact=GapImpact(
            affected_objects=14, business_impact=1.0, retrieval_impact=1.0
        ),
        confidence=0.2,
        ambiguity=0.9,
        dependents=1.0,
    )
    assert high_score > low_score
    assert high == "critical"
    assert low == "low"


def test_status_and_kind_aliases_are_normalized() -> None:
    assert normalize_object_status("observed") == KnowledgeObjectStatus.DISCOVERED.value
    assert normalize_object_status("approved") == KnowledgeObjectStatus.VERIFIED.value
    assert normalize_object_status("archived") == KnowledgeObjectStatus.DEPRECATED.value
    assert normalize_object_type("rule") == "business_rule"
    assert normalize_object_type("glossary_term") == "term"
    assert normalize_object_type("entity") == "entity"


# ---------------------------------------------------------------------------
# C8: eventos de sistema del materializer (repo/sesión/emisor fake)
# ---------------------------------------------------------------------------


class FakeSystemEmitter:
    """Emisor C8 en memoria: registra los eventos de dominio emitidos."""

    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)

    def of_type(self, event_type: KnowledgeEventType) -> list:
        return [event for event in self.events if event.type == event_type]


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def fetchall(self) -> list:
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeGapSession:
    """Sesión fake de `_generate_gaps`: responde solo lo que cada query pide."""

    def __init__(self, occurrences_by_concept: dict[str, int]) -> None:
        self.occurrences = occurrences_by_concept
        self.closed = False
        self.occurrence_reads = 0
        self.assertion = SimpleNamespace(
            id=uuid4(),
            subject_label="Order",
            predicate="states",
            object_value="pedido mínimo",
            confidence=0.4,
            source_id=None,
        )
        self.low_confidence_object = SimpleNamespace(
            id=uuid4(),
            kind="rule",
            name="VAT",
            confidence=0.4,
            source_id=None,
        )

    async def execute(self, statement, params):
        sql = str(statement)
        if "SELECT occurrences FROM context_gaps" in sql:
            self.occurrence_reads += 1
            return _FakeResult(
                [(int(self.occurrences.get(params["concept"], 1)),)]
            )
        if "FROM knowledge_assertions" in sql:
            return _FakeResult([self.assertion])
        if "FROM knowledge_canonical_objects" in sql and "confidence < 0.6" in sql:
            return _FakeResult([self.low_confidence_object])
        return _FakeResult([])

    async def close(self) -> None:
        self.closed = True


class FakeGapRepo:
    def __init__(self) -> None:
        self.gaps: list[dict] = []

    async def upsert_gap(self, organization_id, **kwargs):
        self.gaps.append(kwargs)
        return uuid4()


class FakeImpactRepo:
    def __init__(self, counts: dict) -> None:
        self.counts = counts
        self.impact_calls: list = []

    async def impact(self, organization_id, object_id):
        self.impact_calls.append(object_id)
        return {"count": int(self.counts.get(object_id, 0))}


async def test_materializer_emite_gap_detected_solo_para_gaps_nuevos(
    monkeypatch,
) -> None:
    """Un gap con occurrences==1 tras el upsert viaja al emisor; uno repetido no."""
    org = uuid4()
    session = _FakeGapSession(
        {
            "assertion:Order:states": 1,  # nuevo
            "object:VAT": 3,  # ya existía en corridas previas
        }
    )
    repo = FakeGapRepo()
    emitter = FakeSystemEmitter()
    materializer = KnowledgeModelMaterializer(repo, system_emitter=emitter)

    async def fake_session():
        return session

    monkeypatch.setattr(materializer_module, "get_async_session", fake_session)

    created = await materializer._generate_gaps(org)

    assert created == 2
    assert session.closed is True
    events = emitter.of_type(KnowledgeEventType.KNOWLEDGE_GAP_DETECTED)
    assert len(events) == 1, "solo el gap nuevo debe emitirse"
    event = events[0]
    assert event.organization_id == org
    assert event.payload["gap_type"] == GapType.UNSUPPORTED_ASSERTION.value
    assert event.payload["concept"] == "assertion:Order:states"
    expected_priority, _ = compute_gap_priority(
        impact=GapImpact(affected_objects=1, business_impact=0.6, retrieval_impact=0.4),
        confidence=0.4,
        ambiguity=0.6,
        dependents=0.2,
    )
    assert event.payload["priority"] == expected_priority
    assert event.requires_review is True


async def test_materializer_emite_high_impact_solo_sobre_el_umbral() -> None:
    """Cambios con impacto >= umbral se emiten; por debajo no. Cap de 5."""
    org = uuid4()
    high, low = uuid4(), uuid4()
    repo = FakeImpactRepo({high: 7, low: 2})
    emitter = FakeSystemEmitter()
    materializer = KnowledgeModelMaterializer(repo, system_emitter=emitter)

    await materializer._emit_high_impact_changes(
        org, [("entity", high), ("rule", low)]
    )

    events = emitter.of_type(KnowledgeEventType.HIGH_IMPACT_CHANGE)
    assert len(events) == 1
    event = events[0]
    assert event.organization_id == org
    assert event.object_id == high
    assert event.payload["count"] == 7
    assert event.payload["threshold"] == 5
    assert event.requires_review is True
    assert low in repo.impact_calls, "el bajo también se evalúa pero no se emite"

    # Cap 5 por emisión: con más objetos de alto impacto se emiten cinco y break.
    extra = uuid4()
    repo.counts = {extra: 9}
    emitter.events.clear()
    repo.impact_calls.clear()
    await materializer._emit_high_impact_changes(
        org, [("entity", extra) for _ in range(7)]
    )
    assert len(repo.impact_calls) == 5
    assert len(emitter.of_type(KnowledgeEventType.HIGH_IMPACT_CHANGE)) == 5


async def test_materializer_high_impact_no_estrella_reglas_con_muchas_entidades() -> None:
    """El cap aplica a emisiones: la regla de alto impacto no queda hambreada."""
    org = uuid4()
    entities = [uuid4() for _ in range(7)]
    rule = uuid4()
    repo = FakeImpactRepo({**{eid: 1 for eid in entities}, rule: 9})
    emitter = FakeSystemEmitter()
    materializer = KnowledgeModelMaterializer(repo, system_emitter=emitter)

    changed = [("entity", eid) for eid in entities] + [("rule", rule)]
    await materializer._emit_high_impact_changes(org, changed)

    events = emitter.of_type(KnowledgeEventType.HIGH_IMPACT_CHANGE)
    assert len(events) == 1, "la regla debe emitirse aunque haya 7 entidades antes"
    assert events[0].object_id == rule
    assert events[0].payload["count"] == 9
    assert events[0].payload["threshold"] == 5
    assert events[0].requires_review is True

    # Cap por emisión: 6 reglas de alto impacto → exactamente 5 eventos.
    rules = [uuid4() for _ in range(6)]
    repo.counts = {rid: 9 for rid in rules}
    emitter.events.clear()
    repo.impact_calls.clear()
    await materializer._emit_high_impact_changes(
        org, [("rule", rid) for rid in rules]
    )
    events = emitter.of_type(KnowledgeEventType.HIGH_IMPACT_CHANGE)
    assert len(events) == 5
    assert len(repo.impact_calls) == 5, "break al alcanzar el cap de emisiones"


async def test_materializer_sin_emisor_no_lee_occurrences(monkeypatch) -> None:
    """Sin emisor no hay SELECT extra de ocurrencias; los gaps se persisten."""
    org = uuid4()
    session = _FakeGapSession({"assertion:Order:states": 1, "object:VAT": 1})
    repo = FakeGapRepo()
    materializer = KnowledgeModelMaterializer(repo, system_emitter=None)

    async def fake_session():
        return session

    monkeypatch.setattr(materializer_module, "get_async_session", fake_session)

    created = await materializer._generate_gaps(org)

    assert created == 2
    assert session.occurrence_reads == 0, "sin emisor no se consulta occurrences"
    assert len(repo.gaps) == 2, "los gaps se siguen persistiendo"


class _EmptySession:
    """Sesión fake sin filas: los queries de `_generate_gaps` no crean gaps."""

    async def execute(self, statement, params):
        return _FakeResult([])

    async def close(self) -> None:
        return None


class _MinimalMaterializeRepo:
    """Lo mínimo que `materialize()` invoca, sin contrato de status (legacy)."""

    def __init__(self, *, impact_count: int = 99, existed: bool = True) -> None:
        self.impact_count = impact_count
        self.legacy_existed = existed
        self.impact_calls: list = []

    async def upsert_object(self, organization_id, **kwargs) -> bool:
        return bool(self.legacy_existed)

    async def upsert_edge(self, *args, **kwargs) -> None:
        return None

    async def detect_conflicts(self, organization_id) -> int:
        return 0

    async def refresh_object_counters(self, organization_id) -> None:
        return None

    async def impact(self, organization_id, object_id):
        self.impact_calls.append(object_id)
        return {"count": self.impact_count}


class FakeMaterializeRepo(_MinimalMaterializeRepo):
    """Repo con el contrato C8: `statuses` mapea kind → (existed, changed)."""

    def __init__(
        self, statuses: dict[str, tuple[bool, bool]] | None = None, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.statuses = statuses or {}

    async def upsert_object_with_status(self, organization_id, *, kind, **kwargs):
        return self.statuses.get(kind, (True, False))


def _entity_bundle() -> dict:
    """Bundle mínimo de `_load_bundle`: una entidad sin tabla ni fuente."""
    return {
        "sources": [],
        "tables": [],
        "columns": [],
        "entities": [
            {
                "id": uuid4(),
                "name": "Order",
                "display_name": "Pedido",
                "description": "Pedido de venta",
                "provenance": "OBSERVED",
                "confidence": "high",
                "status": "approved",
                "mapped_table_id": None,
                "table_name": None,
                "schema_name": "sales",
                "source_id": None,
                "updated_at": None,
            }
        ],
        "fields": [],
        "relationships": [],
        "metrics": [],
        "definitions": [],
        "rules": [],
        "verified_queries": [],
        "documents": [],
        "authority": {},
        "entity_names": {},
        "table_names": {},
        "metric_keys": {},
    }


async def _materialize_inmemory(
    monkeypatch, repo, emitter
) -> dict:
    """`materialize()` sobre un bundle fake: sin DB, sin evento de learning."""
    materializer = KnowledgeModelMaterializer(repo, system_emitter=emitter)
    bundle = _entity_bundle()

    async def fake_session():
        return _EmptySession()

    async def fake_load_bundle(session, organization_id, source_id):
        return bundle

    async def noop_emit_event(*args, **kwargs):
        return None

    monkeypatch.setattr(materializer_module, "get_async_session", fake_session)
    monkeypatch.setattr(materializer, "_load_bundle", fake_load_bundle)
    monkeypatch.setattr(materializer, "_emit_event", noop_emit_event)
    return await materializer.materialize(uuid4())


async def test_materializer_high_impact_solo_con_cambio_real(monkeypatch) -> None:
    """Re-observar un objeto idéntico (True, False) no emite; un cambio real sí."""
    emitter = FakeSystemEmitter()
    sin_cambios = FakeMaterializeRepo(
        {"entity": (True, False), "domain": (True, False)}
    )
    await _materialize_inmemory(monkeypatch, sin_cambios, emitter)
    assert emitter.of_type(KnowledgeEventType.HIGH_IMPACT_CHANGE) == []
    assert sin_cambios.impact_calls == [], "sin cambio no se evalúa el impacto"

    emitter.events.clear()
    con_cambio = FakeMaterializeRepo(
        {"entity": (True, True), "domain": (True, False)}
    )
    await _materialize_inmemory(monkeypatch, con_cambio, emitter)
    events = emitter.of_type(KnowledgeEventType.HIGH_IMPACT_CHANGE)
    assert len(events) == 1
    assert events[0].payload["kind"] == "entity"
    assert events[0].payload["count"] == 99
    assert events[0].requires_review is True


async def test_materializer_upsert_sin_status_cae_al_contrato_previo(
    monkeypatch,
) -> None:
    """Repo sin `upsert_object_with_status`: existed=True sigue contando como cambio."""
    emitter = FakeSystemEmitter()
    repo = _MinimalMaterializeRepo(existed=True)
    await _materialize_inmemory(monkeypatch, repo, emitter)
    events = emitter.of_type(KnowledgeEventType.HIGH_IMPACT_CHANGE)
    assert len(events) == 1
    assert events[0].payload["kind"] == "entity"
    assert len(repo.impact_calls) == 1


# ---------------------------------------------------------------------------
# Materialización real + API (requiere Postgres local)
# ---------------------------------------------------------------------------


async def _seed_catalog(
    org: UUID,
    kb_source_id: UUID | None = None,
    connector_config: dict | None = None,
) -> dict:
    ids = {
        "connector": uuid4(),
        "source": uuid4(),
        "orders": uuid4(),
        "customers": uuid4(),
        "order_customer_col": uuid4(),
        "customer_pk_col": uuid4(),
        "customer_entity": uuid4(),
        "order_entity": uuid4(),
        "order_field": uuid4(),
        "relationship": uuid4(),
    }
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO connectors (id, organization_id, name, type, config_json, status)
                VALUES (:connector, :org, 'ERP Test', 'sql', CAST(:config AS jsonb), 'active')
                """
            ),
            {
                "connector": ids["connector"],
                "org": org,
                "config": json.dumps(connector_config or {}),
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO catalog_sources (
                    id, organization_id, connector_id, engine, phase, last_scan_at,
                    kb_source_id
                ) VALUES (:source, :org, :connector, 'postgres', 'COMPLETED', now(),
                          :kb_source_id)
                """
            ),
            {**ids, "org": org, "kb_source_id": kb_source_id},
        )
        await session.execute(
            text(
                """
                INSERT INTO catalog_tables (
                    id, organization_id, source_id, schema_name, table_name,
                    row_count_approx, table_comment
                ) VALUES
                    (:orders, :org, :source, 'erp', 'orders', 100, 'Pedidos de venta'),
                    (:customers, :org, :source, 'erp', 'customers', 50, 'Clientes')
                """
            ),
            {**ids, "org": org},
        )
        await session.execute(
            text(
                """
                INSERT INTO catalog_columns (
                    id, organization_id, table_id, column_name, data_type,
                    is_primary_key, column_comment
                ) VALUES
                    (:order_customer_col, :org, :orders, 'customer_id', 'uuid', false,
                     'Cliente del pedido'),
                    (:customer_pk_col, :org, :customers, 'id', 'uuid', true, 'PK cliente')
                """
            ),
            {**ids, "org": org},
        )
        await session.execute(
            text(
                """
                INSERT INTO catalog_entities (
                    id, organization_id, name, display_name, description,
                    provenance, confidence, status, mapped_table_id
                ) VALUES
                    (:customer_entity, :org, 'Customer', 'Cliente',
                     'Persona que compra', 'OBSERVED', 'high', 'approved', :customers),
                    (:order_entity, :org, 'Order', 'Pedido',
                     'Pedido de venta', 'OBSERVED', 'high', 'approved', :orders)
                """
            ),
            {**ids, "org": org},
        )
        await session.execute(
            text(
                """
                INSERT INTO catalog_fields (
                    id, organization_id, entity_id, name, description, provenance,
                    confidence, status, mapped_column_id
                ) VALUES (
                    :order_field, :org, :order_entity, 'customer_id',
                    'Cliente que realizó el pedido', 'OBSERVED', 'high', 'approved',
                    :order_customer_col
                )
                """
            ),
            {**ids, "org": org},
        )
        await session.execute(
            text(
                """
                INSERT INTO catalog_relationships (
                    id, organization_id, source_id, from_table_id, from_column,
                    to_table_id, to_column, relation_type, confidence, status,
                    evidence, confidence_score, cardinality
                ) VALUES (
                    :relationship, :org, :source, :orders, 'customer_id',
                    :customers, 'id', 'foreign_key', 'high', 'confirmed',
                    '[]'::jsonb, 0.99, 'n:1'
                )
                """
            ),
            {**ids, "org": org},
        )
        await session.commit()
    finally:
        await session.close()
    return ids


async def _count_objects(org: UUID) -> int:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total FROM knowledge_canonical_objects "
                    "WHERE organization_id = :org"
                ),
                {"org": org},
            )
        ).first()
        return int(row.total or 0)
    finally:
        await session.close()


async def test_repo_upsert_object_with_status_detecta_solo_cambios_reales() -> None:
    """(False, True) al crear; (True, False) idéntico; (True, True) con cambio.

    `upsert_object` conserva su bool público para los callers existentes.
    """
    org = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name) VALUES (:org, 'Status Test') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"org": org},
        )
        await session.commit()
    finally:
        await session.close()

    repo = PostgresKnowledgeModelRepository()
    oid = uuid4()
    kwargs = {
        "object_id": oid,
        "kind": "entity",
        "natural_key": f"status-test:{oid}",
        "name": "Order",
        "description": "Pedido de venta",
        "domain": "sales",
        "confidence": 0.7,
        "status": KnowledgeObjectStatus.DISCOVERED.value,
    }

    assert await repo.upsert_object_with_status(org, **kwargs) == (False, True)
    # Contrato público intacto: ya existía → True (aunque no haya cambiado).
    assert await repo.upsert_object(org, **kwargs) is True
    assert await repo.upsert_object_with_status(org, **kwargs) == (True, False)
    assert await repo.upsert_object_with_status(
        org, **{**kwargs, "name": "Order v2"}
    ) == (True, True)

    nuevo = uuid4()
    assert (
        await repo.upsert_object(
            org,
            object_id=nuevo,
            kind="entity",
            natural_key=f"status-test:{nuevo}",
            name="Customer",
        )
        is False
    )


async def test_materialize_produces_objects_edges_assertions_and_evidence() -> None:
    org = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name) VALUES (:org, 'Knowledge Test') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"org": org},
        )
        await session.commit()
    finally:
        await session.close()

    await _seed_catalog(org)

    repository = PostgresKnowledgeModelRepository()
    await repository.ensure_tables()
    materializer = KnowledgeModelMaterializer(repository, max_columns=100)

    first = await materializer.materialize(org)
    assert first["objects_created"] > 0
    assert first["edges"] > 0
    assert first["assertions"] > 0
    assert first["evidence"] > 0

    stats = await repository.stats(org)
    # objects.total excluye artefactos físicos (source/table/column/...).
    assert stats["objects"]["total"] >= 5
    assert stats["by_kind"]["entity"]["total"] == 2
    assert stats["by_kind"]["attribute"]["total"] == 1
    assert stats["by_kind"]["table"]["total"] == 2
    assert stats["by_kind"]["column"]["total"] == 2
    assert stats["by_kind"]["relationship"]["total"] == 1
    assert stats["edges"]["total"] >= 8
    assert stats["assertions"]["total"] >= 4
    assert stats["evidence"]["total"] >= 3

    # La evidencia estructurada tiene locator real.
    entities = await repository.list_objects(org, kinds=["entity"], limit=10)
    customer = next(e for e in entities if e["name"] == "Customer")
    evidence = await repository.object_evidence(org, UUID(customer["id"]))
    assert evidence, "la entidad debe tener evidencia"
    assert all(e["locator"] for e in evidence)

    detail = await repository.object_edges(org, UUID(customer["id"]))
    predicates = {e["predicate"] for e in detail["edges"]}
    assert any(p in ("references", "has_many", "has_one") for p in predicates)

    order = next(e for e in entities if e["name"] == "Order")
    order_edges = await repository.object_edges(org, UUID(order["id"]))
    order_predicates = {e["predicate"] for e in order_edges["edges"]}
    assert "has_attribute" in order_predicates
    assert "references" in order_predicates

    # Verificación humana: promueve el objeto y respeta la approval law.
    verified = await repository.verify_object(org, UUID(customer["id"]), user_id=None)
    assert verified is not None
    assert verified["status"] == "verified"
    assert verified["provenance"] == "APPROVED"

    # Idempotencia: segunda materialización no crea objetos nuevos.
    second = await materializer.materialize(org)
    assert second["objects_created"] == 0
    assert second["objects_updated"] > 0
    total_all = sum(v["total"] for v in stats["by_kind"].values())
    assert await _count_objects(org) == total_all


async def test_materialize_is_tenant_scoped() -> None:
    org_a, org_b = uuid4(), uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name) VALUES "
                "(:a, 'Org A'), (:b, 'Org B') ON CONFLICT (id) DO NOTHING"
            ),
            {"a": org_a, "b": org_b},
        )
        await session.commit()
    finally:
        await session.close()
    await _seed_catalog(org_a)

    repository = PostgresKnowledgeModelRepository()
    await repository.ensure_tables()
    await KnowledgeModelMaterializer(repository, max_columns=100).materialize(org_a)

    assert await _count_objects(org_a) > 0
    assert await _count_objects(org_b) == 0
    stats_b = await repository.stats(org_b)
    assert stats_b["objects"]["total"] == 0
    assert stats_b["sources"]["total"] == 0


async def test_overview_error_is_not_zero(async_client) -> None:
    """Un fallo del backend debe ser 503 tipado, nunca counts=0."""
    from src.api.deps import get_knowledge_model_service
    from src.api.main import app

    class _BrokenService:
        async def overview(self, organization_id):
            raise KnowledgeModelUnavailable("db down")

    app.dependency_overrides[get_knowledge_model_service] = lambda: _BrokenService()
    try:
        auth = await _trial_auth(async_client)
        response = await async_client.get("/api/v1/knowledge/overview", headers=auth)
        assert response.status_code == 503
        body = response.json()
        detail = body.get("detail", body)
        assert detail["error_code"] == "knowledge_model_unavailable"
        assert "NO significa que no exista" in detail["message"]
    finally:
        app.dependency_overrides.pop(get_knowledge_model_service, None)


async def test_api_materialize_explore_and_verify(async_client) -> None:
    auth = await _trial_auth(async_client)
    org = UUID(auth["X-Organization-Id"])
    await _seed_catalog(org)

    # El Command Center materializa el modelo on-demand la primera vez.
    overview = await async_client.get("/api/v1/knowledge/overview", headers=auth)
    assert overview.status_code == 200, overview.text
    payload = overview.json()
    assert payload["state"] in ("partial", "ready")
    assert payload["counts"]["objects"] > 0
    assert payload["health"]["overall"] is not None
    measured = [d for d in payload["health"]["dimensions"] if d["measured"]]
    assert measured, "debe haber dimensiones medidas"
    unmeasured = [d for d in payload["health"]["dimensions"] if not d["measured"]]
    assert all(d["score"] is None for d in unmeasured)

    objects = await async_client.get(
        "/api/v1/knowledge/objects?type=entity", headers=auth
    )
    assert objects.status_code == 200
    items = objects.json()["items"]
    assert len(items) == 2
    customer = next(i for i in items if i["name"] == "Customer")

    detail = await async_client.get(
        f"/api/v1/knowledge/objects/{customer['id']}", headers=auth
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["object"]["name"] == "Customer"
    assert body["evidence"], "el detalle debe exponer evidencia"
    assert body["edges"], "el detalle debe exponer relaciones"
    assert body["impact"]["count"] >= 1

    search = await async_client.get(
        "/api/v1/knowledge/search?q=Customer", headers=auth
    )
    assert search.status_code == 200
    assert search.json()["items"], "la búsqueda global debe encontrar el objeto"

    quality = await async_client.get("/api/v1/knowledge/quality", headers=auth)
    assert quality.status_code == 200
    assert "issues" in quality.json()

    graph = await async_client.get("/api/v1/knowledge/graph", headers=auth)
    assert graph.status_code == 200
    assert graph.json()["nodes"], "el grafo se deriva del modelo, no de un dataset paralelo"


async def test_overview_reports_indexed_documents_without_model(async_client) -> None:
    """Archivos indexados sin objetos: el estado sigue vacío, pero con conteos reales."""
    auth = await _trial_auth(async_client)
    org = UUID(auth["X-Organization-Id"])
    source_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO kb_sources (id, organization_id, name, type, status)
                VALUES (:sid, :org, 'Tbl978_dapp_C.pdf', 'file', 'indexed')
                """
            ),
            {"sid": source_id, "org": org},
        )
        await session.execute(
            text(
                """
                INSERT INTO source_documents (
                    organization_id, source_id, external_id, document_id, content_hash
                ) VALUES (:org, :sid, 'doc-1', :doc, 'hash-1')
                """
            ),
            {"org": org, "sid": source_id, "doc": uuid4()},
        )
        await session.commit()
    finally:
        await session.close()

    overview = await async_client.get("/api/v1/knowledge/overview", headers=auth)
    assert overview.status_code == 200, overview.text
    payload = overview.json()
    assert payload["state"] == "empty"
    assert payload["counts"]["objects"] == 0
    assert payload["counts"]["indexed_sources"] == 1
    assert payload["counts"]["indexed_documents"] == 1
    assert "todavía no tiene modelo de negocio" in payload["headline"]


async def test_rebuild_and_verify_require_privileged_permission(async_client) -> None:
    """Gobernanza: un API token estándar no reconstruye ni verifica conocimiento."""
    auth = await _trial_auth(async_client)
    rebuild = await async_client.post(
        "/api/v1/knowledge/model/rebuild", json={}, headers=auth
    )
    assert rebuild.status_code == 403
    verify = await async_client.post(
        f"/api/v1/knowledge/objects/{uuid4()}/verify", headers=auth
    )
    assert verify.status_code == 403


async def test_start_learning_reconciles_orphan_run(async_client) -> None:
    """Un run activo sin etapas ni job vivo no bloquea el reintento."""
    from src.platform.knowledge_learning.repository import (
        PostgresKnowledgeLearningRepository,
    )

    auth = await _trial_auth(async_client)
    org = UUID(auth["X-Organization-Id"])
    ids = await _seed_catalog(org)

    repo = PostgresKnowledgeLearningRepository()
    await repo.ensure_tables()
    orphan = await repo.create_run(org, catalog_source_id=ids["source"])
    orphan_id = UUID(orphan["id"])
    assert await repo.count_steps(org, orphan_id) == 0
    assert await repo.has_live_job(org, orphan_id) is False

    response = await async_client.post(
        f"/api/v1/knowledge/sources/{ids['source']}/learn",
        json={},
        headers=auth,
    )
    assert response.status_code == 201, response.text

    reconciled = await repo.get_run(org, orphan_id)
    assert reconciled is not None
    assert reconciled["status"] == "failed"
    assert "orphan_run_reconciled" in str(reconciled["error_summary"])

    new_run_id = UUID(response.json()["run"]["id"])
    assert await repo.count_steps(org, new_run_id) > 0
    assert await repo.has_live_job(org, new_run_id) is True

    # Limpieza: el run nuevo queda cancelado para no dejar estado activo.
    from datetime import datetime, timezone

    await repo.update_run(
        org, new_run_id, status="cancelled", finished_at=datetime.now(timezone.utc)
    )


async def test_start_learning_does_not_use_kb_source_as_knowledge_base(async_client) -> None:
    """catalog_sources.kb_source_id es kb_sources, no knowledge_bases.

    Pasarlo como knowledge_base_id del job rompía el FK
    ingestion_jobs_knowledge_base_id_fkey (learning_start_failed).
    """
    from src.api.deps import get_job_repo

    auth = await _trial_auth(async_client)
    org = UUID(auth["X-Organization-Id"])
    ids = await _seed_catalog(org, kb_source_id=uuid4())

    response = await async_client.post(
        f"/api/v1/knowledge/sources/{ids['source']}/learn",
        json={},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    job_id = UUID(response.json()["job_id"])
    job = await get_job_repo().get_job(org, job_id)
    assert job is not None
    assert job.knowledge_base_id is None
    assert (job.cursor_snapshot or {}).get("kb_source_id")


async def test_file_virtual_source_is_not_learnable(async_client) -> None:
    """Un upload (connector postgres host file-virtual) no es una fuente SQL."""
    from src.platform.knowledge_learning.repository import (
        PostgresKnowledgeLearningRepository,
    )

    auth = await _trial_auth(async_client)
    org = UUID(auth["X-Organization-Id"])
    ids = await _seed_catalog(
        org,
        connector_config={"host": "file-virtual", "session_id": str(uuid4())},
    )

    response = await async_client.post(
        f"/api/v1/knowledge/sources/{ids['source']}/learn",
        json={},
        headers=auth,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    detail = body.get("detail", body)
    assert detail["error_code"] == "source_not_learnable"

    repo = PostgresKnowledgeLearningRepository()
    await repo.ensure_tables()
    assert await repo.list_runs(org, catalog_source_id=ids["source"]) == []


async def test_cross_tenant_object_is_404(async_client) -> None:
    auth_a = await _trial_auth(async_client)
    auth_b = await _trial_auth(async_client)
    org_a = UUID(auth_a["X-Organization-Id"])
    await _seed_catalog(org_a)
    overview = await async_client.get("/api/v1/knowledge/overview", headers=auth_a)
    assert overview.status_code == 200, overview.text
    objects = await async_client.get(
        "/api/v1/knowledge/objects?type=entity", headers=auth_a
    )
    object_id = objects.json()["items"][0]["id"]

    cross = await async_client.get(
        f"/api/v1/knowledge/objects/{object_id}", headers=auth_b
    )
    assert cross.status_code == 404

    overview_b = await async_client.get("/api/v1/knowledge/overview", headers=auth_b)
    assert overview_b.status_code == 200
    assert overview_b.json()["counts"]["objects"] == 0
    assert overview_b.json()["state"] == "empty"


async def _trial_auth(client) -> dict[str, str]:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Knowledge Co {uuid4().hex[:8]}",
            "email": f"knowledge-{uuid4().hex[:8]}@example.com",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {
        "Authorization": f"Bearer {data['api_token']}",
        "X-Organization-Id": data["organization_id"],
    }
