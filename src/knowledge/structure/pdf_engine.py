# =============================================================================
# PDF Parser Engine — selección pdfplumber | opendataloader | shadow A/B
# =============================================================================
# Punto único donde se decide qué parser PDF ve la ingesta. `shadow` ejecuta
# dos StructuredDocuments sobre el mismo PDF: el de producción sigue el camino
# normal (persistencia, compilación, indexado) y el de evaluación se guarda
# como artefacto JSON + comparación estructural, jamás como Knowledge Objects.
#
# pdfplumber NO se elimina: sigue siendo default y el camino de producción del
# experimento. OpenDataLoader se integra en paralelo hasta la Fase 2.
# =============================================================================
from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.structure.base import StructuredParser
from src.knowledge.structure.opendataloader_client import OpenDataLoaderOptions
from src.knowledge.structure.opendataloader_parser import OpenDataLoaderPdfParser
from src.knowledge.structure.pdf_parser import PdfParseOptions, PdfParser

logger = get_logger(__name__)

_SAFE_NAME = re.compile(r"[^\w.-]+", re.UNICODE)

ENGINES = ("pdfplumber", "opendataloader")


def options_from_settings(settings: object) -> OpenDataLoaderOptions:
    """Settings tipados -> flags del CLI (tri-estado de struct tree incluido)."""
    policy = str(getattr(settings, "ODL_USE_STRUCT_TREE", "auto") or "auto")
    use_struct_tree: bool | None
    if policy == "always":
        use_struct_tree = True
    elif policy == "never":
        use_struct_tree = False
    else:
        use_struct_tree = None
    return OpenDataLoaderOptions(
        java=str(getattr(settings, "ODL_JAVA", "") or ""),
        java_home=str(getattr(settings, "ODL_JAVA_HOME", "") or ""),
        mode=str(getattr(settings, "ODL_MODE", "local") or "local"),
        hybrid_backend=str(
            getattr(settings, "ODL_HYBRID_BACKEND", "docling-fast") or "docling-fast"
        ),
        hybrid_url=str(getattr(settings, "ODL_HYBRID_URL", "") or ""),
        hybrid_mode=str(getattr(settings, "ODL_HYBRID_MODE", "auto") or "auto"),
        force_ocr=bool(getattr(settings, "ODL_FORCE_OCR", False)),
        use_struct_tree=use_struct_tree,
        table_method=str(getattr(settings, "ODL_TABLE_METHOD", "default") or "default"),
        reading_order=str(getattr(settings, "ODL_READING_ORDER", "xycut") or "xycut"),
        include_header_footer=bool(
            getattr(settings, "ODL_INCLUDE_HEADER_FOOTER", False)
        ),
        threads=int(getattr(settings, "ODL_THREADS", 1) or 1),
        timeout_seconds=int(getattr(settings, "ODL_TIMEOUT_SECONDS", 180) or 180),
    )


def _build_engine_parser(engine: str, settings: object | None) -> StructuredParser:
    if engine == "opendataloader":
        return OpenDataLoaderPdfParser(options=options_from_settings(settings) if settings else None)
    return PdfParser()


def resolve_production_pdf_parser(settings: object | None = None) -> StructuredParser:
    """Parser PDF que usará la ingesta productiva según PDF_PARSER_MODE."""
    mode = str(getattr(settings, "PDF_PARSER_MODE", "pdfplumber") or "pdfplumber")
    if mode == "opendataloader":
        return _build_engine_parser("opendataloader", settings)
    if mode == "shadow":
        production_engine = str(
            getattr(settings, "PDF_SHADOW_PRODUCTION", "pdfplumber") or "pdfplumber"
        )
        if production_engine not in ENGINES:
            production_engine = "pdfplumber"
        evaluation_engine = (
            "opendataloader" if production_engine == "pdfplumber" else "pdfplumber"
        )
        artifact_dir = _shadow_dir(settings)
        return ShadowPdfParser(
            production=_build_engine_parser(production_engine, settings),
            evaluation=_build_engine_parser(evaluation_engine, settings),
            production_label=production_engine,
            evaluation_label=evaluation_engine,
            artifact_dir=artifact_dir,
            artifacts=bool(getattr(settings, "PDF_SHADOW_ARTIFACTS", True)),
        )
    return PdfParser()


