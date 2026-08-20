from __future__ import annotations

from src.connectors.sql.ingestion import (
    _chunk_text,
    _column_to_template,
    _serialize_row,
)


def test_chunk_text_short_unchanged():
    assert _chunk_text("hola", 100, 10) == ["hola"]


def test_chunk_text_splits_with_overlap():
    text = "a" * 250
    chunks = _chunk_text(text, max_chars=100, overlap=20)
    assert len(chunks) >= 3
    assert all(len(c) <= 100 for c in chunks)
    # Overlap: end of first should match start of second
    assert chunks[0][-20:] == chunks[1][:20]


def test_serialize_row_includes_table_label():
    templates = [_column_to_template("name", "text"), _column_to_template("price", "numeric")]
    row = {"name": "Zapato", "price": "99.5"}
    text = _serialize_row(row, templates, "products", is_view=False)
    assert "Zapato" in text
    assert "products" in text.lower() or "Tabla" in text
