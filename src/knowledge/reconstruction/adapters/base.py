# =============================================================================
# Semantic Reconstruction Layer — Source Adapter base + registry
# =============================================================================
# Cada adapter conoce la estructura física de su fuente (PDF, DOCX, Excel,
# CSV, JSON, XML, base de datos, API, eventos, ...), pero todos producen la
# misma estructura compatible con Semantic Reconstruction: RawExtraction.
#
# `specialized understanding -> universal semantic representation`
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import PurePosixPath, PureWindowsPath
from typing import ClassVar

from src.core.domain.knowledge_v2 import StructuredDocument

from ..contracts import RawExtraction, SourceKind

_EXTENSION_KINDS: dict[str, str] = {
    "pdf": SourceKind.PDF.value,
    "docx": SourceKind.DOCX.value,
    "doc": SourceKind.DOCX.value,
    "md": SourceKind.MARKDOWN.value,
    "markdown": SourceKind.MARKDOWN.value,
    "txt": SourceKind.TEXT.value,
    "text": SourceKind.TEXT.value,
    "log": SourceKind.TEXT.value,
    "html": SourceKind.HTML.value,
    "htm": SourceKind.HTML.value,
    "xlsx": SourceKind.SPREADSHEET.value,
    "xlsm": SourceKind.SPREADSHEET.value,
    "xls": SourceKind.SPREADSHEET.value,
    "csv": SourceKind.CSV.value,
    "tsv": SourceKind.CSV.value,
    "json": SourceKind.JSON.value,
    "jsonl": SourceKind.JSON.value,
    "ndjson": SourceKind.JSON.value,
    "xml": SourceKind.XML.value,
    "yaml": SourceKind.API.value,
    "yml": SourceKind.API.value,
    "openapi": SourceKind.API.value,
    "sql": SourceKind.DATABASE.value,
}

_MIME_KINDS: tuple[tuple[str, str], ...] = (
    ("application/pdf", SourceKind.PDF.value),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml", SourceKind.DOCX.value),
    ("application/msword", SourceKind.DOCX.value),
    ("text/markdown", SourceKind.MARKDOWN.value),
    ("text/html", SourceKind.HTML.value),
    ("application/xhtml", SourceKind.HTML.value),
    ("spreadsheet", SourceKind.SPREADSHEET.value),
    ("text/csv", SourceKind.CSV.value),
    ("text/tab-separated-values", SourceKind.CSV.value),
    ("application/json", SourceKind.JSON.value),
    ("application/xml", SourceKind.XML.value),
    ("text/xml", SourceKind.XML.value),
    ("openapi", SourceKind.API.value),
    ("sql", SourceKind.DATABASE.value),
)

_DOCUMENT_KINDS = {
    SourceKind.PDF.value,
    SourceKind.DOCX.value,
    SourceKind.TEXT.value,
    SourceKind.MARKDOWN.value,
    SourceKind.HTML.value,
    SourceKind.JSON.value,
    SourceKind.XML.value,
}


