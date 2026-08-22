# =============================================================================
# Normalizer Registry — extensiones soportadas → normalizers (MIT)
# =============================================================================
from __future__ import annotations

from src.knowledge.normalize.base import register_normalizer
from src.knowledge.normalize.doc_html_normalizer import DocxNormalizer, HtmlNormalizer
from src.knowledge.normalize.pdf_normalizer import PdfNormalizer
from src.knowledge.normalize.text_normalizer import TextNormalizer

_text = TextNormalizer()

for ext in ("txt", "md", "markdown", "json", "log"):
    register_normalizer(ext, _text)

register_normalizer("pdf", PdfNormalizer())
register_normalizer("docx", DocxNormalizer())
register_normalizer("html", HtmlNormalizer())
register_normalizer("htm", HtmlNormalizer())
