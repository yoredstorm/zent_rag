# =============================================================================
# Knowledge OS — Calidad de texto: fragmentos, artefactos y cortes
# =============================================================================
# Un candidato (unidad, entidad, alias, valor de hecho) no puede entrar al
# conocimiento si es un fragmento de otro texto, un corte de layout o una
# extracción de baja calidad. Este módulo es determinista y no tiene I/O:
# recibe el texto y las referencias ya observadas en la misma fuente.
#
# Regla dura: "diferente texto" no implica "conocimiento distinto". Si un
# candidato es un pedazo de otro texto de la misma fuente, se marca
# FRAGMENT_OF_EXISTING_TEXT y NO se convierte en objeto canónico.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class TextQualityStatus(StrEnum):
    """Veredicto de calidad de un texto candidato."""

    OK = "OK"
    LOW_QUALITY_EXTRACTION = "LOW_QUALITY_EXTRACTION"
    FRAGMENT_OF_EXISTING_TEXT = "FRAGMENT_OF_EXISTING_TEXT"
    LAYOUT_ARTIFACT = "LAYOUT_ARTIFACT"
    TRUNCATED_WORD = "TRUNCATED_WORD"
    SENTENCE_FRAGMENT = "SENTENCE_FRAGMENT"
    TOO_LONG_FOR_TERM = "TOO_LONG_FOR_TERM"


@dataclass(frozen=True)
class TextQuality:
    """Resultado explicable de analizar un texto candidato."""

    status: str
    reasons: tuple[str, ...] = ()
    fragment_of: str | None = None
    fragment_ratio: float = 0.0
    confidence: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == TextQualityStatus.OK.value

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "fragment_of": self.fragment_of,
            "fragment_ratio": round(self.fragment_ratio, 4),
            "confidence": round(self.confidence, 4),
        }


_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+")
_VOWELS = frozenset("aeiouáéíóúüAEIOUÁÉÍÓÚÜ")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MULTISPACE_RE = re.compile(r"\s{2,}")

#: Conectores que no cierran una afirmación completa.
_TRAILING_CONNECTORS = frozenset(
    {
        "and", "or", "for", "of", "to", "with", "the", "a", "an", "in", "on",
        "by", "from", "as", "at", "between", "into", "per", "than", "that",
        "when", "which", "where", "y", "o", "u", "de", "del", "con", "para",
        "por", "en", "al", "e", "que", "como", "entre", "sin", "sobre",
    }
)
#: Colas que delatan un término cortado ("(Rule byte", "Field being").
_TRUNCATED_TAILS = frozenset(
    {"byte", "bytes", "field", "campo", "rule", "regla", "being", "case"}
)
_LEADING_CONNECTORS = frozenset(
    {"and", "or", "but", "y", "o", "u", "e", "pero", "aunque", "que", "como"}
)

#: Palabras que no aportan identidad a un término por sí solas.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "for", "to", "in", "on", "by", "and", "or",
        "el", "la", "los", "las", "un", "una", "de", "del", "para", "por",
        "y", "o", "en", "con", "sin",
    }
)


def _is_alnum(char: str) -> bool:
    return bool(char) and (char.isalnum())


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _shortest_containing(text: str, references: tuple[str, ...]) -> tuple[str | None, int]:
    """Primera referencia que contiene el texto, prefiriendo la más corta."""
    if not text:
        return None, -1
    for reference in sorted(references, key=len):
        if not reference or reference == text or len(reference) <= len(text):
            continue
        index = reference.find(text)
        if index >= 0:
            return reference, index
    return None, -1


def _word_in_references(token: str, references: tuple[str, ...]) -> bool:
    """¿La palabra aparece completa (límite de palabra) en alguna referencia?"""
    if not token:
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(token)}(?!\w)")
    return any(pattern.search(reference) for reference in references)


def _appears_standalone(text: str, references: tuple[str, ...]) -> bool:
    """Texto con límites de palabra en la fuente, no un pedazo de otra palabra."""
    needle = text.strip()
    if not needle or not references:
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    return any(pattern.search(reference) for reference in references)


