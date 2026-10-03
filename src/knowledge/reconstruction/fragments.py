# =============================================================================
# Semantic Reconstruction Layer — Fragment Detector
# =============================================================================
# Detecta unidades sospechosas: arranques a mitad de palabra, finales
# truncados, oraciones abruptas, texto mínimo aislado, fragmentos repetidos,
# chunks superpuestos, fragmentos de tabla y artefactos de header/footer.
#
# Un fragmento con alta probabilidad de INCOMPLETE_SEMANTIC_UNIT no se
# convierte nunca en conocimiento canónico.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.knowledge.quality.fragments import (
    TextQualityStatus,
    analyze_text_quality,
    completeness_score,
)

from .continuity import source_tokens
from .contracts import (
    ConfidenceSignals,
    Continuation,
    ElementKind,
    FragmentKind,
    RawElement,
    ReconstructionStatus,
)

_PROSE_KINDS: frozenset[str] = frozenset(
    {
        ElementKind.PARAGRAPH.value,
        ElementKind.LIST_ITEM.value,
        ElementKind.QUOTE.value,
        ElementKind.NOTE.value,
        ElementKind.WARNING.value,
        ElementKind.EXAMPLE.value,
        ElementKind.PROCEDURE.value,
        ElementKind.MESSAGE.value,
        ElementKind.CAPTION.value,
        ElementKind.EVENT.value,
    }
)
#: Elementos cuyo contenido es texto y por tanto pasan por el detector de
#: fragmentos. Los estructurados (props JSON/XML, endpoints, columnas de schema)
#: no se juzgan con heurísticas de prosa.
_TEXTUAL_KINDS: frozenset[str] = _PROSE_KINDS | frozenset(
    {
        ElementKind.TITLE.value,
        ElementKind.HEADING.value,
        ElementKind.CODE.value,
        ElementKind.REFERENCE.value,
        ElementKind.DEFINITION.value,
    }
)
_MIN_TINY = 4
_DUPLICATE_MAX_CHARS = 48
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TERMINAL = (".", "!", "?", ")", "]", "”", '"', "。", "！", "？")
_OPEN_TAIL = (",", ";", ":")
_TRAILING_CONNECTORS = frozenset(
    {
        "and", "or", "for", "of", "to", "with", "the", "a", "an", "in", "on",
        "by", "from", "as", "at", "between", "into", "per", "than", "that",
        "y", "o", "u", "de", "del", "con", "para", "por", "en", "al", "e", "que",
    }
)

_STRUCTURE_BY_KIND: dict[str, float] = {
    ElementKind.TITLE.value: 0.95,
    ElementKind.HEADING.value: 0.95,
    ElementKind.SECTION.value: 0.9,
    ElementKind.PARAGRAPH.value: 0.9,
    ElementKind.LIST.value: 0.9,
    ElementKind.LIST_ITEM.value: 0.9,
    ElementKind.NOTE.value: 0.85,
    ElementKind.WARNING.value: 0.85,
    ElementKind.EXAMPLE.value: 0.85,
    ElementKind.PROCEDURE.value: 0.85,
    ElementKind.QUOTE.value: 0.85,
    ElementKind.CODE.value: 0.9,
    ElementKind.REFERENCE.value: 0.8,
    ElementKind.FIELD.value: 0.85,
    ElementKind.COLUMN.value: 0.85,
    ElementKind.PROPERTY.value: 0.85,
    ElementKind.PARAMETER.value: 0.85,
    ElementKind.ENDPOINT.value: 0.9,
    ElementKind.SCHEMA.value: 0.95,
    ElementKind.TABLE.value: 0.95,
    ElementKind.RECORD.value: 0.9,
}


@dataclass(frozen=True, kw_only=True)
class FragmentVerdict:
    """Veredicto explicable del Fragment Detector sobre un elemento."""

    element_id: object
    status: str
    fragment_kinds: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    signals: ConfidenceSignals = field(default_factory=ConfidenceSignals)
    requires_repair: bool = False
    text_quality: str | None = None

    @property
    def knowledge(self) -> bool:
        return self.status in {
            ReconstructionStatus.VALID.value,
            ReconstructionStatus.RECONSTRUCTED.value,
        }


def _flat(text: str) -> str:
    return " ".join((text or "").split())


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _standalone(token: str, vocabulary: frozenset[str], references: tuple[str, ...]) -> bool:
    if not token:
        return False
    if token.lower() in vocabulary:
        return True
    pattern = re.compile(rf"(?<!\w){re.escape(token)}(?!\w)")
    return any(pattern.search(reference) for reference in references if reference)


