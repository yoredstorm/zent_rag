# =============================================================================
# OpenDataLoader adapter — mapeo JSON -> StructuredDocument (sin JVM)
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.core.domain.knowledge_v2 import (
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.opendataloader_client import OpenDataLoaderConversion
from src.knowledge.structure.opendataloader_mapping import (
    OpenDataLoaderMappingContext,
    element_text,
    map_opendataloader_document,
    odl_bbox,
)

FIXTURES = Path(__file__).parent / "fixtures" / "parser_lab"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _context(**overrides) -> OpenDataLoaderMappingContext:
    values = {
        "organization_id": uuid4(),
        "external_id": "fixture.pdf",
        "source_name": "fixture.pdf",
        "page_heights": (792.0, 792.0),
        "parser_info": {
            "engine": "opendataloader",
            "library": "opendataloader-pdf",
            "version": "2.5.12",
            "mode": "local",
            "options": {},
        },
        "structure_source": "inferred_layout",
        "conversion": OpenDataLoaderConversion(data={}, elapsed_seconds=0.1),
    }
    values.update(overrides)
    return OpenDataLoaderMappingContext(**values)


def _map(name: str, **overrides) -> StructuredDocument:
    payload = _load(name)
    return map_opendataloader_document(payload, context=_context(**overrides))


def test_atpco_symbols_tables_and_provenance_survive() -> None:
    document = _map("atpco_fare_class.json")
    document.check_consistency()

    text = "\n".join(block.text for block in document.blocks)
    assert "&F1" in text
    assert "&F2" in text
    assert "&F3" in text
    assert "-" in text  # rangos de posiciones no se pierden
    assert "Bytes 64-67" in text

    table = document.tables[0]
    assert table.headers == ("Fare Class", "Description", "Advance Purchase")
    assert table.rows[0] == ("&F1", "One-way fare class", "14 days")
    assert table.caption == "Table 4-1: Fare class restrictions."
    cells = table.metadata["cells"]
    assert len(cells) == 9
    assert all(cell["bbox"] for cell in cells)
    assert any(cell["is_header"] for cell in cells)

    # provenance por bloque: engine/version/mode/element id/reading order
    for block in document.blocks:
        assert block.metadata["parser_engine"] == "opendataloader"
        assert block.metadata["parser_version"] == "2.5.12"
        assert block.metadata["parser_mode"] == "local"
        assert block.metadata["reading_order"] == block.order
    orders = [block.order for block in document.blocks]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)


def test_atpco_cross_page_table_continuation_is_preserved() -> None:
    document = _map("atpco_fare_class.json")
    continued = next(
        table
        for table in document.tables
        if table.metadata.get("previous_table_id") is not None
    )
    assert continued.page == 2
    assert continued.metadata["previous_table_id"] == 8
    assert continued.rows[0][0] == "&F3"


def test_bbox_normalized_to_top_left_origin() -> None:
    payload = {
        "number of pages": 1,
        "kids": [
            {
                "type": "paragraph",
                "id": 1,
                "page number": 1,
                "bounding box": [10.0, 700.0, 100.0, 720.0],
                "font": "Helvetica",
                "font size": 12.0,
                "text color": "[0.0]",
                "content": "texto",
            }
        ],
    }
    document = map_opendataloader_document(
        payload, context=_context(page_heights=(792.0,))
    )
    bbox = document.blocks[0].bbox
    assert bbox is not None
    assert bbox.x0 == 10.0 and bbox.x1 == 100.0
    assert bbox.y0 == 72.0  # 792 - 720
    assert bbox.y1 == 92.0  # 792 - 700
    assert document.blocks[0].metadata["bbox_native"] == [10.0, 700.0, 100.0, 720.0]


def test_heading_tree_numbered_and_unnumbered() -> None:
    payload = {
        "number of pages": 1,
        "kids": [
            {
                "type": "heading",
                "id": 1,
                "level": "Doctitle",
                "page number": 1,
                "bounding box": [0, 0, 1, 1],
                "heading level": 1,
                "font": "Helvetica-Bold",
                "font size": 20.0,
                "text color": "[0.0]",
                "content": "Manual",
            },
            {
                "type": "heading",
                "id": 2,
                "level": "1",
                "page number": 1,
                "bounding box": [0, 0, 1, 1],
                "heading level": 1,
                "font": "Helvetica-Bold",
                "font size": 14.0,
                "text color": "[0.0]",
                "content": "5. Compensación",
            },
            {
                "type": "heading",
                "id": 3,
                "level": "2",
                "page number": 1,
                "bounding box": [0, 0, 1, 1],
                "heading level": 2,
                "font": "Helvetica-Bold",
                "font size": 12.0,
                "text color": "[0.0]",
                "content": "5.2 Comisiones",
            },
            {
                "type": "paragraph",
                "id": 4,
                "page number": 1,
                "bounding box": [0, 0, 1, 1],
                "font": "Helvetica",
                "font size": 11.0,
                "text color": "[0.0]",
                "content": "Comisión 5%.",
            },
        ],
    }
    document = map_opendataloader_document(payload, context=_context())
    paths = [section.section_path for section in document.sections]
    assert paths == [("Manual",), ("5",), ("5", "2")]
    child = document.sections[2]
    parent = document.sections[1]
    assert child.parent_id == parent.id
    body = document.blocks[-1]
    assert body.heading_path == ("5", "2")
    assert body.metadata["section_path"] == ["5", "2"]


