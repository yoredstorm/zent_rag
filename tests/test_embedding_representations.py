# =============================================================================
# Embedding Representations + Late Chunking — Fase 10
# =============================================================================
# Reglas que se prueban:
#   - capability registry: nunca asumir late chunking; config y builtin mandan;
#   - can_late_chunk exige capacidad declarada Y método real del provider;
#   - builders content/semantic/concept/question (el dense usa contexto del
#     fabric en semantic, sin inventar);
#   - batches de late chunking agrupados por padre; fallback silencioso si el
#     provider falla (contextual embedding);
#   - el fingerprint incluye la representación de embedding y la invalidación
#     reporta embedding_representation_changed.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.knowledge.representation import (
    change_reason,
    descriptor_for_document,
)
from src.knowledge.semantic import build_retrieval_context
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding
from src.rag.embeddings import (
    EmbeddingTextPlanner,
    can_late_chunk,
    embed_late_chunking_batches,
    plan_late_chunking_batches,
    resolve_embedding_capability,
)
from src.rag.embeddings.late_chunking import (
    configured_late_chunking_models,
    late_chunking_mode,
)


def _fabric_context():
    nodes = [
        {
            "id": str(uuid4()),
            "node_key": "Definition:definition:fclas",
            "node_type": "Definition",
            "label": "FCLAS",
            "text": "fare class field",
            "unit_key": "definition:fclas",
            "block_ids": ["b1"],
            "windows": [0],
            "attributes": {},
        },
        {
            "id": str(uuid4()),
            "node_key": "Rule:rule:fare",
            "node_type": "Rule",
            "label": "Fare rule",
            "text": "The fare must match &&&F",
            "unit_key": "rule:fare",
            "block_ids": ["b1"],
            "windows": [0],
            "attributes": {},
        },
    ]
    edges = [
        {
            "id": str(uuid4()),
            "relation_type": "USES",
            "subject_id": nodes[1]["id"],
            "object_id": nodes[0]["id"],
            "windows": [0],
        }
    ]
    return build_retrieval_context(nodes, edges, mode="shadow")


def _chunk(content: str = "raw content", block_ids=("b1",)):
    return SimpleNamespace(
        id=uuid4(),
        content=content,
        metadata={"block_ids": list(block_ids)},
    )


def _enrichment():
    question = SimpleNamespace(
        question="What does FCLAS mean?",
        source_unit_ids=("b1",),
    )
    return SimpleNamespace(synthetic_questions=(question,))


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


def test_capability_never_assumes_late_chunking() -> None:
    default = resolve_embedding_capability("text-embedding-3-small")
    assert default.supports_late_chunking is False
    assert default.source == "default"

    builtin = resolve_embedding_capability("jina-embeddings-v3")
    assert builtin.supports_late_chunking is True
    assert builtin.source == "builtin"

    configured = resolve_embedding_capability(
        "openai/text-embedding-3-small",
        late_chunking_models={"text-embedding-3-small"},
    )
    assert configured.supports_late_chunking is True
    assert configured.source == "config"


def test_can_late_chunk_requires_real_provider_method() -> None:
    class ProviderWithoutMethod:
        async def embed(self, texts, model=None):
            return [[0.0] for _ in texts]

    class ProviderWithMethod(ProviderWithoutMethod):
        async def embed_late_chunking(self, chunks, model=None):
            return [[1.0] for _ in chunks]

    assert can_late_chunk(ProviderWithoutMethod(), model="jina-embeddings-v3") is False
    assert can_late_chunk(ProviderWithMethod(), model="jina-embeddings-v3") is True
    assert (
        can_late_chunk(
            ProviderWithMethod(), model="jina-embeddings-v3", mode="off"
        )
        is False
    )
    assert (
        can_late_chunk(ProviderWithMethod(), model="text-embedding-3-small")
        is False
    )


def test_late_chunking_settings_defaults(monkeypatch) -> None:
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "EMBEDDING_LATE_CHUNKING", "off", raising=False)
    monkeypatch.setattr(
        get_settings(),
        "EMBEDDING_LATE_CHUNKING_MODELS",
        "custom-embed, other-embed",
        raising=False,
    )
    assert late_chunking_mode() == "off"
    assert configured_late_chunking_models() == {"custom-embed", "other-embed"}


# ---------------------------------------------------------------------------
# Representaciones
# ---------------------------------------------------------------------------


def test_representation_builders() -> None:
    chunk = _chunk()
    fabric = _fabric_context()
    enrichment = _enrichment()

    content = EmbeddingTextPlanner(representation="content")
    assert content.plan(chunk, "section text") == "section text"

    semantic = EmbeddingTextPlanner(
        representation="semantic", fabric_context=fabric
    )
    text = semantic.plan(chunk, "section text")
    assert "Semantic context:" in text
    assert "FCLAS" in text
    assert "fare class field" in text

    concept = EmbeddingTextPlanner(representation="concept", fabric_context=fabric)
    concept_text = concept.plan(chunk, "section text")
    assert concept_text.startswith("Concepts:")
    assert "FCLAS" in concept_text

    question = EmbeddingTextPlanner(
        representation="question", enrichment=enrichment
    )
    question_text = question.plan(chunk, "section text")
    assert "Questions:" in question_text
    assert "What does FCLAS mean?" in question_text

    assert semantic.version.startswith("embedding-rep-1:semantic")


# ---------------------------------------------------------------------------
# Late chunking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_late_chunking_batches_and_fallback() -> None:
    parent_id = uuid4()
    child_a = SimpleNamespace(
        id=uuid4(), parent_id=parent_id, chunk_index=0, content="a"
    )
    child_b = SimpleNamespace(
        id=uuid4(), parent_id=parent_id, chunk_index=1, content="b"
    )
    lone = SimpleNamespace(id=uuid4(), parent_id=uuid4(), chunk_index=0, content="c")
    representations = {
        child_a.id: {"embed": "text a"},
        child_b.id: {"embed": "text b"},
        lone.id: {"embed": "text c"},
    }
    batches = plan_late_chunking_batches([child_a, child_b, lone], representations)
    assert len(batches) == 1
    assert batches[0].size == 2
    assert batches[0].fingerprint

    class GoodProvider:
        async def embed_late_chunking(self, chunks, model=None):
            assert chunks == ["text a", "text b"]
            return [[0.1] * 4, [0.2] * 4]

    class BadProvider:
        async def embed_late_chunking(self, chunks, model=None):
            raise RuntimeError("no soportado")

    vectors = await embed_late_chunking_batches(GoodProvider(), batches)
    assert len(vectors) == 2
    assert vectors[str(child_a.id)][0] == 0.1

    fallback = await embed_late_chunking_batches(BadProvider(), batches)
    assert fallback == {}


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_includes_embedding_representation() -> None:
    document = TextParser().parse(
        b"# Manual\n\nFCLAS - fare class definition.",
        organization_id=uuid4(),
        external_id="embed.md",
        source_id=uuid4(),
        source_name="embed.md",
    )
    document = apply_understanding(document, filename="embed.md")
    payload = descriptor_for_document(document).to_payload()
    assert payload["embedding_representation"] == "content"
    assert payload["embedding_representation_version"].startswith("embedding-rep-1")

    previous = dict(payload)
    previous["embedding_representation"] = "semantic"
    assert (
        change_reason(previous, payload, content_changed=False)
        == "embedding_representation_changed"
    )
