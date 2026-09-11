# =============================================================================
# MarkItDown textual fallback — last resort when a first-class adapter fails
# =============================================================================
from __future__ import annotations

import io

from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_MARKITDOWN_FALLBACK,
    StructuredDocument,
)
from src.knowledge.v2.parsing.adapters.base import ParseError, StructuredAdapter
from src.knowledge.v2.parsing.adapters.markdown import MarkdownAdapter
from src.knowledge.v2.parsing.blocks import make_block
from src.knowledge.v2.parsing.context import ParseContext, assemble_document


class MarkItDownAdapter(StructuredAdapter):
    name = "markitdown"
    mime_type = "text/markdown"

    def parse(self, ctx: ParseContext) -> StructuredDocument:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise ParseError("markitdown is required for textual fallback") from exc
        ext = ctx.extension or "txt"
        try:
            result = MarkItDown().convert_stream(
                io.BytesIO(ctx.data),
                stream_info_guess={"extension": f".{ext}"},
            )
            text = (result.text_content or "").strip()
        except Exception as exc:
            raise ParseError(f"MarkItDown fallback failed for {ctx.filename}: {exc}") from exc
        if not text:
            raise ParseError(f"MarkItDown produced no text: {ctx.filename}")
        inner = ParseContext(
            data=text.encode("utf-8"),
            filename=f"{ctx.stem}.md",
            organization_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            source_id=ctx.source_id,
            document_id=ctx.document_id,
            external_id=ctx.external_id or ctx.filename,
        )
        doc = MarkdownAdapter().parse(inner)
        rewritten = [
            make_block(
                kind=block.kind,
                text=block.text,
                order=block.order,
                page=None,
                page_absent_reason=PAGE_ABSENT_MARKITDOWN_FALLBACK,
                heading_path=block.heading_path,
                char_start=block.char_start,
                char_end=block.char_end,
                metadata={**block.metadata, "fallback": "markitdown"},
            )
            for block in doc.blocks
        ]
        return assemble_document(
            ctx,
            rewritten,
            mime_type=ctx.mime_type or self.mime_type,
            adapter=self.name,
            extra_metadata={"fallback": "markitdown", "source_extension": ext},
            title=doc.title,
        )
