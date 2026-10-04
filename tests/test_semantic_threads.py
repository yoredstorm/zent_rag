# =============================================================================
# SemanticThreads — continuidad bidireccional (Fase 4)
# =============================================================================
# Reglas que se prueban:
#   - una referencia temprana abre thread OPEN y una ventana posterior la
#     RESUELVE (resolved_at_window + resolved_by_unit);
#   - una continuación se resuelve cuando la misma sección sigue;
#   - un símbolo huérfano se resuelve con su definición posterior;
#   - dos candidatos => AMBIGUOUS con candidates auditables;
#   - el tope de threads abiertos degrada los más viejos a UNRESOLVED;
#   - checkpoint: reprocesar una ventana no duplica threads ni deja estados
#     inconsistentes (rollback + re-resolución);
#   - el store Postgres guarda threads scoped por tenant.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.knowledge.semantic import (
    SemanticThread,
    SemanticWindowPlanner,
    SemanticWindowProcessor,
    SemanticWindowResult,
    ThreadStatus,
    ThreadType,
    WindowItem,
    advance_threads,
    cap_open_threads,
    open_threads_from_result,
)
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding


def _understood(text: str):
    parsed = TextParser().parse(
        text.encode("utf-8"),
        organization_id=uuid4(),
        external_id="threads.md",
        source_id=uuid4(),
        source_name="threads.md",
    )
    return apply_understanding(parsed, filename="threads.md")


def _plan(document, *, max_tokens: int = 400, min_tokens: int = 100):
    return SemanticWindowPlanner().plan(
        document,
        profile="balanced",
        model="deepseek-chat",
        max_tokens=max_tokens,
        reserves=0,
        min_tokens=min_tokens,
        headroom_ratio=0.0,
    )


class FakeThreadStore:
    """Store en memoria con resultados, estados y threads."""

    def __init__(self) -> None:
        self.results: dict[tuple[str, int], dict] = {}
        self.states: dict[tuple[str, int], object] = {}
        self.threads: dict[tuple[str, str], SemanticThread] = {}

    async def get_window_result(self, organization_id, *, document_id, window_index):
        return self.results.get((str(document_id), int(window_index)))

    async def save_window_result(
        self, organization_id, *, workspace_id, source_id, document_id, result
    ):
        self.results[(str(document_id), int(result.window_index))] = {
            "window_index": int(result.window_index),
            "status": result.status,
            "fingerprint": result.fingerprint,
            "carry_fingerprint": result.carry_fingerprint,
            "item_count": len(result.items),
        }

    async def get_state(self, organization_id, *, document_id, window_index):
        return self.states.get((str(document_id), int(window_index)))

    async def save_state(
        self, organization_id, *, workspace_id, source_id, document_id, state
    ):
        self.states[(str(document_id), int(state.window_index))] = state

    async def update_window_status(
        self, organization_id, *, document_id, window_index, status
    ):
        return None

    async def list_threads(self, organization_id, *, document_id, **kwargs):
        return [
            thread
            for (doc, _key), thread in self.threads.items()
            if doc == str(document_id)
        ]

    async def save_threads(
        self, organization_id, *, workspace_id, source_id, document_id, threads
    ):
        for thread in threads:
            self.threads[(str(document_id), thread.thread_key)] = thread

    async def delete_window_artifacts(self, organization_id, *, document_id):
        prefix = str(document_id)
        self.results = {
            key: value for key, value in self.results.items() if key[0] != prefix
        }
        self.states = {
            key: value for key, value in self.states.items() if key[0] != prefix
        }
        self.threads = {
            key: value for key, value in self.threads.items() if key[0] != prefix
        }


