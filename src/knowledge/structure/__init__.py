# =============================================================================
# Knowledge V2 — Structured parser registry (PDF + text + DOCX + HTML)
# =============================================================================
# Paralelo a los normalizers V1 (bytes → Markdown). Estos parsers producen el
# árbol StructuredDocument. El registro es extensible por extensión.
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import ChunkType
from src.knowledge.structure.base import (
    StructuredParser,
    StructuredParserError,
    get_parser,
    register_parser,
    supported_extensions,
)
from src.knowledge.structure.chunker import (
    ChunkingConfig,
    assign_blocks_to_sections,
    chunk_structured_document,
)
from src.knowledge.structure.docx_parser import DocxParser
from src.knowledge.structure.html_parser import HtmlParser
from src.knowledge.structure.pdf_parser import PdfParser
from src.knowledge.structure.text_parser import TextParser

_text = TextParser()
for ext in ("txt", "md", "markdown"):
    register_parser(ext, _text)

register_parser("pdf", PdfParser())
register_parser("docx", DocxParser())
_html = HtmlParser()
register_parser("html", _html)
register_parser("htm", _html)

__all__ = [
    "StructuredParser",
    "StructuredParserError",
    "get_parser",
    "register_parser",
    "supported_extensions",
    "ChunkType",
    "ChunkingConfig",
    "assign_blocks_to_sections",
    "chunk_structured_document",
    "DocxParser",
    "HtmlParser",
    "PdfParser",
    "TextParser",
]
