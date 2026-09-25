# =============================================================================
# search_knowledge — el modelo no manda el top_k a la deriva
# =============================================================================
# Caso real: el LLM pidió `top_k: -1`; el corte `chunks[:top_k]` con negativo
# devuelve todo menos los últimos. El tool lo acota (y el runtime ya lo saca).
from __future__ import annotations

from uuid import UUID

import pytest

from src.agents.tools.registry import ToolContext
from src.agents.tools.tools_builtin import SearchKnowledgeTool
from src.core.domain.entities import RetrievalChunk, RetrievalContext

ORG = UUID("11111111-1111-1111-1111-111111111111")


class _RetrieverFalso:
    def __init__(self) -> None:
        self.query = None

    async def retrieve(self, query) -> RetrievalContext:
        self.query = query
        return RetrievalContext(
            chunks=[
                RetrievalChunk(
                    document_id=UUID(int=i + 1),
                    content=f"chunk {i}",
                    score=0.5,
                    metadata={"source_id": str(ORG)},
                )
                for i in range(30)
            ],
            retrieval_latency_ms=1.0,
        )


def _ctx() -> ToolContext:
    return ToolContext(
        tenant_id=str(ORG),
        user_id="test",
        role="admin",
        org_config={"source_ids": [str(ORG)]},
        agent_config={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pedido", "esperado"),
    [
        (None, 5),   # default
        (0, 5),      # 0 se trata como "no lo pedí"
        (-1, 1),     # negativo se sube al mínimo útil
        (3, 3),
        (999, 50),   # techo duro
    ],
)
async def test_top_k_acotado(pedido: int | None, esperado: int) -> None:
    retriever = _RetrieverFalso()
    tool = SearchKnowledgeTool(retriever, embedder=None)
    argumentos: dict = {"query": "byte 105"}
    if pedido is not None:
        argumentos["top_k"] = pedido

    await tool.execute(_ctx(), argumentos)

    assert retriever.query is not None
    assert retriever.query.top_k == esperado
