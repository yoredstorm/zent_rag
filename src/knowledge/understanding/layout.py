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
    """El parser no consulta flags globales.

    Quien llama elige PdfParseOptions. Shadow no puede encender columnas
    en el documento productivo. Esta función queda en False a propósito.
    """
    return False


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


@dataclasses.dataclass(frozen=True)
class ColumnLayout:
    """Decisión de columnas. applied=False conserva el orden original."""

    groups: list[list[dict]]
    column_confidence: float
    applied: bool
    reason: str


def column_word_groups(words: list[dict], page_width: float) -> list[list[dict]]:
    """Grupos en orden de lectura. Sin confianza suficiente, un solo grupo."""
    decision = detect_columns(words, page_width)
    if not decision.applied:
        return [list(words)]
    return decision.groups


def detect_columns(
    words: list[dict],
    page_width: float,
    *,
    min_confidence: float = 0.72,
) -> ColumnLayout:
    """Regiones: encabezado ancho, cuerpo en columnas, pie ancho.

    Una página no se asume de dos columnas. Sidebar, tres columnas o una
    banda a todo el ancho (tabla) no reordenan el texto.
    """
    original = [list(words)]
    material = [word for word in words if str(word.get("text") or "").strip()]
    if len(material) < 8 or page_width <= 0:
        return ColumnLayout(original, 1.0, False, "single_column")

    narrow = [word for word in material if _width(word) <= page_width * 0.45]
    wide = [word for word in material if _width(word) > page_width * 0.45]
    if len(narrow) < 8:
        return ColumnLayout(original, 1.0, False, "single_column")

    split = _gap_detail(narrow, page_width)
    if split is None:
        return ColumnLayout(original, 1.0, False, "single_column")
    left, right, best_gap, second_gap, split_x = split
    if best_gap > 0 and second_gap >= best_gap * 0.7:
        return ColumnLayout(original, 0.3, False, "multi_column")

    full_rows, left, right = _peel_full_width(narrow, split_x, page_width)
    if full_rows:
        return ColumnLayout(original, 0.45, False, "mixed_full_width")
    if not _column_body(left) or not _column_body(right):
        return ColumnLayout(original, 0.4, False, "weak_columns")

    smaller, larger = (left, right) if len(left) <= len(right) else (right, left)
    span = max(_x1(word) for word in smaller) - min(_x0(word) for word in smaller)
    ratio = len(smaller) / max(len(larger), 1)
    # Columna de texto corto puede ser angosta y seguir siendo dos columnas.
    # Sidebar: poca masa Y franja fina.
    if ratio <= 0.5 and span < page_width * 0.12:
        return ColumnLayout(original, 0.34, False, "sidebar")

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
    confidence = 0.84 if above or below else 0.9
    if confidence < min_confidence:
        return ColumnLayout(original, confidence, False, "low_confidence")
    return ColumnLayout(groups, confidence, True, "two_columns")


def _x0(word: dict) -> float:
    return float(word.get("x0") or 0.0)


def _x1(word: dict) -> float:
    return float(word.get("x1") or 0.0)


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


def _gap_detail(
    words: list[dict], page_width: float
) -> tuple[list[dict], list[dict], float, float, float] | None:
    centers = sorted(_center(word) for word in words)
    gaps: list[tuple[float, float]] = []
    for previous, current in zip(centers, centers[1:]):
        gaps.append((current - previous, (previous + current) / 2.0))
    if not gaps:
        return None
    gaps.sort(key=lambda item: item[0], reverse=True)
    best_gap, split_x = gaps[0]
    second_gap = gaps[1][0] if len(gaps) > 1 else 0.0
    threshold = max(96.0, page_width * 0.15)
    if best_gap < threshold:
        return None
    if not (page_width * 0.25 <= split_x <= page_width * 0.75):
        return None
    left = [word for word in words if _center(word) < split_x]
    right = [word for word in words if _center(word) >= split_x]
    if len(left) < 4 or len(right) < 4:
        return None
    return left, right, best_gap, second_gap, split_x


def _peel_full_width(
    words: list[dict], split_x: float, page_width: float
) -> tuple[list[list[dict]], list[dict], list[dict]]:
    """Filas que cruzan el hueco con gaps chicos son banda completa, no columnas."""
    threshold = max(96.0, page_width * 0.15)
    by_top: dict[int, list[dict]] = {}
    for word in words:
        by_top.setdefault(round(_top(word)), []).append(word)
    full: list[list[dict]] = []
    drop: set[int] = set()
    for row in by_top.values():
        centers = sorted(_center(word) for word in row)
        max_gap = max((right - left for left, right in zip(centers, centers[1:])), default=0.0)
        both = any(_center(word) < split_x for word in row) and any(
            _center(word) >= split_x for word in row
        )
        if both and max_gap < threshold and len(row) >= 3:
            full.append(row)
            drop.update(id(word) for word in row)
    left = [word for word in words if _center(word) < split_x and id(word) not in drop]
    right = [word for word in words if _center(word) >= split_x and id(word) not in drop]
    return full, left, right


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
