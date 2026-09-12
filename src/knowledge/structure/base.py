# =============================================================================
# Knowledge V2 — Structured parsers (Phase B, parallel to V1 normalizers)
# =============================================================================
# Los normalizers V1 producen Markdown (str). Estos parsers producen el árbol
# StructuredDocument (pages / blocks / sections / tables) conservando
# provenance y locators. V1 sigue siendo el camino productivo; la salida V2 se
# persiste solo cuando RAG_KNOWLEDGE_V2_ENABLED está activo.
# =============================================================================
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import ClassVar
from uuid import UUID

from ...core.domain.knowledge_v2 import StructuredDocument


class StructuredParserError(Exception):
    """Error parseando un documento a StructuredDocument."""


class StructuredParser(ABC):
    """Convierte bytes de un formato al árbol StructuredDocument (V2)."""

    kind: ClassVar[str]
    mime_type: ClassVar[str | None] = None

    @abstractmethod
    def parse(
        self,
        data: bytes,
        *,
        organization_id: UUID,
        external_id: str,
        source_id: UUID | None = None,
        workspace_id: UUID | None = None,
        source_name: str = "document",
        mime_type: str | None = None,
    ) -> StructuredDocument: ...


def decode_text(data: bytes, source_name: str = "document") -> str:
    """Decodifica bytes de texto con fallback (mismo saneamiento que V1)."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise StructuredParserError(f"Could not decode text document: {source_name}")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def token_count(text: str) -> int:
    return len(text.split())


_parsers: dict[str, StructuredParser] = {}


def register_parser(extension: str, parser: StructuredParser) -> None:
    _parsers[extension.strip().lower().lstrip(".")] = parser


def get_parser(extension: str) -> StructuredParser | None:
    return _parsers.get(extension.strip().lower().lstrip("."))


def supported_extensions() -> list[str]:
    return sorted(_parsers)
