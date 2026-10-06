# =============================================================================
# Parser Lab — comparador estructural
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from src.core.domain.knowledge_v2 import (
    BoundingBox,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.parser_lab.comparison import (
    DocumentParserComparison,
    compare_documents,
    side_metrics,
)
from src.knowledge.structure.base import content_hash, token_count
from src.knowledge.structure.opendataloader_client import OpenDataLoaderConversion
from src.knowledge.structure.opendataloader_mapping import (
    OpenDataLoaderMappingContext,
    map_opendataloader_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "parser_lab"


def _map(name: str) -> StructuredDocument:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return map_opendataloader_document(
        payload,
        context=OpenDataLoaderMappingContext(
            organization_id=uuid4(),
            external_id=name,
            source_name=name,
            page_heights=(792.0, 792.0),
            parser_info={"engine": "opendataloader", "version": "2.5.12", "mode": "local"},
            structure_source="inferred_layout",
            conversion=OpenDataLoaderConversion(data=payload),
        ),
    )


def _doc(external_id: str, blocks: list[StructuredBlock]) -> StructuredDocument:
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id=external_id,
        title=external_id,
        content_hash=content_hash("\n".join(block.text for block in blocks)),
        blocks=tuple(blocks),
    )


def _block(text: str, order: int, *, page: int = 1, bbox: bool = True) -> StructuredBlock:
    return StructuredBlock(
        kind=StructuredBlockKind.PARAGRAPH,
        text=text,
        order=order,
        page=page,
        bbox=(
            BoundingBox(page=page, x0=0.0, y0=0.0, x1=100.0, y1=10.0) if bbox else None
        ),
        token_count=token_count(text),
        content_hash=content_hash(text),
    )


def test_compare_identical_documents_is_neutral() -> None:
    document = _map("atpco_fare_class.json")
    comparison = compare_documents(
        document,
        document,
        labels=("pdfplumber", "opendataloader"),
        reference_text="Fare Class &F1 requires 14 days advance purchase",
    )
    assert comparison["schema"] == "zent.parser_comparison.1"
    summary = comparison["summary"]
    assert summary["blocks_ratio"]["b_over_a"] == 1.0
    assert summary["tables_ratio"]["b_over_a"] == 1.0
    assert summary["bbox_coverage"]["a"] == summary["bbox_coverage"]["b"]
    assert summary["missing_reference_chars"]["a"] == 0
    assert summary["reading_order_monotonic"] == {"a": True, "b": True}


def test_compare_detects_missing_text_and_tables() -> None:
    full = _map("atpco_fare_class.json")
    reduced = _doc(
        "atpco-fare-class.pdf",
        [_block("Fare Class &F1 requires 14 days advance purchase", 0)],
    )
    comparison = compare_documents(
        full,
        reduced,
        labels=("full", "reduced"),
        reference_text="Fare Class &F1 requires 14 days advance purchase. Bytes 64-67 Exception Time.",
    )
    summary = comparison["summary"]
    assert summary["tables_ratio"]["a"] == 2
    assert summary["tables_ratio"]["b"] == 0
    assert summary["missing_reference_chars"]["b"] > 0
    assert summary["blocks_ratio"]["b_over_a"] < 1


def test_duplicate_and_bbox_metrics() -> None:
    duplicated = _doc(
        "dup.pdf",
        [
            _block("Texto duplicado en dos bloques iguales.", 0, bbox=False),
            _block("Texto duplicado en dos bloques iguales.", 1, bbox=False),
            _block("bloque único", 2, bbox=False),
        ],
    )
    metrics = side_metrics(duplicated, label="dup")
    assert metrics["text"]["duplicate_text_groups"] == 1
    assert metrics["bbox"]["block_bbox_coverage"] == 0.0
    assert metrics["reading_order"]["monotonic"] is True


def test_reading_order_regression_detected() -> None:
    out_of_order = _doc(
        "order.pdf",
        [
            _block("primero", 0, page=2),
            _block("segundo", 1, page=1),
        ],
    )
    metrics = side_metrics(out_of_order, label="order")
    assert metrics["reading_order"]["page_regressions"] == 1
    assert metrics["reading_order"]["monotonic"] is False


def test_class_labels_and_side_payload() -> None:
    a = _doc("a.pdf", [_block("uno", 0)])
    b = _doc("a.pdf", [_block("uno", 0), _block("dos", 1)])
    comparison = DocumentParserComparison(labels=("pdfplumber", "opendataloader")).compare(a, b)
    assert comparison["labels"] == {"a": "pdfplumber", "b": "opendataloader"}
    assert set(comparison["sides"]) == {"pdfplumber", "opendataloader"}
    assert comparison["summary"]["blocks_ratio"]["b_minus_a"] == 1
