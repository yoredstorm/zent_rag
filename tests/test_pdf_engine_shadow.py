# =============================================================================
# PDF Parser Engine — selección de motor y shadow A/B
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import (
    StructuredParser,
    content_hash,
    token_count,
)
from src.knowledge.structure.opendataloader_parser import OpenDataLoaderPdfParser
from src.knowledge.structure.pdf_engine import (
    ShadowPdfParser,
    options_from_settings,
    resolve_production_pdf_parser,
)
from src.knowledge.structure.pdf_parser import PdfParser


class _StubParser(StructuredParser):
    kind = "pdf"
    mime_type = "application/pdf"

    def __init__(self, document: StructuredDocument | None = None, error: Exception | None = None):
        self.document = document
        self.error = error
        self.calls = 0

    def parse(
        self,
        data: bytes,
        *,
        organization_id,
        external_id,
        source_id=None,
        workspace_id=None,
        source_name="document",
        mime_type=None,
        options=None,
    ) -> StructuredDocument:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.document is not None
        return self.document


def _doc(external_id: str, texts: tuple[str, ...]) -> StructuredDocument:
    blocks = tuple(
        StructuredBlock(
            kind=StructuredBlockKind.PARAGRAPH,
            text=text,
            order=index,
            page=1,
            token_count=token_count(text),
            content_hash=content_hash(text),
        )
        for index, text in enumerate(texts)
    )
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id=external_id,
        title=external_id,
        content_hash=content_hash("\n".join(texts)),
        blocks=blocks,
    )


def _settings(**overrides) -> SimpleNamespace:
    values = {
        "PDF_PARSER_MODE": "pdfplumber",
        "PDF_SHADOW_PRODUCTION": "pdfplumber",
        "PDF_SHADOW_DIR": "",
        "PDF_SHADOW_ARTIFACTS": True,
        "UPLOAD_DIR": "uploads",
        "ODL_USE_STRUCT_TREE": "auto",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_resolve_modes() -> None:
    assert isinstance(resolve_production_pdf_parser(_settings()), PdfParser)
    assert isinstance(
        resolve_production_pdf_parser(_settings(PDF_PARSER_MODE="opendataloader")),
        OpenDataLoaderPdfParser,
    )
    shadow = resolve_production_pdf_parser(
        _settings(PDF_PARSER_MODE="shadow", PDF_SHADOW_DIR="data/shadow")
    )
    assert isinstance(shadow, ShadowPdfParser)
    assert shadow.production_label == "pdfplumber"
    assert shadow.evaluation_label == "opendataloader"
    assert shadow.artifact_dir == "data/shadow"

    inverted = resolve_production_pdf_parser(
        _settings(PDF_PARSER_MODE="shadow", PDF_SHADOW_PRODUCTION="opendataloader")
    )
    assert inverted.production_label == "opendataloader"
    assert inverted.evaluation_label == "pdfplumber"


def test_shadow_dir_defaults_to_upload_dir() -> None:
    shadow = resolve_production_pdf_parser(
        _settings(PDF_PARSER_MODE="shadow", UPLOAD_DIR="data/uploads")
    )
    assert shadow.artifact_dir is not None
    assert "parser_shadow" in shadow.artifact_dir


def test_options_from_settings_tristate() -> None:
    assert options_from_settings(_settings(ODL_USE_STRUCT_TREE="auto")).use_struct_tree is None
    assert options_from_settings(_settings(ODL_USE_STRUCT_TREE="always")).use_struct_tree is True
    assert options_from_settings(_settings(ODL_USE_STRUCT_TREE="never")).use_struct_tree is False
    assert options_from_settings(_settings(ODL_MODE="hybrid")).mode == "hybrid"


def test_shadow_returns_production_and_writes_artifact(tmp_path) -> None:
    production_doc = _doc("same.pdf", ("producción",))
    evaluation_doc = _doc("same.pdf", ("evaluación", "otro bloque"))
    production = _StubParser(document=production_doc)
    evaluation = _StubParser(document=evaluation_doc)
    shadow = ShadowPdfParser(
        production=production,
        evaluation=evaluation,
        artifact_dir=str(tmp_path),
    )
    result = shadow.parse(
        b"%PDF-1.4",
        organization_id=uuid4(),
        external_id="same.pdf",
        source_name="same.pdf",
    )
    assert result is production_doc  # solo producción continúa
    assert production.calls == 1
    assert evaluation.calls == 1

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["schema"] == "zent.parser_shadow.1"
    assert payload["document"]["external_id"] == "same.pdf"
    assert payload["comparison"]["schema"] == "zent.parser_comparison.1"
    assert payload["comparison"]["labels"]["b"] == "opendataloader"


def test_shadow_failure_does_not_break_production(tmp_path) -> None:
    production_doc = _doc("same.pdf", ("producción",))
    shadow = ShadowPdfParser(
        production=_StubParser(document=production_doc),
        evaluation=_StubParser(error=RuntimeError("odl down")),
        artifact_dir=str(tmp_path),
    )
    result = shadow.parse(
        b"%PDF-1.4",
        organization_id=uuid4(),
        external_id="same.pdf",
        source_name="same.pdf",
    )
    assert result is production_doc
    assert list(tmp_path.glob("*.json")) == []


def test_shadow_without_artifact_dir_still_compares() -> None:
    production_doc = _doc("same.pdf", ("producción",))
    shadow = ShadowPdfParser(
        production=_StubParser(document=production_doc),
        evaluation=_StubParser(document=_doc("same.pdf", ("evaluación",))),
        artifact_dir=None,
    )
    result = shadow.parse(
        b"%PDF-1.4",
        organization_id=uuid4(),
        external_id="same.pdf",
        source_name="same.pdf",
    )
    assert result is production_doc
