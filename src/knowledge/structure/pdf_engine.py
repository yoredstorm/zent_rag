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
from src.knowledge.structure.opendataloader_client import (
    OpenDataLoaderOptions,
    odl_library_version,
)
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


def _pdfplumber_version() -> str:
    try:
        from importlib.metadata import version

        return str(version("pdfplumber"))
    except Exception:  # noqa: BLE001 — versión desconocida no rompe la ingesta
        try:
            import pdfplumber

            return str(getattr(pdfplumber, "__version__", "unknown"))
        except Exception:  # noqa: BLE001
            return "unknown"


def parser_engine_label(parser: StructuredParser) -> str:
    """Etiqueta del motor REAL que parseó (no la configurada)."""
    if isinstance(parser, ShadowPdfParser):
        return str(parser.production_label or "pdfplumber")
    if isinstance(parser, OpenDataLoaderPdfParser):
        return "opendataloader"
    if isinstance(parser, PdfParser):
        return "pdfplumber"
    return type(parser).__name__


def parser_provenance(
    parser: StructuredParser,
    *,
    settings: object | None = None,
    document: StructuredDocument | None = None,
) -> dict:
    """Provenance del parser PDF: engine/version/mode/structure_source.

    Genérico: funciona para pdfplumber y OpenDataLoader; el timestamp sella
    cada ingesta. Sin secretos.
    """
    from datetime import datetime, timezone

    engine = parser_engine_label(parser)
    existing_parser = {}
    if document is not None and isinstance(document.metadata, dict):
        candidate = document.metadata.get("parser")
        if isinstance(candidate, dict):
            existing_parser = dict(candidate)
    provenance: dict[str, object] = {
        "engine": engine,
        "parser_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if engine == "opendataloader":
        options = getattr(parser, "options", None)
        provenance["version"] = (
            existing_parser.get("version") or odl_library_version() or "unknown"
        )
        provenance["mode"] = str(
            getattr(options, "mode", "") or existing_parser.get("mode") or "local"
        )
        provenance["structure_source"] = (
            existing_parser.get("structure_source")
            or (
                document.metadata.get("structure_source")
                if document is not None
                else None
            )
            or "inferred_layout"
        )
        provenance["opendataloader_version"] = provenance["version"]
        java = existing_parser.get("java")
        if java:
            provenance["java_version"] = java
    else:
        provenance["version"] = _pdfplumber_version()
        provenance["mode"] = str(
            getattr(settings, "PDF_PARSER_MODE", "pdfplumber") or "pdfplumber"
        )
        provenance["structure_source"] = (
            existing_parser.get("structure_source") or "text_layout"
        )
    return provenance


def stamp_parser_provenance(
    document: StructuredDocument,
    *,
    parser: StructuredParser,
    settings: object | None = None,
) -> StructuredDocument:
    """Sella el StructuredDocument con el parser real que lo produjo.

    - metadata.parser (nested, canónico) + claves planas §13;
    - metadata.document_parser: trace de ingesta §15 (engine/version/mode/
      structure_source/pages/blocks/tables/status).
    """
    from dataclasses import replace

    provenance = parser_provenance(parser, settings=settings, document=document)
    metadata = dict(document.metadata or {})
    existing = metadata.get("parser")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update({key: value for key, value in provenance.items() if value is not None})
    metadata["parser"] = merged
    metadata["parser_engine"] = merged.get("engine")
    metadata["parser_version"] = merged.get("version")
    metadata["parser_mode"] = merged.get("mode")
    metadata["structure_source"] = merged.get("structure_source")
    metadata["parser_timestamp"] = merged.get("parser_timestamp")
    metadata["document_parser"] = {
        "type": "document_parser",
        "engine": merged.get("engine"),
        "version": merged.get("version"),
        "mode": merged.get("mode"),
        "structure_source": merged.get("structure_source"),
        "pages": len(document.pages),
        "blocks": len(document.blocks),
        "tables": len(document.tables),
        "status": "ok",
    }
    return replace(document, metadata=metadata)


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
