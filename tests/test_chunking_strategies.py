# =============================================================================
# Chunking Strategies — fixed, recursive (markdown-aware), sentence
# =============================================================================
from __future__ import annotations

import pytest

from src.rag.chunking.registry import available_strategies, get_chunker


def test_registry_lists_all_strategies() -> None:
    assert set(available_strategies()) == {"fixed", "recursive", "sentence"}


def test_registry_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError):
        get_chunker("nope")


def test_fixed_chunks_with_overlap() -> None:
    chunker = get_chunker("fixed", chunk_size=100, chunk_overlap=20)
    chunks = chunker.chunk("a" * 250)
    assert len(chunks) >= 3
    assert all(len(c) <= 100 for c in chunks)
    assert chunks[0][-20:] == chunks[1][:20]


def test_fixed_short_text_unchanged() -> None:
    assert get_chunker("fixed", 100, 10).chunk("hola") == ["hola"]


def test_sentence_chunker_groups_sentences() -> None:
    chunker = get_chunker("sentence", chunk_size=80, chunk_overlap=0)
    text = "Primera oración de prueba. Segunda oración de prueba. Tercera oración de prueba."
    chunks = chunker.chunk(text)
    assert len(chunks) >= 1
    assert all(len(c) <= 80 for c in chunks)


def test_recursive_chunker_splits_by_headings() -> None:
    chunker = get_chunker("recursive", chunk_size=200, chunk_overlap=20)
    text = (
        "# Título\n\n"
        + ("a" * 300)
        + "\n\n"
        + "## Sección dos\n\n"
        + ("b" * 50)
    )
    chunks = chunker.chunk(text)
    assert len(chunks) >= 2
    # La segunda sección con heading queda en su propio chunk (o uno iniciado por ella)
    assert any("## Sección dos" in c for c in chunks)
    assert all(len(c) <= 200 + 20 for c in chunks)


def test_recursive_chunker_keeps_tables_atomic() -> None:
    chunker = get_chunker("recursive", chunk_size=1000, chunk_overlap=0)
    table = (
        "| producto | precio |\n"
        "|---|---|\n"
        "| Paracetamol | 2.5 |\n"
        "| Ibuprofeno | 3.0 |\n"
    )
    text = f"Introducción breve.\n\n{table}\n\nFinal."
    chunks = chunker.chunk(text)
    joined = "\n".join(chunks)
    # La tabla no se partió a la mitad: todas sus filas están contiguas
    assert "| Paracetamol | 2.5 |" in joined
    assert "| Ibuprofeno | 3.0 |" in joined
    table_chunk = next(c for c in chunks if "| producto |" in c)
    assert "| Ibuprofeno | 3.0 |" in table_chunk


def test_recursive_hard_splits_giant_block() -> None:
    chunker = get_chunker("recursive", chunk_size=200, chunk_overlap=10)
    chunks = chunker.chunk("x" * 1000)
    assert len(chunks) >= 5
    assert all(len(c) <= 200 for c in chunks)


def test_chunker_validation_errors() -> None:
    with pytest.raises(ValueError):
        get_chunker("fixed", chunk_size=0)
    with pytest.raises(ValueError):
        get_chunker("fixed", chunk_size=100, chunk_overlap=100)