def _shadow_dir(settings: object | None) -> str | None:
    explicit = str(getattr(settings, "PDF_SHADOW_DIR", "") or "").strip()
    if explicit:
        return explicit
    upload_dir = str(getattr(settings, "UPLOAD_DIR", "") or "").strip()
    if not upload_dir:
        return None
    return str(Path(upload_dir) / "parser_shadow")


class ShadowPdfParser(StructuredParser):
    """Corre dos parsers; solo uno cruza hacia producción.

    El parser de evaluación nunca escribe en la base: su resultado se usa para
    comparación estructural y se guarda como artefacto JSON (si hay dir).
    """

    kind = "pdf"
    mime_type = "application/pdf"

    def __init__(
        self,
        *,
        production: StructuredParser,
        evaluation: StructuredParser,
        production_label: str = "pdfplumber",
        evaluation_label: str = "opendataloader",
        artifact_dir: str | None = None,
        artifacts: bool = True,
    ) -> None:
        self.production = production
        self.evaluation = evaluation
        self.production_label = production_label
        self.evaluation_label = evaluation_label
        self.artifact_dir = artifact_dir
        self.artifacts = artifacts

    def parse(
        self,
        data: bytes,
        *,
        organization_id: UUID,
        external_id: str,
        source_id: UUID | None = None,
        workspace_id: UUID | None = None,
        source_name: str = "document",
        mime_type: str | None = None,
        options: PdfParseOptions | None = None,
    ) -> StructuredDocument:
        document = self.production.parse(
            data,
            organization_id=organization_id,
            external_id=external_id,
            source_id=source_id,
            workspace_id=workspace_id,
            source_name=source_name,
            mime_type=mime_type,
            options=options,
        )
        try:
            shadow = self.evaluation.parse(
                data,
                organization_id=organization_id,
                external_id=external_id,
                source_id=source_id,
                workspace_id=workspace_id,
                source_name=source_name,
                mime_type=mime_type,
                options=options,
            )
            self._evaluate_and_record(document, shadow, source_name=source_name)
        except Exception as exc:  # noqa: BLE001 — la sombra jamás rompe producción
            logger.warning(
                "pdf parser shadow failed",
                production=self.production_label,
                evaluation=self.evaluation_label,
                source=source_name,
                error=str(exc)[:300],
            )
        return document

    def _evaluate_and_record(
        self,
        document: StructuredDocument,
        shadow: StructuredDocument,
        *,
        source_name: str,
    ) -> None:
        from src.knowledge.parser_lab.comparison import compare_documents
        from src.knowledge.parser_lab.serialize import write_shadow_artifact

        comparison = compare_documents(
            document,
            shadow,
            labels=(self.production_label, self.evaluation_label),
        )
        summary = comparison["summary"]
        artifact_path: str | None = None
        if self.artifacts and self.artifact_dir:
            artifact_path = write_shadow_artifact(
                self.artifact_dir,
                external_id=document.external_id,
                document=shadow,
                comparison=comparison,
                evaluation_label=self.evaluation_label,
            )
        logger.info(
            "pdf parser shadow compared",
            production=self.production_label,
            evaluation=self.evaluation_label,
            source=source_name,
            blocks=summary["blocks_ratio"],
            tables=summary["tables_ratio"],
            headings=summary["headings_ratio"],
            bbox_coverage=summary["bbox_coverage"],
            artifact=artifact_path,
        )


__all__ = [
    "ENGINES",
    "ShadowPdfParser",
    "options_from_settings",
    "resolve_production_pdf_parser",
]
