# =============================================================================
# PDF adapter — pdfminer.six layout (pages, reading order, headings, tables)
# =============================================================================
# First-class V2 path. MarkItDown remains the V1 textual normalizer and a
# fallback here when layout extract yields no text.
# =============================================================================
from __future__ import annotations

import io
import re
from statistics import median

from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_MARKITDOWN_FALLBACK,
    SECTION_ABSENT_NO_HEADINGS,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.v2.parsing.adapters.base import ParseError, StructuredAdapter
from src.knowledge.v2.parsing.blocks import HeadingTracker, assign_char_spans, make_block
from src.knowledge.v2.parsing.context import ParseContext, assemble_document

_MULTI_SPACE = re.compile(r"\s{2,}")


def _section_meta(path: tuple[str, ...]) -> dict:
    if path:
        return {}
    return {"section_absent_reason": SECTION_ABSENT_NO_HEADINGS}


def _iter_chars(container):
    from pdfminer.layout import LTChar

    if isinstance(container, LTChar):
        yield container
        return
    try:
        children = list(container)
    except TypeError:
        return
    for item in children:
        yield from _iter_chars(item)


def _font_size(container) -> float:
    sizes = [c.size for c in _iter_chars(container) if hasattr(c, "size")]
    return max(sizes) if sizes else 12.0


def _looks_like_table(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    spaced = sum(1 for ln in lines if len(_MULTI_SPACE.split(ln.strip())) >= 2)
    return spaced >= 2 and spaced >= len(lines) / 2


def _pdf_info(data: bytes) -> dict:
    try:
        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdfparser import PDFParser
        from pdfminer.pdftypes import resolve1

        parser = PDFParser(io.BytesIO(data))
        document = PDFDocument(parser)
        if not document.info:
            return {}
        raw = document.info[0]
        out: dict[str, str] = {}
        for key, value in raw.items():
            name = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
            resolved = resolve1(value)
            if isinstance(resolved, bytes):
                out[name.lower()] = resolved.decode("utf-8", "replace")
            else:
                out[name.lower()] = str(resolved)
        return out
    except Exception:  # noqa: BLE001
        return {}


def _markitdown_text(data: bytes) -> str:
    from markitdown import MarkItDown

    result = MarkItDown().convert_stream(
        io.BytesIO(data),
        stream_info_guess={"extension": ".pdf"},
    )
    return (result.text_content or "").strip()


class PdfAdapter(StructuredAdapter):
    name = "pdf"
    mime_type = "application/pdf"

    def parse(self, ctx: ParseContext) -> StructuredDocument:
        try:
            from pdfminer.high_level import extract_pages
            from pdfminer.layout import LAParams, LTFigure, LTTextContainer
        except ImportError as exc:
            raise ParseError("pdfminer.six is required for PDF V2 parsing") from exc

        info = _pdf_info(ctx.data)
        laparams = LAParams(boxes_flow=0.5, line_margin=0.4, char_margin=2.0, word_margin=0.1)
        try:
            pages = list(extract_pages(io.BytesIO(ctx.data), laparams=laparams))
        except Exception as exc:  # noqa: BLE001
            pages = []
            layout_error = str(exc)[:200]
        else:
            layout_error = None

        boxes: list[tuple[int, float, str, object]] = []
        for page_index, layout in enumerate(pages, start=1):
            for element in layout:
                if isinstance(element, LTTextContainer):
                    text = element.get_text()
                    if text and text.strip():
                        boxes.append((page_index, _font_size(element), text, element))
                elif isinstance(element, LTFigure):
                    text = getattr(element, "get_text", lambda: "")()
                    if text and str(text).strip():
                        boxes.append((page_index, 12.0, str(text), element))

        if not boxes:
            fallback = _markitdown_text(ctx.data)
            if not fallback:
                raise ParseError(
                    f"PDF produced no text: {ctx.filename}"
                    + (f" ({layout_error})" if layout_error else "")
                )
            return self._from_fallback_text(ctx, fallback, info)

        sizes = [size for _, size, _, _ in boxes]
        typical = median(sizes) if sizes else 12.0
        heading_cut = max(typical * 1.15, 13.0)

        tracker = HeadingTracker()
        blocks: list = []
        order = 0
        saw_title = False
        for page_number, size, text, _element in boxes:
            cleaned = re.sub(r"[ \t]+\n", "\n", text).strip()
            if not cleaned:
                continue
            is_heading = size >= heading_cut or (size >= typical + 3 and len(cleaned) < 120)
            if is_heading and "\n" not in cleaned:
                level = 1 if size >= heading_cut + 4 else 2
                path = tracker.push(level, cleaned)
                kind = (
                    StructuredBlockKind.TITLE
                    if not saw_title and page_number == 1
                    else StructuredBlockKind.HEADING
                )
                saw_title = True
                blocks.append(
                    make_block(
                        kind=kind,
                        text=cleaned,
                        order=order,
                        page=page_number,
                        heading_path=path,
                        metadata={"font_size": size, **_section_meta(path)},
                    )
                )
                order += 1
                continue
            path = tracker.path()
            kind = StructuredBlockKind.TABLE if _looks_like_table(cleaned) else StructuredBlockKind.PARAGRAPH
            blocks.append(
                make_block(
                    kind=kind,
                    text=cleaned,
                    order=order,
                    page=page_number,
                    heading_path=path,
                    metadata={"font_size": size, **_section_meta(path)},
                )
            )
            order += 1

        if not blocks:
            raise ParseError(f"PDF produced no text: {ctx.filename}")
        blocks = assign_char_spans(blocks)
        extra = {
            "reading_order": "pdfminer_layout",
            "page_count": len(pages) or max((b.page or 0) for b in blocks),
            "pdf_info": info,
            "tables_heuristic": "multi_space_columns",
        }
        title = info.get("title") if info.get("title") and info["title"] not in {"None", ""} else None
        return assemble_document(
            ctx,
            blocks,
            mime_type=self.mime_type,
            adapter=self.name,
            extra_metadata=extra,
            title=title,
        )

    def _from_fallback_text(self, ctx: ParseContext, text: str, info: dict) -> StructuredDocument:
        from src.knowledge.v2.parsing.adapters.markdown import MarkdownAdapter

        inner = ParseContext(
            data=text.encode("utf-8"),
            filename=ctx.stem + ".md",
            organization_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            source_id=ctx.source_id,
            document_id=ctx.document_id,
            external_id=ctx.external_id or ctx.filename,
        )
        doc = MarkdownAdapter().parse(inner)
        rewritten = []
        for block in doc.blocks:
            meta = dict(block.metadata)
            meta["fallback"] = "markitdown"
            rewritten.append(
                make_block(
                    kind=block.kind,
                    text=block.text,
                    order=block.order,
                    page=None,
                    page_absent_reason=PAGE_ABSENT_MARKITDOWN_FALLBACK,
                    heading_path=block.heading_path,
                    char_start=block.char_start,
                    char_end=block.char_end,
                    metadata=meta,
                )
            )
        extra = {
            "reading_order": "markitdown_textual_fallback",
            "pdf_info": info,
            "fallback": "markitdown",
        }
        return assemble_document(
            ctx,
            rewritten,
            mime_type=self.mime_type,
            adapter=self.name,
            extra_metadata=extra,
        )
