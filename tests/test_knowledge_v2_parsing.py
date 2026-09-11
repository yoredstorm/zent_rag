# =============================================================================
# Knowledge V2 — Phase B document parsing (StructuredDocument + provenance)
# =============================================================================
# Pure parser tests: real bytes in, StructuredDocument out. No productive mocks,
# no engine/Qdrant/LLM stubs. V1 normalizers stay the production path.
# =============================================================================
from __future__ import annotations

import hashlib
import io
import zipfile
import zlib
from pathlib import Path
from uuid import uuid4

import pytest

from src.core.config import Settings, get_settings
from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
    PAGE_ABSENT_STUB_FORMAT,
    StructuredBlock,
    StructuredBlockKind,
)

_SESSION_KEY = "aa" * 32


def _settings(**_env: str) -> Settings:
    get_settings.cache_clear()
    return Settings()


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_text_pdf(pages: list[list[tuple[int, str]]]) -> bytes:
    """Minimal multi-page PDF. Each page is (font_size, text) lines top-to-bottom."""
    font_obj = 3 + 2 * len(pages)
    page_nums: list[int] = []
    bodies: dict[int, bytes] = {}
    obj_num = 3
    for page_items in pages:
        parts = ["BT"]
        first = True
        for size, text in page_items:
            escaped = _pdf_escape(text)
            if first:
                parts.append(f"/F1 {size} Tf")
                parts.append("72 720 Td")
                parts.append(f"({escaped}) Tj")
                first = False
            else:
                parts.append(f"/F1 {size} Tf")
                parts.append("0 -28 Td")
                parts.append(f"({escaped}) Tj")
        parts.append("ET")
        raw = "\n".join(parts).encode("latin-1", "replace")
        stream = zlib.compress(raw)
        content_num = obj_num + 1
        bodies[content_num] = (
            b"<< /Length %d /Filter /FlateDecode >> stream\n" % len(stream) + stream + b"\nendstream"
        )
        bodies[obj_num] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>" % (content_num, font_obj)
        )
        page_nums.append(obj_num)
        obj_num += 2
    kids = " ".join(f"{n} 0 R" for n in page_nums)
    bodies[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    bodies[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids.encode(), len(pages))
    bodies[font_obj] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    ordered = sorted(bodies)
    head = b"%PDF-1.4\n"
    chunks: list[bytes] = []
    offsets: list[int] = []
    pos = len(head)
    for num in ordered:
        chunk = b"%d 0 obj " % num + bodies[num] + b" endobj\n"
        offsets.append(pos)
        chunks.append(chunk)
        pos += len(chunk)
    xref_pos = pos
    xref = b"xref\n0 %d\n0000000000 65535 f \n" % (len(ordered) + 1)
    xref += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    trailer = (
        b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n" % (len(ordered) + 1)
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return head + b"".join(chunks) + xref + trailer


def _tiny_docx(*, heading: str, body: str, table_rows: list[list[str]] | None = None) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<w:document xmlns:w="{ns}"><w:body>',
        "<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr>"
        f"<w:r><w:t>{heading}</w:t></w:r></w:p>",
        f"<w:p><w:r><w:t>{body}</w:t></w:r></w:p>",
    ]
    if table_rows:
        parts.append("<w:tbl>")
        for row in table_rows:
            parts.append("<w:tr>")
            for cell in row:
                parts.append(f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>")
            parts.append("</w:tr>")
        parts.append("</w:tbl>")
    parts.append("</w:body></w:document>")
    document_xml = "".join(parts)
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    sheet = wb.active
    assert sheet is not None
    sheet.title = "Refunds"
    sheet["A1"] = "Item"
    sheet["B1"] = "Days"
    sheet["A2"] = "Standard"
    sheet["B2"] = 30
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _assert_block_provenance(block: StructuredBlock, *, expect_page: bool) -> None:
    assert block.block_index == block.order
    assert block.content == block.text
    assert block.content_type == block.kind.value
    assert block.section_path == block.heading_path
    assert block.page_number == block.page
    assert block.content_hash == hashlib.sha256(block.text.encode("utf-8")).hexdigest()
    locator = block.citation_locator()
    assert locator["block_index"] == block.order
    assert locator["content_type"] == block.kind.value
    assert locator["content_hash"] == block.content_hash
    if expect_page:
        assert block.page is not None and block.page >= 1
        assert block.page_absent_reason is None
        assert locator["page_number"] == block.page
    else:
        assert block.page is None
        assert block.page_absent_reason, "null page must carry an explicit reason"
        assert locator["page_absent_reason"] == block.page_absent_reason
    if not block.heading_path:
        reason = block.metadata.get("section_absent_reason")
        assert reason, "empty section_path must carry section_absent_reason in metadata"


def test_parse_structured_import_exists() -> None:
    from src.knowledge.v2.parsing import parse_structured

    assert callable(parse_structured)


def test_gated_parse_returns_none_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PORTAL_SESSION_KEY", _SESSION_KEY)
    monkeypatch.delenv("RAG_KNOWLEDGE_V2_ENABLED", raising=False)
    _settings()
    from src.knowledge.v2.parsing import parse_structured_if_enabled

    org = uuid4()
    result = parse_structured_if_enabled(
        b"# Hello\n",
        "note.md",
        organization_id=org,
    )
    assert result is None
    get_settings.cache_clear()


def test_gated_parse_returns_document_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PORTAL_SESSION_KEY", _SESSION_KEY)
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_ENABLED", "true")
    _settings()
    from src.knowledge.v2.parsing import parse_structured_if_enabled

    org = uuid4()
    doc = parse_structured_if_enabled(
        b"# Hello\n\nWorld.\n",
        "note.md",
        organization_id=org,
    )
    assert doc is not None
    assert doc.organization_id == org
    get_settings.cache_clear()


def test_v1_pdf_normalizer_still_returns_str() -> None:
    from src.knowledge.normalize.pdf_normalizer import PdfNormalizer

    data = build_text_pdf([[(12, "Hello from V1")]])
    text = PdfNormalizer().normalize(data, source_name="v1.pdf")
    assert isinstance(text, str)
    assert "Hello from V1" in text


def test_pdf_parser_populates_page_section_block() -> None:
    from src.knowledge.v2.parsing import parse_structured

    org = uuid4()
    source = uuid4()
    workspace = uuid4()
    data = build_text_pdf(
        [
            [(24, "Refund Policy"), (12, "Customers may request a refund within 30 days.")],
            [(18, "Exceptions"), (12, "Digital goods are not refundable.")],
        ]
    )
    doc = parse_structured(
        data,
        "policy.pdf",
        organization_id=org,
        workspace_id=workspace,
        source_id=source,
    )
    assert doc.organization_id == org
    assert doc.workspace_id == workspace
    assert doc.source_id == source
    assert doc.mime_type == "application/pdf"
    assert doc.blocks
    pages = {b.page for b in doc.blocks}
    assert 1 in pages
    assert 2 in pages
    for block in doc.blocks:
        _assert_block_provenance(block, expect_page=True)
    headings = [b for b in doc.blocks if b.kind in (StructuredBlockKind.HEADING, StructuredBlockKind.TITLE)]
    assert headings, "PDF adapter should detect larger-font headings"
    body = [b for b in doc.blocks if "30 days" in b.text]
    assert body
    assert "Refund Policy" in body[0].heading_path or "Refund Policy" in body[0].text
    locators = [b.citation_locator() for b in doc.blocks]
    assert all("page_number" in loc for loc in locators)
    assert doc.metadata.get("reading_order") == "pdfminer_layout"


def test_docx_parser_section_path_and_table() -> None:
    from src.knowledge.v2.parsing import parse_structured

    org = uuid4()
    data = _tiny_docx(
        heading="Refund Policy",
        body="Customers may request a refund within 30 days.",
        table_rows=[["Item", "Days"], ["Standard", "30"]],
    )
    doc = parse_structured(data, "policy.docx", organization_id=org)
    assert doc.mime_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert doc.blocks
    for block in doc.blocks:
        _assert_block_provenance(block, expect_page=False)
        assert block.page_absent_reason == PAGE_ABSENT_FORMAT_HAS_NO_PAGES
    headings = [b for b in doc.blocks if b.kind in (StructuredBlockKind.HEADING, StructuredBlockKind.TITLE)]
    assert any("Refund Policy" in b.text for b in headings)
    tables = [b for b in doc.blocks if b.kind is StructuredBlockKind.TABLE]
    assert tables
    assert "Standard" in tables[0].text
    para = next(b for b in doc.blocks if "30 days" in b.text)
    assert para.section_path[0] == "Refund Policy"


def test_markdown_parser_heading_path_and_char_offsets() -> None:
    from src.knowledge.v2.parsing import parse_structured

    org = uuid4()
    text = "# Refunds\n\n30 days to return.\n\n## Exceptions\n\nDigital goods excluded.\n"
    doc = parse_structured(text.encode(), "guide.md", organization_id=org)
    assert doc.blocks
    for block in doc.blocks:
        _assert_block_provenance(block, expect_page=False)
        assert block.page_absent_reason == PAGE_ABSENT_FORMAT_HAS_NO_PAGES
    para = next(b for b in doc.blocks if "Digital goods" in b.text)
    assert para.section_path == ("Refunds", "Exceptions")
    assert para.char_start is not None
    assert para.char_end is not None
    assert text[para.char_start : para.char_end].strip().startswith("Digital")


def test_html_parser_headings_lists_tables() -> None:
    from src.knowledge.v2.parsing import parse_structured

    html = """
    <html><head><title>Handbook</title></head>
    <body>
      <h1>Refunds</h1>
      <p>30 days to return.</p>
      <h2>Exceptions</h2>
      <ul><li>Digital goods</li></ul>
      <table><tr><th>Item</th><th>Days</th></tr><tr><td>Standard</td><td>30</td></tr></table>
    </body></html>
    """
    org = uuid4()
    doc = parse_structured(html.encode(), "guide.html", organization_id=org)
    assert doc.title == "Handbook" or "Refunds" in doc.title
    for block in doc.blocks:
        _assert_block_provenance(block, expect_page=False)
    assert any(b.kind is StructuredBlockKind.TABLE and "Standard" in b.text for b in doc.blocks)
    assert any(b.kind is StructuredBlockKind.LIST and "Digital goods" in b.text for b in doc.blocks)
    para = next(b for b in doc.blocks if "30 days" in b.text)
    assert para.section_path[0] == "Refunds"


def test_txt_parser_null_page_with_reason() -> None:
    from src.knowledge.v2.parsing import parse_structured

    org = uuid4()
    doc = parse_structured(b"Hello.\n\nSecond paragraph.\n", "notes.txt", organization_id=org)
    assert len(doc.blocks) >= 2
    for block in doc.blocks:
        _assert_block_provenance(block, expect_page=False)
        assert block.page_absent_reason == PAGE_ABSENT_FORMAT_HAS_NO_PAGES
        assert block.metadata.get("section_absent_reason")


def test_csv_and_xlsx_and_json_emit_table_or_structured_blocks() -> None:
    from src.knowledge.v2.parsing import parse_structured

    org = uuid4()
    csv_doc = parse_structured(b"item,days\nStandard,30\n", "data.csv", organization_id=org)
    assert any(b.kind is StructuredBlockKind.TABLE for b in csv_doc.blocks)
    for block in csv_doc.blocks:
        _assert_block_provenance(block, expect_page=False)

    xlsx_doc = parse_structured(_xlsx_bytes(), "data.xlsx", organization_id=org)
    assert any("Refunds" in b.heading_path or "Refunds" in b.text for b in xlsx_doc.blocks)
    for block in xlsx_doc.blocks:
        _assert_block_provenance(block, expect_page=False)

    json_doc = parse_structured(
        b'{"policy": "refund", "days": 30}',
        "facts.json",
        organization_id=org,
    )
    assert json_doc.blocks
    for block in json_doc.blocks:
        _assert_block_provenance(block, expect_page=False)


def test_stub_format_sets_explicit_null_page_reason() -> None:
    from src.knowledge.v2.parsing import parse_structured

    org = uuid4()
    doc = parse_structured(b"not a real deck", "slides.pptx", organization_id=org)
    assert doc.metadata.get("adapter") == "stub"
    assert doc.blocks
    for block in doc.blocks:
        _assert_block_provenance(block, expect_page=False)
        assert block.page_absent_reason == PAGE_ABSENT_STUB_FORMAT


def test_identity_is_copied_not_invented() -> None:
    from src.knowledge.v2.parsing import parse_structured

    org_a = uuid4()
    org_b = uuid4()
    doc_a = parse_structured(b"# A\n", "a.md", organization_id=org_a)
    doc_b = parse_structured(b"# B\n", "b.md", organization_id=org_b)
    assert doc_a.organization_id == org_a
    assert doc_b.organization_id == org_b
    assert doc_a.organization_id != doc_b.organization_id


def test_v1_engine_still_does_not_import_v2_parsing() -> None:
    engine = Path("src/knowledge/engine/service.py").read_text(encoding="utf-8")
    assert "knowledge.v2" not in engine
    assert "parse_structured" not in engine
    file_source = Path("src/knowledge/connectors/file_source.py").read_text(encoding="utf-8")
    assert "parse_structured" not in file_source
    assert "knowledge.v2" not in file_source
