# =============================================================================
# Adapter registry — extension → V2 StructuredAdapter
# =============================================================================
from __future__ import annotations

from src.knowledge.v2.parsing.adapters.base import StructuredAdapter
from src.knowledge.v2.parsing.adapters.docx import DocxAdapter
from src.knowledge.v2.parsing.adapters.html import HtmlAdapter
from src.knowledge.v2.parsing.adapters.markdown import MarkdownAdapter
from src.knowledge.v2.parsing.adapters.pdf import PdfAdapter
from src.knowledge.v2.parsing.adapters.stub import StubAdapter
from src.knowledge.v2.parsing.adapters.tabular import CsvAdapter, ExcelAdapter, JsonAdapter
from src.knowledge.v2.parsing.adapters.text import TextAdapter

_ADAPTERS: dict[str, StructuredAdapter] = {}


def register_adapter(extension: str, adapter: StructuredAdapter) -> None:
    _ADAPTERS[extension.strip().lower().lstrip(".")] = adapter


def get_adapter(extension: str) -> StructuredAdapter | None:
    return _ADAPTERS.get(extension.strip().lower().lstrip("."))


def supported_v2_extensions() -> list[str]:
    return sorted(_ADAPTERS)


def _register_defaults() -> None:
    text = TextAdapter()
    markdown = MarkdownAdapter()
    html = HtmlAdapter()
    stub = StubAdapter()
    for ext in ("txt", "text", "log"):
        register_adapter(ext, text)
    for ext in ("md", "markdown"):
        register_adapter(ext, markdown)
    register_adapter("html", html)
    register_adapter("htm", html)
    register_adapter("pdf", PdfAdapter())
    register_adapter("docx", DocxAdapter())
    register_adapter("csv", CsvAdapter())
    register_adapter("xlsx", ExcelAdapter())
    register_adapter("json", JsonAdapter())
    for ext in (
        "pptx",
        "ppt",
        "odt",
        "rtf",
        "epub",
        "xls",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "mp3",
        "mp4",
        "wav",
        "doc",
    ):
        register_adapter(ext, stub)


_register_defaults()
