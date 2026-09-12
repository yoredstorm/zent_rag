# =============================================================================
# Knowledge V2 — Hierarchical chunking (Phase C slice 1)
# =============================================================================
# document_structure + parent_child: chunk padre por sección hoja + hijos
# pequeños para retrieval; bloques fuera de secciones → root implícito.
# =============================================================================
from __future__ import annotations

import zlib
from uuid import uuid4

from src.core.domain.knowledge_v2 import ChunkType
from src.knowledge.structure import (
    TextParser,
    assign_blocks_to_sections,
    chunk_structured_document,
)
from src.knowledge.structure.chunker import ChunkingConfig
from src.knowledge.structure.pdf_parser import PdfParser

_MARKDOWN_WITH_SECTIONS = """# Manual Operaciones

## 5. Compensación

Comisión 5% para contratos vigentes.

### 5.2 Comisiones

| Clave | Valor |
| --- | --- |
| A | 5% |

- cláusula uno
"""


def _markdown_doc():
    return TextParser().parse(
        _MARKDOWN_WITH_SECTIONS.encode("utf-8"),
        organization_id=uuid4(),
        external_id="manual.md",
    )


def test_assign_blocks_attaches_body_blocks_to_active_section() -> None:
    doc = assign_blocks_to_sections(_markdown_doc())
    root, section5, section52 = doc.sections
    assert root.heading == "Manual Operaciones"
    assert section5.heading == "5. Compensación"
    assert section52.heading == "5.2 Comisiones"
    # el párrafo cae bajo 5. Compensación; tabla+lista bajo 5.2
    assert any("Comisión 5%" in b.text for b in doc.blocks if b.id in section5.block_ids)
    assert any("Clave" in b.text for b in doc.blocks if b.id in section52.block_ids)


def test_chunk_structured_document_builds_parent_child_tree() -> None:
    source = _markdown_doc()
    doc = chunk_structured_document(source, config=ChunkingConfig(child_max_chars=600))
    assert doc

    parents = [c for c in doc if c.chunk_type is ChunkType.DOCUMENT_STRUCTURE]
    children = [c for c in doc if c.chunk_type is ChunkType.PARENT_CHILD]
    assert parents
    assert children
    parent_ids = {p.id for p in parents}
    for child in children:
        assert child.parent_id in parent_ids
        assert child.content
        assert child.content_hash
        assert child.page_start is None  # markdown sin páginas

    # parent de la sección hoja debe incluir heading + contenidos
    leaves = [
        s for s in source.sections if not any(o.parent_id == s.id for o in source.sections)
    ]
    leaf = leaves[0]
    assert leaf.heading == "5.2 Comisiones"
    leaf_parents = [p for p in parents if p.section_id == leaf.id]
    assert leaf_parents
    assert "Clave" in leaf_parents[0].content

    # chunk_index secuencial 0..N-1
    assert [c.chunk_index for c in doc] == list(range(len(doc)))

    # los child chunks mantienen el char_range válido cuando el padre lo tiene
    for child in children:
        if child.char_range is not None:
            assert child.char_range.start < child.char_range.end


def test_chunk_without_sections_uses_implicit_root() -> None:
    doc = TextParser().parse(
        "Texto plano sin headings repartido en varios párrafos.\n\nSegundo párrafo.".encode("utf-8"),
        organization_id=uuid4(),
        external_id="nota.txt",
    )
    chunks = chunk_structured_document(doc, config=ChunkingConfig(child_max_chars=30))
    assert chunks
    assert all(c.section_id is None for c in chunks)
    assert all(c.parent_id is None for c in chunks if c.chunk_type is ChunkType.DOCUMENT_STRUCTURE)


def _tiny_pdf() -> bytes:
    show = (
        "BT /F1 12 Tf 72 720 Td (Section 5.2 Commission) Tj ET\n"
        "BT /F1 12 Tf 72 680 Td (Commission rate 5 percent.) Tj ET\n"
    ).encode("latin-1")
    stream = zlib.compress(show)
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj"
        ),
        b"4 0 obj << /Length %d /Filter /FlateDecode >> stream\n" % len(stream)
        + stream
        + b"\nendstream endobj",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
    ]
    head = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    pos = len(head)
    for obj in objs:
        offsets.append(pos)
        body += obj + b"\n"
        pos += len(obj) + 1
    xref_pos = pos
    xref = (
        b"xref\n0 6\n0000000000 65535 f \n"
        + b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    )
    trailer = (
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return head + body + xref + trailer


def test_chunk_pdf_preserves_page_spans() -> None:
    pdf_doc = PdfParser().parse(
        _tiny_pdf(),
        organization_id=uuid4(),
        external_id="manual.pdf",
    )
    chunks = chunk_structured_document(pdf_doc, config=ChunkingConfig(child_max_chars=40))
    assert chunks
    for chunk in chunks:
        assert chunk.page_start == 1
        assert chunk.page_end == 1
    assert any("Commission" in c.content for c in chunks)
