# =============================================================================
# PDF normalizer — markitdown (MIT) → Markdown con headings/tablas
# =============================================================================
from __future__ import annotations

from src.knowledge.normalize.base import Normalizer, NormalizerError


class PdfNormalizer(Normalizer):
    """PDF → Markdown vía markitdown (pdfminer.six, licencia MIT)."""

    def normalize(self, data: bytes, source_name: str = "document") -> str:
        try:
            from markitdown import MarkItDown

            converter = MarkItDown()
            import io

            import pdfminer  # noqa: F401  (asegura el extra instalado)

            result = converter.convert_stream(
                io.BytesIO(data),
                stream_info_guess={"extension": ".pdf"},
            )
            text = (result.text_content or "").strip()
        except Exception as exc:
            raise NormalizerError(
                f"PDF conversion failed for {source_name}: {exc}"
            ) from exc
        if not text:
            raise NormalizerError(f"PDF produced no text: {source_name}")
        return text
