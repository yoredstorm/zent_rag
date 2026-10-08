# =============================================================================
# OpenDataLoader PDF — parser nativo de ZENT (StructuredParser)
# =============================================================================
# PDF -> OpenDataLoader (JVM) -> adapter -> StructuredDocument.
# El resto de Knowledge OS no sabe que OpenDataLoader existe: consume el
# mismo contrato que PdfParser (pdfplumber).
#
# Document Intelligence Layer: UNA ejecución produce JSON (autoridad
# estructural) + Markdown (representación LLM-ready) + crosswalk. El
# StructuredDocument sigue siendo el contrato principal de Knowledge OS.
#
# El probe de PDF (alturas de página, StructTreeRoot, metadata) usa pdfminer
# (ya presente vía pdfplumber) y NO importa pdfplumber: ese motor queda como
# shadow/fallback temporal (ver src/knowledge/structure/PDFPLUMBER_DEPRECATION.md).
# =============================================================================
from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.structure.base import (
    StructuredParser,
    StructuredParserError,
)
from src.knowledge.structure.document_bundle import (
    ParsedDocumentBundle,
    build_parsed_document_bundle,
    canonical_json_text,
    place_bundle_artifacts,
)
from src.knowledge.structure.opendataloader_client import (
    ConversionRunner,
    OpenDataLoaderConversion,
    OpenDataLoaderOptions,
    convert_pdf,
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
    """Alturas de página y presence de structure tree (pdfminer, sin pdfplumber).

    OpenDataLoader entrega bboxes con origen abajo-izquierda; ZENT usa el
    mismo origen que pdfplumber (arriba-izquierda). También decide si
    corresponde --use-struct-tree en modo auto.

    pdfminer.six es dependencia transitiva de pdfplumber y se mantiene incluso
    si pdfplumber se retira del runtime productivo (Stage C de la deprecación).
    """
    try:
        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdfpage import PDFPage
        from pdfminer.pdfparser import PDFParser
    except ImportError:  # pragma: no cover — pdfminer no instalado
        return PdfProbe()
    try:
        with open(path, "rb") as handle:
            parser = PDFParser(handle)
            document = PDFDocument(parser)
            heights: list[float] = []
            for page in PDFPage.create_pages(document):
                box = getattr(page, "mediabox", None)
                if not box or len(box) < 4:
                    continue
                try:
                    heights.append(abs(float(box[3]) - float(box[1])))
                except (TypeError, ValueError):
                    continue
            catalog = getattr(document, "catalog", None) or {}
            tagged = any(
                str(key).lstrip("/").replace("b'", "").replace("'", "")
                == "StructTreeRoot"
                for key in catalog
            )
            metadata: dict[str, str] = {}
            for info in getattr(document, "info", ()) or ():
                if not isinstance(info, dict):
                    continue
                for key, value in info.items():
                    metadata[str(key)] = str(value)
        return PdfProbe(
            page_heights=tuple(heights), has_structure_tree=tagged, metadata=metadata
        )
    except Exception:  # noqa: BLE001 — el probe nunca tumba el parseo
        return PdfProbe()


class OpenDataLoaderPdfParser(StructuredParser):
    """PDF -> StructuredDocument / ParsedDocumentBundle vía OpenDataLoader."""

    kind = "pdf"
    mime_type = "application/pdf"

    def __init__(
        self,
        *,
        options: OpenDataLoaderOptions | None = None,
        runner: ConversionRunner | None = None,
        page_probe: Callable[[Path], PdfProbe] | None = None,
        artifact_root: str | Path | None = None,
    ) -> None:
        self._options = options or OpenDataLoaderOptions()
        self._runner = runner or convert_pdf
        self._page_probe = page_probe or probe_pdf
        self._artifact_root = artifact_root

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

    def _resolve_artifact_root(self) -> Path | None:
        """Root de artefactos: explícito > UPLOAD_DIR del runtime."""
        if self._artifact_root:
            return Path(str(self._artifact_root))
        try:
            from src.core.config import get_settings

            raw = getattr(get_settings(), "UPLOAD_DIR", None)
            if raw:
                return Path(str(raw))
        except Exception:  # noqa: BLE001 — sin root no se persisten artefactos
            return None
        return None

    def parse_document(
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
        place_artifacts: bool = True,
    ) -> ParsedDocumentBundle:
        """UNA conversión ODL -> bundle dual (JSON canónico + Markdown LLM)."""
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
                "formats": list(options_fp.resolved_formats()),
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
            document = map_opendataloader_document(conversion.data, context=context)
            bundle = build_parsed_document_bundle(
                document,
                conversion=conversion,
                parser_info=parser_info,
                fallback_warnings=fallback_warnings,
            )
            if place_artifacts and bundle.markdown.strip():
                artifact_root = self._resolve_artifact_root()
                if artifact_root is not None:
                    bundle = place_bundle_artifacts(
                        bundle,
                        root=artifact_root,
                        organization_id=str(organization_id),
                        canonical_json_text_value=canonical_json_text(conversion.data),
                    )
            # Metadata LIVIANA en el contrato principal: refs/hashes/métricas,
            # nunca el Markdown gigante (Qdrant recibe section-level aparte).
            document = replace(
                document,
                metadata={
                    **(document.metadata or {}),
                    "representations": bundle.metadata_block(),
                },
            )
            return replace(bundle, structured_document=document)
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

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
        """Contrato histórico: StructuredDocument (con metadata representations)."""
        bundle = self.parse_document(
            data,
            organization_id=organization_id,
            external_id=external_id,
            source_id=source_id,
            workspace_id=workspace_id,
            source_name=source_name,
            mime_type=mime_type,
            options=options,
        )
        return bundle.structured_document


__all__ = ["OpenDataLoaderPdfParser", "PdfProbe", "probe_pdf"]
