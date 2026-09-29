# =============================================================================
# PDF — filas de layout fixed-width sin bordes (genérico, sin dominio)
# =============================================================================
# Un layout de posiciones («14-22 Campo») suele venir sin reglas de tabla.
# pdfplumber no lo ve como grilla y las líneas quedaban como párrafos sueltos,
# donde el chunker podía partirlas. Acá se agrupan en un bloque TABLE.
from __future__ import annotations

import zlib
from uuid import uuid4

from src.core.domain.knowledge_v2 import StructuredBlockKind
from src.knowledge.structure import PdfParser, chunk_structured_document
from src.knowledge.structure.chunker import ChunkingConfig
from src.knowledge.structure.pdf_parser import _is_layout_row, _layout_row_groups

_FILAS = [
    "1-13 Record Header",
    "14-22 Advance Reservation First",
    "23-26 Advance Reservation Time",
    "64-67 Exception Time",
]


def _escape_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pdf_sin_bordes() -> bytes:
    """Una página: título, cuatro líneas de layout sin reglas y prosa al final."""
    ops: list[str] = []
    ops.append("BT /F1 12 Tf 60 730 Td (Record Layout) Tj ET")
    y = 700
    for fila in _FILAS:
        ops.append(f"BT /F1 10 Tf 60 {y} Td ({_escape_text(fila)}) Tj ET")
        y -= 14
    ops.append("BT /F1 11 Tf 60 630 Td (Texto normal despues del layout.) Tj ET")

    stream = zlib.compress("\n".join(ops).encode("latin-1"))
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


def test_is_layout_row_reconoce_rangos() -> None:
    assert _is_layout_row("14-22 Advance Reservation First")
    assert _is_layout_row("Bytes 64-67 Exception Time")
    assert not _is_layout_row("The valid values are 1-5")
    assert not _is_layout_row("")


def test_layout_row_groups_une_solo_consecutivas() -> None:
    lines = [
        {"text": "14-22 A"},
        {"text": "23-26 B"},
        {"text": "texto normal"},
        {"text": "64-67 C"},
        {"text": "70-80 D"},
        {"text": "90-99 E"},
    ]

    assert _layout_row_groups(lines) == [(0, 1), (3, 5)]


def test_una_fila_suelta_no_es_layout() -> None:
    lines = [{"text": "14-22 A"}, {"text": "texto normal"}]

    assert _layout_row_groups(lines) == []


def test_las_filas_de_layout_llegan_a_un_bloque_tabla() -> None:
    document = PdfParser().parse(
        _pdf_sin_bordes(),
        organization_id=uuid4(),
        external_id="layout.pdf",
        source_name="layout.pdf",
    )

    bloques_tabla = [b for b in document.blocks if b.kind is StructuredBlockKind.TABLE]
    assert bloques_tabla, "el layout debe ser un bloque TABLE, no párrafos sueltos"

    texto = "\n".join(b.text for b in bloques_tabla)
    for fila in _FILAS:
        assert fila in texto
    assert "\n" in texto, "las filas van una por línea"

    chunks = chunk_structured_document(document, config=ChunkingConfig())
    assert any("64-67 Exception Time" in c.content for c in chunks)
