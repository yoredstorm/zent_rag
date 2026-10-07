# =============================================================================
# DecisionEvidenceResolver — hidratar refs del envelope sin retrieval semántico
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.runtime.authorized_scope import AuthorizedKnowledgeScope
from src.runtime.decision_evidence import DecisionEvidenceResolver

SOURCE_A = str(uuid4())
SOURCE_B = str(uuid4())
CHUNK_1 = str(uuid4())


class _Chunk:
    def __init__(self, *, content: str, metadata: dict) -> None:
        self.content = content
        self.metadata = metadata
        self.document_id = metadata.get("document_id", "")


class _Context:
    def __init__(self, chunks: list) -> None:
        self.chunks = chunks


class _FakeStore:
    """Store mínimo: chunk lookup por metadata.chunk_id / document_id."""

    def __init__(self, chunks: list[_Chunk]) -> None:
        self.chunks = chunks
        self.calls: list[str] = []

    async def get_documents_by_chunk_ids(self, organization_id, ids, **kwargs):
        self.calls.append("chunk_ids")
        wanted = {str(value) for value in ids}
        return _Context(
            [
                chunk
                for chunk in self.chunks
                if str(chunk.metadata.get("chunk_id") or "") in wanted
            ]
        )

    async def get_documents(self, organization_id, ids, **kwargs):
        self.calls.append("point_ids")
        return _Context([])

    async def get_documents_by_metadata(
        self, organization_id, *, document_ids=None, source_ids=None, **kwargs
    ):
        self.calls.append("metadata")
        wanted = {str(value) for value in (document_ids or source_ids or [])}
        return _Context(
            [
                chunk
                for chunk in self.chunks
                if str(chunk.metadata.get("document_id") or "") in wanted
                or str(chunk.metadata.get("source_id") or "") in wanted
            ][:2]
        )


def _chunk(*, chunk_id: str, source_id: str, document_id: str) -> _Chunk:
    return _Chunk(
        content="Matching is positional, left to right.",
        metadata={
            "chunk_id": chunk_id,
            "source_id": source_id,
            "document_id": document_id,
            "filename": "atpco-rules.pdf",
            "title": "Data Application For Record 2",
            "page_start": 11,
            "section_path": ["Matching"],
            "content_hash": "abc123",
            "parser_version": "pdfplumber-text-1.1",
        },
    )


@pytest.mark.asyncio
async def test_resuelve_por_chunk_id_y_marca_decision_evidence() -> None:
    store = _FakeStore([_chunk(chunk_id=CHUNK_1, source_id=SOURCE_A, document_id="doc-1")])
    resolver = DecisionEvidenceResolver(organization_id=uuid4(), vector_store=store)
    resolution = await resolver.resolve([CHUNK_1])
    assert resolution.unresolved == []
    [item] = resolution.items
    assert item.evidence_id == CHUNK_1
    assert item.title == "Data Application For Record 2"
    assert item.page == 11
    assert item.metadata.get("decision_evidence") is True
    assert item.metadata.get("source_id") == SOURCE_A
    assert resolution.resolved_basis[CHUNK_1] == "chunk_id"


@pytest.mark.asyncio
async def test_ref_inexistente_queda_unresolved() -> None:
    store = _FakeStore([])
    resolver = DecisionEvidenceResolver(organization_id=uuid4(), vector_store=store)
    resolution = await resolver.resolve([str(uuid4())])
    assert resolution.items == []
    assert len(resolution.unresolved) == 1


@pytest.mark.asyncio
async def test_evidencia_fuera_de_scope_no_se_hidrata() -> None:
    store = _FakeStore([_chunk(chunk_id=CHUNK_1, source_id=SOURCE_B, document_id="doc-b")])
    scope = AuthorizedKnowledgeScope(
        organization_id=str(uuid4()), source_ids=(SOURCE_A,)
    )
    resolver = DecisionEvidenceResolver(
        organization_id=uuid4(), scope=scope, vector_store=store
    )
    resolution = await resolver.resolve([CHUNK_1])
    assert resolution.items == []
    assert CHUNK_1 in resolution.out_of_scope


@pytest.mark.asyncio
async def test_lookup_por_document_id_como_fallback() -> None:
    document_id = str(uuid4())
    store = _FakeStore(
        [_chunk(chunk_id=str(uuid4()), source_id=SOURCE_A, document_id=document_id)]
    )
    resolver = DecisionEvidenceResolver(organization_id=uuid4(), vector_store=store)
    resolution = await resolver.resolve([document_id])
    assert [item.evidence_id for item in resolution.items] == [document_id]
    assert resolution.resolved_basis[document_id] == "metadata"