def test_list_aggregated_without_duplicating_text() -> None:
    document = _map("procedimiento_lista_anidada.json")
    lists = [
        block for block in document.blocks if block.kind is StructuredBlockKind.LIST
    ]
    assert len(lists) == 1
    list_block = lists[0]
    assert list_block.metadata["numbering_style"] == "ordered"
    items = list_block.metadata["list_items"]
    assert len(items) == 2
    assert "Documento oficial vigente." in list_block.text  # lista anidada
    # sin bloques LIST_ITEM duplicando el texto del contenedor
    assert not any(
        block.kind is StructuredBlockKind.LIST_ITEM for block in document.blocks
    )


def test_formula_and_figure_mapping() -> None:
    contract = _map("contrato.json")
    formulas = [
        block
        for block in contract.blocks
        if block.kind is StructuredBlockKind.FORMULA
    ]
    assert len(formulas) == 1
    assert "\\times" in formulas[0].text
    assert formulas[0].metadata["format"] == "latex"

    manual = _map("manual_tecnico_multicolumna.json")
    figures = manual.figures
    assert len(figures) == 1
    assert figures[0].alt_text == "Diagrama de la secuencia de montaje del motor"
    assert figures[0].figure_type == "chart"
    figure_blocks = [
        block for block in manual.blocks if block.kind is StructuredBlockKind.FIGURE
    ]
    assert len(figure_blocks) == 1


def test_reading_order_checks_warn_on_duplicates() -> None:
    payload = {
        "number of pages": 1,
        "kids": [
            {
                "type": "paragraph",
                "id": 1,
                "page number": 1,
                "bounding box": [0, 0, 1, 1],
                "font": "Helvetica",
                "font size": 11.0,
                "text color": "[0.0]",
                "content": "Texto repetido en dos bloques distintos.",
            },
            {
                "type": "paragraph",
                "id": 2,
                "page number": 1,
                "bounding box": [0, 0, 1, 1],
                "font": "Helvetica",
                "font size": 11.0,
                "text color": "[0.0]",
                "content": "Texto repetido en dos bloques distintos.",
            },
        ],
    }
    document = map_opendataloader_document(payload, context=_context())
    warnings = document.metadata["parser_warnings"]
    assert any("texto repetido" in warning for warning in warnings)


def test_unknown_element_type_degrades_with_warning() -> None:
    payload = {
        "number of pages": 1,
        "kids": [
            {
                "type": "watermark",
                "id": 1,
                "page number": 1,
                "bounding box": [0, 0, 1, 1],
                "content": "borrador",
            }
        ],
    }
    document = map_opendataloader_document(payload, context=_context())
    assert document.blocks[0].kind is StructuredBlockKind.PARAGRAPH
    assert any("sin mapeo" in warning for warning in document.metadata["parser_warnings"])


def test_element_text_recurses_lists_and_kids() -> None:
    element = {
        "type": "list item",
        "content": "padre",
        "kids": [
            {
                "type": "list",
                "list items": [{"type": "list item", "content": "hijo", "kids": []}],
            }
        ],
    }
    assert element_text(element) == "padre\nhijo"


def test_odl_bbox_returns_none_without_page() -> None:
    assert odl_bbox([0, 0, 10, 10], page=None, page_heights=(792.0,)) is None


CROSS_DOMAIN = sorted(
    path.name
    for path in FIXTURES.glob("*.json")
    if not path.name.endswith(".expectations.json")
)


@pytest.mark.parametrize("fixture_name", CROSS_DOMAIN)
def test_cross_domain_fixture_invariants(fixture_name: str) -> None:
    document = _map(fixture_name)
    document.check_consistency()
    assert document.page_count >= 1
    assert document.block_count >= 1
    orders = [block.order for block in document.blocks]
    assert len(set(orders)) == len(orders)
    for block in document.blocks:
        assert block.metadata["parser_engine"] == "opendataloader"
        if block.kind is not StructuredBlockKind.HEADING:
            assert block.text or block.kind in {
                StructuredBlockKind.FIGURE,
                StructuredBlockKind.TABLE,
            }
    for table in document.tables:
        assert table.headers
        assert table.metadata["cells"]
