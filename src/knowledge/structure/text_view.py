# =============================================================================
# Bytes -> texto plano por el parser estructural (sin normalizers paralelos)
# =============================================================================
# Un solo camino: el mismo parser que entiende el documento para indexarlo y
# compilarlo es el que entrega su texto. No hay una segunda implementación de
# "bytes a texto" que pueda divergir de la que produce el conocimiento.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.knowledge.structure.base import get_parser

# Organización de relleno: la vista de texto no persiste nada ni consulta nada.
_TEXT_VIEW_ORG = UUID("00000000-0000-0000-0000-000000000000")
_MAX_FALLBACK_BYTES = 8000


def extract_text(data: bytes, filename: str) -> str:
    """Texto plano de un archivo, usando el parser del formato real.

    Si no hay parser registrado para la extensión (o el parseo falla), cae a
    UTF-8 recortado: nunca lanza, nunca inventa contenido.
    """
    extension = (
        filename.rsplit(".", 1)[-1].lower() if "." in (filename or "") else "txt"
    )
    parser = get_parser(extension)
    if parser is not None:
        try:
            document = parser.parse(
                data,
                organization_id=_TEXT_VIEW_ORG,
                external_id=filename or "upload",
                source_name=filename or "upload",
            )
            from src.knowledge.understanding.views import to_markdown

            text = to_markdown(document)
            if text and text.strip():
                return text
        except Exception:  # noqa: BLE001 — la vista de texto es best-effort
            pass
    return data[:_MAX_FALLBACK_BYTES].decode("utf-8", errors="replace")
