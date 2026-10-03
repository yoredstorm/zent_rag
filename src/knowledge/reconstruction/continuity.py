# =============================================================================
# Semantic Reconstruction Layer — Semantic Continuity Detection
# =============================================================================
# Decide si dos elementos aparentemente separados pertenecen a la misma unidad
# lógica. Señales: proximidad visual, orden de lectura, puntuación, contexto de
# heading, estructura de tabla, continuidad léxica y vocabulario de la propia
# fuente. Nunca inventa: la reconstrucción exige evidencia.
# =============================================================================
from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable

from .contracts import (
    Continuation,
    ContinuityKind,
    ElementKind,
    RawElement,
    RawTable,
)

_CONTINUABLE_KINDS: frozenset[str] = frozenset(
    {
        ElementKind.PARAGRAPH.value,
        ElementKind.LIST_ITEM.value,
        ElementKind.QUOTE.value,
        ElementKind.NOTE.value,
        ElementKind.WARNING.value,
        ElementKind.EXAMPLE.value,
        ElementKind.PROCEDURE.value,
        ElementKind.CAPTION.value,
        ElementKind.MESSAGE.value,
    }
)

_TERMINAL_PUNCTUATION = (".", "!", "?", ":", ";", ")", "]", "”", '"', "。", "！", "？")

_CONTINUATION_WORDS: frozenset[str] = frozenset(
    {
        "and", "or", "but", "when", "where", "while", "which", "that", "because",
        "y", "e", "o", "u", "pero", "cuando", "mientras", "que", "porque",
    }
)

_HYPHEN_CHARS = "-‐‑‒\u00ad"
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

MAX_X_OFFSET = 72.0
MAX_Y_GAP = 40.0
MIN_FRAGMENT_LEFT = 3
MIN_FRAGMENT_RIGHT = 2
MIN_DECISION_CONFIDENCE = 0.55


def is_continuable(element: RawElement) -> bool:
    if element.is_chrome or element.attributes.get("superseded"):
        return False
    return element.kind in _CONTINUABLE_KINDS


def source_tokens(texts: Iterable[str]) -> set[str]:
    """Vocabulario real observado en la fuente (palabras y compuestos)."""
    tokens: set[str] = set()
    for text in texts:
        for token in _WORD_RE.findall(text or ""):
            lowered = token.lower()
            tokens.add(lowered)
            for part in re.split(r"[-‐‑‒]", lowered):
                if part:
                    tokens.add(part)
    return tokens


def _word_present(token: str, references: tuple[str, ...]) -> bool:
    if not token:
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(token)}(?!\w)")
    return any(pattern.search(reference) for reference in references if reference)


def _flat(text: str) -> str:
    return " ".join((text or "").split())


def _phrase_present(text: str, references: tuple[str, ...]) -> bool:
    needle = " ".join((text or "").split())
    if len(needle) < 6:
        return False
    return any(needle in " ".join((reference or "").split()) for reference in references)


def _ends_mid_word(text: str) -> bool:
    stripped = (text or "").rstrip()
    if not stripped or stripped[-1] in _HYPHEN_CHARS or stripped[-1].isspace():
        return False
    return bool(re.search(r"[^\W_]$", stripped, re.UNICODE))


def _starts_mid_word(text: str) -> bool:
    stripped = (text or "").lstrip()
    return bool(stripped) and bool(re.match(r"[^\W_]", stripped, re.UNICODE))


def _structurally_adjacent(left: RawElement, right: RawElement) -> bool:
    left_page = left.provenance.page
    right_page = right.provenance.page
    cross_page = bool(left_page and right_page and left_page != right_page)
    if left.heading_path and right.heading_path and left.heading_path != right.heading_path:
        return False
    if cross_page:
        # Las coordenadas de páginas distintas no son comparables; la decisión
        # de continuación cross-page la toma `evaluate_pair` con evidencia.
        return True
    left_bbox = left.provenance.bbox
    right_bbox = right.provenance.bbox
    if left_bbox and right_bbox:
        left_x0, left_y0, left_x1, left_y1 = left_bbox
        right_x0, right_y0, right_x1, right_y1 = right_bbox
        if right_y0 - left_y1 > MAX_Y_GAP:
            return False
        if right_y0 + 1.0 < left_y0:
            return False
        overlap = min(left_x1, right_x1) - max(left_x0, right_x0)
        if overlap <= 0 and abs(left_x0 - right_x0) > MAX_X_OFFSET:
            return False
    return True


def _cross_page(left: RawElement, right: RawElement) -> bool:
    return bool(
        left.provenance.page
        and right.provenance.page
        and left.provenance.page != right.provenance.page
    )


