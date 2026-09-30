# =============================================================================
# Exact tokens — lo que la pregunta nombra y debe sobrevivir literalmente
# =============================================================================
# Unión de fuentes, sin dominio:
#   1. anchors existentes (máscaras, códigos, siglas, rangos) — se reutilizan;
#   2. formas entrecomilladas y rutas/campos (`a.b`, `a_b`, `0x1F`);
#   3. pares nombre+número («record 2», «byte 105», «tabla 961») y valores
#      con símbolo («15%»).
# Es la base de la pata exacta y del pin MUST_KEEP. No conoce ningún vertical:
# todo se detecta por forma.
# =============================================================================
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from src.intelligence.response.anchors import extract_anchors

MAX_EXACT_TOKENS = 8
MAX_EXACT_NEEDLES = 12

_QUOTED_RE = re.compile(
    r"[`\"'\u00ab\u00bb\u201c\u201d]([^`\"'\u00ab\u00bb\u201c\u201d]{2,80})[`\"'\u00ab\u00bb\u201c\u201d]"
)
_FIELD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")
_DOTTED_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]+)+\b")
_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")
_WORD_NUM_RE = re.compile(r"\b([A-Za-zÁÉÍÓÚÑÜáéíóúñü]{3,14})\s+(\d{1,6})\b")
_PERCENT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?%")

#: Palabras funcionales: «en 2024» no es un identificador compuesto.
_STOPWORDS = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
        "al", "a", "en", "con", "para", "por", "y", "o", "u", "que", "se",
        "su", "sus", "es", "son", "the", "of", "and", "or", "to", "in", "on",
        "for", "with", "at", "by", "is", "are", "was", "were", "be",
    }
)

#: Mapeo de kind de Anchor a kind exacto (mismo vocabulario del core).
_ANCHOR_KINDS = {
    "codigo": "codigo",
    "sigla": "sigla",
    "mascara": "mascara",
    "rango": "rango",
}


@dataclass(frozen=True)
class ExactToken:
    """Token que la pata exacta busca literalmente y el pin protege."""

    value: str
    kind: str
    needles: tuple[str, ...]
    origin: str = "form"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "kind": self.kind,
            "needles": list(self.needles),
        }


def _token(value: str, kind: str, origin: str = "form") -> ExactToken:
    forms = tuple(dict.fromkeys([value, value.lower()]))
    return ExactToken(value=value, kind=kind, needles=forms, origin=origin)


def _quoted(text: str) -> list[ExactToken]:
    found: list[ExactToken] = []
    for match in _QUOTED_RE.finditer(text):
        value = match.group(1).strip()
        if len(value) >= 2:
            found.append(_token(value, "cita", "quoted"))
    return found


def _fields(text: str) -> list[ExactToken]:
    found: list[ExactToken] = []
    for match in _DOTTED_RE.finditer(text):
        found.append(_token(match.group(0), "campo", "dotted"))
    for match in _FIELD_RE.finditer(text):
        found.append(_token(match.group(0), "campo", "field"))
    for match in _HEX_RE.finditer(text):
        found.append(_token(match.group(0), "codigo", "hex"))
    return found


def _anchors(text: str) -> list[ExactToken]:
    """Anchors del core, priorizando máscaras y códigos sobre siglas sueltas."""
    priority = {"mascara": 0, "codigo": 1, "rango": 2, "sigla": 3}
    anchors = sorted(
        extract_anchors(text, max_items=MAX_EXACT_TOKENS * 2),
        key=lambda anchor: priority.get(anchor.kind, 4),
    )
    found: list[ExactToken] = []
    for anchor in anchors:
        kind = _ANCHOR_KINDS.get(anchor.kind)
        if kind is None:
            continue
        found.append(
            ExactToken(
                value=anchor.value,
                kind=kind,
                needles=tuple(dict.fromkeys(anchor.needles)),
                origin="anchor",
            )
        )
    return found


def _word_numbers(text: str) -> list[ExactToken]:
    found: list[ExactToken] = []
    for match in _WORD_NUM_RE.finditer(text):
        word = match.group(1)
        if word.lower() in _STOPWORDS:
            continue
        found.append(_token(f"{word} {match.group(2)}", "valor_compuesto", "pair"))
    return found


def _values(text: str) -> list[ExactToken]:
    return [
        _token(match.group(0), "valor", "value")
        for match in _PERCENT_RE.finditer(text)
    ]


def extract_exact_tokens(
    question: str,
    *,
    max_items: int = MAX_EXACT_TOKENS,
) -> list[ExactToken]:
    """Tokens exactos de la pregunta, sin repetir, ordenados por especificidad."""
    text = html.unescape(question or "")
    found: list[ExactToken] = []
    found.extend(_quoted(text))
    found.extend(_fields(text))
    found.extend(_anchors(text))
    found.extend(_word_numbers(text))
    found.extend(_values(text))

    deduped: list[ExactToken] = []
    seen: set[str] = set()
    for token in found:
        value = token.value.strip()
        key = value.lower()
        if len(value) < 2 or key in seen:
            continue
        seen.add(key)
        deduped.append(token)
    return deduped[: max(1, int(max_items))]


def exact_needles(
    tokens: list[ExactToken] | tuple[ExactToken, ...],
    *,
    max_items: int = MAX_EXACT_NEEDLES,
) -> list[str]:
    """Needles literales de todos los tokens, sin repetir (case-insensitive)."""
    needles: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        for needle in token.needles:
            value = (needle or "").strip()
            key = value.lower()
            if len(value) < 2 or key in seen:
                continue
            seen.add(key)
            needles.append(value)
    return needles[: max(1, int(max_items))]


def exact_needles_for_query(
    question: str,
    *,
    max_tokens: int = MAX_EXACT_TOKENS,
    max_needles: int = MAX_EXACT_NEEDLES,
) -> list[str]:
    """Atajo: tokens exactos y needles de una consulta cruda."""
    return exact_needles(
        extract_exact_tokens(question, max_items=max_tokens),
        max_items=max_needles,
    )


__all__ = [
    "ExactToken",
    "MAX_EXACT_NEEDLES",
    "MAX_EXACT_TOKENS",
    "exact_needles",
    "exact_needles_for_query",
    "extract_exact_tokens",
]
