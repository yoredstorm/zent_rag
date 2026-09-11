# =============================================================================
# Stub adapter — architecture hook for formats not parsed in Phase B
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_STUB_FORMAT,
    SECTION_ABSENT_STUB_FORMAT,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.v2.parsing.adapters.base import StructuredAdapter
from src.knowledge.v2.parsing.blocks import make_block
from src.knowledge.v2.parsing.context import ParseContext, assemble_document

_MIME = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "epub": "application/epub+zip",
    "xls": "application/vnd.ms-excel",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "wav": "audio/wav",
    "doc": "application/msword",
}


class StubAdapter(StructuredAdapter):
    """Explicit non-parser: one METADATA block with null page + reason.

    Later phases can replace the registration without changing the V2 API.
    """

    name = "stub"
    mime_type = "application/octet-stream"

    def parse(self, ctx: ParseContext) -> StructuredDocument:
        ext = ctx.extension or "unknown"
        message = (
            f"Structured parsing for '.{ext}' is not implemented in Phase B "
            "(architecture hook). Page/section locators are null with reason "
            f"'{PAGE_ABSENT_STUB_FORMAT}'."
        )
        blocks = [
            make_block(
                kind=StructuredBlockKind.METADATA,
                text=message,
                order=0,
                page=None,
                page_absent_reason=PAGE_ABSENT_STUB_FORMAT,
                heading_path=(),
                metadata={
                    "section_absent_reason": SECTION_ABSENT_STUB_FORMAT,
                    "stub": True,
                    "extension": ext,
                },
            )
        ]
        return assemble_document(
            ctx,
            blocks,
            mime_type=_MIME.get(ext, self.mime_type),
            adapter=self.name,
            extra_metadata={
                "parse_status": "unsupported_format",
                "stub_extension": ext,
            },
            title=ctx.stem,
        )
