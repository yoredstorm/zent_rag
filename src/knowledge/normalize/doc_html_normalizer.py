# =============================================================================
# DOCX / HTML normalizers — markitdown (MIT) → Markdown
# =============================================================================
from __future__ import annotations

from src.knowledge.normalize.base import Normalizer, NormalizerError


def _markitdown_convert(data: bytes, extension: str, source_name: str) -> str:
    try:
        import io

        from markitdown import MarkItDown

        converter = MarkItDown()
        result = converter.convert_stream(
            io.BytesIO(data),
            stream_info_guess={"extension": extension},
        )
        text = (result.text_content or "").strip()
    except Exception as exc:
        raise NormalizerError(
            f"{extension} conversion failed for {source_name}: {exc}"
        ) from exc
    if not text:
        raise NormalizerError(f"{extension} produced no text: {source_name}")
    return text


class DocxNormalizer(Normalizer):
    """DOCX → Markdown vía markitdown (mammoth)."""

    def normalize(self, data: bytes, source_name: str = "document") -> str:
        return _markitdown_convert(data, ".docx", source_name)


class HtmlNormalizer(Normalizer):
    """HTML → Markdown vía markitdown (markdownify)."""

    def normalize(self, data: bytes, source_name: str = "document") -> str:
        text = _markitdown_convert(data, ".html", source_name)
        return text
