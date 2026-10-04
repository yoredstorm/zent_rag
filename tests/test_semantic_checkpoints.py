# =============================================================================
# Checkpoints + resume + incremental update (Fases 2, 23, 28)
# =============================================================================
# Reglas que se prueban:
#   - una ventana que falla no invalida la fuente (failure isolation);
#   - el retry reanuda SOLO la ventana fallida (no vuelve a la 1);
#   - modificar una región re-procesa solo las ventanas afectadas;
#   - los fingerprints de las ventanas no afectadas no cambian.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.knowledge.semantic import (
    SemanticWindowPlanner,
    SemanticWindowProcessor,
)
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding


def _document(text: str, *, organization_id=None, source_id=None):
    parsed = TextParser().parse(
        text.encode("utf-8"),
        organization_id=organization_id or uuid4(),
        external_id="checkpoints.md",
        source_id=source_id or uuid4(),
        source_name="checkpoints.md",
    )
    return apply_understanding(parsed, filename="checkpoints.md")


def _paragraphs_document(count: int, *, mutate: int | None = None):
    lines = ["# Manual"]
    for index in range(count):
        text = f"Parrafo {index} con contenido operativo del manual."
        if mutate is not None and index == mutate:
            text = "Parrafo modificado con contenido distinto del manual."
        lines.append("")
        lines.append(text)
    return "\n".join(lines)


def _plan(document, *, max_tokens: int = 40, min_tokens: int = 5):
    return SemanticWindowPlanner().plan(
        document,
        profile="balanced",
        model="deepseek-chat",
        max_tokens=max_tokens,
        reserves=0,
        min_tokens=min_tokens,
        headroom_ratio=0.0,
    )


class FakeStore:
    def __init__(self) -> None:
        self.results: dict[tuple[str, int], dict] = {}
        self.states: dict[tuple[str, int], object] = {}
        self.threads: dict[tuple[str, str], object] = {}

    async def get_window_result(self, organization_id, *, document_id, window_index):
        return self.results.get((str(document_id), int(window_index)))

    async def list_window_results(
        self, organization_id, *, document_id, include_items=False, limit=2000
    ):
        return [
            dict(payload)
            for (doc, _index), payload in sorted(self.results.items())
            if doc == str(document_id)
        ][:limit]

    async def save_window_result(
        self, organization_id, *, workspace_id, source_id, document_id, result
    ):
        self.results[(str(document_id), int(result.window_index))] = {
            "window_index": int(result.window_index),
            "status": result.status,
            "fingerprint": result.fingerprint,
            "carry_fingerprint": result.carry_fingerprint,
            "item_count": len(result.items),
            "items": [item.to_dict() for item in result.items],
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


@pytest.mark.asyncio
async def test_failure_at_window_10_resumes_at_window_10() -> None:
    document = _document(_paragraphs_document(24))
    plan = _plan(document, max_tokens=14)
    assert plan.window_count > 11, "se necesitan al menos 12 ventanas"

    store = FakeStore()
    processor = SemanticWindowProcessor(store)
    original = processor._process_window
    flaky = {"active": True}

    async def _flaky(document_arg, spec, **kwargs):
        if spec.window_index == 10 and flaky["active"]:
            raise RuntimeError("provider timeout")
        return await original(document_arg, spec, **kwargs)

    processor._process_window = _flaky  # type: ignore[method-assign]

    first = await processor.process(document, plan)
    assert first.failed == 1
    assert first.processed == plan.window_count - 1
    assert first.complete is False
    results = await store.list_window_results(
        document.organization_id, document_id=document.id
    )
    failed = [row for row in results if row["window_index"] == 10]
    assert failed and failed[0]["status"] == "failed"

    # Retry: reanuda la ventana 10 y, como mucho, la siguiente (su
    # carry-forward cambia); las demás quedan SKIP.
    flaky["active"] = False
    second = await processor.process(document, plan)
    assert 1 <= second.processed <= 2
    assert second.skipped == plan.window_count - second.processed
    assert second.failed == 0
    results_after = await store.list_window_results(
        document.organization_id, document_id=document.id
    )
    window_10 = next(row for row in results_after if row["window_index"] == 10)
    assert window_10["status"] in ("complete", "partial")


@pytest.mark.asyncio
async def test_incremental_update_reprocesses_only_affected_windows() -> None:
    organization_id = uuid4()
    source_id = uuid4()
    base_text = _paragraphs_document(20)
    document_a = _document(
        base_text, organization_id=organization_id, source_id=source_id
    )
    document_b = _document(
        _paragraphs_document(20, mutate=12),
        organization_id=organization_id,
        source_id=source_id,
    )
    # Mismo documento lógico (mismo org/source/external): id determinista.
    assert document_a.id == document_b.id

    plan_a = _plan(document_a, max_tokens=14)
    plan_b = _plan(document_b, max_tokens=14)
    assert plan_a.window_count == plan_b.window_count

    store = FakeStore()
    processor = SemanticWindowProcessor(store)
    first = await processor.process(document_a, plan_a)
    assert first.processed == plan_a.window_count
    fingerprints_before = {
        key[1]: value["fingerprint"]
        for key, value in store.results.items()
        if key[0] == str(document_a.id)
    }

    second = await processor.process(document_b, plan_b)
    # Solo las ventanas afectadas se reprocesan: la que contiene el párrafo
    # modificado y la cadena de carry-forward que cambia (acotada).
    assert 1 <= second.processed <= 4
    assert second.skipped == plan_b.window_count - second.processed
    assert second.processed < plan_b.window_count
    fingerprints_after = {
        key[1]: value["fingerprint"]
        for key, value in store.results.items()
        if key[0] == str(document_b.id)
    }
    changed = [
        index
        for index, fingerprint in fingerprints_before.items()
        if fingerprints_after.get(index) != fingerprint
    ]
    # Solo UNA ventana cambió de contenido; las reprocesadas extra lo fueron
    # por carry-forward (su fingerprint de contenido no cambió).
    assert len(changed) == 1
    assert second.processed <= 4
    assert len(changed) < plan_b.window_count
