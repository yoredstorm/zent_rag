# =============================================================================
# Knowledge V2 parse API — StructuredDocument with citation provenance
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.v2.parsing.adapters.base import ParseError
from src.knowledge.v2.parsing.adapters.fallback import MarkItDownAdapter
from src.knowledge.v2.parsing.context import ParseContext
from src.knowledge.v2.parsing.registry import get_adapter, supported_v2_extensions

__all__ = [
    "ParseError",
    "parse_structured",
    "parse_structured_if_enabled",
    "supported_v2_extensions",
]


def parse_structured(
    data: bytes,
    filename: str,
    *,
    organization_id: UUID,
    workspace_id: UUID | None = None,
    source_id: UUID | None = None,
    document_id: UUID | None = None,
    mime_type: str | None = None,
    external_id: str | None = None,
) -> StructuredDocument:
    """Parse bytes into a StructuredDocument (library API; not used by V1 engine).

    Identity fields (org / workspace / source / document) are copied onto the
    result so Phase G citations can join a block locator back to a source.
    """
    ctx = ParseContext(
        data=data,
        filename=filename,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_id=source_id,
        document_id=document_id,
        mime_type=mime_type,
        external_id=external_id,
    )
    adapter = get_adapter(ctx.extension)
    if adapter is None:
        try:
            return MarkItDownAdapter().parse(ctx)
        except ParseError as exc:
            raise ParseError(
                f"Unsupported file type '{ctx.extension or filename}'. "
                f"V2 adapters: {', '.join(supported_v2_extensions())}"
            ) from exc
    try:
        return adapter.parse(ctx)
    except ParseError:
        if adapter.name in {"stub", "markitdown"}:
            raise
        try:
            return MarkItDownAdapter().parse(ctx)
        except ParseError:
            raise


def parse_structured_if_enabled(
    data: bytes,
    filename: str,
    *,
    organization_id: UUID,
    workspace_id: UUID | None = None,
    source_id: UUID | None = None,
    document_id: UUID | None = None,
    mime_type: str | None = None,
    external_id: str | None = None,
) -> StructuredDocument | None:
    """Production gate: returns None while RAG_KNOWLEDGE_V2_ENABLED is false."""
    from src.core.config import get_settings

    if not get_settings().KNOWLEDGE_V2_ENABLED:
        return None
    return parse_structured(
        data,
        filename,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_id=source_id,
        document_id=document_id,
        mime_type=mime_type,
        external_id=external_id,
    )
