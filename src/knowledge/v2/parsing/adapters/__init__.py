# =============================================================================
# V2 structured adapters (PDF, DOCX, Markdown, HTML, TXT, tabular, stubs)
# =============================================================================
from src.knowledge.v2.parsing.adapters.base import ParseError, StructuredAdapter
from src.knowledge.v2.parsing.adapters.docx import DocxAdapter
from src.knowledge.v2.parsing.adapters.fallback import MarkItDownAdapter
from src.knowledge.v2.parsing.adapters.html import HtmlAdapter
from src.knowledge.v2.parsing.adapters.markdown import MarkdownAdapter
from src.knowledge.v2.parsing.adapters.pdf import PdfAdapter
from src.knowledge.v2.parsing.adapters.stub import StubAdapter
from src.knowledge.v2.parsing.adapters.tabular import CsvAdapter, ExcelAdapter, JsonAdapter
from src.knowledge.v2.parsing.adapters.text import TextAdapter

__all__ = [
    "CsvAdapter",
    "DocxAdapter",
    "ExcelAdapter",
    "HtmlAdapter",
    "JsonAdapter",
    "MarkdownAdapter",
    "MarkItDownAdapter",
    "ParseError",
    "PdfAdapter",
    "StructuredAdapter",
    "StubAdapter",
    "TextAdapter",
]
