# =============================================================================
# Knowledge Sessions — aprendizaje observable, no animación decorativa
# =============================================================================
# Lo que se verifica:
#   1. Los eventos de alta frecuencia se AGREGAN (jamás 5.000 updates/s).
#   2. Los textos son humanos: el evento crudo nunca llega a la UI.
#   3. Los contadores del Knowledge Pulse salen de eventos reales.
#   4. El delta de conocimiento se deriva de estadísticas persistidas.
#   5. Los errores se traducen a frases accionables (con detalle técnico).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.core.domain.knowledge_session import (
    KnowledgeDelta,
    SessionEventType,
)
from src.platform.knowledge_sessions.emitter import LearningSessionObserver
from src.platform.knowledge_sessions.semantics import (
    describe,
    humanize_error,
    severity_for,
)
from src.platform.knowledge_sessions.service import (
    LearningSessionService,
    group_discoveries,
)

ORG = UUID("11111111-2222-3333-4444-555555555555")
SESSION = UUID("22222222-3333-4444-5555-666666666666")
SOURCE_ROW = UUID("33333333-4444-5555-6666-777777777777")
SOURCE = UUID("44444444-5555-6666-7777-888888888888")


class FakeSessionRepo:
    """Store en memoria con el mismo contrato que el Postgres."""

    def __init__(self) -> None:
        self.batches: list[list[dict]] = []
        self.source_touches: list[dict] = []
        self.rollups = 0

    async def append_events(self, organization_id, *, events):
        stored = []
        for index, item in enumerate(events):
            payload = dict(item.get("payload") or {})
            stored.append(
                {
                    "seq": len(self.batches) * 100 + index + 1,
                    "id": str(index),
                    "organization_id": str(organization_id),
                    "session_id": str(item.get("session_id")),
                    "source_id": str(item["source_id"]) if item.get("source_id") else None,
                    "event_type": item.get("event_type"),
                    "stage": item.get("stage"),
                    "severity": item.get("severity") or "info",
                    "message": item.get("message") or "",
                    "payload": payload,
                    "aggregate": bool(item.get("aggregate")),
                    "created_at": "2026-10-01T00:00:00+00:00",
                }
            )
        self.batches.append(stored)
        return stored

    async def update_source(self, source_row_id, **fields):
        self.source_touches.append({"id": str(source_row_id), **fields})

    async def refresh_session_rollup(self, organization_id, session_id):
        self.rollups += 1

    async def list_events(self, organization_id, session_id, *, since_seq=0, limit=400, **kwargs):
        flat = [event for batch in self.batches for event in batch]
        return [event for event in flat if event["seq"] > since_seq][:limit]


@pytest.fixture()
def observer() -> LearningSessionObserver:
    return LearningSessionObserver(
        FakeSessionRepo(),
        session_id=SESSION,
        organization_id=ORG,
        source_row_id=SOURCE_ROW,
        source_id=SOURCE,
        name="Rec4_dapp_C.pdf",
        source_type="file",
    )


@pytest.mark.asyncio
async def test_repositorio_de_sesiones_persiste_eventos_y_metricas() -> None:
    """Integración real con Postgres: sesión -> fuente -> eventos -> rollup."""
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
    from src.platform.knowledge_sessions.repository import (
        PostgresKnowledgeSessionRepository,
    )

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Sessions {uuid4().hex[:6]}"
    )
    repo = PostgresKnowledgeSessionRepository()
    await repo.ensure_tables()
    service = LearningSessionService(repo)

    session = await service.start_session(
        org.id, title="Aprendiendo 2 fuentes", origin="test"
    )
    row = await service.attach_source(
        session,
        source_id=uuid4(),
        job_id=uuid4(),
        name="Rec4_dapp_C.pdf",
        source_type="file",
    )
    await repo.append_events(
        org.id,
        events=[
            {
                "session_id": session.id,
                "source_id": row.source_id,
                "event_type": "ENTITY_DISCOVERED",
                "stage": "connecting",
                "severity": "info",
                "message": "ZENT reconoció 3 entidades nuevas",
                "payload": {"count": 3},
                "aggregate": True,
            },
            {
                "session_id": session.id,
                "source_id": row.source_id,
                "event_type": "FACT_REINFORCED",
                "stage": "verifying",
                "severity": "info",
                "message": "ZENT reforzó un hecho",
                "payload": {"count": 1},
                "aggregate": False,
            },
        ],
    )
    events = await repo.list_events(org.id, session.id)
    assert [event["event_type"] for event in events] == [
        "SESSION_STARTED",
        "ENTITY_DISCOVERED",
        "FACT_REINFORCED",
    ]
    assert events[1]["payload"]["count"] == 3
    assert events[1]["seq"] < events[2]["seq"]

    await repo.update_source(
        row.id,
        status="completed",
        stage="learned",
        stats={"entities_new": 3, "entities_enriched": 2, "facts_new": 1},
    )
    await repo.refresh_session_rollup(org.id, session.id)
    pending = await service.get_session_detail(org.id, session.id)
    assert pending is not None
    # Sin sellar, la sesión es consultable pero no declara el aprendizaje cerrado.
    assert pending["status"] == "available"

    await repo.seal_session(org.id, session.id)
    await repo.refresh_session_rollup(org.id, session.id)
    detail = await service.get_session_detail(org.id, session.id)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["sources"][0]["name"] == "Rec4_dapp_C.pdf"
    assert detail["metrics"]["entities"] == 5
    assert detail["knowledge_delta"]["new_entities"] == 3
    assert detail["delta_totals"]["entities"] == 0

    # El engine encuentra la sesión y su fuente por job_id (sin carrera).
    found = await repo.find_session_for_job(org.id, row.job_id)
    assert found is not None and found.id == session.id
    by_job = await repo.get_source_by_job(org.id, row.job_id)
    assert by_job is not None and by_job.name == "Rec4_dapp_C.pdf"

    # El replay durable alimenta el SSE sin duplicar.
    tail = await repo.list_events(org.id, session.id, since_seq=events[1]["seq"])
    assert [event["event_type"] for event in tail] == ["FACT_REINFORCED"]


