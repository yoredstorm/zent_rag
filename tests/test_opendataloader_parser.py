# =============================================================================
# OpenDataLoader parser — contrato StructuredParser con runner inyectado
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.knowledge.structure.base import StructuredParserError
from src.knowledge.structure.opendataloader_client import (
    OpenDataLoaderConversion,
    OpenDataLoaderOptions,
)
from src.knowledge.structure.opendataloader_parser import (
    OpenDataLoaderPdfParser,
    PdfProbe,
)
from src.knowledge.structure.pdf_parser import PdfParseOptions


def _payload() -> dict:
    return {
        "file name": "doc.pdf",
        "number of pages": 1,
        "author": None,
        "title": "Doc",
        "creation date": None,
        "modification date": None,
        "kids": [
            {
                "type": "paragraph",
                "id": 1,
                "page number": 1,
                "bounding box": [10.0, 700.0, 100.0, 720.0],
                "font": "Helvetica",
                "font size": 12.0,
                "text color": "[0.0]",
                "content": "contenido",
            }
        ],
    }


def _runner(captured: dict):
    def run(data: bytes, *, options, use_struct_tree: bool, workdir):
        captured["use_struct_tree"] = use_struct_tree
        captured["options"] = options
        captured["workdir"] = Path(workdir)
        captured["input_exists"] = (Path(workdir) / "input.pdf").is_file()
        return OpenDataLoaderConversion(
            data=_payload(),
            elapsed_seconds=0.5,
            output_json_bytes=321,
            java="java-test",
        )

    return run


def test_parser_contract_with_injected_runner() -> None:
    captured: dict = {}
    parser = OpenDataLoaderPdfParser(
        runner=_runner(captured),
        page_probe=lambda path: PdfProbe(page_heights=(792.0,), has_structure_tree=False),
    )
    document = parser.parse(
        b"%PDF-1.4 fake",
        organization_id=uuid4(),
        external_id="doc.pdf",
        source_id=uuid4(),
        source_name="doc.pdf",
        options=PdfParseOptions(column_detection=True),
    )
    document.check_consistency()
    assert captured["use_struct_tree"] is False
    assert captured["input_exists"] is True
    assert not captured["workdir"].exists()  # el temp se limpia
    parser_meta = document.metadata["parser"]
    assert parser_meta["engine"] == "opendataloader"
    assert parser_meta["version"] != ""
    assert parser_meta["mode"] == "local"
    assert parser_meta["structure_source"] == "inferred_layout"
    assert parser_meta["requested_columns"] is True
    assert parser_meta["conversion"]["output_json_bytes"] == 321
    assert document.blocks[0].metadata["parser_engine"] == "opendataloader"


def test_struct_tree_auto_uses_probe() -> None:
    captured: dict = {}
    parser = OpenDataLoaderPdfParser(
        runner=_runner(captured),
        page_probe=lambda path: PdfProbe(page_heights=(792.0,), has_structure_tree=True),
    )
    document = parser.parse(
        b"%PDF-1.4 fake",
        organization_id=uuid4(),
        external_id="tagged.pdf",
        source_name="tagged.pdf",
    )
    assert captured["use_struct_tree"] is True
    assert document.metadata["parser"]["structure_source"] == "tagged_pdf"


def test_struct_tree_policy_override() -> None:
    captured: dict = {}
    parser = OpenDataLoaderPdfParser(
        options=OpenDataLoaderOptions(use_struct_tree=True),
        runner=_runner(captured),
        page_probe=lambda path: PdfProbe(page_heights=(792.0,), has_structure_tree=False),
    )
    parser.parse(
        b"%PDF-1.4 fake",
        organization_id=uuid4(),
        external_id="forced.pdf",
        source_name="forced.pdf",
    )
    assert captured["use_struct_tree"] is True


def test_runner_error_is_normalized() -> None:
    def broken(data, *, options, use_struct_tree, workdir):
        raise RuntimeError("jvm exploded")

    parser = OpenDataLoaderPdfParser(
        runner=broken,
        page_probe=lambda path: PdfProbe(page_heights=(792.0,), has_structure_tree=False),
    )
    with pytest.raises(StructuredParserError, match="jvm exploded"):
        parser.parse(
            b"%PDF-1.4 fake",
            organization_id=uuid4(),
            external_id="broken.pdf",
            source_name="broken.pdf",
        )


def test_parser_error_passthrough() -> None:
    def broken(data, *, options, use_struct_tree, workdir):
        raise StructuredParserError("java 11+ missing")

    parser = OpenDataLoaderPdfParser(
        runner=broken,
        page_probe=lambda path: PdfProbe(page_heights=(792.0,), has_structure_tree=False),
    )
    with pytest.raises(StructuredParserError, match="java 11\\+"):
        parser.parse(
            b"%PDF-1.4 fake",
            organization_id=uuid4(),
            external_id="broken.pdf",
            source_name="broken.pdf",
        )
