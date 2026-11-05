# =============================================================================
# Normalización de texto para workflows.
#
# Herramienta genérica y determinista: convierte una pregunta o frase en los
# términos útiles para buscar, validar o comparar. No consulta fuentes ni
# inventa datos; el usuario configura el modo y las frases a ignorar desde el
# nodo `text_normalize`.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from typing import Any

MODES: tuple[str, ...] = ("product_query", "email", "name", "free")

# Palabras de pregunta, pedido, artículos y unidades que no aportan a una
# búsqueda de producto. El usuario puede agregar frases con `ignore_phrases`.
PRODUCT_STOPWORDS: frozenset[str] = frozenset(
    {
        "tienes",
        "tiene",
        "tienen",
        "hay",
        "quiero",
        "quisiera",
        "deseo",
        "desea",
        "busco",
        "buscame",
        "necesito",
        "dame",
        "vendes",
        "vende",
        "venden",
        "vender",
        "venta",
        "comprar",
        "compro",
        "precio",
        "precios",
        "cuanto",
        "cuanta",
        "cuantos",
        "cuantas",
        "cuesta",
        "cuestan",
        "vale",
        "valen",
        "de",
        "del",
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "y",
        "en",
        "por",
        "al",
        "a",
        "o",
        "favor",
        "hola",
        "buenas",
        "me",
        "mi",
        "para",
        "con",
        "que",
        "algo",
        "algun",
        "alguna",
        "producto",
        "productos",
        "articulo",
        "articulos",
        "cosa",
        "cosas",
        "kilo",
        "kilos",
        "kg",
        "gramo",
        "gramos",
        "g",
        "litro",
        "litros",
        "l",
        "unidad",
        "unidades",
        "caja",
        "cajas",
        "bolsa",
        "bolsas",
        "paquete",
        "paquetes",
    }
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_WORD_RE = re.compile(r"[a-z0-9]+")
_PHRASE_SPLIT_RE = re.compile(r"[,;\n]+")
_SPACE_RE = re.compile(r"\s+")
_NAME_CLEAN_RE = re.compile(r"[^\w\s'-]", re.UNICODE)


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "si", "sí", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _fold(value: str, *, strip_accents: bool) -> str:
    if not strip_accents:
        return value
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _phrases(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = _PHRASE_SPLIT_RE.split(value)
    elif isinstance(value, (list, tuple, set)):
        raw = [str(item) for item in value]
    else:
        raw = []
    out: list[str] = []
    for item in raw:
        phrase = str(item).strip().lower()
        if phrase and phrase not in out:
            out.append(phrase)
    return out


def _remove_phrases(value: str, phrases: list[str]) -> str:
    for phrase in phrases:
        value = re.sub(
            rf"(?<![\w-]){re.escape(phrase)}(?![\w-])",
            " ",
            value,
            flags=re.IGNORECASE,
        )
    return value


def _collapse(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


def _result(
    *,
    text: str,
    terms: list[str],
    original: str,
    removed: list[str],
    mode: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "terms": terms,
        "original": original,
        "removed": removed,
        "status": "OK" if text else "EMPTY",
        "mode": mode,
    }


def normalize_text(
    text: str,
    *,
    mode: str = "product_query",
    ignore_phrases: Any = None,
    lowercase: Any = True,
    strip_accents: Any = True,
    max_terms: Any = 6,
) -> dict[str, Any]:
    """Normaliza un texto según el modo configurado en el nodo."""
    original = str(text or "")
    normalized_mode = str(mode or "product_query").strip().lower()
    if normalized_mode not in MODES:
        normalized_mode = "product_query"
    keep_lowercase = _as_bool(lowercase, True)
    remove_accents = _as_bool(strip_accents, True)
    phrases = [
        _fold(phrase, strip_accents=remove_accents).lower()
        for phrase in _phrases(ignore_phrases)
    ]
    limit = _as_int(max_terms, 6, 1, 20)

    if normalized_mode == "email":
        match = _EMAIL_RE.search(original)
        value = match.group(0).lower() if match else ""
        return _result(
            text=value,
            terms=[value] if value else [],
            original=original,
            removed=[],
            mode=normalized_mode,
        )

    value = _fold(original, strip_accents=remove_accents)
    if keep_lowercase:
        value = value.lower()
    value = _remove_phrases(value, phrases)

    if normalized_mode == "product_query":
        # Las vocales acentuadas ya se plegaron; la ñ también cae a n.
        value = value.replace("ñ", "n").replace("Ñ", "N")
        tokens = _WORD_RE.findall(value)
        terms: list[str] = []
        removed: list[str] = []
        for token in tokens:
            if token in PRODUCT_STOPWORDS or (len(token) < 2 and not token.isdigit()):
                removed.append(token)
                continue
            if token not in terms:
                terms.append(token)
        terms = terms[:limit]
        return _result(
            text=" ".join(terms),
            terms=terms,
            original=original,
            removed=list(dict.fromkeys(removed)),
            mode=normalized_mode,
        )

    if normalized_mode == "name":
        value = _NAME_CLEAN_RE.sub(" ", value)
        value = _collapse(value)
        terms = value.split() if value else []
        return _result(
            text=value,
            terms=terms[:limit],
            original=original,
            removed=[],
            mode=normalized_mode,
        )

    value = _collapse(value)
    terms = value.split() if value else []
    return _result(
        text=value,
        terms=terms[:limit],
        original=original,
        removed=[],
        mode=normalized_mode,
    )


__all__ = ["MODES", "PRODUCT_STOPWORDS", "normalize_text"]
