# =============================================================================
# Retrieval Acceptance Gate — tests
# =============================================================================
# Reglas que se prueban:
#   - probes con evidencia esperada real (documento/sección/unidad)
#   - recall@k/MRR miden EVIDENCIA, no solo documento
#   - un tenant no puede validar evidencia de otro tenant
#   - modos observe/warn/quarantine y persistencia
#   - store Postgres: probes/evaluaciones scoped y re-ejecutables
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.knowledge.acceptance import (
    AcceptanceMode,
    PostgresAcceptanceStore,
    RetrievalProbe,
    evaluate_probes,
    generate_probes,
    run_acceptance_gate,
)
from src.knowledge.enrichment import enrich_document
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding

MANUAL = """# Category 31 - Voluntary Changes

Category 31 (CAT31) defines voluntary changes for exchange eligibility.

Field: Status Byte
Bytes: 105-105
Description: status of the voluntary change

Byte 105 indicates the status for voluntary changes.

Effective from 2024-01-01 to 2024-12-31.
"""


def _understood(text: str = MANUAL, external_id: str = "manual.md", organization_id=None):
    parser = TextParser()
    document = parser.parse(
        text.encode("utf-8"),
        organization_id=organization_id or uuid4(),
        external_id=external_id,
        source_id=uuid4(),
        source_name=external_id,
    )
    return apply_understanding(document, filename=external_id)


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts, model=None):
        self.calls += 1
        if isinstance(texts, str):
            return [0.1] * 8
        return [[0.1] * 8 for _ in texts]


class ScriptedStore:
    """Vector store que devuelve chunks en el orden de las queries."""

    def __init__(self, scripts: list[list]) -> None:
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    async def search(
        self,
        organization_id,
        query_embedding,
        top_k=5,
        filters=None,
        exclude_filters=None,
        score_threshold=0.1,
        role="admin",
        knowledge_base_id=None,
        user_id=None,
        groups=None,
        workspace_id=None,
        source_ids=None,
    ):
        self.calls.append(
            {
                "organization_id": organization_id,
                "role": role,
                "workspace_id": workspace_id,
                "filters": filters,
            }
        )
        chunks = self.scripts.pop(0) if self.scripts else []
        return SimpleNamespace(chunks=chunks[:top_k])


class SpyAcceptanceStore:
    def __init__(self) -> None:
        self.saved_probes = []
        self.saved_evaluations = []
        self.updated = 0

    async def save_probes(self, probes):
        self.saved_probes.extend(probes)
        return len(probes)

    async def save_evaluation(self, report):
        self.saved_evaluations.append(report)
        return "eval-1"

    async def update_probe_results(self, report):
        self.updated += 1


def _chunk(document_id, *, block_ids=(), section_id=None, chunk_id=None, score=0.9):
    return SimpleNamespace(
        document_id=UUID(int=0),
        score=score,
        metadata={
            "document_id": str(document_id),
            "block_ids": [str(value) for value in block_ids],
            "section_id": str(section_id) if section_id else None,
            "chunk_id": str(chunk_id) if chunk_id else None,
        },
    )


def _probe(document, *, query, query_type="exact_identifier", unit=None, section=None):
    return RetrievalProbe(
        probe_id=str(uuid4()),
        organization_id=document.organization_id,
        document_id=document.id,
        source_id=document.source_id,
        workspace_id=document.workspace_id,
        query=query,
        query_type=query_type,
        expected_document_id=str(document.id),
        expected_section_id=str(section) if section else None,
        expected_unit_id=str(unit) if unit else None,
    )


@pytest.mark.asyncio
async def test_generate_probes_from_enrichment() -> None:
    document = _understood()
    enrichment = enrich_document(document)
    probes = generate_probes(document, enrichment, max_probes=24)
    assert probes
    types = {probe.query_type for probe in probes}
    assert "exact_identifier" in types
    assert any("Byte 105" in probe.query for probe in probes)
    for probe in probes:
        assert probe.expected_document_id == str(document.id)
        assert probe.organization_id == document.organization_id
        assert probe.query.strip()
    # Sin enrichment no hay probes (no se inventan consultas).
    assert generate_probes(document, None) == ()


