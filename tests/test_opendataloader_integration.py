# =============================================================================
# OpenDataLoader — integración real (JVM). Se salta si no hay Java 11+.
# =============================================================================
# Para correr localmente:  $env:ZENT_ODL_JAVA="C:\ruta\java.exe"; pytest tests/test_opendataloader_integration.py
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.knowledge.structure.opendataloader_client import (
    OpenDataLoaderOptions,
    availability,
)
from src.knowledge.structure.opendataloader_parser import OpenDataLoaderPdfParser
from src.knowledge.structure.pdf_parser import PdfParser

_JAVA = os.environ.get("ZENT_ODL_JAVA", "")
_READY = bool(availability(OpenDataLoaderOptions(java=_JAVA)).get("ready"))

pytestmark = pytest.mark.skipif(
    not _READY,
    reason="OpenDataLoader no disponible (instalar opendataloader-pdf + Java 11+; set ZENT_ODL_JAVA)",
)


def _tiny_pdf_with_table() -> bytes:
    content = [
        "BT /F1 24 Tf 72 720 Td (Fare Class Rules) Tj ET",
        "BT /F1 12 Tf 72 692 Td (Fare Class F1 requires 14 days advance purchase.) Tj ET",
        "2 w",
    ]
    for y in (600, 580, 560):
        content.append(f"72 {y} m 540 {y} l S")
    for x in (72, 250, 540):
        content.append(f"{x} 560 m {x} 600 l S")
    content.append("BT /F1 12 Tf 80 586 Td (Code) Tj ET")
    content.append("BT /F1 12 Tf 258 586 Td (Description) Tj ET")
    content.append("BT /F1 12 Tf 80 566 Td (&F1) Tj ET")
    content.append("BT /F1 12 Tf 258 566 Td (Fare class, one-way) Tj ET")
    stream = "\n".join(content).encode("latin-1")
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj"
        ),
        b"4 0 obj << /Length %d >> stream\n" % len(stream) + stream + b"\nendstream endobj",
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
    xref = b"xref\n0 6\n0000000000 65535 f \n" + b"".join(
        f"{off:010d} 00000 n \n".encode() for off in offsets
    )
    trailer = (
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return head + body + xref + trailer


@pytest.mark.timeout(280)
def test_real_opendataloader_end_to_end() -> None:
    data = _tiny_pdf_with_table()
    parser = OpenDataLoaderPdfParser(options=OpenDataLoaderOptions(java=_JAVA))
    document = parser.parse(
        data,
        organization_id=uuid4(),
        external_id="sample.pdf",
        source_name="sample.pdf",
    )
    document.check_consistency()
    assert document.page_count == 1
    assert document.block_count >= 3
    assert document.table_count == 1

    table = document.tables[0]
    assert table.headers == ("Code", "Description")
    assert table.rows[0] == ("&F1", "Fare class, one-way")
    assert table.metadata["cells"]
    assert all(block.bbox is not None for block in document.blocks)
    assert document.metadata["parser"]["engine"] == "opendataloader"
    assert document.metadata["parser"]["version"] != ""
    assert document.metadata["structure_source"] == "inferred_layout"


@pytest.mark.timeout(280)
def test_real_opendataloader_matches_pdfplumber_contract() -> None:
    data = _tiny_pdf_with_table()
    odl = OpenDataLoaderPdfParser(options=OpenDataLoaderOptions(java=_JAVA)).parse(
        data,
        organization_id=uuid4(),
        external_id="sample.pdf",
        source_name="sample.pdf",
    )
    pdfplumber_doc = PdfParser().parse(
        data,
        organization_id=uuid4(),
        external_id="sample.pdf",
        source_name="sample.pdf",
    )
    # Mismo contrato downstream: ambos documentos son consistentes y tienen
    # páginas/bloques/tablas; los conteos exactos los decide el benchmark.
    odl.check_consistency()
    pdfplumber_doc.check_consistency()
    assert odl.page_count == pdfplumber_doc.page_count == 1
    assert odl.block_count >= 1
    assert pdfplumber_doc.block_count >= 1
    assert odl.table_count >= 1
