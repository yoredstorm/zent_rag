# =============================================================================
# Graph-aware retrieval — spreading activation (Fase 11)
# =============================================================================
# Reglas que se prueban:
#   - activación limitada por relación, confianza, hops, decay y nodos;
#   - seeds desde payload `fabric_node_ids` (lista o string);
#   - chunks activados ordenados por activación y marcados en metadata;
#   - FabricActivationExpansion usa el store real (método opcional) y devuelve
#     vacío sin fabric, sin frenar el retrieval;
#   - default_strategies incluye la etapa.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.entities import RetrievalChunk
from src.rag.longcontext.expansion import ExpansionContext, default_strategies
from src.rag.longcontext.graph_activation import (
    ActivationPolicy,
    FabricActivationExpansion,
    chunks_for_activated_nodes,
    seed_node_ids_from_chunks,
    spreading_activation,
)
from src.rag.retrieval.models import RetrievalQuery


def _edge(edge_id, relation, subject, object_id, confidence=0.9):
    return {
        "id": edge_id,
        "relation_type": relation,
        "subject_id": subject,
        "object_id": object_id,
        "confidence": confidence,
        "subject_label": f"label-{subject}",
        "object_label": f"label-{object_id}",
        "subject_kind": "Rule",
        "object_kind": "Definition",
    }


def _chunk(document_id, node_ids, content="content", score=0.5):
    return RetrievalChunk(
        document_id=document_id,
        content=content,
        score=score,
        metadata={"fabric_node_ids": list(node_ids)},
    )


def test_spreading_activation_limits() -> None:
    edges = [
        _edge("e1", "DEFINES", "a", "b", 0.9),
        _edge("e2", "USES", "b", "c", 0.8),
        _edge("e3", "RELATED_TO", "c", "d", 0.9),
        _edge("e4", "USES", "a", "e", 0.2),
    ]
    policy = ActivationPolicy(max_hops=2, decay=0.75, min_confidence=0.35)
    activated = spreading_activation(["a"], edges, policy=policy)
    assert activated["a"].hop == 0
    assert activated["b"].hop == 1
    assert abs(activated["b"].activation - 0.675) < 1e-6
    assert activated["c"].hop == 2
    assert abs(activated["c"].activation - 0.405) < 1e-6
    assert "d" not in activated  # RELATED_TO no propaga
    assert "e" not in activated  # bajo min_confidence


def test_spreading_activation_node_cap() -> None:
    edges = [_edge(f"e{i}", "USES", "a", f"n{i}", 0.9) for i in range(10)]
    activated = spreading_activation(
        ["a"], edges, policy=ActivationPolicy(max_nodes=3, max_hops=1)
    )
    assert len(activated) == 3


def test_seed_node_ids_from_chunks() -> None:
    document_id = uuid4()
    chunks = [
        _chunk(document_id, ["n1", "n2"]),
        RetrievalChunk(
            document_id=document_id,
            content="str metadata",
            score=0.5,
            metadata={"fabric_node_ids": "n2"},
        ),
        _chunk(document_id, []),
    ]
    assert seed_node_ids_from_chunks(chunks) == ["n1", "n2"]


def test_chunks_for_activated_nodes_orders_and_marks() -> None:
    document_id = uuid4()
    chunks = [
        _chunk(document_id, ["a"], content="seed"),
        _chunk(document_id, ["b"], content="neighbor"),
        _chunk(document_id, ["zzz"], content="unrelated"),
    ]
    activated = spreading_activation(["a"], [_edge("e1", "USES", "a", "b", 0.9)])
    selected = chunks_for_activated_nodes(chunks, activated, limit=5)
    assert [chunk.content for chunk in selected] == ["seed", "neighbor"]
    assert selected[1].metadata["retrieval"] == "fabric_activation"
    assert selected[1].metadata["fabric_activation"] > 0


class FakeFabricStore:
    def __init__(self, neighbor: RetrievalChunk) -> None:
        self.calls = 0
        self._neighbor = neighbor

    async def list_fabric_edges_for_nodes(self, organization_id, node_ids, *, limit=2000):
        self.calls += 1
        return [_edge("e1", "USES", "a", "b", 0.9)]

    async def get_chunks_by_fabric_nodes(
        self, organization_id, *, node_ids, role="admin", user_id=None,
        groups=None, limit=60,
    ):
        from src.core.domain.entities import RetrievalContext

        return RetrievalContext(
            chunks=[self._neighbor], retrieval_latency_ms=0.0
        )


class FakeStoreWithoutFabric:
    async def get_documents(self, *args, **kwargs):
        return []


@pytest.mark.asyncio
async def test_fabric_activation_expansion() -> None:
    document_id = uuid4()
    neighbor = RetrievalChunk(
        document_id=document_id,
        content="neighbor",
        score=0.0,
        metadata={"fabric_node_ids": ["b"], "chunk_id": "c2"},
    )
    store = FakeFabricStore(neighbor)
    strategy = FabricActivationExpansion(store)
    query = RetrievalQuery(query="q", organization_id=uuid4())
    seed = RetrievalChunk(
        document_id=document_id,
        content="seed",
        score=0.5,
        metadata={"fabric_node_ids": ["a"], "chunk_id": "c1"},
    )
    expansion = await strategy.expand(
        ExpansionContext(query=query, chunks=[seed], limit=5)
    )
    assert expansion.name == "fabric_activation"
    assert store.calls >= 1
    assert [chunk.content for chunk in expansion.chunks] == ["neighbor"]
    assert expansion.chunks[0].metadata["retrieval"] == "fabric_activation"
    assert expansion.chunks[0].metadata["fabric_activation"] > 0

    # Sin fetch de chunks, el fallback activa solo lo ya presente (semilla
    # excluida): no hay nada nuevo.
    empty = await FabricActivationExpansion(FakeStoreWithoutFabric()).expand(
        ExpansionContext(query=query, chunks=[seed], limit=5)
    )
    assert empty.chunks == []


def test_default_strategies_includes_fabric_activation() -> None:
    names = [
        strategy.name
        for strategy in default_strategies(FakeStoreWithoutFabric(), None)
    ]
    assert "fabric_activation" in names
