# =============================================================================
# Block factory — provenance required when page is absent
# =============================================================================
from __future__ import annotations

import hashlib
from dataclasses import replace

from src.core.domain.knowledge_v2 import StructuredBlock, StructuredBlockKind


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_block(
    *,
    kind: StructuredBlockKind,
    text: str,
    order: int,
    page: int | None = None,
    heading_path: tuple[str, ...] = (),
    page_absent_reason: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
    metadata: dict | None = None,
) -> StructuredBlock:
    """Build a block with citation provenance. Null page requires a reason."""
    cleaned = text.strip() if kind is not StructuredBlockKind.CODE else text
    if not cleaned and kind is not StructuredBlockKind.METADATA:
        cleaned = text
    if page is None:
        if not page_absent_reason:
            raise ValueError("page_absent_reason is required when page is None")
    else:
        page_absent_reason = None
        if page < 1:
            raise ValueError("page_number must be 1-based")
    meta = dict(metadata or {})
    if not heading_path and "section_absent_reason" not in meta:
        raise ValueError("empty section_path requires metadata['section_absent_reason']")
    return StructuredBlock(
        kind=kind,
        text=cleaned,
        order=order,
        page=page,
        heading_path=tuple(heading_path),
        page_absent_reason=page_absent_reason,
        char_start=char_start,
        char_end=char_end,
        content_hash=sha256_text(cleaned),
        metadata=meta,
    )


def assign_char_spans(blocks: list[StructuredBlock]) -> list[StructuredBlock]:
    """Fill char_start/end from concatenated block text when the adapter omitted them."""
    pos = 0
    out: list[StructuredBlock] = []
    for block in blocks:
        if block.char_start is None or block.char_end is None:
            start = pos
            end = pos + len(block.text)
            block = replace(block, char_start=start, char_end=end)
        pos = (block.char_end or pos) + 2
        out.append(block)
    return out


class HeadingTracker:
    """Stack of (level, title) so paragraphs inherit section_path."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def push(self, level: int, title: str) -> tuple[str, ...]:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, title))
        return self.path()

    def path(self) -> tuple[str, ...]:
        return tuple(title for _, title in self._stack)
