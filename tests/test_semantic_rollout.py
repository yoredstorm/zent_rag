# =============================================================================
# Rollout shadow/canary + observabilidad (Fase 17)
# =============================================================================
# Reglas que se prueban:
#   - off nunca procesa; shadow/active siempre; canary por porcentaje;
#   - la selección canary es determinista por org+source+external_id y
#     aproximadamente del tamaño configurado;
#   - las métricas de ventanas/threads/nodos del fabric se emiten sin frenar.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.knowledge.semantic import SemanticIngestionService
from src.knowledge.semantic.processor import WindowProcessingOutcome
from src.knowledge.semantic.service import _observe_fabric, _observe_semantics
from src.knowledge.semantic.threads import ThreadStats


class _NullStore:
    async def get_manifest(self, *args, **kwargs):
        return None

    async def upsert_manifest(self, *args, **kwargs):
        return None


def _service(mode: str) -> SemanticIngestionService:
    return SemanticIngestionService(_NullStore(), mode=mode)


def test_should_process_modes() -> None:
    org = uuid4()
    source = uuid4()
    assert (
        _service("off").should_process(
            organization_id=org, source_id=source, external_id="a"
        )
        is False
    )
    for mode in ("shadow", "active"):
        assert (
            _service(mode).should_process(
                organization_id=org, source_id=source, external_id="a"
            )
            is True
        )


def test_canary_selection_is_deterministic_and_bounded(monkeypatch) -> None:
    from src.core.config import get_settings

    service = _service("canary")
    org = uuid4()

    monkeypatch.setattr(
        get_settings(),
        "KNOWLEDGE_SEMANTIC_INGESTION_CANARY_PERCENTAGE",
        0,
        raising=False,
    )
    assert (
        service.should_process(
            organization_id=org, source_id=uuid4(), external_id="a"
        )
        is False
    )

    monkeypatch.setattr(
        get_settings(),
        "KNOWLEDGE_SEMANTIC_INGESTION_CANARY_PERCENTAGE",
        100,
        raising=False,
    )
    assert (
        service.should_process(
            organization_id=org, source_id=uuid4(), external_id="a"
        )
        is True
    )

    monkeypatch.setattr(
        get_settings(),
        "KNOWLEDGE_SEMANTIC_INGESTION_CANARY_PERCENTAGE",
        50,
        raising=False,
    )
    source = uuid4()
    first = service.should_process(
        organization_id=org, source_id=source, external_id="doc.md"
    )
    second = service.should_process(
        organization_id=org, source_id=source, external_id="doc.md"
    )
    assert first == second  # determinista

    selected = sum(
        1
        for index in range(200)
        if service.should_process(
            organization_id=org, source_id=uuid4(), external_id=f"doc-{index}.md"
        )
    )
    assert 60 <= selected <= 140  # ~50% con hash estable


def test_metrics_are_emitted_best_effort() -> None:
    from src.infrastructure.observability.metrics import (
        knowledge_semantic_fabric_nodes_total,
        knowledge_semantic_threads_total,
        knowledge_semantic_windows_total,
    )

    org = uuid4()
    outcome = WindowProcessingOutcome(
        windows_total=2,
        processed=2,
        threads_opened=1,
        threads_resolved=1,
    )
    before = knowledge_semantic_windows_total.labels(
        organization_id=str(org), status="processed"
    )._value.get()
    _observe_semantics(organization_id=org, outcome=outcome)
    after = knowledge_semantic_windows_total.labels(
        organization_id=str(org), status="processed"
    )._value.get()
    assert after == before + 2
    threads_before = knowledge_semantic_threads_total.labels(
        organization_id=str(org), status="opened"
    )._value.get()
    assert threads_before >= 1

    class _Node:
        def __init__(self, node_type: str) -> None:
            self.node_type = node_type

    class _Projection:
        nodes = (_Node("Rule"), _Node("Rule"), _Node("Symbol"))

    fabric_before = knowledge_semantic_fabric_nodes_total.labels(
        organization_id=str(org), node_type="Rule"
    )._value.get()
    _observe_fabric(organization_id=org, projection=_Projection())
    fabric_after = knowledge_semantic_fabric_nodes_total.labels(
        organization_id=str(org), node_type="Rule"
    )._value.get()
    assert fabric_after == fabric_before + 2
    assert ThreadStats(opened=1).to_dict()["opened"] == 1
