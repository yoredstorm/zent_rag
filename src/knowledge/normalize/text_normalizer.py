# =============================================================================
# Text/Markdown/JSON normalizer — passthrough con saneamiento mínimo
# =============================================================================
from __future__ import annotations

from src.knowledge.normalize.base import Normalizer, NormalizerError


class TextNormalizer(Normalizer):
    """txt/md/json pasan tal cual (decode UTF-8 con fallback latin-1)."""

    def normalize(self, data: bytes, source_name: str = "document") -> str:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise NormalizerError(f"Could not decode text document: {source_name}")
