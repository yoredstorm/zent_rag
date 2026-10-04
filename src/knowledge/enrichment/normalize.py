# =============================================================================
# Enrichment — normalización determinista (sin LLM)
# =============================================================================
# Estas funciones SOLO generan variantes de búsqueda. El valor original nunca
# se pierde: las variantes son aliases con provenance, no reemplazos.
# =============================================================================
from __future__ import annotations

import re
import unicodedata

_ARTICLE_PREFIXES = ("the ", "el ", "la ", "los ", "las ", "un ", "una ")
_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\-]+", re.UNICODE)


def collapse(value: str) -> str:
    return _WS.sub(" ", str(value or "").strip())


def ascii_fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_key(value: str) -> str:
    """Clave de dedupe/comparación (minúsculas, sin acentos, sin puntuación)."""
    folded = ascii_fold(collapse(value)).lower()
    return _NON_WORD.sub(" ", folded).strip()


def title_first(value: str) -> str:
    cleaned = collapse(value)
    if not cleaned:
        return ""
    if cleaned.isupper() or cleaned.islower():
        return cleaned[:1].upper() + cleaned[1:].lower()
    return cleaned


def without_article(value: str) -> str:
    lowered = collapse(value).lower()
    for prefix in _ARTICLE_PREFIXES:
        if lowered.startswith(prefix):
            return collapse(value)[len(prefix):]
    return collapse(value)


def surface_variants(value: str, *, max_variants: int = 8) -> tuple[str, ...]:
    """Variantes de superficie para retrieval (case, separadores, código)."""
    cleaned = collapse(value)
    if not cleaned or len(cleaned) > 80:
        return ()
    variants: list[str] = [cleaned, cleaned.lower(), cleaned.upper()]
    canonical = title_first(cleaned)
    if canonical:
        variants.append(canonical)
    no_article = without_article(canonical or cleaned)
    if no_article and no_article != canonical:
        variants.append(no_article)

    tokens = [token for token in re.split(r"[\s\-_/]+", cleaned) if token]
    if 1 < len(tokens) <= 5:
        variants.append("".join(tokens))
        variants.append("-".join(tokens).lower())
        variants.append("_".join(tokens).lower())
        # "CAT 31" -> "CAT31"; "Category 31" -> "Category31"
        joined = "".join(tokens).lower()
        if any(char.isdigit() for char in joined):
            variants.append(joined.upper())
        # "Category 31" -> "Cat 31" (abreviatura determinista del primer token).
        if len(tokens[0]) >= 5:
            variants.append(" ".join([tokens[0][:3], *tokens[1:]]))

    seen: set[str] = set()
    result: list[str] = []
    for variant in variants:
        folded = collapse(variant)
        if folded and folded.lower() not in seen and folded.lower() != cleaned.lower():
            seen.add(folded.lower())
            result.append(folded)
        elif folded.lower() == cleaned.lower():
            seen.add(folded.lower())
    return tuple(result[:max_variants])


def is_terse_code(value: str) -> bool:
    """Código corto en mayúsculas/dígitos («CAT31», «CXRCD», «BYTE105»)."""
    cleaned = collapse(value)
    if not 2 <= len(cleaned) <= 24:
        return False
    if " " in cleaned:
        return False
    letters = sum(1 for char in cleaned if char.isalpha())
    digits = sum(1 for char in cleaned if char.isdigit())
    if letters < 2:
        return False
    upper_ratio = sum(1 for char in cleaned if char.isupper()) / max(letters, 1)
    return upper_ratio >= 0.6 and (digits >= 1 or len(cleaned) >= 4)


def split_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token for token in re.split(r"[\s\-_/.]+", collapse(value)) if token
    )