@pytest.mark.asyncio
async def test_recall_measures_evidence_not_only_document() -> None:
    document = _understood()
    unit = document.blocks[0].id
    probe_hit = _probe(document, query="Byte 105", unit=unit)
    probe_wrong_unit = _probe(document, query="Other byte", unit=uuid4())
    store = ScriptedStore(
        [
            [_chunk(document.id, block_ids=[unit])],
            [_chunk(document.id, block_ids=[uuid4()])],
        ]
    )
    report = await evaluate_probes(
        (probe_hit, probe_wrong_unit),
        embedder=FakeEmbedder(),
        vector_store=store,
        measure_lexical=False,
        min_recall_at_5=0.5,
    )
    assert report.probes_total == 2
    assert report.probes_passed == 1
    assert report.recall_at_1 == 0.5
    assert report.mrr == 0.5
    assert report.correct_document_rate == 1.0
    assert report.evidence_hit_rate == 0.5
    assert report.accepted is True
    # El probe con unidad equivocada conserva el rank de documento, no el de evidencia.
    wrong = next(outcome for outcome in report.outcomes if outcome.probe_id == probe_wrong_unit.probe_id)
    assert wrong.rank is None
    assert wrong.document_rank == 1
    assert wrong.hit_document is True
    assert wrong.hit_unit is False


def test_nutrition_score_temporal_dimension_not_applicable_is_none() -> None:
    from types import SimpleNamespace

    from src.knowledge.nutrition import compute_nutrition_score

    # Documento sin contenido temporal: la dimensión no aplica (None, no 0).
    document = _understood("# Manual\n\nRecord 4 defines the exchange rule.\n")
    enrichment = enrich_document(document)
    facts = [SimpleNamespace(valid_from=None, valid_to=None, evidence=[])]
    compiled = SimpleNamespace(
        facts=facts, entities=[], rules=[], relationships=[]
    )
    score = compute_nutrition_score(document, enrichment=enrichment, compiled=compiled)
    assert score.dimensions.temporal_quality is None
    # Con señales temporales en la fuente pero sin facts temporales: 0.0 medido.
    temporal_doc = _understood(
        "# Manual\n\nEffective from 2024-01-01 to 2024-12-31.\n"
    )
    temporal_enrichment = enrich_document(temporal_doc)
    assert temporal_enrichment.temporal_qualifiers
    score = compute_nutrition_score(
        temporal_doc, enrichment=temporal_enrichment, compiled=compiled
    )
    assert score.dimensions.temporal_quality == 0.0


def test_acceptance_probe_embedding_fanout_is_bounded() -> None:
    from src.knowledge.acceptance.evaluate import (
        PROBE_EMBED_BATCH_SIZE,
        PROBE_INDIVIDUAL_RETRY_BUDGET,
    )

    class DownProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def embed(self, texts, model=None):
            self.calls += 1
            raise TimeoutError("provider down")

    import asyncio

    document = _understood()
    unit = document.blocks[0].id
    probes = tuple(
        _probe(document, query=f"q{index}", unit=unit) for index in range(100)
    )
    provider = DownProvider()
    report = asyncio.run(
        evaluate_probes(
            probes,
            embedder=provider,
            vector_store=ScriptedStore([[] for _ in range(100)]),
            measure_lexical=False,
        )
    )
    assert report.probes_total == 100
    assert report.probes_passed == 0
    expected_batches = (100 + PROBE_EMBED_BATCH_SIZE - 1) // PROBE_EMBED_BATCH_SIZE
    # Batches + retries individuales acotados por presupuesto.
    assert provider.calls <= expected_batches + PROBE_INDIVIDUAL_RETRY_BUDGET
    assert provider.calls < 100 * 2


@pytest.mark.asyncio
async def test_gate_states_pass_degraded_fail() -> None:
    document = _understood()
    unit = document.blocks[0].id
    other_unit = uuid4()
    # PASS: evidencia encontrada y umbral cumplido.
    probes = tuple(
        _probe(document, query=f"query {index}", unit=unit) for index in range(3)
    )
    store = ScriptedStore(
        [[_chunk(document.id, block_ids=[unit])] for _ in range(3)]
    )
    report = await evaluate_probes(
        probes, embedder=FakeEmbedder(), vector_store=store, measure_lexical=False
    )
    assert report.gate_state == "PASS"
    # DEGRADED: hay evidencia parcial pero el umbral no se alcanza.
    store = ScriptedStore(
        [
            [_chunk(document.id, block_ids=[unit])],
            [],
            [],
        ]
    )
    report = await evaluate_probes(
        probes, embedder=FakeEmbedder(), vector_store=store, measure_lexical=False
    )
    assert report.probes_passed == 1
    assert report.gate_state == "DEGRADED"
    assert report.to_dict()["state"] == "DEGRADED"
    # FAIL: ninguna evidencia.
    store = ScriptedStore([[] for _ in range(3)])
    report = await evaluate_probes(
        probes, embedder=FakeEmbedder(), vector_store=store, measure_lexical=False
    )
    assert report.gate_state == "FAIL"


