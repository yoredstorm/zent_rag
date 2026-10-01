# =============================================================================
# Document Understanding — fidelidad estructural, no “PDF a markdown”
# =============================================================================
from __future__ import annotations

import json
import zlib
from uuid import uuid4

from src.core.domain.knowledge_v2 import (
    BoundingBox,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.chunker import chunk_structured_document
from src.knowledge.structure.pdf_parser import PdfParser, _group_words_into_lines
from src.knowledge.understanding import (
    annotate_chunks,
    apply_understanding,
    expand_exact,
    understand_document,
)
from src.knowledge.understanding.layout import column_word_groups

ORG = uuid4()
NOTE = "Note: Characters following the matched portion stay literal."


def _block(
    text: str,
    order: int,
    page: int = 1,
    *,
    kind: StructuredBlockKind = StructuredBlockKind.PARAGRAPH,
    y0: float = 120.0,
    table_id: object | None = None,
) -> StructuredBlock:
    metadata: dict = {}
    if table_id is not None:
        metadata["table_id"] = str(table_id)
    return StructuredBlock(
        kind=kind,
        text=text,
        order=order,
        page=page,
        bbox=BoundingBox(page=page, x0=72, y0=y0, x1=420, y1=y0 + 12),
        metadata=metadata,
    )


def _document(
    blocks: list[StructuredBlock],
    *,
    sections: tuple[DocumentSection, ...] = (),
    tables: tuple[DocumentTable, ...] = (),
    pages: tuple[DocumentPage, ...] = (),
    title: str = "Record layout",
) -> StructuredDocument:
    doc_id = uuid4()
    rebound_sections = tuple(
        DocumentSection(
            id=section.id,
            document_id=doc_id,
            organization_id=ORG,
            section_path=section.section_path,
            heading=section.heading,
            depth=section.depth,
            parent_id=section.parent_id,
            order=section.order,
            page_start=section.page_start,
            page_end=section.page_end,
            block_ids=section.block_ids,
            text=section.text,
        )
        for section in sections
    )
    return StructuredDocument(
        id=doc_id,
        organization_id=ORG,
        external_id="layout.pdf",
        title=title,
        content_hash="pending",
        blocks=tuple(blocks),
        sections=rebound_sections,
        tables=tuple(
            DocumentTable(
                id=table.id,
                document_id=doc_id,
                organization_id=ORG,
                headers=table.headers,
                rows=table.rows,
                page=table.page,
                caption=table.caption,
                metadata=dict(table.metadata),
            )
            for table in tables
        ),
        pages=tuple(
            DocumentPage(
                id=page.id,
                document_id=doc_id,
                organization_id=ORG,
                page_number=page.page_number,
                text=page.text,
                block_ids=page.block_ids,
            )
            for page in pages
        ),
    )


def _fclas_document() -> StructuredDocument:
    heading = _block("FCLAS", 0, 42, kind=StructuredBlockKind.HEADING, y0=80)
    definition = _block("FCLAS — Fare Class", 1, 42, y0=110)
    positions = _block("Bytes 43-50", 2, 42, y0=140)
    pattern = _block("&&&F", 3, 42, y0=170)
    note = _block(NOTE, 4, 42, y0=210)
    section = DocumentSection(
        document_id=uuid4(),
        organization_id=ORG,
        section_path=("FCLAS",),
        heading="FCLAS",
        depth=0,
        order=0,
        page_start=42,
        page_end=42,
        block_ids=(heading.id,),
        text="FCLAS",
    )
    return _document(
        [heading, definition, positions, pattern, note],
        sections=(section,),
        title="Record 2 Rules",
    )


def test_simbolo_exacto_sobrevive_en_canonico_markdown_y_indice() -> None:
    understood = understand_document(_fclas_document(), file_hash="abc", filename="Rec2_Rules.pdf")
    payload = understood.metadata["understanding"]
    values = [item["value"] for item in payload["exact_literals"]]
    assert "&&&F" in values
    assert "F" not in values
    assert "&& F" not in values
    assert "&&&F" in payload["views"]["markdown"]
    assert "&&&F" in json.dumps(payload["views"]["ast"])
    assert payload["file_hash"] == "abc"
    assert payload["schema_version"] == "2"
    field = next(item for item in payload["technical_fields"] if item["name"] == "FCLAS")
    assert field["start_position"] == 43
    assert field["end_position"] == 50
    assert field["literal_pattern"] == "&&&F"
    assert any(item["relation_type"] == "HAS_NOTE" for item in payload["relations"])
    assert any(item["relation_type"] == "HAS_PATTERN" and item["target_literal"] == "&&&F" for item in payload["relations"])


def test_retrieval_de_mascara_expande_al_padre_sin_exigir_el_ejemplo() -> None:
    from src.knowledge.understanding.units import chunks_for_document

    understood = understand_document(_fclas_document())
    understood.check_consistency()
    chunks = annotate_chunks(understood, chunks_for_document(understood))
    hit = expand_exact(chunks, "&&&F")
    assert hit is not None
    assert hit["parent"] is not None
    assert "FCLAS" in hit["parent"].content
    assert "matched portion" in hit["parent"].content
    blob = "\n".join(chunk.content for chunk in chunks)
    assert "QNNF0SME" not in blob
    assert hit["child"].metadata["canonical_version"] == "2"
    tree = understood.metadata["understanding"]["tree"]
    assert tree["children"][0]["heading"] == "FCLAS"
    kinds = {node["type"] for node in tree["children"][0]["children"]}
    assert "note" in kinds or "definition" in kinds


def test_no_normaliza_mascaras_y_conserva_el_raw_de_letras_sueltas() -> None:
    spaced = _block("F C L A S", 0, y0=100)
    mask = _block("&&&F", 1, y0=140)
    understood = understand_document(_document([spaced, mask], title="codes"))
    texts = {block.metadata.get("raw_extraction", block.text): block.text for block in understood.blocks}
    assert texts["F C L A S"] == "FCLAS"
    assert any(block.text == "&&&F" for block in understood.blocks)
    raw = next(block.metadata.get("raw_extraction") for block in understood.blocks if block.text == "FCLAS")
    assert raw == "F C L A S"


def test_campo_generico_no_depende_de_un_dominio() -> None:
    heading = _block("FLAGS", 0, kind=StructuredBlockKind.HEADING, y0=80)
    definition = _block("FLAGS — control bits", 1, y0=110)
    mask = _block("??1?", 2, y0=140)
    section = DocumentSection(
        document_id=uuid4(),
        organization_id=ORG,
        section_path=("FLAGS",),
        heading="FLAGS",
        depth=0,
        order=0,
        page_start=1,
        page_end=1,
        block_ids=(heading.id,),
        text="FLAGS",
    )
    understood = understand_document(_document([heading, definition, mask], sections=(section,)))
    fields = understood.metadata["understanding"]["technical_fields"]
    assert any(item["name"] == "FLAGS" and item["literal_pattern"] == "??1?" for item in fields)
    assert "??1?" in [item["value"] for item in understood.metadata["understanding"]["exact_literals"]]


def test_tabla_multipagina_es_una_sola() -> None:
    headers = ("Bytes", "Field", "Description")
    first = DocumentTable(
        document_id=uuid4(),
        organization_id=ORG,
        headers=headers,
        rows=(("43-50", "FCLAS", "Fare Class"),),
        page=5,
        metadata={"table_index": 0},
    )
    second = DocumentTable(
        document_id=uuid4(),
        organization_id=ORG,
        headers=headers,
        rows=(headers, ("51-55", "NEXT", "Continuation")),
        page=6,
        metadata={"table_index": 0},
    )
    blocks = [
        _block("Bytes | Field | Description\n43-50 | FCLAS | Fare Class", 0, 5, kind=StructuredBlockKind.TABLE, table_id=first.id),
        _block("Bytes | Field | Description\n51-55 | NEXT | Continuation", 1, 6, kind=StructuredBlockKind.TABLE, table_id=second.id),
    ]
    understood = understand_document(_document(blocks, tables=(first, second)))
    assert len(understood.tables) == 1
    flat = " ".join(" ".join(row) for row in understood.tables[0].rows)
    assert "FCLAS" in flat and "NEXT" in flat
    assert understood.tables[0].metadata["merged_pages"] == [5, 6]
    superseded = [block for block in understood.blocks if block.metadata.get("superseded")]
    assert len(superseded) == 1


def test_nota_queda_ligada_a_la_tabla() -> None:
    table_id = uuid4()
    table = _block("Bytes | Field\n43-50 | FCLAS", 0, kind=StructuredBlockKind.TABLE, y0=100, table_id=table_id)
    note = _block("Note: applies to the row above.", 1, y0=180)
    understood = understand_document(_document([table, note]))
    relations = understood.metadata["understanding"]["relations"]
    assert any(
        item["relation_type"] == "HAS_NOTE" and item["from_block_id"] == str(table.id)
        for item in relations
    )


def test_pie_repetido_no_entra_en_chunks_semanticos() -> None:
    blocks: list[StructuredBlock] = []
    order = 0
    for page in range(1, 5):
        blocks.append(_block(f"Body paragraph {page}", order, page, y0=200))
        order += 1
        blocks.append(_block("Confidential Notice", order, page, y0=740))
        order += 1
    understood = understand_document(_document(blocks, title="Manual"))
    chrome = [block for block in understood.blocks if block.metadata.get("chrome") == "footer"]
    assert len(chrome) == 4
    chunks = chunk_structured_document(understood)
    blob = "\n".join(chunk.content for chunk in chunks)
    assert blob.count("Confidential Notice") == 0
    assert "Body paragraph 1" in blob


def test_ocr_solo_en_paginas_sin_text_layer() -> None:
    pages = (
        DocumentPage(document_id=uuid4(), organization_id=ORG, page_number=1, text="Pagina digital con texto suficiente para nativo."),
        DocumentPage(document_id=uuid4(), organization_id=ORG, page_number=2, text=""),
        DocumentPage(document_id=uuid4(), organization_id=ORG, page_number=3, text="Otra pagina digital con texto de sobra."),
    )
    calls: list[int] = []

    class _Ocr:
        def recognize_page(self, *, page_number: int, page_text: str, image: bytes | None = None) -> str:
            calls.append(page_number)
            return "LINEA ESCANEADA"

    without = understand_document(_document([_block("Pagina digital con texto suficiente para nativo.", 0)], pages=pages))
    assert without.metadata["understanding"]["report"]["ocr_pages"] == [2]
    assert without.metadata["understanding"]["quality"]["ocr_used"] is False

    with_provider = understand_document(
        _document([_block("Pagina digital con texto suficiente para nativo.", 0)], pages=pages),
        ocr_provider=_Ocr(),
    )
    assert calls == [2]
    assert with_provider.metadata["understanding"]["quality"]["ocr_used"] is True
    assert any(block.text == "LINEA ESCANEADA" for block in with_provider.blocks)


def test_dos_columnas_leen_izquierda_completa_luego_derecha() -> None:
    def word(text: str, x: float, y: float) -> dict:
        return {"text": text, "x0": x, "x1": x + 70, "top": y, "bottom": y + 10}

    words = [
        word("Left", 72, 100),
        word("One", 150, 100),
        word("Right", 400, 100),
        word("Uno", 480, 100),
        word("Left", 72, 140),
        word("Two", 150, 140),
        word("Right", 400, 140),
        word("Dos", 480, 140),
    ]
    groups = column_word_groups(words, 612)
    assert len(groups) == 2
    lines = [line["text"] for group in groups for line in _group_words_into_lines(group)]
    assert lines == ["Left One", "Left Two", "Right Uno", "Right Dos"]


def test_pdf_dos_columnas_no_mezcla_lineas() -> None:
    from src.knowledge.structure.pdf_parser import PdfParseOptions

    data = _pdf(
        [
            [
                "BT /F1 11 Tf 72 620 Td (Left One) Tj ET",
                "BT /F1 11 Tf 72 600 Td (Left Two) Tj ET",
                "BT /F1 11 Tf 360 620 Td (Right Uno) Tj ET",
                "BT /F1 11 Tf 360 600 Td (Right Dos) Tj ET",
            ]
        ]
    )
    document = PdfParser().parse(
        data,
        organization_id=ORG,
        external_id="cols.pdf",
        source_name="cols.pdf",
        options=PdfParseOptions(column_detection=True),
    )
    texts = [block.text for block in document.blocks]
    assert texts.index("Left One") < texts.index("Left Two") < texts.index("Right Uno") < texts.index("Right Dos")


def test_hash_canonico_estable_y_entendimiento_idempotente() -> None:
    original = _fclas_document()
    first = understand_document(original)
    second = understand_document(original)
    assert first.metadata["understanding"]["canonical_hash"] == second.metadata["understanding"]["canonical_hash"]
    understood = apply_understanding(original, file_hash="abc")
    assert [block.text for block in understood.blocks] == [
        block.text for block in first.blocks
    ]
    assert "understanding" in understood.metadata
    assert [section.section_path for section in understood.sections] == [
        section.section_path for section in original.sections
    ]
    assert understood.content_hash == first.content_hash


def test_referencia_ambigua_no_se_resuelve() -> None:
    first = _block("see Section 4.2 for the rule", 0, y0=100)
    understood = understand_document(_document([first], title="refs"))
    ref = understood.metadata["understanding"]["cross_references"][0]
    assert ref["target_candidate"] == "4.2"
    assert ref["resolved_target"] is None
    assert ref["confidence"] < 0.5


def test_texto_repetido_conserva_su_block_id() -> None:
    from src.knowledge.understanding.units import chunks_for_document

    text = "Applies when the condition holds."
    first_heading = _block("ONE", 0, kind=StructuredBlockKind.HEADING, y0=40)
    first_body = _block(text, 1, y0=80)
    second_heading = _block("TWO", 2, kind=StructuredBlockKind.HEADING, y0=140)
    second_body = _block(text, 3, y0=180)
    first_section = DocumentSection(
        document_id=uuid4(),
        organization_id=ORG,
        section_path=("ONE",),
        heading="ONE",
        depth=0,
        order=0,
        page_start=1,
        page_end=1,
        block_ids=(first_heading.id,),
        text="ONE",
    )
    second_section = DocumentSection(
        document_id=uuid4(),
        organization_id=ORG,
        section_path=("TWO",),
        heading="TWO",
        depth=0,
        order=1,
        page_start=1,
        page_end=1,
        block_ids=(second_heading.id,),
        text="TWO",
    )
    understood = understand_document(
        _document(
            [first_heading, first_body, second_heading, second_body],
            sections=(first_section, second_section),
        )
    )
    hits = [
        chunk
        for chunk in chunks_for_document(understood)
        if chunk.content.strip() == text
    ]
    assert len(hits) == 2
    assert {chunk.metadata["primary_block_id"] for chunk in hits} == {
        str(first_body.id),
        str(second_body.id),
    }


def test_literal_and_f_pertenece_a_fclas() -> None:
    understood = understand_document(_fclas_document(), filename="Rec2_Rules.pdf")
    literal = next(
        item
        for item in understood.metadata["understanding"]["exact_literals"]
        if item["value"] == "&&&F"
    )
    assert literal["field_name"] == "FCLAS"
    assert literal["section_id"]
    assert literal["block_id"]
    assert literal["page"] == 42
    assert literal["bbox"]["page"] == 42
    assert literal["canonical_source"] == "text_layer"
    assert literal["provenance"] == "EXTRACTED"


def test_unidad_chica_no_se_parte_y_la_grande_si() -> None:
    from src.knowledge.understanding.units import build_retrieval_units, chunks_from_retrieval_units

    heading = _block("DEF", 0, kind=StructuredBlockKind.HEADING, y0=40)
    definition = _block("TERM — " + ("a" * 220), 1, y0=80)
    section = DocumentSection(
        document_id=uuid4(),
        organization_id=ORG,
        section_path=("DEF",),
        heading="DEF",
        depth=0,
        order=0,
        page_start=1,
        page_end=1,
        block_ids=(heading.id,),
        text="DEF",
    )
    understood = understand_document(_document([heading, definition], sections=(section,)))
    units = build_retrieval_units(understood, budget=1200)
    definitions = [unit for unit in units if unit.unit_type == "DEFINITION"]
    assert len(definitions) == 1
    assert len(definitions[0].content) > 200
    huge = _block("PARA\n" + "\n".join(f"line {index} " + ("x" * 40) for index in range(40)), 1, y0=80)
    huge_doc = understand_document(_document([heading, huge], sections=(section,)))
    split_units = [
        unit
        for unit in build_retrieval_units(huge_doc, budget=80)
        if unit.unit_type == "PARAGRAPH_GROUP"
    ]
    assert len(split_units) > 1
    chunks = chunks_from_retrieval_units(understood, units)
    parent = next(chunk for chunk in chunks if chunk.metadata.get("level") == "parent")
    assert parent.metadata["retrieval_unit"] == "SECTION"
    assert "TERM" in parent.content


def test_tablas_con_misma_cabecera_y_distinto_caption_no_se_fusionan() -> None:
    headers = ("Code", "Description")
    first = DocumentTable(
        document_id=uuid4(),
        organization_id=ORG,
        headers=headers,
        rows=(("A", "Alpha"),),
        page=10,
        caption="Table A",
        metadata={"table_index": 0, "section_id": "section-a"},
    )
    second = DocumentTable(
        document_id=uuid4(),
        organization_id=ORG,
        headers=headers,
        rows=(("B", "Beta"),),
        page=11,
        caption="Table B",
        metadata={"table_index": 0, "section_id": "section-b"},
    )
    understood = understand_document(
        _document(
            [
                _block("Code | Description\nA | Alpha", 0, 10, kind=StructuredBlockKind.TABLE, table_id=first.id),
                _block("Code | Description\nB | Beta", 1, 11, kind=StructuredBlockKind.TABLE, table_id=second.id),
            ],
            tables=(first, second),
        )
    )
    assert len(understood.tables) == 2
    assert any(table.metadata.get("continuation_candidate") for table in understood.tables)
    assert all(table.metadata.get("merge_decision") != "merged" for table in understood.tables)


def test_layout_no_reordena_casos_debiles() -> None:
    from src.knowledge.understanding.layout import detect_columns

    def word(text: str, x: float, y: float, width: float = 70) -> dict:
        return {"text": text, "x0": x, "x1": x + width, "top": y, "bottom": y + 10}

    single = [word(f"W{index}", 72, 80 + index * 16) for index in range(8)]
    single_layout = detect_columns(single, 612)
    assert single_layout.applied is False
    assert single_layout.reason == "single_column"

    two = [
        word("Left", 72, 100),
        word("One", 150, 100),
        word("Right", 400, 100),
        word("Uno", 480, 100),
        word("Left", 72, 140),
        word("Two", 150, 140),
        word("Right", 400, 140),
        word("Dos", 480, 140),
    ]
    titled = [word("TITLE", 72, 40, width=460), *two]
    titled_layout = detect_columns(titled, 612)
    assert titled_layout.applied is True
    assert titled_layout.groups[0][0]["text"] == "TITLE"
    assert titled_layout.column_confidence >= 0.72

    foot = [*two, word("FOOT", 72, 700, width=460)]
    foot_layout = detect_columns(foot, 612)
    assert foot_layout.applied is True
    assert foot_layout.groups[-1][0]["text"] == "FOOT"

    sidebar = [word(f"L{index}", 72, 80 + (index % 4) * 20) for index in range(8)]
    sidebar += [word("S", 560, 100, width=24), word("B", 560, 140, width=24), word("A", 560, 180, width=24), word("R", 560, 220, width=24)]
    sidebar_layout = detect_columns(sidebar, 612)
    assert sidebar_layout.applied is False

    table = [
        *two,
        word("C0", 72, 220, width=40),
        word("C1", 140, 220, width=40),
        word("C2", 210, 220, width=40),
        word("C3", 280, 220, width=40),
        word("C4", 360, 220, width=40),
        word("C5", 430, 220, width=40),
        word("C6", 500, 220, width=40),
    ]
    table_layout = detect_columns(table, 612)
    assert table_layout.applied is False
    three = []
    for y in (100, 140, 180):
        three.extend([word("A", 60, y), word("B", 250, y), word("C", 460, y)])
    assert detect_columns(three, 612).applied is False


def test_sigla_suelta_no_inventa_technical_specification() -> None:
    understood = understand_document(_document([_block("ABC", 0, y0=100)], title="notes"))
    profile = understood.metadata["understanding"]["profile"]
    assert profile["document_type"] == "document"
    assert profile["profile_confidence"] < 0.7
    quality = understood.metadata["understanding"]["quality"]
    assert quality["quality_is_estimate"] is False
    assert "text_fidelity" in quality["dimensions"]
    assert "section_confidence" in quality["dimensions"]


def test_artefacto_canonico_sale_de_metadata_si_supera_el_umbral(tmp_path) -> None:
    from src.knowledge.understanding.artifacts import CanonicalArtifactStore

    store = CanonicalArtifactStore(tmp_path)
    placed = store.place(
        organization_id="org",
        document_id="doc",
        markdown="x" * 40,
        ast={"type": "document", "children": [{"block_id": "b1"}]},
        max_inline_bytes=10,
    )
    assert placed["storage"] == "artifact"
    assert "markdown" not in placed
    assert (tmp_path / "org" / "understanding" / "doc" / "canonical.md").read_text(encoding="utf-8").startswith("x")


def test_retrieval_hash_ignora_el_informe() -> None:
    first = understand_document(_fclas_document())
    second = understand_document(_fclas_document())
    assert first.metadata["understanding"]["retrieval_hash"] == second.metadata["understanding"]["retrieval_hash"]
    assert first.content_hash == first.metadata["understanding"]["retrieval_hash"]
    changed = _fclas_document()
    blocks = list(changed.blocks)
    blocks[3] = _block("&&&G", 3, 42, y0=170)
    altered = understand_document(_document(blocks, sections=changed.sections, title=changed.title))
    assert altered.metadata["understanding"]["retrieval_hash"] != first.metadata["understanding"]["retrieval_hash"]


def test_diagnostico_separa_capas_sin_llm() -> None:
    from src.knowledge.understanding.diagnose import diagnose_question, find_literal, regression_gate, score_expected
    from src.knowledge.understanding.units import chunks_for_document

    understood = understand_document(_fclas_document(), filename="Rec2_Rules.pdf")
    chunks = chunks_for_document(understood)
    found = find_literal(understood, chunks, "&&&F")
    assert found["found"] is True
    assert found["field_name"] == "FCLAS"
    assert found["parent_heading"] == "FCLAS"
    query = (
        "consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir "
        "que el farebasis debe ser de ese tamaño? en el boleto viene asi QNNF0SME cumplira?"
    )
    report = diagnose_question(
        understood,
        chunks,
        query,
        field_name="FCLAS",
        literal="&&&F",
        example="QNNF0SME",
    )
    assert report["layers"]["INGESTION"] == "PASS"
    assert report["layers"]["EXACT_RETRIEVAL"] == "PASS"
    assert report["layers"]["STRUCTURAL_EXPANSION"] == "PASS"
    assert report["layers"]["EVIDENCE"] == "PASS"
    assert report["layers"]["GENERATION"] == "SKIPPED"
    assert report["example"]["source_match_required"] is False
    scores = score_expected(
        understood,
        {"sections": ["FCLAS"], "exact_literals": ["&&&F"], "fields": ["FCLAS"], "tables": 0},
    )
    assert scores["exact_literal_recall"] == 1
    assert score_expected(understood, None) == {}
    assert regression_gate(scores, {**scores, "exact_literal_recall": 0.0}) == ["exact_literal_recall"]


def test_rol_de_provider_rearma_derivados() -> None:
    class _Provider:
        def correct(self, *, raw_text: str, layout_blocks: list[dict], page_image: bytes | None = None) -> dict:
            target = next(block for block in layout_blocks if str(block.get("text") or "").startswith("Note:"))
            return {"block_roles": {target["id"]: "warning"}, "confidence": 0.66}

    understood = understand_document(_fclas_document(), model_provider=_Provider())
    note = next(block for block in understood.blocks if block.text.startswith("Note:"))
    assert note.metadata["derived_by"] == "model"
    assert note.metadata["role"] == "warning"
    assert any(
        item["relation_type"] == "HAS_WARNING" for item in understood.metadata["understanding"]["relations"]
    )


def _shape(document) -> dict:
    return {
        "blocks": [(block.kind.value, block.text, block.page, block.order) for block in document.blocks],
        "sections": [(section.heading, section.section_path, section.page_start) for section in document.sections],
        "tables": [(table.headers, table.rows, table.page, table.caption) for table in document.tables],
    }


def _pdf(page_ops: list[list[str]]) -> bytes:
    """PDF mínimo de varias páginas. Coordenadas PDF (origen abajo)."""
    streams = [zlib.compress("\n".join(ops).encode("latin-1")) for ops in page_ops]
    count = len(page_ops)
    font_id = 3 + 2 * count
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(count))
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj")
    objects.append(
        f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {count} >> endobj".encode()
    )
    for index, stream in enumerate(streams):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        objects.append(
            (
                f"{page_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >> endobj"
            ).encode()
        )
        objects.append(
            f"{content_id} 0 obj << /Length {len(stream)} /Filter /FlateDecode >> stream\n".encode()
            + stream
            + b"\nendstream endobj"
        )
    objects.append(
        f"{font_id} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj".encode()
    )
    head = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    pos = len(head)
    for obj in objects:
        offsets.append(pos)
        body += obj + b"\n"
        pos += len(obj) + 1
    size = font_id + 1
    xref = b"xref\n0 %d\n0000000000 65535 f \n" % size
    xref += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    trailer = (
        f"trailer << /Size {size} /Root 1 0 R >>\nstartxref\n{pos}\n%%EOF\n".encode()
    )
    return head + body + xref + trailer