def _join_wrap(left: str, right: str) -> str:
    return f"{left.rstrip()} {right.lstrip()}"


def _join_fragment(left: str, right: str) -> str:
    return f"{left.rstrip()}{right.lstrip()}"


def _join_dehyphenated(left: str, right: str) -> str:
    return f"{left.rstrip().rstrip(_HYPHEN_CHARS)}{right.lstrip()}"


def _first_token(text: str) -> str:
    match = _WORD_RE.search(text or "")
    return match.group(0) if match else ""


def _last_token(text: str) -> str:
    matches = _WORD_RE.findall(text or "")
    return matches[-1] if matches else ""


def evaluate_pair(
    left: RawElement,
    right: RawElement,
    *,
    references: tuple[str, ...] = (),
    vocabulary: frozenset[str] = frozenset(),
) -> Continuation | None:
    """Evalúa si `right` continúa a `left`. Devuelve la decisión o None.

    `ambiguity=True` significa: hay señales de continuación pero falta
    evidencia suficiente; no se aplica salvo escalamiento explícito.
    """
    if not is_continuable(left) or not is_continuable(right):
        return None
    left_text = (left.text or "").strip()
    right_text = (right.text or "").strip()
    if not left_text or not right_text:
        return None
    if not _structurally_adjacent(left, right):
        return None
    # Un par no se valida a sí mismo: sus textos salen de las referencias y su
    # vocabulario no puede sostener la evidencia de continuación.
    left_flat = _flat(left_text)
    right_flat = _flat(right_text)
    pair_references = tuple(
        reference
        for reference in references
        if _flat(reference) not in {left_flat, right_flat}
    )
    self_tokens = {
        token.lower() for token in _WORD_RE.findall(f"{left_flat} {right_flat}")
    }
    pair_vocabulary = frozenset(
        token for token in vocabulary if token not in self_tokens
    )

    cross_page = _cross_page(left, right)
    last = left_text[-1]
    right_first = right_text[:1]

    # 1 · Palabra partida con guion.
    if last in _HYPHEN_CHARS:
        joined = _join_dehyphenated(left_text, right_text)
        first_word = _first_token(right_text)
        merged_token = (_last_token(left_text) or "") + first_word
        evidence: dict = {"cross_page": cross_page}
        strong = merged_token.lower() in pair_vocabulary or _word_present(merged_token, pair_references)
        if strong:
            evidence["evidence"] = "word_in_source"
        ambiguous = not strong and right_first.isupper()
        if cross_page and not strong:
            return None
        return Continuation(
            id=f"cont:{left.id}:{right.id}",
            kind=ContinuityKind.DEHYPHENATION.value,
            left_id=left.id,
            right_id=right.id,
            merged_text=joined,
            confidence=0.9 if strong else 0.72,
            reason="line_break_hyphen",
            ambiguity=ambiguous,
            evidence=evidence,
        )

    # 2 · Corte a mitad de palabra sin guion (celda/línea partida).
    if _ends_mid_word(left_text) and _starts_mid_word(right_text) and not right_text[:1].isspace():
        tail = _last_token(left_text)
        head = _first_token(right_text)
        if len(tail) >= MIN_FRAGMENT_LEFT and len(head) >= MIN_FRAGMENT_RIGHT:
            joined_word = f"{tail}{head}"
            tail_standalone = _word_present(tail, pair_references)
            head_standalone = _word_present(head, pair_references)
            joined_known = joined_word.lower() in pair_vocabulary or _word_present(joined_word, pair_references)
            evidence = {
                "tail": tail,
                "head": head,
                "tail_standalone": tail_standalone,
                "head_standalone": head_standalone,
                "cross_page": cross_page,
            }
            if joined_known:
                evidence["evidence"] = "joined_word_in_source"
                return Continuation(
                    id=f"cont:{left.id}:{right.id}",
                    kind=ContinuityKind.WORD_FRAGMENT.value,
                    left_id=left.id,
                    right_id=right.id,
                    merged_text=_join_fragment(left_text, right_text),
                    confidence=0.92 if not cross_page else 0.85,
                    reason="joined_word_present_in_source",
                    evidence=evidence,
                )
            if not tail_standalone and not head_standalone:
                if cross_page:
                    return None
                return Continuation(
                    id=f"cont:{left.id}:{right.id}",
                    kind=ContinuityKind.WORD_FRAGMENT.value,
                    left_id=left.id,
                    right_id=right.id,
                    merged_text=_join_fragment(left_text, right_text),
                    confidence=0.5,
                    reason="adjacent_fragments_without_vocabulary_evidence",
                    ambiguity=True,
                    evidence=evidence,
                )

    # 3 · Frase partida: línea visual sin puntuación terminal.
    if last not in _TERMINAL_PUNCTUATION:
        first_lower = right_first.islower()
        first_word = _first_token(right_text).lower()
        connector = first_word in _CONTINUATION_WORDS
        if first_lower or connector:
            if cross_page and not connector:
                # Cruzar página exige señal fuerte (conector explícito); una
                # minúscula inicial no basta para saltar el límite de página.
                return None
            confidence = 0.9 if connector else 0.82
            if cross_page:
                confidence -= 0.1
            return Continuation(
                id=f"cont:{left.id}:{right.id}",
                kind=(
                    ContinuityKind.PAGE_CONTINUATION.value
                    if cross_page
                    else ContinuityKind.LINE_WRAP.value
                ),
                left_id=left.id,
                right_id=right.id,
                merged_text=_join_wrap(left_text, right_text),
                confidence=confidence,
                reason="sentence_continues_across_lines",
                evidence={"connector": connector, "cross_page": cross_page},
            )
    return None


