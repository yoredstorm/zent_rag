# =============================================================================
# Semantic Reconstruction Layer — Source Adapter registry
# =============================================================================
# Especialización por formato, salida universal. Registrar un adapter nuevo
# (un formato futuro) no toca la reconstrucción ni el Knowledge Compiler.
# =============================================================================
from __future__ import annotations

from ..contracts import RawExtraction, SourceKind
from .base import (
    SourceAdapter,
    adapter_for,
    detect_source_kind,
    get_adapter,
    register_adapter,
    registered_kinds,
)


def register_default_adapters() -> None:
    from .api import ApiSourceAdapter
    from .database import DatabaseSourceAdapter
    from .document import (
        DocxSourceAdapter,
        HtmlSourceAdapter,
        MarkdownSourceAdapter,
        PdfSourceAdapter,
        TextSourceAdapter,
    )
    from .events import (
        ConversationSourceAdapter,
        EmailSourceAdapter,
        EventSourceAdapter,
    )
    from .spreadsheet import CsvSourceAdapter, SpreadsheetSourceAdapter
    from .structured_data import JsonSourceAdapter, XmlSourceAdapter

    register_adapter(PdfSourceAdapter())
    register_adapter(DocxSourceAdapter())
    register_adapter(TextSourceAdapter())
    register_adapter(MarkdownSourceAdapter())
    register_adapter(HtmlSourceAdapter())
    register_adapter(SpreadsheetSourceAdapter())
    register_adapter(CsvSourceAdapter())
    register_adapter(JsonSourceAdapter())
    register_adapter(XmlSourceAdapter())
    register_adapter(DatabaseSourceAdapter())
    register_adapter(ApiSourceAdapter())
    register_adapter(EventSourceAdapter())
    register_adapter(EmailSourceAdapter())
    register_adapter(ConversationSourceAdapter())


register_default_adapters()

__all__ = [
    "RawExtraction",
    "SourceAdapter",
    "SourceKind",
    "adapter_for",
    "detect_source_kind",
    "get_adapter",
    "register_adapter",
    "register_default_adapters",
    "registered_kinds",
]
