# =============================================================================
# Document Understanding — layout: columnas, cabecera, pie
# =============================================================================
# El PDF no se concatena línea a línea de izquierda a derecha cuando hay dos
# columnas. La cabecera y el pie repetidos se marcan, no se borran: siguen en
# el árbol para provenance y salen de los chunks semánticos.
# =============================================================================
from __future__ import annotations

import dataclasses
import re

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)

_PAGE_HEIGHT = 792.0
_EDGE_RATIO = 0.12
_CHROME_MAX_CHARS = 90


def layout_analysis_enabled() -> bool:
    """Columnas solo con el master flag. Off = el parser V2 de siempre."""
    try:
        from src.core.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001 — un fallo de config no cambia el parseo
        return False
    master = bool(
        getattr(settings, "DOCUMENT_UNDERSTANDING_ENABLED", False)
        or getattr(settings, "DOCUMENT_UNDERSTANDING_SHADOW", False)
    )
    return master and bool(getattr(settings, "DOCUMENT_UNDERSTANDING_LAYOUT", True))


def _width(word: dict) -> float:
    return float(word.get("x1") or 0.0) - float(word.get("x0") or 0.0)


def _center(word: dict) -> float:
    return (float(word.get("x0") or 0.0) + float(word.get("x1") or 0.0)) / 2.0


def _top(word: dict) -> float:
    return float(word.get("top") or 0.0)


def _bottom(word: dict) -> float:
    return float(word.get("bottom") or _top(word))


def _vertical_span(words: list[dict]) -> float:
    if not words:
        return 0.0
    return max(_bottom(word) for word in words) - min(_top(word) for word in words)


def _distinct_tops(words: list[dict]) -> int:
    return len({round(_top(word), 0) for word in words})


def column_word_groups(words: list[dict], page_width: float) -> list[list[dict]]:
    """Grupos de palabras en orden de lectura. Una columna devuelve un solo grupo.

    Dos columnas: bloque ancho de arriba, columna izquierda completa, columna
    derecha completa, bloque ancho de abajo. Nunca intercala línea izquierda
    con línea derecha.
    """
    material = [word for word in words if str(word.get("text") or "").strip()]
    if len(material) < 8 or page_width <= 0:
        return [list(words)]

    narrow = [word for word in material if _width(word) <= page_width * 0.45]
    wide = [word for word in material if _width(word) > page_width * 0.45]
    if len(narrow) < 8:
        return [list(words)]

    split = _gap_split(narrow, page_width)
    if split is None:
        return [list(words)]
    left, right = split
    if not _column_body(left) or not _column_body(right):
        return [list(words)]

    body_top = min(_top(word) for word in left + right)
    body_bottom = max(_bottom(word) for word in left + right)
    above = [word for word in wide if _top(word) < body_top - 2]
    below = [word for word in wide if _top(word) > body_bottom - 2]
    groups: list[list[dict]] = []
    if above:
        groups.append(above)
    groups.append(left)
    groups.append(right)
    if below:
        groups.append(below)
    return groups


def _column_body(words: list[dict]) -> bool:
    return len(words) >= 4 and _distinct_tops(words) >= 2 and _vertical_span(words) >= 16


def _gap_split(words: list[dict], page_width: float) -> tuple[list[dict], list[dict]] | None:
    centers = sorted(_center(word) for word in words)
    best_gap = 0.0
    split_x: float | None = None
    for previous, current in zip(centers, centers[1:]):
        gap = current - previous
        if gap > best_gap:
            best_gap = gap
            split_x = (previous + current) / 2.0
    threshold = max(96.0, page_width * 0.15)
    if split_x is None or best_gap < threshold:
        return None
    if not (page_width * 0.25 <= split_x <= page_width * 0.75):
        return None
    left = [word for word in words if _center(word) < split_x]
    right = [word for word in words if _center(word) >= split_x]
    if len(left) < 4 or len(right) < 4:
        return None
    return left, right


def _norm_chrome(text: str) -> str:
    folded = re.sub(r"\d+", "#", (text or "").strip().lower())
    return re.sub(r"\s+", " ", folded).strip()


def _near_edge(block: StructuredBlock) -> str | None:
    if block.bbox is None:
        return None
    if block.bbox.y0 <= _PAGE_HEIGHT * _EDGE_RATIO:
        return "header"
    if block.bbox.y0 >= _PAGE_HEIGHT * (1.0 - _EDGE_RATIO):
        return "footer"
    return None


def _page_number_text(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:page|pagina|página|pág\.?|pag\.)?\s*\d{1,4}",
            (text or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def mark_repeated_chrome(document: StructuredDocument) -> StructuredDocument:
    """Marca cabecera, pie y número de página repetidos. No los borra."""
    page_count = document.page_count or len({block.page for block in document.blocks if block.page})
    if page_count < 2 or not document.blocks:
        return document
    required = page_count if page_count < 3 else max(2, int(page_count * 0.6 + 0.999))

    grouped: dict[str, list[int]] = {}
    for index, block in enumerate(document.blocks):
        key = _norm_chrome(block.text)
        if not key or len(block.text.strip()) > _CHROME_MAX_CHARS:
            continue
        grouped.setdefault(key, []).append(index)

    chrome_at: dict[int, str] = {}
    for indexes in grouped.values():
        pages = {document.blocks[index].page for index in indexes if document.blocks[index].page}
        if len(pages) < required:
            continue
        for index in indexes:
            block = document.blocks[index]
            edge = _near_edge(block)
            if _page_number_text(block.text):
                chrome_at[index] = "page_number"
            elif edge == "header":
                chrome_at[index] = "header"
            elif edge == "footer":
                chrome_at[index] = "footer"

    if not chrome_at:
        return document

    kind_for = {
        "header": StructuredBlockKind.HEADER,
        "footer": StructuredBlockKind.FOOTER,
        "page_number": StructuredBlockKind.PAGE_NUMBER,
    }
    blocks = list(document.blocks)
    for index, role in chrome_at.items():
        block = blocks[index]
        meta = dict(block.metadata)
        meta["chrome"] = role
        meta["role"] = role
        meta["index_semantic"] = False
        meta["provenance_type"] = "EXTRACTED"
        blocks[index] = dataclasses.replace(
            block,
            kind=kind_for[role],
            metadata=meta,
        )
    return dataclasses.replace(document, blocks=tuple(blocks))
