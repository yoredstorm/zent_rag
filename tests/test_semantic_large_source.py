# =============================================================================
# Large source — 100% procesado sin depender de una sola llamada LLM (Fase 22)
# =============================================================================
# Reglas que se prueban:
#   - una fuente mayor que una ventana se procesa completa en N ventanas;
#   - ninguna ventana queda sin resultado;
#   - el procesamiento determinista no hace llamadas LLM.
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


def _large_document(count: int = 300):
    lines = ["# Manual"]
    for index in range(count):
        lines.append("")
        lines.append(f"Parrafo {index} con contenido operativo del manual extenso.")
    text = "\n".join(lines)
    parsed = TextParser().parse(
        text.encode("utf-8"),
        organization_id=uuid4(),
        external_id="large.md",
        source_id=uuid4(),
        source_name="large.md",
    )
    return apply_understanding(parsed, filename="large.md")


class FakeStore:
    def __init__(self) -> None:
        self.results: dict[tuple[str, int], dict] = {}
        self.states: dict[tuple[str, int], object] = {}

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
        return []

    async def save_threads(self, organization_id, **kwargs):
        return None


@pytest.mark.asyncio
async def test_large_source_is_fully_processed_without_llm() -> None:
    document = _large_document(300)
    plan = SemanticWindowPlanner().plan(
        document,
        profile="balanced",
        model="deepseek-chat",
        max_tokens=120,
        reserves=0,
        min_tokens=10,
        headroom_ratio=0.0,
    )
    assert plan.window_count >= 20, "la fuente debe superar una sola ventana"

    store = FakeStore()
    processor = SemanticWindowProcessor(store)  # sin provider LLM
    outcome = await processor.process(document, plan)

    assert outcome.complete
    assert outcome.processed == plan.window_count
    assert outcome.failed == 0
    assert outcome.llm_calls == 0

    results = await store.list_window_results(
        document.organization_id, document_id=document.id
    )
    assert len(results) == plan.window_count
    assert all(row["status"] in ("complete", "partial") for row in results)

    # Cobertura de la fuente: las ventanas son contiguas y cubren todo.
    position = 0
    for window in plan.windows:
        assert window.unit_start == position
        position = window.unit_end + 1
    assert position == plan.total_units
