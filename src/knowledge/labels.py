# =============================================================================
# Etiquetas con contenido léxico real (genérico, sin vocabulario de dominio).
# =============================================================================
# Un nodo del fabric puede ser una máscara del manual (&a&m&2, *a, &&test):
# no es vocabulario, no puede activar ni reemplazar la pregunta. Mismo criterio
# en extracción, enrichment y activación del plan semántico.
# =============================================================================
from __future__ import annotations

import re

_LETTER = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]")
#: Símbolos con los que arranca una máscara/código operativo, no una palabra.
_SYMBOL_START = re.compile(r"^[&*!#$%^~|<>]")


def meaningful_label(label: str) -> bool:
    """Etiqueta con contenido léxico real. Genérico, sin dominio."""
    text = " ".join(str(label or "").split())
    if len(text) < 3 or _SYMBOL_START.match(text):
        return False
    letters = len(_LETTER.findall(text))
    if letters < 3:
        return False
    return letters / len(text) >= 0.5


def word_like_label(label: str) -> bool:
    """Etiqueta que puede ser vocabulario operativo (palabra o código).

    Más laxo que `meaningful_label`: un código corto (NX7, FPROC) sí entra al
    fabric; una máscara (&a&m&2, *a) o un valor puramente numérico/simbólico,
    no.
    """
    text = " ".join(str(label or "").split())
    if not text or _SYMBOL_START.match(text):
        return False
    return bool(_LETTER.search(text))