@pytest.mark.asyncio
async def test_eventos_frecuentes_se_agregan_en_una_ventana(observer) -> None:
    for index in range(50):
        await observer.event(
            SessionEventType.ENTITY_DISCOVERED.value,
            payload={"name": f"Entidad {index}", "entity_type": "concept"},
        )
    await observer.close()

    batches = observer._repo.batches
    assert batches, "no se persistió ningún lote"
    flat = [event for batch in batches for event in batch]
    entity_events = [
        event for event in flat if event["event_type"] == "ENTITY_DISCOVERED"
    ]
    assert len(entity_events) == 1, "50 eventos deben colapsar en una ventana"
    aggregated = entity_events[0]
    assert aggregated["aggregate"] is True
    assert aggregated["payload"]["count"] == 50
    # Muestras acotadas: la UI nunca recibe 50 payloads.
    assert len(aggregated["payload"]["items"]) <= 4
    # El texto es humano y dice cuántas entidades reales se reconocieron.
    assert "50" in aggregated["message"]
    assert "entidades" in aggregated["message"]


@pytest.mark.asyncio
async def test_evento_significativo_vacia_pendientes_y_se_escribe_ya(observer) -> None:
    for index in range(5):
        await observer.event(
            SessionEventType.FACT_DISCOVERED.value,
            payload={"subject": f"S{index}", "predicate": "defined_as"},
        )
    await observer.event(
        SessionEventType.CONFLICT_DETECTED.value,
        payload={"subject": "Record 4", "conflict_type": "VERSION_CHANGE"},
    )
    await observer.close()

    flat = [event for batch in observer._repo.batches for event in batch]
    fact_events = [event for event in flat if event["event_type"] == "FACT_DISCOVERED"]
    conflict_events = [
        event for event in flat if event["event_type"] == "CONFLICT_DETECTED"
    ]
    assert sum(event["payload"]["count"] for event in fact_events) == 5
    assert len(conflict_events) == 1
    assert fact_events[0]["seq"] < conflict_events[0]["seq"]


@pytest.mark.asyncio
async def test_pulse_cuenta_solo_eventos_reales(observer) -> None:
    await observer.event(
        SessionEventType.ENTITY_DISCOVERED.value, payload={"name": "A"}, count=3
    )
    await observer.event(
        SessionEventType.ENTITY_MATCHED.value, payload={"name": "B"}, count=2
    )
    await observer.event(
        SessionEventType.FACT_DISCOVERED.value, payload={"subject": "A"}, count=7
    )
    await observer.event(
        SessionEventType.FACT_REINFORCED.value, payload={"subject": "A"}, count=1
    )
    await observer.event(
        SessionEventType.EVIDENCE_LINKED.value, payload={}, count=12
    )
    await observer.close()

    snapshot = observer.metrics_snapshot()
    assert snapshot["entities_new"] == 3
    assert snapshot["entities_enriched"] == 2
    assert snapshot["entities"] == 5  # alias compuesto del Pulse
    assert snapshot["facts_new"] == 7
    assert snapshot["facts_reinforced"] == 1
    assert snapshot["facts"] == 8
    assert snapshot["evidence"] == 12


@pytest.mark.asyncio
async def test_eventos_crudos_se_conservan_para_inspeccion(observer) -> None:
    await observer.event(SessionEventType.ENTITY_DISCOVERED.value, payload={"name": "A"})
    await observer.event(SessionEventType.RULE_DISCOVERED.value, payload={"subject": "R"})
    await observer.close()
    snapshot = observer.technical_snapshot()
    assert len(snapshot["raw_events"]) == 2
    assert snapshot["raw_events"][0]["event_type"] == "ENTITY_DISCOVERED"


