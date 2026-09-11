# =============================================================================
# Text adapter — UTF-8 paragraphs (no pages, no headings)
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_EMPTY_DOCUMENT,
    PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
    SECTION_ABSENT_PLAIN_TEXT,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.v2.parsing.adapters.base import StructuredAdapter
from src.knowledge.v2.parsing.blocks import assign_char_spans, make_block
from src.knowledge.v2.parsing.context import ParseContext, assemble_document


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class TextAdapter(StructuredAdapter):
    name = "txt"
    mime_type = "text/plain"

    def parse(self, ctx: ParseContext) -> StructuredDocument:
        text = decode_text(ctx.data)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs and text.strip():
            paragraphs = [text.strip()]
        blocks = []
        if not paragraphs:
            blocks.append(
                make_block(
                    kind=StructuredBlockKind.METADATA,
                    text="",
                    order=0,
                    page=None,
                    page_absent_reason=PAGE_ABSENT_EMPTY_DOCUMENT,
                    heading_path=(),
                    metadata={"section_absent_reason": SECTION_ABSENT_PLAIN_TEXT},
                )
            )
        else:
            cursor = 0
            for order, para in enumerate(paragraphs):
                start = text.find(para, cursor)
                if start < 0:
                    start = cursor
                end = start + len(para)
                cursor = end
                blocks.append(
                    make_block(
                        kind=StructuredBlockKind.PARAGRAPH,
                        text=para,
                        order=order,
                        page=None,
                        page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                        heading_path=(),
                        char_start=start,
                        char_end=end,
                        metadata={"section_absent_reason": SECTION_ABSENT_PLAIN_TEXT},
                    )
                )
        blocks = assign_char_spans(blocks)
        return assemble_document(ctx, blocks, mime_type=self.mime_type, adapter=self.name)