def analyze_text_quality(
    text: str,
    *,
    references: tuple[str, ...] | list[str] = (),
    min_length: int = 3,
    allow_code: bool = True,
    max_words: int = 24,
    max_length: int = 240,
) -> TextQuality:
    """Evalúa si un texto puede ser conocimiento o es basura de extracción.

    ``references`` son los textos completos ya observados en la misma fuente:
    contra ellos se detecta que el candidato es un fragmento (corte a mitad de
    palabra) y no una entidad propia.
    """
    raw = " ".join((text or "").split())
    corpus = tuple(reference for reference in references if reference)
    reasons: list[str] = []

    if not raw:
        return TextQuality(
            status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
            reasons=("empty",),
            confidence=0.0,
        )
    if raw.isdigit():
        return TextQuality(
            status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
            reasons=("numeric_only",),
            confidence=0.8,
        )

    # 1 · Artefactos de layout: nunca son identidad.
    if _CONTROL_RE.search(raw):
        reasons.append("control_chars")
    if "|" in raw:
        reasons.append("pipe_delimiter")
    if raw.count("(") != raw.count(")") or raw.count("[") != raw.count("]"):
        reasons.append("unbalanced_brackets")
    if "\n" in raw or "\r" in raw:
        reasons.append("multi_line")
    if raw[:1] in "-–—•*∙" and len(raw) > 1 and raw[1:2].isspace():
        reasons.append("orphan_bullet")
    if raw.endswith(("-", "–", "—", ":", ";", ",")):
        reasons.append("open_punctuation_tail")
    if reasons:
        return TextQuality(
            status=TextQualityStatus.LAYOUT_ARTIFACT.value,
            reasons=tuple(reasons),
            confidence=0.9,
        )

    tokens = _tokens(raw)
    if len(raw) < min_length or not tokens:
        code_like = allow_code and len(raw) >= 2 and bool(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,15}", raw)
        )
        if not code_like:
            return TextQuality(
                status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
                reasons=("too_short",),
                confidence=0.8,
            )

    # 2 · Demasiado largo para un término/alias: es una oración o un párrafo.
    if len(tokens) > max_words or len(raw) > max_length:
        return TextQuality(
            status=TextQualityStatus.TOO_LONG_FOR_TERM.value,
            reasons=(f"words={len(tokens)}", f"length={len(raw)}"),
            confidence=0.85,
        )

    # 3 · Fragmento de otro texto de la misma fuente (corte a mitad de palabra).
    #    Si el texto aparece completo (límites de palabra) en alguna referencia,
    #    NO es fragmento: puede ser corto y seguir siendo una identidad propia.
    if not _appears_standalone(raw, corpus):
        reference, index = _shortest_containing(raw, corpus)
        if reference is not None:
            starts_mid_word = (
                index > 0 and _is_alnum(reference[index - 1]) and _is_alnum(raw[0])
            )
            end = index + len(raw)
            ends_mid_word = (
                end < len(reference) and _is_alnum(reference[end]) and _is_alnum(raw[-1])
            )
            ratio = len(raw) / max(len(reference), 1)
            if starts_mid_word or ends_mid_word:
                return TextQuality(
                    status=TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value,
                    reasons=(
                        "starts_mid_word" if starts_mid_word else "ends_mid_word",
                    ),
                    fragment_of=reference[:400],
                    fragment_ratio=ratio,
                    confidence=0.92,
                )
            if ratio <= 0.35:
                return TextQuality(
                    status=TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value,
                    reasons=("extreme_substring",),
                    fragment_of=reference[:400],
                    fragment_ratio=ratio,
                    confidence=0.75,
                )

    # 4 · Palabra única cortada (prefijo/sufijo de otra palabra de la fuente).
    if len(tokens) == 1 and not allow_code:
        token = tokens[0]
        if not _word_in_references(token, corpus):
            for reference in corpus:
                for word in _WORD_RE.findall(reference):
                    if len(word) <= len(token) or word == token:
                        continue
                    if word.startswith(token) or word.endswith(token):
                        return TextQuality(
                            status=TextQualityStatus.TRUNCATED_WORD.value,
                            reasons=(f"cut_of:{word[:60]}",),
                            fragment_of=reference[:400],
                            fragment_ratio=len(token) / len(word),
                            confidence=0.85,
                        )

    # 5 · Fragmento de oración: no cierra afirmación ni tiene estructura.
    lowered = [token.lower() for token in tokens]
    if lowered and lowered[-1] in _TRAILING_CONNECTORS:
        reasons.append("trailing_connector")
    if 2 <= len(tokens) <= 3 and lowered and lowered[-1] in _TRUNCATED_TAILS:
        reasons.append("truncated_tail")
    if lowered and lowered[0] in _LEADING_CONNECTORS and len(tokens) <= 4:
        reasons.append("leading_connector")
    if raw.endswith((",", ";", ":")) and len(tokens) <= 8:
        reasons.append("open_punctuation")
    if (
        len(tokens) == 1
        and len(tokens[0]) <= 2
        and tokens[0].isalpha()
    ):
        reasons.append("single_short_token")
    letters = sum(1 for char in raw if char.isalpha())
    vowels = sum(1 for char in raw if char in _VOWELS)
    if letters >= 4 and vowels == 0:
        reasons.append("no_vowels")
    if reasons and reasons != ["double_space"]:
        status = (
            TextQualityStatus.SENTENCE_FRAGMENT.value
            if "trailing_connector" in reasons or "open_punctuation" in reasons
            else TextQualityStatus.LOW_QUALITY_EXTRACTION.value
        )
        return TextQuality(status=status, reasons=tuple(reasons), confidence=0.7)

    return TextQuality(status=TextQualityStatus.OK.value, confidence=0.9)


