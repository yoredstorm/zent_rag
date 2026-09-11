# =============================================================================
# HTML adapter — headings, paragraphs, lists, tables (stdlib + BeautifulSoup)
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import (
    PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
    SECTION_ABSENT_NO_HEADINGS,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.v2.parsing.adapters.base import StructuredAdapter
from src.knowledge.v2.parsing.blocks import HeadingTracker, assign_char_spans, make_block
from src.knowledge.v2.parsing.context import ParseContext, assemble_document


def _section_meta(path: tuple[str, ...]) -> dict:
    if path:
        return {}
    return {"section_absent_reason": SECTION_ABSENT_NO_HEADINGS}


def _table_markdown(tag) -> str:
    rows: list[list[str]] = []
    for tr in tag.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        rows.append([c.get_text(" ", strip=True) for c in cells])
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


class HtmlAdapter(StructuredAdapter):
    name = "html"
    mime_type = "text/html"

    def parse(self, ctx: ParseContext) -> StructuredDocument:
        from bs4 import BeautifulSoup, Tag

        soup = BeautifulSoup(ctx.data, "html.parser")
        for junk in soup.find_all(["script", "style", "noscript"]):
            junk.decompose()
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.get_text(" ", strip=True)
        root = soup.body or soup
        tracker = HeadingTracker()
        blocks: list = []
        order = 0

        def emit(kind: StructuredBlockKind, text: str) -> None:
            nonlocal order
            if not text.strip() and kind is not StructuredBlockKind.METADATA:
                return
            path = tracker.path()
            meta = _section_meta(path)
            blocks.append(
                make_block(
                    kind=kind,
                    text=text,
                    order=order,
                    page=None,
                    page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                    heading_path=path,
                    metadata=meta,
                )
            )
            order += 1

        def walk(node) -> None:
            nonlocal order
            if not isinstance(node, Tag):
                return
            name = (node.name or "").lower()
            if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                level = int(name[1])
                heading = node.get_text(" ", strip=True)
                if not heading:
                    return
                path = tracker.push(level, heading)
                kind = (
                    StructuredBlockKind.TITLE
                    if level == 1 and order == 0
                    else StructuredBlockKind.HEADING
                )
                blocks.append(
                    make_block(
                        kind=kind,
                        text=heading,
                        order=order,
                        page=None,
                        page_absent_reason=PAGE_ABSENT_FORMAT_HAS_NO_PAGES,
                        heading_path=path,
                        metadata=_section_meta(path),
                    )
                )
                order += 1
                return
            if name == "p":
                emit(StructuredBlockKind.PARAGRAPH, node.get_text(" ", strip=True))
                return
            if name in {"ul", "ol"}:
                items = [li.get_text(" ", strip=True) for li in node.find_all("li", recursive=False)]
                items = [i for i in items if i]
                if items:
                    emit(StructuredBlockKind.LIST, "\n".join(f"- {i}" for i in items))
                return
            if name == "table":
                md = _table_markdown(node)
                if md:
                    emit(StructuredBlockKind.TABLE, md)
                return
            if name == "pre":
                emit(StructuredBlockKind.CODE, node.get_text())
                return
            for child in node.children:
                walk(child)

        walk(root)
        if not blocks:
            body_text = root.get_text("\n", strip=True)
            emit(StructuredBlockKind.PARAGRAPH, body_text or "")
        blocks = assign_char_spans(blocks)
        return assemble_document(
            ctx,
            blocks,
            mime_type=self.mime_type,
            adapter=self.name,
            title=title or None,
        )
