# =============================================================================
# P0 — Corpus sintético: PDFs válidos para ambos parsers
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.knowledge.parser_lab.p0.corpus import CORPUS, build_corpus_pdf
from src.knowledge.structure.opendataloader_parser import probe_pdf
from src.knowledge.structure.pdf_parser import PdfParser


def test_all_ready_corpus_pdfs_parse_with_pdfplumber() -> None:
    for doc in CORPUS:
        if doc.status != "ready":
            continue
        data = build_corpus_pdf(doc)
        assert data.startswith(b"%PDF")
        document = PdfParser().parse(
            data,
            organization_id=uuid4(),
            external_id=f"{doc.name}.pdf",
            source_name=f"{doc.name}.pdf",
        )
        document.check_consistency()
        assert document.page_count >= 1
        assert document.block_count >= 1


def test_tagged_corpus_has_structure_tree() -> None:
    tagged = next(doc for doc in CORPUS if doc.name == "tagged")
    data = build_corpus_pdf(tagged)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tagged.pdf"
        path.write_bytes(data)
        probe = probe_pdf(path)
    assert probe.has_structure_tree is True
    assert probe.page_heights and probe.page_heights[0] > 0


def test_fixed_width_and_table_corpus_have_tables() -> None:
    from src.knowledge.parser_lab.p0.corpus import corpus_by_name

    tables_doc = build_corpus_pdf(corpus_by_name("manual_tablas"))
    document = PdfParser().parse(
        tables_doc,
        organization_id=uuid4(),
        external_id="tablas.pdf",
        source_name="tablas.pdf",
    )
    assert document.table_count >= 1


def test_large_manual_builds_n_pages() -> None:
    from src.knowledge.parser_lab.p0.corpus import corpus_by_name

    doc = corpus_by_name("manual_tecnico_grande")
    data = build_corpus_pdf(doc, pages=30)
    parsed = PdfParser().parse(
        data,
        organization_id=uuid4(),
        external_id="manual.pdf",
        source_name="manual.pdf",
    )
    assert parsed.page_count == 30
    golden = __import__(
        "src.knowledge.parser_lab.p0.corpus", fromlist=["golden_for"]
    ).golden_for(doc, pages=30)
    assert len(golden["objects"]) >= 60  # 2+ objetos por página