def _partial_of_corpus(token: str, vocabulary: frozenset[str]) -> bool:
    lowered = token.lower()
    if len(lowered) < 3:
        return False
    # Exige una diferencia real (>1) para no confundir plural/derivación corta
    # ("byte" vs "bytes") con una palabra partida ("CATEG" vs "CATEGORY").
    return any(
        (word.startswith(lowered) or word.endswith(lowered))
        for word in vocabulary
        if len(word) > len(lowered) + 1
    )


def evaluate_fragment(
    element: RawElement,
    *,
    references: tuple[str, ...] = (),
    vocabulary: frozenset[str] = frozenset(),
    seen_texts: set[str] | None = None,
    absorbed_texts: set[str] | None = None,
    continuity: Continuation | None = None,
    has_repair_neighbor: bool = False,
    source_quality: float = 0.0,
) -> FragmentVerdict:
    """Clasifica un elemento y registra las señales de reconstrucción."""
    flat = _flat(element.text)
    seen = seen_texts if seen_texts is not None else set()
    absorbed = absorbed_texts if absorbed_texts is not None else set()
    normalized = flat.lower()
    tokens = _tokens(flat)
    # Un fragmento no se valida a sí mismo: su propio texto sale de las
    # referencias y del vocabulario antes de decidir.
    effective_references = tuple(
        reference
        for reference in references
        if " ".join((reference or "").split()) != flat
    )
    if effective_references:
        effective_vocabulary = frozenset(source_tokens(effective_references))
    else:
        self_tokens = {token.lower() for token in tokens}
        effective_vocabulary = frozenset(
            token for token in vocabulary if token not in self_tokens
        )
    structure = _STRUCTURE_BY_KIND.get(element.kind, 0.8)
    fragment_kinds: list[str] = []
    reasons: list[str] = []

    if element.is_chrome or element.attributes.get("chrome"):
        return FragmentVerdict(
            element_id=element.id,
            status=ReconstructionStatus.STRUCTURAL_ARTIFACT.value,
            fragment_kinds=(FragmentKind.HEADER_FOOTER_ARTIFACT.value,),
            reasons=("chrome",),
            signals=ConfidenceSignals.compute(
                structure_confidence=0.9, semantic_completeness=0.5, source_quality=source_quality
            ),
            text_quality=TextQualityStatus.OK.value,
        )
    if element.attributes.get("superseded"):
        return FragmentVerdict(
            element_id=element.id,
            status=ReconstructionStatus.DUPLICATE.value,
            reasons=("superseded_into_other_element",),
            signals=ConfidenceSignals.compute(structure_confidence=0.5, source_quality=source_quality),
        )
    if not flat:
        return FragmentVerdict(
            element_id=element.id,
            status=ReconstructionStatus.LOW_QUALITY.value,
            reasons=("empty",),
            signals=ConfidenceSignals.compute(structure_confidence=0.1, source_quality=source_quality),
        )

    # Los elementos estructurados (propiedades JSON/XML, endpoints, columnas de
    # schema, hojas...) no son prosa: su estructura ES la reconstrucción. No se
    # trocean por heurísticas de texto.
    if element.kind not in _TEXTUAL_KINDS:
        return FragmentVerdict(
            element_id=element.id,
            status=ReconstructionStatus.VALID.value,
            signals=ConfidenceSignals.compute(
                structure_confidence=structure,
                semantic_completeness=0.95,
                source_quality=source_quality,
            ),
            text_quality=TextQualityStatus.OK.value,
        )

    quality = analyze_text_quality(
        flat,
        references=effective_references,
        min_length=2,
        allow_code=True,
        max_words=120,
        max_length=4000,
    )
    # Una fila estructurada "Byte 105 | 3 | Currency Code" no es un artefacto
    # de layout: los pipes son delimitadores. Se re-evalúa sin ellos.
    if (
        quality.status == TextQualityStatus.LAYOUT_ARTIFACT.value
        and "pipe_delimiter" in quality.reasons
    ):
        depiped = " ".join(flat.replace("|", " ").split())
        quality = analyze_text_quality(
            depiped,
            references=effective_references,
            min_length=2,
            allow_code=True,
            max_words=120,
            max_length=4000,
        )
    requires_repair = False

    # 1 · Fragmento de otro texto de la misma fuente.
    if quality.status in {
        TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value,
        TextQualityStatus.TRUNCATED_WORD.value,
    }:
        fragment_kinds.append(FragmentKind.TRUNCATED_WORD.value)
        reasons.append(quality.status.lower())
        if quality.reasons:
            reasons.extend(quality.reasons)

    # 2 · Arranque/final a mitad de palabra contra el vocabulario de la fuente.
    if tokens:
        first, last = tokens[0], tokens[-1]
        starts_mid = (
            not _standalone(first, effective_vocabulary, effective_references)
            and _partial_of_corpus(first, effective_vocabulary)
            and len(first) <= 7
        )
        if starts_mid and len(tokens) <= 12:
            fragment_kinds.append(FragmentKind.MID_WORD_START.value)
        if (
            not _standalone(last, effective_vocabulary, effective_references)
            and last[-1:].isalnum()
            and _partial_of_corpus(last, effective_vocabulary)
        ):
            fragment_kinds.append(FragmentKind.MID_WORD_END.value)
            fragment_kinds.append(FragmentKind.PARTIAL_ENTITY.value)

    # 3 · Oración abrupta o cola truncada.
    if element.kind in _PROSE_KINDS:
        if tokens and tokens[-1].lower() in _TRAILING_CONNECTORS and len(tokens) <= 6:
            fragment_kinds.append(FragmentKind.ABRUPT_SENTENCE.value)
        if flat[-1:] in _OPEN_TAIL and len(tokens) <= 10:
            fragment_kinds.append(FragmentKind.ABRUPT_SENTENCE.value)

    # 4 · Texto mínimo aislado.
    if len(flat) < _MIN_TINY and len(tokens) <= 1 and not flat.isdigit():
        fragment_kinds.append(FragmentKind.TINY_ISOLATED_TEXT.value)

    # 5 · Fragmento repetido (misma pieza sin valor propio).
    if (
        normalized in absorbed
        or (
            normalized in seen
            and len(flat) <= _DUPLICATE_MAX_CHARS
            and element.kind in _PROSE_KINDS
            and (fragment_kinds or len(tokens) <= 2)
        )
    ):
        fragment_kinds.append(FragmentKind.REPEATED_FRAGMENT.value)

    # 6 · Overlapping chunk: pedazo extremo de otro elemento.
    if not fragment_kinds and len(flat) <= 200:
        for reference in references:
            if flat == reference or flat not in reference:
                continue
            ratio = len(flat) / max(len(reference), 1)
            if ratio <= 0.35 and not _standalone(flat, effective_vocabulary, effective_references):
                fragment_kinds.append(FragmentKind.OVERLAPPING_CHUNK.value)
                break

    # 7 · Continuación no resuelta: pieza que esperaba a otra.
    if continuity is not None and continuity.ambiguity:
        requires_repair = True
        fragment_kinds.append(FragmentKind.CONTINUATION_FRAGMENT.value)

    deduped_kinds = tuple(dict.fromkeys(fragment_kinds))
    if quality.status == TextQualityStatus.LAYOUT_ARTIFACT.value:
        status = ReconstructionStatus.LOW_QUALITY.value
        reasons.append("layout_artifact")
    elif FragmentKind.REPEATED_FRAGMENT.value in deduped_kinds:
        status = ReconstructionStatus.DUPLICATE.value
    elif FragmentKind.TINY_ISOLATED_TEXT.value in deduped_kinds:
        status = ReconstructionStatus.LOW_QUALITY.value
    elif deduped_kinds:
        if requires_repair or (has_repair_neighbor and any(
            kind in deduped_kinds
            for kind in (
                FragmentKind.MID_WORD_START.value,
                FragmentKind.MID_WORD_END.value,
                FragmentKind.CONTINUATION_FRAGMENT.value,
                FragmentKind.TABLE_FRAGMENT.value,
            )
        )):
            status = ReconstructionStatus.REQUIRES_REPAIR.value
        else:
            status = ReconstructionStatus.INCOMPLETE.value
    elif quality.status == TextQualityStatus.SENTENCE_FRAGMENT.value and completeness_score(flat) < 0.45:
        status = ReconstructionStatus.LOW_QUALITY.value
        reasons.append("low_completeness")
    else:
        status = ReconstructionStatus.VALID.value

    completeness = _completeness_for(element, flat, quality.status, status)
    signals = ConfidenceSignals.compute(
        structure_confidence=structure if status in {
            ReconstructionStatus.VALID.value,
            ReconstructionStatus.RECONSTRUCTED.value,
        } else max(0.2, structure - 0.35),
        continuity_confidence=continuity.confidence if continuity is not None else 0.0,
        semantic_completeness=completeness,
        source_quality=source_quality,
    )
    return FragmentVerdict(
        element_id=element.id,
        status=status,
        fragment_kinds=deduped_kinds,
        reasons=tuple(dict.fromkeys(reasons)),
        signals=signals,
        requires_repair=requires_repair,
        text_quality=quality.status,
    )


def _completeness_for(element: RawElement, flat: str, quality_status: str, status: str) -> float:
    if status == ReconstructionStatus.VALID.value:
        if element.kind in _PROSE_KINDS:
            return max(0.35, completeness_score(flat))
        return 0.9
    if status == ReconstructionStatus.RECONSTRUCTED.value:
        return 0.85
    if quality_status == TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value:
        return 0.3
    return 0.2


def vocabulary_for(references: tuple[str, ...]) -> frozenset[str]:
    return frozenset(source_tokens(references))


__all__ = ["FragmentVerdict", "evaluate_fragment", "vocabulary_for"]
