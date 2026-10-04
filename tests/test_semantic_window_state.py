# =============================================================================
# Semantic Window — comprensión local + SemanticState (Fase 3)
# =============================================================================
# Reglas que se prueban:
#   - el extractor determinista produce items estructurados por kind (no un
#     resumen): definición, regla, excepción, símbolo, referencia sin resolver;
#   - la ventana abierta produce continuation candidate;
#   - una referencia temprana se RESUELVE cuando una ventana posterior define
#     el target (información posterior resuelve unknowns anteriores);
#   - el selector hace carry-forward SOLO de lo relevante;
#   - checkpoint por ventana: fingerprint igual = SKIP; una ventana stale se
#     reprocesa sin tocar las demás;
#   - el gate del LLM rechaza items sin quote literal;
#   - el store Postgres guarda resultados/estados scoped por tenant.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.knowledge.semantic import (
    LLMWindowProvider,
    SemanticState,
    SemanticStateSelector,
    SemanticWindowPlanner,
    SemanticWindowProcessor,
    SemanticWindowResult,
    WindowItem,
    extract_window_items,
    indexable_blocks,
)
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding


def _understood(text: str):
    parsed = TextParser().parse(
        text.encode("utf-8"),
        organization_id=uuid4(),
        external_id="doc.md",
        source_id=uuid4(),
        source_name="doc.md",
    )
    return apply_understanding(parsed, filename="doc.md")


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


class FakeWindowStore:
    def __init__(self) -> None:
        self.results: dict[tuple[str, int], dict] = {}
        self.states: dict[tuple[str, int], SemanticState] = {}

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

    async def delete_window_artifacts(self, organization_id, *, document_id):
        prefix = str(document_id)
        self.results = {
            key: value for key, value in self.results.items() if key[0] != prefix
        }
        self.states = {
            key: value for key, value in self.states.items() if key[0] != prefix
        }


# ---------------------------------------------------------------------------
# Extractor determinista
# ---------------------------------------------------------------------------


def test_extract_window_items_produces_structured_kinds() -> None:
    document = _understood(
        "# Manual\n\n"
        "FCLAS - Fare class field definition.\n\n"
        "The fare basis must match the mask &&&F.\n\n"
        "Exception: unless the validating carrier applies.\n\n"
        "See Appendix D for details."
    )
    blocks = indexable_blocks(document)
    items = extract_window_items(
        document=document, window_blocks=blocks, window_index=0
    )
    kinds = {item.kind for item in items}
    assert {"definition", "rule", "exception", "symbol"} <= kinds
    assert any(item.kind == "unresolved_reference" for item in items)
    assert any(item.kind == "topic" for item in items)
    definition = next(item for item in items if item.kind == "definition")
    assert definition.label == "FCLAS"
    assert definition.to_dict()["derived"] is True
    assert definition.to_dict()["canonical"] is False


def test_open_ending_produces_continuation_candidate() -> None:
    document = _understood(
        "The fare rules continue in the following section without closing"
    )
    blocks = indexable_blocks(document)
    items = extract_window_items(
        document=document, window_blocks=blocks, window_index=0
    )
    continuations = [item for item in items if item.kind == "continuation"]
    assert len(continuations) == 1
    assert continuations[0].attributes["target_hint"] == "next_window"


# ---------------------------------------------------------------------------
# SemanticState: resolución hacia atrás
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_later_window_resolves_early_reference() -> None:
    filler = " ".join(f"w{index}" for index in range(40))
    document = _understood(
        "# Manual\n\n"
        f"See note NX7 for the fare rules. {filler}\n\n"
        "# Appendix\n\n"
        "NX7 - Fare class note definition."
    )
    plan = _plan(document, max_tokens=40, min_tokens=10)
    assert plan.window_count >= 3

    processor = SemanticWindowProcessor(FakeWindowStore())
    outcome = await processor.process(document, plan)
    assert outcome.complete
    assert outcome.state is not None

    resolved = [entry["label"] for entry in outcome.state.resolved_references]
    unresolved = [entry["label"] for entry in outcome.state.unresolved_references]
    assert "NX7" in resolved
    assert "NX7" not in unresolved
    assert any(
        entry.get("resolved_by_window") == outcome.state.window_index
        for entry in outcome.state.resolved_references
    )
    # El glosario acumulado conserva la definición posterior.
    assert any(entry["term"] == "NX7" for entry in outcome.state.glossary)


