# =============================================================================
# SemanticFabric — nodos, aristas e identidad cross-source (Fase 8)
# =============================================================================
# Reglas que se prueban:
#   - la proyección usa el vocabulario de nodos/aristas de la misión §21;
#   - cada nodo conserva unit_key/block_ids/ventanas (provenance exacta);
#   - las aristas derivadas (DEPENDS_ON, CONSTRAINS, APPLIES_TO, DERIVED_FROM,
#     VALID_FROM) se materializan sin inventar;
#   - cross-source: propone same_identity/likely_identity/alias_candidate con
#     evidencia y NUNCA fusiona nodos;
#   - store Postgres replace/list/find/delete scoped por tenant.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.knowledge.semantic import (
    GlobalModelBuilder,
    RegionalModelBuilder,
    SemanticFabricBuilder,
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
        external_id="fabric.md",
        source_id=uuid4(),
        source_name="fabric.md",
    )
    return apply_understanding(parsed, filename="fabric.md")


def _plan(document, *, max_tokens: int = 40, min_tokens: int = 10):
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


async def _fabric(document, plan, *, existing_nodes=None):
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
    global_model = GlobalModelBuilder().build(
        document=document,
        regions=regions,
        units=list(stitch.units),
        relations=list(stitch.relations),
        threads=list(stitch.threads_updated) or threads,
    )
    projection = SemanticFabricBuilder().project(
        document=document,
        global_model=global_model,
        units=list(stitch.units),
        relations=list(stitch.relations),
        existing_nodes=existing_nodes,
    )
    return projection


@pytest.mark.asyncio
async def test_fabric_projects_mission_vocabulary() -> None:
    document = _understood(
        "# Manual\n\n"
        "Field: FCLAS\nBytes: 5-8\nFormat: A\nPattern: &&&F\n\n"
        "FCLAS - fare class definition.\n\n"
        "The fare must match &&&F.\n\n"
        "Exception: unless the validating carrier applies &&&F.\n\n"
        "Vigente desde 2026-01-01."
    )
    projection = await _fabric(document, _plan(document))
    node_types = {node.node_type for node in projection.nodes}
    assert {"Definition", "Symbol", "Rule", "Exception", "Evidence"} <= node_types
    assert "TemporalAssertion" in node_types
    assert "Attribute" in node_types

    edge_types = {edge.relation_type for edge in projection.edges}
    assert {"DEFINES", "USES", "HAS_EXCEPTION", "DERIVED_FROM"} <= edge_types
    assert "DEPENDS_ON" in edge_types
    assert {"CONSTRAINS", "APPLIES_TO"} & edge_types

    # Provenance exacta en cada nodo.
    knowledge_nodes = [
        node for node in projection.nodes if node.node_type != "Evidence"
    ]
    assert all(node.unit_key for node in knowledge_nodes)
    assert all(node.block_ids for node in knowledge_nodes)


@pytest.mark.asyncio
async def test_provenance_traversal_node_to_source_range() -> None:
    """Fase 12: Fabric node -> semantic unit -> block -> source range."""
    document = _understood("# Manual\n\nFCLAS - fare class definition.")
    projection = await _fabric(document, _plan(document))
    definition = next(
        node for node in projection.nodes if node.node_type == "Definition"
    )
    assert definition.unit_key
    assert definition.block_ids

    blocks = {str(block.id): block for block in document.blocks}
    source_block = blocks[definition.block_ids[0]]
    assert source_block.char_range is not None
    assert source_block.char_range.end > source_block.char_range.start

    evidence = next(
        node
        for node in projection.nodes
        if node.node_type == "Evidence"
        and node.block_ids == (definition.block_ids[0],)
    )
    assert any(
        edge.relation_type == "DERIVED_FROM"
        and edge.subject_id == definition.id
        and edge.object_id == evidence.id
        for edge in projection.edges
    )