def is_probable_fragment(
    candidate: str,
    *,
    references: tuple[str, ...] | list[str] = (),
    min_length: int = 3,
) -> bool:
    quality = analyze_text_quality(
        candidate, references=references, min_length=min_length
    )
    return quality.status in {
        TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value,
        TextQualityStatus.TRUNCATED_WORD.value,
    }


def repair_fragmented_parts(
    parts: list[str],
    *,
    vocabulary: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    """Reconstruye palabras partidas en celdas contiguas.

    Solo fusiona cuando la concatenación forma una palabra completa conocida
    (vocabulario de palabras reales de la misma página/documento). Nunca
    inventa: si no hay evidencia, deja las partes como están.
    """
    cleaned = [str(part or "").strip() for part in parts]
    if not vocabulary or len(cleaned) < 2:
        return cleaned
    folded = {word.lower() for word in vocabulary}

    def _fold(value: str) -> str:
        return _WORD_RE.sub("", value).lower()

    merged: list[str] = []
    index = 0
    while index < len(cleaned):
        current = cleaned[index]
        if not current:
            merged.append(current)
            index += 1
            continue
        probe = _fold(current)
        found = False
        if probe and probe not in folded:
            cursor = index
            while cursor + 1 < len(cleaned):
                nxt = _fold(cleaned[cursor + 1])
                if not nxt:
                    break
                probe += nxt
                cursor += 1
                if probe in folded:
                    merged.append("".join(cleaned[index : cursor + 1]))
                    index = cursor + 1
                    found = True
                    break
        if not found:
            merged.append(current)
            index += 1
    return merged


def completeness_score(text: str) -> float:
    """0..1 · qué tan completa es una afirmación (para el gate de conflictos)."""
    raw = (text or "").strip()
    if not raw:
        return 0.0
    quality = analyze_text_quality(raw, min_length=2, max_words=60, max_length=600)
    if quality.status != TextQualityStatus.OK.value:
        return 0.25 if quality.status == TextQualityStatus.SENTENCE_FRAGMENT.value else 0.1
    tokens = _tokens(raw)
    score = min(1.0, 0.35 + len(tokens) * 0.08)
    if raw[-1:] in ".!?)]’\"":
        score = min(1.0, score + 0.15)
    return round(score, 4)


__all__ = [
    "TextQuality",
    "TextQualityStatus",
    "analyze_text_quality",
    "is_probable_fragment",
    "repair_fragmented_parts",
    "completeness_score",
]