# ---------------------------------------------------------------------------
# Apertura / resolución
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reference_thread_resolved_by_later_window() -> None:
    filler = " ".join(f"w{index}" for index in range(40))
    document = _understood(
        "# Manual\n\n"
        f"See note NX7 for the fare rules. {filler}\n\n"
        "# Appendix\n\n"
        "NX7 - Fare class note definition."
    )
    plan = _plan(document, max_tokens=40, min_tokens=10)
    store = FakeThreadStore()
    outcome = await SemanticWindowProcessor(store).process(document, plan)

    assert outcome.complete
    assert outcome.threads_opened >= 1
    assert outcome.threads_resolved >= 1
    threads = await store.list_threads(document.organization_id, document_id=document.id)
    reference = next(
        thread for thread in threads if thread.thread_type == ThreadType.REFERENCE.value
    )
    assert reference.status == ThreadStatus.RESOLVED.value
    assert reference.resolved_at_window is not None
    assert reference.resolved_by_unit
    assert reference.opened_at_window < reference.resolved_at_window
    assert reference.target_hint == "NX7"


@pytest.mark.asyncio
async def test_continuation_thread_resolves_when_section_continues() -> None:
    document = _understood(
        "# Manual\n\n"
        "Primera oracion del procedimiento operativo.\n\n"
        "Segunda oracion del procedimiento operativo.\n\n"
        "Tercera oracion del procedimiento operativo."
    )
    plan = _plan(document, max_tokens=14, min_tokens=5)
    assert plan.window_count >= 3
    store = FakeThreadStore()
    outcome = await SemanticWindowProcessor(store).process(document, plan)
    assert outcome.complete
    threads = await store.list_threads(document.organization_id, document_id=document.id)
    continuations = [
        thread
        for thread in threads
        if thread.thread_type == ThreadType.CONTINUATION.value
    ]
    assert continuations
    assert any(
        thread.status == ThreadStatus.RESOLVED.value for thread in continuations
    )


@pytest.mark.asyncio
async def test_symbol_thread_resolved_by_later_definition() -> None:
    document = _understood(
        "# Manual\n\nValidate &&&F before continuing.\n\n"
        "# Appendix\n\n&&&F - one alphanumeric character mask."
    )
    plan = _plan(document, max_tokens=8, min_tokens=5)
    store = FakeThreadStore()
    outcome = await SemanticWindowProcessor(store).process(document, plan)
    assert outcome.complete
    threads = await store.list_threads(document.organization_id, document_id=document.id)
    symbols = [
        thread for thread in threads if thread.thread_type == ThreadType.SYMBOL.value
    ]
    assert symbols
    assert any(thread.status == ThreadStatus.RESOLVED.value for thread in symbols)


def test_ambiguous_thread_keeps_candidates() -> None:
    document_id = uuid4()
    source_id = uuid4()
    reference_result = SemanticWindowResult(
        window_index=0,
        organization_id=uuid4(),
        source_id=source_id,
        document_id=document_id,
        items=(
            WindowItem(
                kind="unresolved_reference",
                key="reference:section:record",
                label="RECORD",
                text="See section RECORD",
                confidence=0.6,
                block_ids=(str(uuid4()),),
                attributes={"target_kind": "section"},
            ),
        ),
    )
    threads = {
        thread.thread_key: thread
        for thread in open_threads_from_result(reference_result)
    }
    definition_result = SemanticWindowResult(
        window_index=1,
        organization_id=reference_result.organization_id,
        source_id=source_id,
        document_id=document_id,
        items=(
            WindowItem(
                kind="definition",
                key="record-a",
                label="RECORD",
                text="definicion A",
                confidence=0.7,
                block_ids=(str(uuid4()),),
            ),
            WindowItem(
                kind="definition",
                key="record-b",
                label="RECORD",
                text="definicion B",
                confidence=0.72,
                block_ids=(str(uuid4()),),
            ),
        ),
    )
    updated, touched, stats = advance_threads(threads, definition_result)
    thread = next(iter(updated.values()))
    assert thread.status == ThreadStatus.AMBIGUOUS.value
    assert len(thread.candidates) == 2
    assert stats.ambiguous == 1


