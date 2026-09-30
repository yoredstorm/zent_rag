# =============================================================================
# Normalización triple — semántica / lexical / exacta
# =============================================================================
# Una sola normalización no sirve para tres patas: la semántica quiere prosa,
# la lexical quiere tokens útiles y la exacta NO puede perder símbolos
# (&&&F, *F*, F%, R007D03E000). El embedding sigue usando el texto original;
# estas funciones alimentan cada pata por separado. Sin negocio vertical.
# =============================================================================
from __future__ import annotations

import html
import re
import unicodedata

#: Símbolos que en documentación técnica son parte del token, no separadores.
_TECH_SYMBOLS = "&*%#._-+/=<>@$"

_WS_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LEXICAL_KEEP_RE = re.compile(rf"[^a-z0-9{re.escape(_TECH_SYMBOLS)}\s]+")


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def normalize_for_exact_search(text: str) -> str:
    """Copia fiel de la consulta: símbolos, máscaras, mayúsculas, puntuación.

    Sólo desescapa entidades HTML (`&amp;` vuelve a `&`), normaliza unicode y
    colapsa espacios. NUNCA aplica regex que borre símbolos: `&&&F` llega
    intacto hasta la comparación literal.
    """
    raw = html.unescape(text or "")
    raw = unicodedata.normalize("NFKC", raw)
    raw = _CONTROL_RE.sub(" ", raw)
    return _WS_RE.sub(" ", raw).strip()


def normalize_for_lexical_search(text: str) -> str:
    """Tokens útiles para BM25 conservando patrones técnicos.

    Minúsculas, sin acentos, puntuación de prosa a espacio; los símbolos
    técnicos (`&*%#._-+/=<>@$`) sobreviven dentro del token: `FCLAS &&&F` queda
    `fclas &&&f`. El tokenizador aguas abajo puede partir distinto; esta
    normalización garantiza que la información no se destruya ANTES de llegar.
    """
    stripped = _strip_accents(html.unescape(text or "").lower())
    cleaned = _LEXICAL_KEEP_RE.sub(" ", stripped)
    return _WS_RE.sub(" ", cleaned).strip()


def normalize_for_semantic_search(text: str) -> str:
    """Prosa limpia para el embedding: unicode NFC, espacios, sin controles.

    La pata semántica parte del texto ORIGINAL (acentos y contexto valen). Si
    el llamador quiere expulsar tokens opacos del embedding, la función
    `dense_query_rewrite` de anchors ya existe y hace exactamente eso.
    """
    raw = html.unescape(text or "")
    raw = unicodedata.normalize("NFC", raw)
    raw = _CONTROL_RE.sub(" ", raw)
    return _WS_RE.sub(" ", raw).strip()


__all__ = [
    "normalize_for_exact_search",
    "normalize_for_lexical_search",
    "normalize_for_semantic_search",
]
