# =============================================================================
# DOCX adapter — word/document.xml paragraphs + tables (no python-docx dep)
# =============================================================================
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
    SECTION_ABSENT_NO_HEADINGS,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.v2.parsing.adapters.base import ParseError, StructuredAdapter
from src.knowledge.v2.parsing.blocks import HeadingTracker, assign_char_spans, make_block
from src.knowledge.v2.parsing.context import ParseContext, assemble_document

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_STYLE = re.compile(r"^(Heading|heading|Título|Titulo)\s*(\d+)$", re.I)
_TITLE_STYLE = re.compile(r"^(Title|Título|Titulo)$", re.I)

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _section_meta(path: tuple[str, ...]) -> dict:
    if path:
        return {}
    return {"section_absent_reason": SECTION_ABSENT_NO_HEADINGS}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _para_text(p: ET.Element) -> str:
    parts: list[str] = []
    for node in p.iter(f"{W}t"):
        parts.append(node.text or "")
    return "".join(parts)


def _p_style(p: ET.Element) -> str:
    p_pr = p.find(f"{W}pPr")
    if p_pr is None:
        return ""
    style = p_pr.find(f"{W}pStyle")
    if style is None:
        return ""
    return style.get(f"{W}val") or ""


def _heading_level(style: str) -> int | None:
    if _TITLE_STYLE.match(style or ""):
        return 1
    match = _HEADING_STYLE.match(style or "")
    if match:
        return int(match.group(2))
    return None


def _cell_text(tc: ET.Element) -> str:
    paras = [_para_text(p) for p in tc.findall(f"{W}p")]
    return " ".join(p for p in paras if p).strip()


def _table_markdown(tbl: ET.Element) -> str:
    rows: list[list[str]] = []
    for tr in tbl.findall(f"{W}tr"):
        cells = [_cell_text(tc) for tc in tr.findall(f"{W}tc")]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header = norm[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in norm[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


class DocxAdapter(StructuredAdapter):
    name = "docx"
    mime_type = MIME

    def parse(self, ctx: ParseContext) -> StructuredDocument:
        try:
            with zipfile.ZipFile(io.BytesIO(ctx.data)) as zf:
                xml = zf.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ParseError(f"Invalid DOCX: {ctx.filename}") from exc
        root = ET.fromstring(xml)  # noqa: S314 — local upload bytes, no network
        body = root.find(f"{W}body")
        if body is None:
            body = root
        tracker = HeadingTracker()
        blocks: list = []
        order = 0

        def emit(kind: StructuredBlockKind, text: str) -> None:
            nonlocal order
            if not text.strip():
                return
            path = tracker.path()
            blocks.append(
                make_block(
                    kind=kind,
                    text=text,
                    order=order,
                    page=None,
                    page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                    heading_path=path,
                    metadata=_section_meta(path),
                )
            )
            order += 1

        for child in list(body):
            tag = _local(child.tag)
            if tag == "p":
                text = _para_text(child)
                level = _heading_level(_p_style(child))
                if level is not None and text.strip():
                    path = tracker.push(level, text.strip())
                    kind = (
                        StructuredBlockKind.TITLE
                        if level == 1 and order == 0
                        else StructuredBlockKind.HEADING
                    )
                    blocks.append(
                        make_block(
                            kind=kind,
                            text=text.strip(),
                            order=order,
                            page=None,
                            page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                            heading_path=path,
                            metadata=_section_meta(path),
                        )
                    )
                    order += 1
                else:
                    emit(StructuredBlockKind.PARAGRAPH, text)
            elif tag == "tbl":
                md = _table_markdown(child)
                emit(StructuredBlockKind.TABLE, md)

        if not blocks:
            raise ParseError(f"DOCX produced no text: {ctx.filename}")
        blocks = assign_char_spans(blocks)
        return assemble_document(ctx, blocks, mime_type=self.mime_type, adapter=self.name)