def extension_of(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    name = PureWindowsPath(PurePosixPath(text).name).name
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def detect_source_kind(document: StructuredDocument, raw_text: str | None = None) -> str:
    """Detecta el tipo de fuente sin confiar en una única señal.

    Orden: metadata explícita del conector -> árbol tabular -> extensión/MIME.
    """
    explicit = str(document.metadata.get("source_kind") or "").lower()
    if explicit in {kind.value for kind in SourceKind}:
        return explicit

    metadata = document.metadata or {}
    database_tables = metadata.get("tables")
    if isinstance(metadata.get("database_schema"), dict) or (
        isinstance(database_tables, list)
        and database_tables
        and all(isinstance(item, dict) for item in database_tables[:5])
    ):
        return SourceKind.DATABASE.value
    if any(isinstance(metadata.get(key), (dict, str)) for key in ("openapi", "api_spec", "swagger")):
        return SourceKind.API.value
    if isinstance(metadata.get("events"), list):
        return SourceKind.EVENT.value
    if isinstance(metadata.get("conversation"), (list, dict)) or isinstance(metadata.get("messages"), list):
        return SourceKind.CONVERSATION.value

    if raw_text:
        head = raw_text[:1000]
        if '"openapi"' in head or "openapi:" in head or '"swagger"' in head:
            return SourceKind.API.value

    if document.tabular is not None:
        fmt = str(getattr(document.tabular, "format", "") or "").lower()
        if fmt in {"csv", "tsv"}:
            return SourceKind.CSV.value
        return SourceKind.SPREADSHEET.value

    filename = str(
        document.metadata.get("filename")
        or document.metadata.get("external_id")
        or document.external_id
        or ""
    )
    extension = extension_of(filename)
    if extension in _EXTENSION_KINDS:
        return _EXTENSION_KINDS[extension]

    mime = str(document.mime_type or "").lower()
    for needle, kind in _MIME_KINDS:
        if needle in mime:
            return kind

    # Conectores que declaran su tipo físico (database/API/eventos/emails).
    connector = str(document.metadata.get("connector_type") or "").lower()
    connector_map = {
        "postgres": SourceKind.DATABASE.value,
        "mysql": SourceKind.DATABASE.value,
        "mssql": SourceKind.DATABASE.value,
        "oracle": SourceKind.DATABASE.value,
        "db2": SourceKind.DATABASE.value,
        "rest_api": SourceKind.API.value,
        "graphql": SourceKind.API.value,
        "openapi": SourceKind.API.value,
        "events": SourceKind.EVENT.value,
        "email": SourceKind.EMAIL.value,
        "conversation": SourceKind.CONVERSATION.value,
    }
    if connector in connector_map:
        return connector_map[connector]

    if raw_text:
        stripped = raw_text.lstrip()
        if stripped[:1] in "{[":
            return SourceKind.JSON.value
        if stripped[:1] == "<":
            return SourceKind.XML.value
    return SourceKind.TEXT.value


class SourceAdapter(ABC):
    """Convierte una fuente física en RawExtraction."""

    kind: ClassVar[str] = SourceKind.UNKNOWN.value
    description: ClassVar[str] = ""

    @property
    def name(self) -> str:
        return type(self).__name__

    def supports(self, document: StructuredDocument, raw_text: str | None = None) -> bool:
        return detect_source_kind(document, raw_text) == self.kind

    @abstractmethod
    def extract(
        self,
        document: StructuredDocument,
        *,
        raw_text: str | None = None,
    ) -> RawExtraction: ...


_ADAPTERS: dict[str, SourceAdapter] = {}


def register_adapter(adapter: SourceAdapter, *, kinds: tuple[str, ...] | None = None) -> None:
    for kind in kinds or (adapter.kind,):
        _ADAPTERS[kind] = adapter


def get_adapter(kind: str) -> SourceAdapter | None:
    return _ADAPTERS.get(str(kind or "").lower())


def adapter_for(
    document: StructuredDocument,
    *,
    raw_text: str | None = None,
    preferred: str | None = None,
) -> tuple[str, SourceAdapter | None]:
    """Devuelve (source_kind, adapter). Sin adapter específico, el documento."""
    kind = str(preferred or detect_source_kind(document, raw_text)).lower()
    adapter = get_adapter(kind)
    if adapter is not None:
        return kind, adapter
    fallback = get_adapter(SourceKind.TEXT.value)
    if fallback is not None and kind in _DOCUMENT_KINDS:
        return kind, fallback
    return kind, fallback


def registered_kinds() -> list[str]:
    return sorted(_ADAPTERS)


def _reset_registry() -> None:
    """Solo para tests: vuelve a registrar los adapters por defecto."""
    _ADAPTERS.clear()
    from . import register_default_adapters

    register_default_adapters()


__all__ = [
    "SourceAdapter",
    "adapter_for",
    "detect_source_kind",
    "extension_of",
    "get_adapter",
    "register_adapter",
    "registered_kinds",
]
