# =============================================================================
# Knowledge Tabular V2 — parsers estructurados XLSX/CSV (StructuredDocument)
# =============================================================================
from __future__ import annotations

from uuid import UUID

import pytest

from src.knowledge.structure import (
    CsvParser,
    StructuredParserError,
    XlsxParser,
    get_parser,
    supported_extensions,
)
from src.knowledge.structure.base import StructuredParser
from tests import tabular_fixtures as fx

_ORG = UUID("00000000-0000-0000-0000-0000000000aa")
_SOURCE = UUID("00000000-0000-0000-0000-0000000000bb")


def test_registry_exposes_tabular_parsers() -> None:
    assert isinstance(get_parser("xlsx"), XlsxParser)
    assert isinstance(get_parser("XLSM"), XlsxParser)
    assert isinstance(get_parser("csv"), CsvParser)
    assert isinstance(get_parser("tsv"), CsvParser)
    assert isinstance(get_parser(".xlsx"), XlsxParser)
    extensions = supported_extensions()
    for extension in ("xlsx", "xlsm", "csv", "tsv", "pdf", "docx", "md"):
        assert extension in extensions


def test_xlsx_parser_builds_tabular_document_with_skeleton() -> None:
    parser = XlsxParser()
    document = parser.parse(
        fx.atpco_workbook_bytes(),
        organization_id=_ORG,
        external_id="obj/ATPCO_TEST.xlsx",
        source_id=_SOURCE,
        source_name="ATPCO_TEST.xlsx",
    )
    document.check_consistency()

    assert document.tabular is not None
    assert document.metadata["tabular"] is True
    assert document.metadata["table_count"] == 1
    assert document.metadata["row_count"] == 4
    assert document.metadata["sheet_count"] == 1

    # Esqueleto: heading de hoja + sección de tabla (sin volcar 100k filas).
    kinds = [block.kind.value for block in document.blocks]
    assert "heading" in kinds
    assert "table" in kinds
    assert [section.heading for section in document.sections] == [
        "Record2",
        "ATPCO RECORD 2 RULES",
    ]
    # DocumentTable conserva SOLO el schema (las filas viven en tabular).
    assert document.table_count == 1
    table = document.tables[0]
    assert table.headers == (
        "Field Name",
        "Start Position",
        "End Position",
        "Length",
        "Description",
    )
    assert table.rows == ()
    assert table.metadata["row_count"] == 4
    assert table.metadata["columns"][1]["semantic_type"] == "position"


def test_csv_parser_builds_tabular_document_and_detects_dialect() -> None:
    parser = CsvParser()
    document = parser.parse(
        fx.semicolon_csv_bytes(),
        organization_id=_ORG,
        external_id="obj/semi.csv",
        source_id=_SOURCE,
        source_name="semi.csv",
    )
    document.check_consistency()
    assert document.tabular is not None
    assert document.tabular.format.value == "csv"
    assert document.metadata["dialect"]["delimiter"] == ";"
    table = document.tabular.tables()[0]
    assert table.columns[1].original_name == "Start Position"
    assert table.rows[0].values[1] == "28"


def test_csv_parser_latin1_and_bom() -> None:
    parser = CsvParser()
    latin = parser.parse(
        fx.latin1_csv_bytes(),
        organization_id=_ORG,
        external_id="obj/latin.csv",
        source_id=_SOURCE,
        source_name="latin.csv",
    )
    assert latin.tabular is not None
    assert latin.tabular.tables()[0].columns[0].original_name == "Código"

    bom = parser.parse(
        fx.utf8_bom_csv_bytes(),
        organization_id=_ORG,
        external_id="obj/bom.csv",
        source_id=_SOURCE,
        source_name="bom.csv",
    )
    assert bom.metadata["dialect"]["has_bom"] is True
    assert bom.tabular is not None
    assert bom.tabular.tables()[0].columns[0].original_name == "Field Name"


def test_parsers_never_break_the_generic_contract() -> None:
    assert issubclass(XlsxParser, StructuredParser)
    assert issubclass(CsvParser, StructuredParser)


def test_invalid_xlsx_raises_structured_parser_error() -> None:
    parser = XlsxParser()
    with pytest.raises(StructuredParserError):
        parser.parse(
            b"not-a-real-xlsx",
            organization_id=_ORG,
            external_id="obj/broken.xlsx",
            source_id=_SOURCE,
            source_name="broken.xlsx",
        )


def test_empty_csv_raises_structured_parser_error() -> None:
    parser = CsvParser()
    with pytest.raises(StructuredParserError):
        parser.parse(
            b"",
            organization_id=_ORG,
            external_id="obj/empty.csv",
            source_id=_SOURCE,
            source_name="empty.csv",
        )