def test_selector_carries_only_relevant_items() -> None:
    state = SemanticState(
        organization_id=uuid4(),
        window_index=3,
        glossary=(
            {"term": "FCLAS", "definition": "fare class", "window_index": 3},
            {"term": "ZZZ", "definition": "viejo", "window_index": 0},
        ),
        unresolved_references=(
            {"key": "ref:d", "label": "D", "window_index": 2},
        ),
        open_continuations=(
            {"key": "cont:1", "label": "sigue", "section_id": "s1", "window_index": 3},
        ),
    )
    slice_ = SemanticStateSelector().select(
        state, window_text="FCLAS rules apply", window_index=4
    )
    terms = [entry["term"] for entry in slice_.glossary]
    assert "FCLAS" in terms
    assert "ZZZ" not in terms
    assert len(slice_.unresolved_references) == 1
    assert len(slice_.open_continuations) == 1
    assert slice_.stats["selected"] >= 3


# ---------------------------------------------------------------------------
# Checkpoint por ventana
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_processor_skips_unchanged_and_reprocesses_one_window() -> None:
    document = _understood(
        "# Manual\n\n"
        + "\n\n".join(
            f"Parrafo {index} con contenido operativo del manual."
            for index in range(30)
        )
    )
    plan = _plan(document, max_tokens=120, min_tokens=30)
    assert plan.window_count >= 2
    store = FakeWindowStore()
    processor = SemanticWindowProcessor(store)

    first = await processor.process(document, plan)
    assert first.processed == plan.window_count
    assert first.skipped == 0

    second = await processor.process(document, plan)
    assert second.processed == 0
    assert second.skipped == plan.window_count

    # Una sola ventana stale se reprocesa; el resto sigue SKIP.
    stale_index = 1
    store.results.pop((str(document.id), stale_index))
    third = await processor.process(document, plan)
    assert third.processed == 1
    assert third.skipped == plan.window_count - 1


# ---------------------------------------------------------------------------
# LLM opcional: gate de quote
# ---------------------------------------------------------------------------


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content

    async def generate(self, prompt, **kwargs):
        return SimpleNamespace(
            content=self.content, prompt_tokens=10, completion_tokens=5
        )


@pytest.mark.asyncio
async def test_llm_provider_rejects_items_without_literal_quote() -> None:
    payload = {
        "items": [
            {
                "kind": "concept",
                "label": "FCLAS",
                "text": "fare class",
                "quote": "FCLAS mask",
                "confidence": 0.6,
            },
            {
                "kind": "rule",
                "label": "inventada",
                "text": "no existe",
                "quote": "texto que no está",
                "confidence": 0.9,
            },
        ]
    }
    provider = LLMWindowProvider(FakeLLM(json.dumps(payload)))
    result = await provider.extract(text="FCLAS mask &&&F applies")
    assert result.calls == 1
    assert len(result.items) == 1
    assert result.items[0]["label"] == "FCLAS"
    assert result.items[0]["confidence"] <= 0.7


# ---------------------------------------------------------------------------
# Store Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_window_results_and_states_roundtrip() -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.knowledge.semantic import PostgresSemanticIngestionStore

    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"SW Org {uuid4().hex[:6]}"
    )
    store = PostgresSemanticIngestionStore()
    document_id = uuid4()
    source_id = uuid4()

    result = SemanticWindowResult(
        window_index=0,
        organization_id=organization.id,
        source_id=source_id,
        document_id=document_id,
        status="complete",
        items=(
            WindowItem(
                kind="definition",
                key="fclas",
                label="FCLAS",
                text="Fare class field",
                confidence=0.9,
                block_ids=(str(uuid4()),),
            ),
        ),
        fingerprint="f" * 64,
        carry_fingerprint="c" * 64,
    )
    await store.save_window_result(
        organization.id,
        workspace_id=None,
        source_id=source_id,
        document_id=document_id,
        result=result,
    )
    loaded = await store.get_window_result(
        organization.id, document_id=document_id, window_index=0
    )
    assert loaded is not None
    assert loaded["fingerprint"] == "f" * 64
    assert loaded["item_count"] == 1

    state = SemanticState(
        organization_id=organization.id,
        source_id=source_id,
        document_id=document_id,
        window_index=0,
        glossary=({"term": "FCLAS", "definition": "Fare class", "window_index": 0},),
    )
    await store.save_state(
        organization.id,
        workspace_id=None,
        source_id=source_id,
        document_id=document_id,
        state=state,
    )
    latest = await store.latest_state(organization.id, document_id=document_id)
    assert latest is not None
    assert latest.window_index == 0
    assert latest.glossary[0]["term"] == "FCLAS"

    await store.delete_window_artifacts(organization.id, document_id=document_id)
    assert (
        await store.get_window_result(
            organization.id, document_id=document_id, window_index=0
        )
        is None
    )
    assert await store.latest_state(organization.id, document_id=document_id) is None
