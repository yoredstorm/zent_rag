# =============================================================================
# RegionalSemanticModel — comprensión regional (Fase 6)
# =============================================================================
# Reglas que se prueban:
#   - las ventanas se agrupan por región lógica (capítulo/sección de primer
#     nivel; "document" para preámbulo);
#   - cada región consolida definiciones/reglas/entidades/relaciones de SUS
#     ventanas (sin sustituir evidencia: unit_key + block_ids + windows);
#   - las dependencias sin resolver quedan en la región donde abrieron;
#   - fingerprint determinista;
#   - store Postgres replace/list/delete scoped por tenant.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.knowledge.semantic import (
    RegionalModelBuilder,
    SemanticStitcher,
    SemanticWindowPlanner,
    SemanticWindowProcessor,
    window_result_from_dict,
)
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding


def _understood(text: str):
    parsed = TextParser().parse(
        text.encode("utf-8"),
        organization_id=uuid4(),
        external_id="regional.md",
        source_id=uuid4(),
        source_name="regional.md",
    )
    return apply_understanding(parsed, filename="regional.md")


def _plan(document, *, max_tokens: int = 12, min_tokens: int = 5):
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
            "organization_id": str(organization_id),
            "document_id": str(document_id),
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


async def _regional_models(document, plan):
    store = FakeStore()
    processor = SemanticWindowProcessor(store)
    outcome = await processor.process(document, plan)
    assert outcome.complete
    rows = await store.list_window_results(
        document.organization_id, document_id=document.id, include_items=True
    )
    results = [window_result_from_dict(row) for row in rows]
    threads = await store.list_threads(
        document.organization_id, document_id=document.id
    )
    stitch = SemanticStitcher().stitch(
        document=document, results=results, threads=threads
    )
    models = RegionalModelBuilder().build(
        document=document,
        plan=plan,
        results=results,
        units=list(stitch.units),
        relations=list(stitch.relations),
        threads=list(stitch.threads_updated) or threads,
    )
    return models, stitch


@pytest.mark.asyncio
async def test_regions_split_by_top_level_section() -> None:
    document = _understood(
        "# Manual\n\n"
        "FCLAS - fare class definition.\n\n"
        "The fare must match &&&F.\n\n"
        "# Appendix\n\n"
        "&&&F - one alphanumeric character mask."
    )
    plan = _plan(document)
    assert plan.window_count >= 3
    models, _stitch = await _regional_models(document, plan)
    region_ids = {model.region_id for model in models}
    assert "section:manual" in region_ids
    assert "section:appendix" in region_ids

    manual = next(model for model in models if model.region_id == "section:manual")
    appendix = next(
        model for model in models if model.region_id == "section:appendix"
    )
    manual_units = {item["unit_key"] for item in manual.definitions}
    appendix_units = {item["unit_key"] for item in appendix.definitions}
    assert "definition:fclas" in manual_units
    assert "definition:&&&f" in appendix_units
    # Toda unidad regional conserva evidencia física y ventanas.
    for model in models:
        for item in (*model.definitions, *model.rules, *model.entities):
            assert item["block_ids"]
            assert item["source_windows"]


@pytest.mark.asyncio
async def test_region_keeps_unresolved_dependencies() -> None:
    filler = " ".join(f"w{index}" for index in range(30))
    document = _understood(
        "# Manual\n\n"
        f"See note NX7 for the fare rules. {filler}\n\n"
        "# Appendix\n\n"
        "Contenido del apendice sin la definicion."
    )
    plan = _plan(document, max_tokens=20, min_tokens=5)
    models, _stitch = await _regional_models(document, plan)
    manual = next(
        (model for model in models if model.region_id == "section:manual"), None
    )
    appendix = next(
        (model for model in models if model.region_id == "section:appendix"), None
    )
    assert manual is not None and appendix is not None
    manual_threads = {
        item["thread_key"] for item in manual.unresolved_dependencies
    }
    appendix_threads = {
        item["thread_key"] for item in appendix.unresolved_dependencies
    }
    assert any("nx7" in key for key in manual_threads)
    assert not any("nx7" in key for key in appendix_threads)


@pytest.mark.asyncio
async def test_regional_fingerprint_is_deterministic() -> None:
    document = _understood(
        "# Manual\n\nFCLAS - fare class definition.\n\n"
        "# Appendix\n\n&&&F - one alphanumeric character mask."
    )
    plan = _plan(document)
    models_a, _ = await _regional_models(document, plan)
    models_b, _ = await _regional_models(document, plan)
    assert models_a
    assert [model.fingerprint for model in models_a] == [
        model.fingerprint for model in models_b
    ]


# ---------------------------------------------------------------------------
# Store Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_regional_roundtrip() -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.knowledge.semantic import (
        PostgresSemanticIngestionStore,
        RegionalSemanticModel,
    )

    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"SR Org {uuid4().hex[:6]}"
    )
    store = PostgresSemanticIngestionStore()
    document_id = uuid4()
    model = RegionalSemanticModel(
        id=uuid4(),
        region_id="section:manual",
        label="Manual",
        organization_id=organization.id,
        document_id=document_id,
        window_start=0,
        window_end=2,
        window_indexes=(0, 1, 2),
        definitions=(
            {
                "unit_key": "definition:fclas",
                "unit_kind": "definition",
                "label": "FCLAS",
                "text": "fare class",
                "confidence": 0.85,
                "source_windows": [0],
                "block_ids": [str(uuid4())],
            },
        ),
        unresolved_dependencies=(
            {
                "thread_key": "reference:note:nx7",
                "thread_type": "REFERENCE",
                "status": "OPEN",
                "target_hint": "NX7",
                "opened_at_window": 0,
                "confidence": 0.6,
            },
        ),
        stats={"windows": 3, "units": 1, "relations": 0, "unresolved": 1},
    )
    await store.replace_regional_models(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        models=[model],
    )
    regions = await store.list_regional_models(
        organization.id, document_id=document_id
    )
    assert len(regions) == 1
    assert regions[0]["region_id"] == "section:manual"
    assert regions[0]["model"]["definitions"][0]["unit_key"] == "definition:fclas"
    assert regions[0]["fingerprint"] == model.fingerprint

    # Replace idempotente.
    await store.replace_regional_models(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        models=[model],
    )
    assert len(await store.list_regional_models(organization.id, document_id=document_id)) == 1

    await store.delete_window_artifacts(organization.id, document_id=document_id)
    assert (
        await store.list_regional_models(organization.id, document_id=document_id)
        == []
    )