@dataclasses.dataclass
class SequenceReconstruction:
    """Resultado de reconstruir una secuencia de elementos crudos."""

    elements: list[RawElement]
    continuations: list[Continuation]
    ambiguous: list[Continuation]
    absorbed: dict = dataclasses.field(default_factory=dict)  # UUID -> RawElement
    merged_into: dict = dataclasses.field(default_factory=dict)  # UUID -> UUID
    merged_from: dict = dataclasses.field(default_factory=dict)  # UUID -> tuple[UUID, ...]

    def continuation_for(self, element_id) -> Continuation | None:
        for continuation in self.continuations:
            if continuation.right_id == element_id or continuation.left_id == element_id:
                return continuation
        return None


def reconstruct_sequence(
    elements: list[RawElement],
    *,
    references: tuple[str, ...] = (),
    vocabulary: frozenset[str] = frozenset(),
) -> SequenceReconstruction:
    """Une cadenas de continuación cuando la evidencia lo sostiene.

    Los elementos absorbidos se conservan en `absorbed` (provenance viva) y el
    elemento raíz mantiene su id: la identidad no cambia, el texto se completa.
    """
    result = SequenceReconstruction(elements=[], continuations=[], ambiguous=[])
    index = 0
    while index < len(elements):
        current = elements[index]
        if not is_continuable(current):
            result.elements.append(current)
            index += 1
            continue
        absorbed_ids: list = []
        merged_text = (current.text or "").strip()
        root = current
        cursor = index + 1
        while cursor < len(elements):
            decision = evaluate_pair(
                root,
                elements[cursor],
                references=references,
                vocabulary=vocabulary,
            )
            if decision is None:
                break
            if decision.ambiguity:
                result.ambiguous.append(decision)
                break
            if decision.confidence < MIN_DECISION_CONFIDENCE:
                break
            absorbed_ids.append(elements[cursor].id)
            result.absorbed[elements[cursor].id] = elements[cursor]
            result.merged_into[elements[cursor].id] = root.id
            merged_text = decision.merged_text
            root = dataclasses.replace(
                root,
                text=merged_text,
                attributes={
                    **root.attributes,
                    "merged_from": [str(value) for value in absorbed_ids],
                    "continuation_kind": decision.kind,
                },
            )
            result.continuations.append(decision)
            cursor += 1
        if absorbed_ids:
            result.merged_from[root.id] = tuple(absorbed_ids)
        result.elements.append(root)
        index = cursor
    return result


def detect_repeated_table_headers(table: RawTable) -> list[Continuation]:
    """Filas de datos idénticas al header repetido tras un salto de página."""
    if not table.headers or not table.rows:
        return []
    header_key = tuple(" ".join(cell.lower().split()) for cell in table.headers)
    found: list[Continuation] = []
    for position, row in enumerate(table.rows):
        row_key = tuple(" ".join(cell.lower().split()) for cell in row)
        if row_key == header_key:
            found.append(
                Continuation(
                    id=f"repeated-header:{table.id}:{position}",
                    kind=ContinuityKind.REPEATED_HEADER.value,
                    left_id=table.id,  # type: ignore[arg-type]
                    right_id=table.id,  # type: ignore[arg-type]
                    merged_text=" | ".join(table.headers),
                    confidence=0.9,
                    reason="data_row_repeats_header",
                    evidence={"row_index": position},
                )
            )
    return found


__all__ = [
    "SequenceReconstruction",
    "detect_repeated_table_headers",
    "evaluate_pair",
    "is_continuable",
    "reconstruct_sequence",
    "source_tokens",
]