@pytest.mark.asyncio
async def test_fabric_identity_candidates_cross_source_without_merge() -> None:
    document_a = _understood(
        "# Manual\n\nFCLAS - fare class definition.\n\nValidate &&&F before use."
    )
    projection_a = await _fabric(document_a, _plan(document_a))
    existing = [
        {
            "id": str(node.id),
            "document_id": str(node.document_id),
            "source_id": str(node.source_id) if node.source_id else None,
            "node_key": node.node_key,
            "node_type": node.node_type,
            "label": node.label,
            "unit_key": node.unit_key,
            "block_ids": list(node.block_ids),
            "windows": list(node.windows),
            "attributes": dict(node.attributes),
        }
        for node in projection_a.nodes
        if node.node_type != "Evidence"
    ]

    document_b = _understood(
        "# Otro\n\nFCLAS - fare class definition.\n\n&&&F - one alphanumeric mask."
    )
    projection_b = await _fabric(
        document_b, _plan(document_b), existing_nodes=existing
    )
    assert projection_b.identity_candidates
    statuses = {
        candidate.identity_status for candidate in projection_b.identity_candidates
    }
    assert "same_identity" in statuses
    assert "alias_candidate" in statuses

    # Nunca fusiona: los nodos de B son propios (ids distintos de A) y las
    # candidatas referencian ambos lados con evidencia.
    ids_a = {node.id for node in projection_a.nodes}
    ids_b = {node.id for node in projection_b.nodes}
    assert not (ids_a & ids_b)
    for candidate in projection_b.identity_candidates:
        assert candidate.left_node_id != candidate.right_node_id
        assert candidate.evidence["left"]["node_key"]
        assert candidate.evidence["right"]["node_key"]
        assert candidate.confidence > 0


# ---------------------------------------------------------------------------
# Store Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_fabric_roundtrip() -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.knowledge.semantic import (
        FabricEdge,
        FabricNode,
        IdentityCandidate,
        PostgresSemanticIngestionStore,
    )

    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"SF Org {uuid4().hex[:6]}"
    )
    store = PostgresSemanticIngestionStore()
    document_id = uuid4()
    node = FabricNode(
        id=uuid4(),
        node_key="Definition:definition:fclas",
        node_type="Definition",
        label="FCLAS",
        organization_id=organization.id,
        document_id=document_id,
        unit_key="definition:fclas",
        block_ids=(str(uuid4()),),
        windows=(0,),
    )
    evidence = FabricNode(
        id=uuid4(),
        node_key=f"Evidence:block:{node.block_ids[0]}",
        node_type="Evidence",
        label=str(node.block_ids[0])[:36],
        organization_id=organization.id,
        document_id=document_id,
        block_ids=node.block_ids,
    )
    edge = FabricEdge(
        id=uuid4(),
        edge_key="DERIVED_FROM:Definition:definition:fclas->Evidence:block:x",
        relation_type="DERIVED_FROM",
        subject_id=node.id,
        object_id=evidence.id,
        subject_key=node.node_key,
        object_key=evidence.node_key,
        organization_id=organization.id,
        document_id=document_id,
        evidence=node.block_ids,
        windows=(0,),
    )
    candidate = IdentityCandidate(
        id=uuid4(),
        identity_status="same_identity",
        left_node_id=node.id,
        right_node_id=uuid4(),
        left_key=node.node_key,
        right_key="Definition:definition:fclas@other",
        left_label="FCLAS",
        right_label="FCLAS",
        organization_id=organization.id,
        left_document_id=document_id,
        right_document_id=uuid4(),
        confidence=0.9,
        reason="same_type_same_normalized_label",
    )
    await store.replace_fabric(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        nodes=[node, evidence],
        edges=[edge],
    )
    await store.save_identity_candidates(organization.id, candidates=[candidate])

    nodes = await store.list_fabric_nodes(organization.id, document_id=document_id)
    assert len(nodes) == 2
    edges = await store.list_fabric_edges(
        organization.id, document_id=document_id, relation_type="DERIVED_FROM"
    )
    assert len(edges) == 1
    identities = await store.list_identity_candidates(
        organization.id, document_id=document_id, status="same_identity"
    )
    assert len(identities) == 1

    found = await store.find_fabric_nodes_by_labels(
        organization.id, ["FCLAS"], exclude_document_id=None
    )
    assert found and found[0]["node_type"] == "Definition"
    excluded = await store.find_fabric_nodes_by_labels(
        organization.id, ["FCLAS"], exclude_document_id=document_id
    )
    assert excluded == []

    await store.delete_window_artifacts(organization.id, document_id=document_id)
    assert await store.list_fabric_nodes(organization.id, document_id=document_id) == []
    assert await store.list_fabric_edges(organization.id, document_id=document_id) == []
    assert (
        await store.list_identity_candidates(
            organization.id, document_id=document_id
        )
        == []
    )