def test_descripcion_humana_no_expone_el_evento_crudo() -> None:
    message = describe("ENTITY_MATCHED", {"name": "Record 4"})
    assert "Record 4" in message
    assert "ya conocía" in message
    assert "ENTITY_MATCHED" not in message
    assert severity_for("CONFLICT_DETECTED") == "warning"
    assert severity_for("SOURCE_FAILED") == "error"
    assert severity_for("ENTITY_DISCOVERED") == "info"


@pytest.mark.asyncio
async def test_stream_replay_durable_antes_de_suscribirse(observer) -> None:
    """El SSE entrega primero lo ya ocurrido; un cliente tarde no pierde nada."""
    await observer.event(
        SessionEventType.ENTITY_DISCOVERED.value,
        payload={"name": "Record 4", "count": 2},
    )
    await observer.close()

    from src.platform.knowledge_sessions.emitter import (
        learning_session_event_source,
    )

    stream = learning_session_event_source(ORG, SESSION, repository=observer._repo)
    frames: list[str] = []
    async for frame in stream:
        frames.append(frame)
        break
    await stream.aclose()

    assert len(frames) == 1
    assert "event: ENTITY_DISCOVERED" in frames[0]
    assert '"count": 2' in frames[0]
    assert '"session_id"' in frames[0]


def test_errores_traducidos_a_lenguaje_humano() -> None:
    assert "tabla" in humanize_error("xlsx parse error: sheet 3 malformed")
    assert "conectarse" in humanize_error(RuntimeError("connection refused to host"))
    assert "límite" in humanize_error("429 Too Many Requests")
    # El detalle técnico sigue disponible en el fallback.
    assert humanize_error("weird internal failure") != "weird internal failure"


def test_delta_solo_cuenta_lo_que_cambio() -> None:
    service = LearningSessionService(repository=FakeSessionRepo())
    sources = [
        SimpleNamespace(stats={"entities_new": 10, "entities_enriched": 4, "facts_new": 8}),
        SimpleNamespace(stats={"entities_new": 2, "facts_reinforced": 5, "relationships": 3}),
    ]
    delta = service._delta_from_sources(sources)
    assert delta.new_entities == 12
    assert delta.enriched_entities == 4
    assert delta.new_facts == 8
    assert delta.reinforced_facts == 5
    assert delta.new_relationships == 3
    assert delta.to_dict()["new_entities"] == 12


def test_delta_prioriza_delta_sobre_totales() -> None:
    delta = KnowledgeDelta(
        new_entities=412,
        totals_before={"entities": 18204, "facts": 139822},
        totals_after={"entities": 18616, "facts": 141664},
    )
    assert delta.delta_totals["entities"] == 412
    assert delta.delta_totals["facts"] == 1842


def test_feed_agrupa_descubrimientos_y_omite_ruido_de_pipeline() -> None:
    events = [
        {
            "event_type": "SOURCE_RECEIVED",
            "source_id": str(SOURCE),
            "stage": "reading",
            "payload": {"name": "Rec4.pdf"},
            "message": "ZENT recibió Rec4.pdf",
            "severity": "info",
            "seq": 1,
            "created_at": "2026-10-01T00:00:00+00:00",
        },
        {
            "event_type": "ENTITY_DISCOVERED",
            "source_id": str(SOURCE),
            "stage": "connecting",
            "payload": {"count": 20, "items": [{"name": "Record 4"}]},
            "message": "ZENT reconoció 20 entidades nuevas",
            "severity": "info",
            "seq": 2,
            "created_at": "2026-10-01T00:00:01+00:00",
        },
        {
            "event_type": "ENTITY_DISCOVERED",
            "source_id": str(SOURCE),
            "stage": "connecting",
            "payload": {"count": 4, "items": [{"name": "Category 31"}]},
            "message": "ZENT reconoció 4 entidades nuevas",
            "severity": "info",
            "seq": 3,
            "created_at": "2026-10-01T00:00:02+00:00",
        },
        {
            "event_type": "CONFLICT_DETECTED",
            "source_id": str(SOURCE),
            "stage": "verifying",
            "payload": {"subject": "Carrier Code", "count": 1},
            "message": "ZENT detectó una posible inconsistencia",
            "severity": "warning",
            "seq": 4,
            "created_at": "2026-10-01T00:00:03+00:00",
        },
    ]
    discoveries = group_discoveries(events)
    kinds = [item["event_type"] for item in discoveries]
    assert "SOURCE_RECEIVED" not in kinds
    entity_items = [
        item for item in discoveries if item["event_type"] == "ENTITY_DISCOVERED"
    ]
    assert len(entity_items) == 1, "eventos consecutivos del mismo tipo se agrupan"
    assert entity_items[0]["count"] == 24
    assert any(item["severity"] == "warning" for item in discoveries)
