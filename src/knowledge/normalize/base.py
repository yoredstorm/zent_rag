# =============================================================================
# Normalizers — raw bytes → Markdown (canal único antes de chunking)
# =============================================================================
# Cada formato se normaliza a Markdown para que el chunker recursivo pueda
# partir por secciones y mantener tablas atómicas. Registro extensible por
# extensión (mismo patrón que SourceRegistry).
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod


class NormalizerError(Exception):
    """Error normalizando un documento."""


class Normalizer(ABC):
    """Convierte bytes de un formato a Markdown."""

    @abstractmethod
    def normalize(self, data: bytes, source_name: str = "document") -> str: ...


_normalizers: dict[str, Normalizer] = {}


def register_normalizer(extension: str, normalizer: Normalizer) -> None:
    _normalizers[extension.strip().lower().lstrip(".")] = normalizer


def get_normalizer(extension: str) -> Normalizer | None:
    return _normalizers.get(extension.strip().lower().lstrip("."))


def supported_extensions() -> list[str]:
    return sorted(_normalizers)