@pytest.mark.asyncio
async def test_multi_tenant_probe_never_validates_other_tenant_evidence() -> None:
    document = _understood()
    unit = document.blocks[0].id
    probe = _probe(document, query="Byte 105", unit=unit)
    other_tenant_document = uuid4()
    store = ScriptedStore([[_chunk(other_tenant_document, block_ids=[unit])]])
    report = await evaluate_probes(
        (probe,), embedder=FakeEmbedder(), vector_store=store, measure_lexical=False
    )
    assert report.probes_passed == 0
    assert report.outcomes[0].hit_document is False
    # El retrieval corrió scoped a la organización del probe.
    assert store.calls[0]["organization_id"] == document.organization_id
    assert store.calls[0]["filters"] == {"metadata.v2_doc": "true"}


class AllMatchingStore:
    """Vector store que devuelve un chunk que cubre TODA la evidencia del doc."""

    def __init__(self, document) -> None:
        self.document = document
        self.calls = 0

    async def search(
        self,
        organization_id,
        query_embedding,
        top_k=5,
        filters=None,
        **kwargs,
    ):
        self.calls += 1
        section = self.document.sections[0] if self.document.sections else None
        chunk = _chunk(
            self.document.id,
            block_ids=[block.id for block in self.document.blocks],
            section_id=section.id if section else None,
        )
        return SimpleNamespace(chunks=[chunk])


@pytest.mark.asyncio
async def test_acceptance_modes_observe_vs_warn() -> None:
    document = _understood()
    enrichment = enrich_document(document)
    # observe: no persiste
    spy = SpyAcceptanceStore()
    result = await run_acceptance_gate(
        document=document,
        enrichment=enrichment,
        embedder=FakeEmbedder(),
        vector_store=ScriptedStore([[] for _ in range(40)]),
        mode=AcceptanceMode.OBSERVE.value,
        store=spy,
    )
    assert result.ran
    assert result.persisted is False
    assert spy.saved_probes == []
    # warn: persiste probes + evaluación + resultados; evidencia cubierta.
    spy = SpyAcceptanceStore()
    result = await run_acceptance_gate(
        document=document,
        enrichment=enrichment,
        embedder=FakeEmbedder(),
        vector_store=AllMatchingStore(document),
        mode=AcceptanceMode.WARN.value,
        store=spy,
        min_recall_at_5=0.5,
    )
    assert result.persisted is True
    assert spy.saved_probes
    assert spy.saved_evaluations
    assert spy.updated == 1
    assert result.report.accepted is True
    assert result.report.recall_at_5 == 1.0


@pytest.mark.asyncio
async def test_quarantine_marks_document_when_below_threshold() -> None:
    document = _understood()
    enrichment = enrich_document(document)
    result = await run_acceptance_gate(
        document=document,
        enrichment=enrichment,
        embedder=FakeEmbedder(),
        vector_store=ScriptedStore([[] for _ in range(40)]),
        mode=AcceptanceMode.QUARANTINE.value,
        store=SpyAcceptanceStore(),
        min_recall_at_5=0.6,
    )
    assert result.ran
    assert result.report.accepted is False
    assert result.quarantined is True
    assert result.report.quality_status == "NOT_RETRIEVABLE"


@pytest.mark.asyncio
async def test_acceptance_store_roundtrip_is_scoped_and_reexecutable() -> None:
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Acceptance Org {uuid4().hex[:6]}"
    )
    document = _understood(organization_id=organization.id)
    enrichment = enrich_document(document)
    probes = generate_probes(document, enrichment, max_probes=6)
    store = PostgresAcceptanceStore()
    await store.save_probes(probes)

    # Otro tenant no ve los probes.
    foreign = await store.list_probes(uuid4(), document_id=document.id)
    assert foreign == []
    listed = await store.list_probes(document.organization_id, document_id=document.id)
    assert {row["probe_id"] for row in listed} >= {probe.probe_id for probe in probes}

    report = await evaluate_probes(
        probes[:2],
        embedder=FakeEmbedder(),
        vector_store=ScriptedStore([[] for _ in probes[:2]]),
        measure_lexical=False,
    )
    await store.save_evaluation(report)
    await store.update_probe_results(report)
    last = await store.last_evaluation(document.organization_id, document.id)
    assert last is not None
    assert last["probes_total"] == 2
    assert last["recall_at_5"] == 0.0
    assert last["accepted"] is False

    # Re-ejecución sin re-ingesta: los probes siguen ahí.
    again = await store.list_probes(document.organization_id, document_id=document.id)
    updated = [row for row in again if row["last_result"] is not None]
    assert updated
