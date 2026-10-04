# =============================================================================
# GlobalSemanticModel — síntesis global estructurada (Fase 7)
# =============================================================================
# Reglas que se prueban:
#   - el modelo global NO es un resumen: glossary, clusters, dependencias,
#     reference graph y temporal model con estructura;
#   - los items conservan unit_key/regiones/ventanas/evidencia;
#   - RECONCILE marca relaciones cross-region;
#   - las dependencias sin resolver se reportan globalmente;
#   - fingerprint determinista;
#   - store Postgres upsert/get/delete scoped por tenant.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.knowledge.semantic import (
    GlobalModelBuilder,
    GlobalSemanticModel,
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
        external_id="global.md",
        source_id=uuid4(),
        source_name="global.md",
    )
    return apply_understanding(parsed, filename="global.md")


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


async def _global_model(document, plan):
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
    regions = RegionalModelBuilder().build(
        document=document,
        plan=plan,
        results=results,
        units=list(stitch.units),
        relations=list(stitch.relations),
        threads=list(stitch.threads_updated) or threads,
    )
    model = GlobalModelBuilder().build(
        document=document,
        regions=regions,
        units=list(stitch.units),
        relations=list(stitch.relations),
        threads=list(stitch.threads_updated) or threads,
    )
    return model, regions


@pytest.mark.asyncio
async def test_global_model_has_structure_not_summary() -> None:
    document = _understood(
        "# Manual\n\n"
        "FCLAS - fare class definition.\n\n"
        "The fare must match &&&F.\n\n"
        "# Appendix\n\n"
        "&&&F - one alphanumeric character mask."
    )
    plan = _plan(document)
    model, regions = await _global_model(document, plan)

    assert len(model.regions) >= 2
    terms = {entry["term"].casefold() for entry in model.glossary}
    assert "fclas" in terms
    assert "&&&f" in terms
    assert model.semantic_clusters, "los clusters conectan unidades por relaciones"
    assert model.dependencies, "las dependencias se materializan"
    assert any(
        item["relation_type"] in {"DEFINES", "USES"} for item in model.dependencies
    )
    # Estructura, no resumen: no existe un campo "summary" y todo item lleva
    # unit_key/ventanas.
    payload = model.to_dict()
    assert "summary" not in payload
    for item in payload["concepts"] + payload["entities"] + payload["rules"]:
        assert item["unit_key"]
        assert item["windows"]
    assert payload["stats"]["regions"] == len(regions)


@pytest.mark.asyncio
async def test_global_model_marks_cross_region_relations() -> None:
    document = _understood(
        "# Manual\n\n"
        "The fare must match &&&F.\n\n"
        "# Appendix\n\n"
        "&&&F - one alphanumeric character mask."
    )
    plan = _plan(document)
    model, _regions = await _global_model(document, plan)
    uses = [
        item
        for item in model.relationships
        if item["relation_type"] == "USES"
    ]
    assert uses
    assert any(item["cross_region"] for item in uses)


@pytest.mark.asyncio
async def test_global_model_reports_unresolved_dependencies() -> None:
    filler = " ".join(f"w{index}" for index in range(30))
    document = _understood(
        "# Manual\n\n"
        f"See note NX7 for the fare rules. {filler}\n\n"
        "# Appendix\n\n"
        "Contenido del apendice sin la definicion."
    )
    plan = _plan(document, max_tokens=20, min_tokens=5)
    model, _regions = await _global_model(document, plan)
    unresolved_keys = {
        item["thread_key"] for item in model.unresolved_items
    }
    assert any("nx7" in key for key in unresolved_keys)
    assert model.stats["unresolved"] == len(model.unresolved_items)


@pytest.mark.asyncio
async def test_global_fingerprint_is_deterministic() -> None:
    document = _understood(
        "# Manual\n\nFCLAS - fare class definition.\n\n"
        "# Appendix\n\n&&&F - one alphanumeric character mask."
    )
    plan = _plan(document)
    first, _ = await _global_model(document, plan)
    second, _ = await _global_model(document, plan)
    assert first.fingerprint == second.fingerprint


# ---------------------------------------------------------------------------
# Store Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_global_roundtrip() -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.knowledge.semantic import PostgresSemanticIngestionStore

    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"SG Org {uuid4().hex[:6]}"
    )
    store = PostgresSemanticIngestionStore()
    document_id = uuid4()
    model = GlobalSemanticModel(
        id=uuid4(),
        organization_id=organization.id,
        document_id=document_id,
        regions=("section:manual", "section:appendix"),
        glossary=(
            {
                "term": "FCLAS",
                "definition": "fare class",
                "unit_key": "definition:fclas",
                "regions": ["section:manual"],
                "windows": [0],
                "block_ids": [str(uuid4())],
                "confidence": 0.85,
            },
        ),
        semantic_clusters=(
            {"cluster_id": str(uuid4()), "label": "FCLAS", "size": 2},
        ),
        stats={"regions": 2, "units": 3, "relations": 2},
    )
    await store.replace_global_model(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        model=model,
    )
    loaded = await store.get_global_model(organization.id, document_id=document_id)
    assert loaded is not None
    assert loaded["fingerprint"] == model.fingerprint
    assert loaded["model"]["glossary"][0]["term"] == "FCLAS"
    assert loaded["model"]["stats"]["regions"] == 2

    # Upsert idempotente.
    await store.replace_global_model(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        model=model,
    )
    again = await store.get_global_model(organization.id, document_id=document_id)
    assert again is not None and again["fingerprint"] == model.fingerprint

    await store.delete_window_artifacts(organization.id, document_id=document_id)
    assert await store.get_global_model(organization.id, document_id=document_id) is None
