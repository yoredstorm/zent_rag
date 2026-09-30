# =============================================================================
# Source references — «record 2», «byte 105», «tabla 961» como referencia
# =============================================================================
# Capa genérica y determinística: convierte lo que la pregunta nombra en
# referencias documentales con ALIASES aptos para nombres de fuente
# («Rec2_Rules», «Cat10_dapp», «TBL_961»). No conoce ningún dominio: sólo
# vocabulario ESTRUCTURAL (record, byte, category, table, section, chapter,
# part, appendix, field, figure, item) y variantes ES/EN.
#
# Uso principal: SourceRouter (priorizar fuentes ANTES del chunk ranking) y
# cobertura de referencias. Nunca hardcodea un archivo concreto.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from src.intelligence.response.entities import AskedEntity, asked_entities

#: Palabras estructurales por tipo (ES/EN). Orden = prioridad de forma.
BASE_WORDS: dict[str, tuple[str, ...]] = {
    "record": ("record", "rec", "registro"),
    "byte": ("byte",),
    "category": ("category", "cat", "categoria"),
    "table": ("table", "tabla", "tbl"),
    "section": ("section", "seccion", "sec"),
    "chapter": ("chapter", "capitulo", "cap"),
    "part": ("part", "parte"),
    "appendix": ("appendix", "anexo", "apendice"),
    "field": ("field", "campo"),
    "figure": ("figure", "figura", "fig"),
    "item": ("item", "elemento"),
}

#: kind de asked_entities → kind canónico de referencia.
_ENTITY_KIND_MAP = {
    "record": "record",
    "byte": "byte",
    "categoría": "category",
    "tabla": "table",
    "campo": "field",
}

#: Regex de parseo por kind: acepta «record 2», «rec2», «record_2», «Rec-2».
_REFERENCE_PATTERNS: dict[str, re.Pattern[str]] = {
    kind: re.compile(
        rf"\b(?:{'|'.join(re.escape(word) for word in words)})"
        rf"[\s._\-#]*(\d{{1,4}})(?!\d)",
        re.IGNORECASE,
    )
    for kind, words in BASE_WORDS.items()
}


