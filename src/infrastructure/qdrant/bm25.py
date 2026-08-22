# =============================================================================
# BM25 Tokenizer — sparse vectors para búsqueda lexical en Qdrant
# =============================================================================
# Computa vectores sparse {token: term_frequency} sin dependencias externas.
# El IDF lo resuelve el índice sparse de Qdrant (modifier IDF cuando el
# servidor lo soporta). Query e ingesta usan el MISMO tokenizador, lo que
# garantiza consistencia de matching.
# =============================================================================
from __future__ import annotations

import hashlib
import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def _token_index(token: str) -> int:
    """Índice determinista de 32 bits por token.

    Importante: NO usar hash() de Python (PYTHONHASHSEED lo hace aleatorio
    por proceso; el matching entre ingesta y query se rompería).
    """
    return int.from_bytes(
        hashlib.md5(token.encode("utf-8")).digest()[:4], "big"  # noqa: S324 (hashing no criptográfico)
    )


def tokenize(text: str) -> list[str]:
    """Tokeniza: minúsculas, sin acentos, split por no-alfanumérico."""
    stripped = _strip_accents((text or "").lower())
    return _TOKEN_RE.findall(stripped)


def encode_sparse(text: str) -> dict[str, float]:
    """Vector sparse TF (frecuencia de términos) de un texto."""
    vector: dict[str, float] = {}
    for token in tokenize(text):
        vector[token] = vector.get(token, 0.0) + 1.0
    return vector


def to_sparse_payload(tf: dict[str, float]) -> tuple[list[int], list[float]]:
    """Convierte {token: tf} en (indices, values) deterministas para Qdrant."""
    tokens = sorted(tf)
    return [ _token_index(t) for t in tokens ], [tf[t] for t in tokens]
