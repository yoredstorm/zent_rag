# =============================================================================
# Commerce — parser determinista de líneas de pedido
# =============================================================================
# "quiero 1 kilo de arroz" → {product_query: "arroz", quantity: 1, unit: "KG"}
#
# Es determinista y SIN LLM a propósito: la cantidad y la unidad son datos
# transaccionales (dinero e inventario). El LLM puede proponer la lectura de una
# frase ambigua, pero jamás fija el número que termina en una orden o un cobro.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

#: Palabras que no describen producto (intención, cortesía, conectores).
_STOPWORDS = frozenset(
    {
        "quiero", "queria", "querría", "necesito", "dame", "deme", "me", "das", "dale",
        "por", "favor", "un", "una", "uno", "unos", "unas", "el", "la", "los", "las", "de", "del",
        "y", "mas", "más", "tambien", "también", "agrega", "agregame", "agrégame", "anade", "añade",
        "suma", "sumame", "sí", "si", "no", "gracias", "hola", "buenas", "buenos", "dias", "días",
        "tardes", "noches", "para", "con", "sin", "que", "qué", "algo", "otro", "otra",
        "porfa", "porfavor", "cuanto", "cuánto", "cuesta", "vale", "precio", "hay", "tienen", "tiene",
        "adicional", "ademas", "además", "llevo", "llevame", "llévame", "kilos", "gramos",
    }
)

#: Unidad canónica por alias (singular/plural, abreviaturas).
_UNIT_ALIASES: dict[str, tuple[str, Decimal]] = {
    "kg": ("KG", Decimal("1")),
    "kilo": ("KG", Decimal("1")),
    "kilos": ("KG", Decimal("1")),
    "kilogramo": ("KG", Decimal("1")),
    "kilogramos": ("KG", Decimal("1")),
    "g": ("G", Decimal("1")),
    "gr": ("G", Decimal("1")),
    "gramo": ("G", Decimal("1")),
    "gramos": ("G", Decimal("1")),
    "l": ("L", Decimal("1")),
    "lt": ("L", Decimal("1")),
    "litro": ("L", Decimal("1")),
    "litros": ("L", Decimal("1")),
    "ml": ("ML", Decimal("1")),
    "mililitro": ("ML", Decimal("1")),
    "mililitros": ("ML", Decimal("1")),
    "unidad": ("UNIT", Decimal("1")),
    "unidades": ("UNIT", Decimal("1")),
    "uni": ("UNIT", Decimal("1")),
    "un": ("UNIT", Decimal("1")),
    "paquete": ("PACK", Decimal("1")),
    "paquetes": ("PACK", Decimal("1")),
    "pack": ("PACK", Decimal("1")),
    "caja": ("BOX", Decimal("1")),
    "cajas": ("BOX", Decimal("1")),
    "docena": ("DOZEN", Decimal("12")),
    "docenas": ("DOZEN", Decimal("12")),
    "media": ("HALF", Decimal("0.5")),
    "botella": ("UNIT", Decimal("1")),
    "botellas": ("UNIT", Decimal("1")),
    "lata": ("UNIT", Decimal("1")),
    "latas": ("UNIT", Decimal("1")),
    "saco": ("SACK", Decimal("1")),
    "sacos": ("SACK", Decimal("1")),
}

_NUMBER_WORDS: dict[str, Decimal] = {
    "un": Decimal("1"), "una": Decimal("1"), "uno": Decimal("1"), "medio": Decimal("0.5"),
    "media": Decimal("0.5"), "dos": Decimal("2"), "tres": Decimal("3"), "cuatro": Decimal("4"),
    "cinco": Decimal("5"), "seis": Decimal("6"), "siete": Decimal("7"), "ocho": Decimal("8"),
    "nueve": Decimal("9"), "diez": Decimal("10"),
}

_NUM_RE = re.compile(r"^\d+(?:[.,]\d+)?$")

#: Palabras que significan "no quiero nada más".
NEGATIVE_CLOSERS = (
    "nada mas", "nada más", "eso es todo", "es todo", "no gracias", "ninguno mas",
    "ninguno más", "nada", "no, nada", "nada por ahora", "solo eso", "sólo eso",
)
#: Palabras que confirman.
AFFIRMATIVES = ("si", "sí", "yes", "confirmo", "confirmado", "de acuerdo", "ok", "okay", "dale", "correcto")
#: Palabras que rechazan.
NEGATIVES = ("no", "nope", "cancelar", "cancela", "anula", "anular", "mejor no", "no quiero")


def normalize_text(value: str) -> str:
    """minúsculas + sin tildes + espacios colapsados (comparación estable)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s.,/-]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def parse_order_line(text: str) -> dict[str, Any]:
    """Extrae producto, cantidad y unidad de una frase de cliente.

    Devuelve `{product_query, quantity, unit, tokens}`. Nunca lanza: una frase
    sin producto devuelve `product_query` vacío para que la capa de negocio
    decida (preguntar de nuevo, no inventar un producto).
    """
    normalized = normalize_text(text)
    tokens = normalized.split()
    quantity: Decimal | None = None
    unit: str | None = None
    product_tokens: list[str] = []

    for token in tokens:
        if _NUM_RE.match(token):
            if quantity is None:
                quantity = _decimal(token)
            continue
        if token in _UNIT_ALIASES:
            canon, factor = _UNIT_ALIASES[token]
            unit = canon
            if factor != 1 and quantity is None:
                quantity = factor
            elif factor != 1 and quantity is not None:
                quantity = quantity * factor
            continue
        if token in _NUMBER_WORDS and quantity is None:
            quantity = _NUMBER_WORDS[token]
            continue
        if token in _STOPWORDS:
            continue
        # plural simple → singular (arroz, leches → leche, arroces)
        product_tokens.append(token)

    product_query = " ".join(product_tokens).strip()
    return {
        "product_query": product_query,
        "quantity": float(quantity) if quantity is not None else None,
        "unit": unit,
        "tokens": product_tokens,
    }


def is_negative_closer(text: str) -> bool:
    normalized = normalize_text(text)
    return any(normalized == phrase or normalized.startswith(phrase) for phrase in NEGATIVE_CLOSERS)


def is_affirmative(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    first = normalized.split()[0]
    return first in AFFIRMATIVES or normalized in AFFIRMATIVES


def is_negative(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    first = normalized.split()[0]
    return first in NEGATIVES or normalized in NEGATIVES


def token_score(haystack: str, needle_tokens: list[str]) -> float:
    """Similitud determinista 0..1 entre un nombre de producto y tokens de query."""
    if not needle_tokens:
        return 0.0
    hay = normalize_text(haystack)
    hay_tokens = set(hay.split())
    matched = 0.0
    for token in needle_tokens:
        if token in hay_tokens:
            matched += 1.0
        elif token and token in hay:
            matched += 0.75
        elif token and len(token) >= 4 and any(
            h.startswith(token[:4]) for h in hay_tokens if len(h) >= 4
        ):
            matched += 0.5
    return round(matched / len(needle_tokens), 4)