@dataclass(frozen=True)
class SourceReference:
    """Referencia estructural pedida por el usuario, con sus formas de match."""

    kind: str
    value: str
    label: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "value": self.value,
            "label": self.label,
            "aliases": list(self.aliases[:8]),
        }


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def normalize_source_name(text: str) -> str:
    """Nombre de fuente comparable: sin extensión, minúsculas, sin acentos.

    Conserva separadores como espacio (`Rec2_Rules.pdf` → `rec2 rules`).
    """
    plain = _strip_accents(str(text or "")).lower()
    plain = re.sub(r"\.(pdf|docx?|txt|md|csv|xlsx?|html?)$", "", plain.strip())
    plain = re.sub(r"[\s._\-/\\]+", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


def reference_aliases(kind: str, value: str) -> tuple[str, ...]:
    """Aliases filename-friendly de una referencia: record 2 → rec2, rec_2..."""
    words = BASE_WORDS.get(kind, (kind,))
    forms: list[str] = []
    for word in words:
        forms.extend(
            [
                f"{word} {value}",
                f"{word}{value}",
                f"{word}_{value}",
                f"{word}-{value}",
                f"{word}.{value}",
                f"{word}/{value}",
            ]
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for form in forms:
        key = form.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(form)
    return tuple(deduped)


#: Sinónimos por palabra: «record» ≡ «rec» ≡ «registro» al matchear nombres.
_WORD_SYNONYMS: dict[str, tuple[str, ...]] = {}
for _kind_words in BASE_WORDS.values():
    for _word in _kind_words:
        _WORD_SYNONYMS[_word] = _kind_words


def _reference_pattern(alias: str) -> str | None:
    """Patrón regex tolerante para «palabra valor», con sinónimos.

    «record2», «rec-2» y «registro 2» producen el mismo patrón de match.
    """
    match = re.match(
        r"^([a-z]+)[\s._\-/\\]*(\d{1,4})$", str(alias or "").strip().lower()
    )
    if not match:
        return None
    word, value = match.group(1), match.group(2)
    words = _WORD_SYNONYMS.get(word, (word,))
    alternatives = "|".join(
        re.escape(candidate)
        for candidate in sorted(words, key=len, reverse=True)
    )
    return rf"(?:{alternatives})[\s._\-/\\]*{value}"


def alias_in_source_name(alias: str, source_name: str) -> bool:
    """¿El alias aparece en el nombre, con separadores libres y sin comerse dígitos?

    Acepta sinónimos estructurales («record 2» ↔ `Rec2`, «category 31» ↔
    `Cat31`) y NO matchea números distintos (`Cat15` con «cat 1»).
    """
    if not alias or not source_name:
        return False
    normalized = normalize_source_name(source_name)
    pattern = _reference_pattern(alias)
    if pattern:
        for haystack in (normalized, normalized.replace(" ", "")):
            if re.search(rf"(?<![a-z0-9]){pattern}(?!\d)", haystack):
                return True
        return False
    compact_alias = re.sub(r"[\s._\-/\\]+", "", alias.lower())
    if not compact_alias:
        return False
    if re.search(rf"(?<![a-z0-9]){re.escape(compact_alias)}(?!\d)", normalized.replace(" ", "")):
        return True
    spaced = re.sub(r"\s+", r"[\\s._\\-]*", re.escape(re.sub(r"[\s._\-/\\]+", " ", alias.lower()).strip()))
    return bool(re.search(rf"(?<![a-z0-9]){spaced}(?!\d)", normalized))


def references_from_entities(
    entities: list[AskedEntity] | tuple[AskedEntity, ...],
) -> list[SourceReference]:
    """Convierte entidades pedidas en referencias (sin duplicar kind+valor)."""
    references: list[SourceReference] = []
    seen: set[tuple[str, str]] = set()
    for entity in entities or ():
        kind = _ENTITY_KIND_MAP.get(str(entity.kind))
        value = str(entity.value or "").strip()
        if not kind or not value:
            continue
        key = (kind, value.lower())
        if key in seen:
            continue
        seen.add(key)
        references.append(
            SourceReference(
                kind=kind,
                value=value,
                label=f"{kind} {value}",
                aliases=reference_aliases(kind, value),
            )
        )
    return references


def extract_source_references(question: str) -> list[SourceReference]:
    """Referencias estructurales de la pregunta, genéricas y sin dominio.

    Combina lo que ya detecta `asked_entities` (record/byte/categoría/tabla/
    campo) con el resto del vocabulario estructural (sección, capítulo, parte,
    apéndice, figura, ítem).
    """
    references = references_from_entities(asked_entities(question))
    seen = {(reference.kind, reference.value.lower()) for reference in references}
    for kind, pattern in _REFERENCE_PATTERNS.items():
        for match in pattern.finditer(question or ""):
            value = match.group(1)
            if not value:
                continue
            key = (kind, value.lower())
            if key in seen:
                continue
            seen.add(key)
            references.append(
                SourceReference(
                    kind=kind,
                    value=value,
                    label=f"{kind} {value}",
                    aliases=reference_aliases(kind, value),
                )
            )
    return references


def parse_declared_references(source_name: str, *, title: str = "") -> list[SourceReference]:
    """Referencias DECLARADAS por el nombre/título de una fuente.

    «Rec2_Cat10_dapp_C.pdf» → record 2 + category 10. Sirve para:
    match contra lo pedido y penalización de qualifiers extra.
    """
    text = f"{source_name or ''} {title or ''}".strip()
    if not text:
        return []
    references: list[SourceReference] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _REFERENCE_PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group(1)
            if not value:
                continue
            key = (kind, value.lower())
            if key in seen:
                continue
            seen.add(key)
            references.append(
                SourceReference(
                    kind=kind,
                    value=value,
                    label=f"{kind} {value}",
                    aliases=reference_aliases(kind, value),
                )
            )
    return references


def reference_matches_source(reference: SourceReference, source_name: str, *, title: str = "") -> bool:
    """¿La fuente (nombre/título) declara esta referencia?"""
    haystack = f"{source_name or ''} {title or ''}"
    return any(
        alias_in_source_name(alias, haystack) for alias in reference.aliases
    )


__all__ = [
    "BASE_WORDS",
    "SourceReference",
    "alias_in_source_name",
    "extract_source_references",
    "normalize_source_name",
    "parse_declared_references",
    "reference_aliases",
    "reference_matches_source",
    "references_from_entities",
]
