# =============================================================================
# Document Understanding — reconstrucción semántica de layout
# =============================================================================
# El PDF entrega líneas visuales, no párrafos. Antes de derivar semántica se
# reconstruye el bloque lógico:
#   - líneas que continúan una oración se unen (wrap),
#   - palabras partidas con guion se recomponen,
#   - los fragmentos unidos quedan marcados como superseded (provenance viva).
#
# Solo aplica a prosa. Tablas, headings y chrome no se tocan: su estructura es
# una señal, no un corte que haya que reparar.
# =============================================================================
from __future__ import annotations

import dataclasses

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)

_PROSALIKE = {
    StructuredBlockKind.PARAGRAPH,
    StructuredBlockKind.LIST_ITEM,
    StructuredBlockKind.QUOTE,
}

_DEFINITIONAL = {
    StructuredBlockKind.HEADING,
    StructuredBlockKind.TITLE,
    StructuredBlockKind.TABLE,
    StructuredBlockKind.FIGURE,
    StructuredBlockKind.HEADER,
    StructuredBlockKind.FOOTER,
    StructuredBlockKind.PAGE_NUMBER,
}

_TERMINAL_PUNCTUATION = (".", "!", "?", ":", ";", ")", "]", "”", '"')

#: Conectores que confirman continuación de oración.
_CONTINUATIONS = frozenset(
    {
        "and", "or", "but", "when", "where", "while", "which", "that", "because",
        "y", "e", "o", "u", "pero", "cuando", "mientras", "que", "porque",
    }
)


def _text_of(block: StructuredBlock) -> str:
    return (block.text or "").strip()


def _is_prose(block: StructuredBlock) -> bool:
    if block.metadata.get("chrome") or block.metadata.get("superseded"):
        return False
    if block.kind in _DEFINITIONAL:
        return False
    return block.kind in _PROSALIKE or block.kind is StructuredBlockKind.PARAGRAPH


def _continues(previous: StructuredBlock, current: StructuredBlock) -> bool:
    before = _text_of(previous)
    after = _text_of(current)
    if not before or not after:
        return False
    if previous.page and current.page and previous.page != current.page:
        return False
    if before[-1:] in _TERMINAL_PUNCTUATION and not before.endswith("-"):
        return False
    if before.endswith("-"):
        # Guion de corte: la palabra continúa en la línea siguiente.
        return after[:1].islower() or after[:1].isalnum()
    first_word = after.split(maxsplit=1)[0].strip(".,;:()[]").lower()
    starts_lower = after[:1].islower()
    starts_continuation = first_word in _CONTINUATIONS
    if not (starts_lower or starts_continuation):
        return False
    # Debe seguir en la misma franja horizontal (no es otra columna ni un pie).
    if previous.bbox is not None and current.bbox is not None:
        left_delta = abs(previous.bbox.x0 - current.bbox.x0)
        if left_delta > 72.0:
            return False
        if current.bbox.y0 - previous.bbox.y1 > 40.0:
            return False
    return True


def reflow_wrapped_blocks(document: StructuredDocument) -> StructuredDocument:
    """Une líneas visuales que forman un mismo párrafo lógico.

    El bloque fusionado conserva el lugar de la primera línea; las líneas
    absorbidas quedan marcadas ``superseded`` en su posición original para que
    la procedencia siga viva.
    """
    blocks = list(document.blocks)
    result: list[StructuredBlock] = []
    index = 0
    changed = False
    while index < len(blocks):
        current = blocks[index]
        if not _is_prose(current):
            result.append(current)
            index += 1
            continue
        merged = current
        absorbed: list[StructuredBlock] = []
        cursor = index + 1
        while cursor < len(blocks) and _continues(merged, blocks[cursor]):
            nxt = blocks[cursor]
            before = (merged.text or "").strip()
            after = (nxt.text or "").strip()
            joiner = "" if before.endswith("-") else " "
            text = before.rstrip("-") + joiner + after
            meta = dict(merged.metadata)
            meta["reflowed"] = True
            meta["reflow_parts"] = [
                *(meta.get("reflow_parts") or [str(merged.id)]),
                str(nxt.id),
            ]
            merged = dataclasses.replace(
                merged,
                text=text,
                token_count=len(text.split()),
                metadata=meta,
            )
            next_meta = dict(nxt.metadata)
            next_meta["superseded"] = True
            next_meta["superseded_into"] = str(current.id)
            next_meta["index_semantic"] = False
            next_meta["reflow_continuation"] = True
            absorbed.append(dataclasses.replace(nxt, metadata=next_meta))
            cursor += 1
        result.append(merged)
        if absorbed:
            changed = True
            result.extend(absorbed)
        index = cursor

    if not changed:
        return document
    return dataclasses.replace(document, blocks=tuple(result))


__all__ = ["reflow_wrapped_blocks"]