def test_cap_open_threads_demotes_oldest_to_unresolved() -> None:
    organization_id = uuid4()
    document_id = uuid4()
    threads: dict[str, SemanticThread] = {}
    for index in range(3):
        thread = SemanticThread(
            id=uuid4(),
            thread_key=f"reference:section:t{index}",
            thread_type=ThreadType.REFERENCE.value,
            status=ThreadStatus.OPEN.value,
            organization_id=organization_id,
            document_id=document_id,
            target_hint=f"T{index}",
            opened_at_window=index,
            last_seen_window=index,
        )
        threads[thread.thread_key] = thread
    updated, touched = cap_open_threads(threads, max_open=2)
    assert len(touched) == 1
    assert touched[0].thread_key == "reference:section:t0"
    assert updated["reference:section:t0"].status == ThreadStatus.UNRESOLVED.value


# ---------------------------------------------------------------------------
# Checkpoint + rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reprocessing_window_keeps_threads_consistent() -> None:
    filler = " ".join(f"w{index}" for index in range(40))
    document = _understood(
        "# Manual\n\n"
        f"See note NX7 for the fare rules. {filler}\n\n"
        "# Appendix\n\n"
        "NX7 - Fare class note definition."
    )
    plan = _plan(document, max_tokens=40, min_tokens=10)
    store = FakeThreadStore()
    processor = SemanticWindowProcessor(store)

    first = await processor.process(document, plan)
    assert first.complete
    resolved_before = [
        thread
        for thread in store.threads.values()
        if thread.status == ThreadStatus.RESOLVED.value
    ]
    assert resolved_before

    # Segunda corrida completa: SKIP, threads intactos.
    second = await processor.process(document, plan)
    assert second.processed == 0
    assert second.skipped == plan.window_count
    assert (
        len(
            [
                thread
                for thread in store.threads.values()
                if thread.status == ThreadStatus.RESOLVED.value
            ]
        )
        == len(resolved_before)
    )

    # Reprocesar SOLO la ventana que resolvía: rollback + re-resolución, sin duplicar.
    resolution_window = resolved_before[0].resolved_at_window
    store.results.pop((str(document.id), resolution_window))
    third = await processor.process(document, plan)
    assert third.processed == 1
    resolved_after = [
        thread
        for thread in store.threads.values()
        if thread.status == ThreadStatus.RESOLVED.value
    ]
    assert len(resolved_after) == len(resolved_before)
    assert all(
        thread.resolved_at_window is not None for thread in resolved_after
    )


# ---------------------------------------------------------------------------
# Store Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_threads_roundtrip() -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.knowledge.semantic import PostgresSemanticIngestionStore

    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"ST Org {uuid4().hex[:6]}"
    )
    store = PostgresSemanticIngestionStore()
    document_id = uuid4()
    thread = SemanticThread(
        id=UUID(int=0),
        thread_key="reference:note:nx7",
        thread_type=ThreadType.REFERENCE.value,
        status=ThreadStatus.RESOLVED.value,
        organization_id=organization.id,
        document_id=document_id,
        target_hint="NX7",
        target_kind="note",
        source_units=(str(uuid4()),),
        source_windows=(1, 2),
        opened_at_window=1,
        last_seen_window=2,
        resolved_at_window=2,
        resolved_by_unit=str(uuid4()),
        confidence=0.82,
        candidates=({"kind": "definition", "label": "NX7"},),
        history=({"window": 1, "status": "OPEN", "reason": "opened"},),
    )
    await store.save_threads(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        threads=[thread],
    )
    loaded = await store.list_threads(organization.id, document_id=document_id)
    assert len(loaded) == 1
    assert loaded[0].status == ThreadStatus.RESOLVED.value
    assert loaded[0].source_windows == (1, 2)
    assert loaded[0].candidates[0]["label"] == "NX7"

    only_resolved = await store.list_threads(
        organization.id,
        document_id=document_id,
        status=ThreadStatus.RESOLVED.value,
    )
    assert len(only_resolved) == 1
    only_open = await store.list_threads(
        organization.id,
        document_id=document_id,
        status=ThreadStatus.OPEN.value,
    )
    assert only_open == []

    await store.delete_window_artifacts(organization.id, document_id=document_id)
    assert await store.list_threads(organization.id, document_id=document_id) == []
