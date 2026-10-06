# =============================================================================
# OpenDataLoader PDF — parser nativo de ZENT (StructuredParser)
# =============================================================================
# PDF -> OpenDataLoader (JVM, JSON) -> adapter -> StructuredDocument.
# El resto de Knowledge OS no sabe que OpenDataLoader existe: consume el
# mismo contrato que PdfParser (pdfplumber).
#
# Fase 1: experimental en paralelo. No reemplaza a pdfplumber en producción.
# =============================================================================
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.structure.base import (
    StructuredParser,
    StructuredParserError,
)
from src.knowledge.structure.opendataloader_client import (
    ConversionRunner,
    OpenDataLoaderConversion,
    OpenDataLoaderOptions,
    convert_pdf_to_json,
    odl_library_version,
)
from src.knowledge.structure.opendataloader_mapping import (
    OpenDataLoaderMappingContext,
    map_opendataloader_document,
)
from src.knowledge.structure.pdf_parser import PdfParseOptions


@dataclass(frozen=True, kw_only=True)
class PdfProbe:
    """Datos del PDF que el mapper necesita (alturas de página, tags)."""

    page_heights: tuple[float, ...] = ()
    has_structure_tree: bool = False
    metadata: dict[str, str] | None = None


def probe_pdf(path: Path) -> PdfProbe:
    """Alturas de página y presencia de structure tree (pdfminer, barato).

    OpenDataLoader entrega bboxes con origen abajo-izquierda; ZENT usa el
    mismo origen que pdfplumber (arriba-izquierda). También decide si
    corresponde --use-struct-tree en modo auto.
    """
    try:
        import pdfplumber
    except ImportError:
        return PdfProbe()
    try:
        with pdfplumber.open(path) as pdf:
            heights = tuple(
                float(getattr(page, "height", 0) or 0.0) for page in pdf.pages
            )
            catalog = getattr(getattr(pdf, "doc", None), "catalog", None) or {}
            tagged = any(
                str(key).lstrip("/") == "StructTreeRoot" for key in catalog
            )
            metadata = {
                str(key): str(value) for key, value in (pdf.metadata or {}).items()
            }
        return PdfProbe(
            page_heights=heights, has_structure_tree=tagged, metadata=metadata
        )
    except Exception:  # noqa: BLE001 — el probe nunca tumba el parseo
        return PdfProbe()


class OpenDataLoaderPdfParser(StructuredParser):
    """PDF -> StructuredDocument usando OpenDataLoader (JSON estructurado)."""

    kind = "pdf"
    mime_type = "application/pdf"

    def __init__(
        self,
        *,
        options: OpenDataLoaderOptions | None = None,
        runner: ConversionRunner | None = None,
        page_probe: Callable[[Path], PdfProbe] | None = None,
    ) -> None:
        self._options = options or OpenDataLoaderOptions()
        self._runner = runner or convert_pdf_to_json
        self._page_probe = page_probe or probe_pdf

    @property
    def options(self) -> OpenDataLoaderOptions:
        return self._options

    def _structure_source(
        self, *, use_struct_tree: bool, mode: str, force_ocr: bool
    ) -> str:
        if use_struct_tree:
            return "tagged_pdf"
        if mode == "hybrid":
            return "ocr" if force_ocr else "hybrid"
        return "inferred_layout"

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
        options = options or PdfParseOptions()
        options_fp = self._options
        root = Path(tempfile.mkdtemp(prefix="zent_odl_parse_"))
        try:
            input_path = root / "input.pdf"
            input_path.write_bytes(data)
            probe = self._page_probe(input_path)
            use_struct_tree = options_fp.use_struct_tree
            if use_struct_tree is None:
                use_struct_tree = bool(probe.has_structure_tree)
            try:
                raw = self._runner(
                    data,
                    options=options_fp,
                    use_struct_tree=use_struct_tree,
                    workdir=root,
                )
            except StructuredParserError:
                raise
            except Exception as exc:  # noqa: BLE001 — normalizado al contrato
                raise StructuredParserError(
                    f"OpenDataLoader falló parseando {source_name}: {exc}"
                ) from exc
            conversion = OpenDataLoaderConversion.from_payload(raw)
            fallback_warnings: list[str] = []
            auto_struct = options_fp.use_struct_tree is None
            if (
                use_struct_tree
                and auto_struct
                and probe.has_structure_tree
                and not (conversion.data.get("kids") or [])
            ):
                # Un tagged PDF mal etiquetado puede devolver árbol vacío.
                # En modo auto se reintenta layout; en always/never se respeta.
                raw = self._runner(
                    data,
                    options=options_fp,
                    use_struct_tree=False,
                    workdir=root,
                )
                conversion = OpenDataLoaderConversion.from_payload(raw)
                use_struct_tree = False
                fallback_warnings.append(
                    "tagged_pdf_empty_fallback: structure tree sin elementos; "
                    "se usó inferencia de layout"
                )
            structure_source = self._structure_source(
                use_struct_tree=use_struct_tree,
                mode=options_fp.mode,
                force_ocr=options_fp.force_ocr,
            )
            parser_info: dict[str, Any] = {
                "engine": "opendataloader",
                "library": "opendataloader-pdf",
                "version": odl_library_version(),
                "mode": options_fp.mode,
                "structure_source": structure_source,
                "use_struct_tree": use_struct_tree,
                "java": conversion.java,
                "requested_columns": bool(getattr(options, "column_detection", False)),
                "options": options_fp.fingerprint(),
            }
            context = OpenDataLoaderMappingContext(
                organization_id=organization_id,
                external_id=external_id,
                source_id=source_id,
                workspace_id=workspace_id,
                source_name=source_name,
                mime_type=mime_type,
                page_heights=probe.page_heights,
                parser_info=parser_info,
                structure_source=structure_source,
                conversion=conversion,
                extra_warnings=tuple(fallback_warnings),
            )
            return map_opendataloader_document(conversion.data, context=context)
        finally:
            shutil.rmtree(root, ignore_errors=True)


__all__ = ["OpenDataLoaderPdfParser", "PdfProbe", "probe_pdf"]
