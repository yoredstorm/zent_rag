# =============================================================================
# Markdown adapter — ATX headings, tables, lists, fences, source char offsets
# =============================================================================
from __future__ import annotations

import re

from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
    SECTION_ABSENT_NO_HEADINGS,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.v2.parsing.adapters.base import StructuredAdapter
from src.knowledge.v2.parsing.adapters.text import decode_text
from src.knowledge.v2.parsing.blocks import HeadingTracker, make_block
from src.knowledge.v2.parsing.context import ParseContext, assemble_document

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^```")
_TABLE = re.compile(r"^\s*\|.+\|\s*$")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _section_meta(path: tuple[str, ...]) -> dict:
    if path:
        return {}
    return {"section_absent_reason": SECTION_ABSENT_NO_HEADINGS}


class MarkdownAdapter(StructuredAdapter):
    name = "markdown"
    mime_type = "text/markdown"

    def parse(self, ctx: ParseContext) -> StructuredDocument:
        text = decode_text(ctx.data)
        lines: list[tuple[int, str]] = []
        offset = 0
        for raw in text.splitlines(keepends=True):
            lines.append((offset, raw))
            offset += len(raw)

        tracker = HeadingTracker()
        blocks = []
        order = 0
        i = 0
        n = len(lines)

        def emit(kind: StructuredBlockKind, body: str, start: int, end: int) -> None:
            nonlocal order
            path = tracker.path()
            blocks.append(
                make_block(
                    kind=kind,
                    text=body,
                    order=order,
                    page=None,
                    page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                    heading_path=path,
                    char_start=start,
                    char_end=end,
                    metadata=_section_meta(path),
                )
            )
            order += 1

        while i < n:
            start, raw = lines[i]
            line = raw.rstrip("\r\n")
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            heading = _HEADING.match(stripped)
            if heading:
                level = len(heading.group(1))
                title = heading.group(2).strip()
                path = tracker.push(level, title)
                kind = StructuredBlockKind.TITLE if level == 1 and order == 0 else StructuredBlockKind.HEADING
                blocks.append(
                    make_block(
                        kind=kind,
                        text=title,
                        order=order,
                        page=None,
                        page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                        heading_path=path,
                        char_start=start,
                        char_end=start + len(raw),
                        metadata=_section_meta(path),
                    )
                )
                order += 1
                i += 1
                continue
            if _FENCE.match(stripped):
                fence_start = start
                buf = [line]
                i += 1
                while i < n:
                    buf.append(lines[i][1].rstrip("\r\n"))
                    if _FENCE.match(lines[i][1].strip()):
                        end = lines[i][0] + len(lines[i][1])
                        i += 1
                        break
                    i += 1
                else:
                    end = lines[-1][0] + len(lines[-1][1])
                emit(StructuredBlockKind.CODE, "\n".join(buf), fence_start, end)
                continue
            if _TABLE.match(stripped):
                table_start = start
                buf = [line]
                i += 1
                while i < n and (_TABLE.match(lines[i][1].strip()) or _SEP.match(lines[i][1].strip())):
                    buf.append(lines[i][1].rstrip("\r\n"))
                    i += 1
                end = lines[i - 1][0] + len(lines[i - 1][1])
                emit(StructuredBlockKind.TABLE, "\n".join(buf), table_start, end)
                continue
            if _LIST.match(line):
                list_start = start
                buf = [stripped]
                i += 1
                while i < n and _LIST.match(lines[i][1]):
                    buf.append(lines[i][1].strip())
                    i += 1
                end = lines[i - 1][0] + len(lines[i - 1][1])
                emit(StructuredBlockKind.LIST, "\n".join(buf), list_start, end)
                continue
            para_start = start
            buf = [stripped]
            i += 1
            while i < n:
                nxt = lines[i][1].rstrip("\r\n")
                if not nxt.strip():
                    break
                if (
                    _HEADING.match(nxt.strip())
                    or _FENCE.match(nxt.strip())
                    or _TABLE.match(nxt.strip())
                    or _LIST.match(nxt)
                ):
                    break
                buf.append(nxt.strip())
                i += 1
            end = lines[i - 1][0] + len(lines[i - 1][1])
            emit(StructuredBlockKind.PARAGRAPH, "\n".join(buf), para_start, end)

        if not blocks:
            empty_path: tuple[str, ...] = ()
            blocks.append(
                make_block(
                    kind=StructuredBlockKind.PARAGRAPH,
                    text=text.strip(),
                    order=0,
                    page=None,
                    page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                    heading_path=empty_path,
                    char_start=0,
                    char_end=len(text),
                    metadata=_section_meta(empty_path),
                )
            )
        return assemble_document(ctx, blocks, mime_type=self.mime_type, adapter=self.name)
