# =============================================================================
# Anchors — identificadores estructurados de la pregunta, sin dominio.
# =============================================================================
# Un «anchor» es un token que la pata densa no sabe buscar: un run largo de
# dígitos, un código alfanumérico, un rango de posiciones. El core los extrae
# por FORMA (regex), no por semántica: no conoce categorías, records ni bytes.
#
# Los providers de dominio (plugins cargados por `RAG_ANCHOR_MODULES`) agregan
# semántica sin tocar el core: declaran cómo partir un token estructurado en
# anchors y qué términos de expansión sumar a la búsqueda.
# =============================================================================
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

MAX_ANCHORS = 4

#: Un run de 7+ dígitos no es prosa: es un identificador (tabla, cuenta, trama).
_MIN_DIGITS = 7
_DIGIT_RUN_RE = re.compile(rf"\b\d{{{_MIN_DIGITS},}}\b")
#: Código mixto (letras + dígitos, 8+ chars): R007D03E000, SKU-1234X.
_CODE_RE = re.compile(r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{8,}\b")
#: Rango numérico: 14-22, 64–67.
_RANGE_RE = re.compile(r"\b(\d{1,4})\s*[-–]\s*(\d{1,4})\b")


@dataclass(frozen=True)
class Anchor:
    """Identificador estructurado con sus formas de búsqueda y cobertura."""

    kind: str
    value: str
    label: str
    variants: tuple[str, ...]
    needles: tuple[str, ...]
    expansion_terms: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 1.0

    def to_public_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "value": self.value,
            "label": self.label,
            "expansion_terms": list(self.expansion_terms),
        }


@runtime_checkable
class AnchorProvider(Protocol):
    """Plugin de dominio: parte tokens estructurados en anchors semánticos."""

    def extract(self, question: str) -> list[Anchor]: ...


_providers: list[AnchorProvider] = []
_modules_loaded = False


def register_anchor_provider(provider: AnchorProvider) -> None:
    """Registra un provider de dominio (idempotente por tipo)."""
    if any(isinstance(existing, type(provider)) for existing in _providers):
        return
    _providers.append(provider)


def anchor_providers() -> tuple[AnchorProvider, ...]:
    return tuple(_providers)


def clear_anchor_providers() -> None:
    """Sólo tests: vuelve el registry a cero."""
    _providers.clear()


def load_anchor_modules(module_paths: list[str] | None = None) -> None:
    """Importa módulos de dominio que registran providers (patrón tools).

    Mismo contrato que `RAG_AGENT_TOOL_MODULES`: el módulo expone `register()`
    y llama a `register_anchor_provider`. Un módulo roto no rompe el sistema.
    """
    paths = module_paths
    if paths is None:
        try:
            from src.core.config import get_settings

            paths = [
                part.strip()
                for part in str(getattr(get_settings(), "ANCHOR_MODULES", "") or "").split(",")
                if part.strip()
            ]
        except Exception:  # noqa: BLE001 — settings nunca rompe el arranque
            paths = []
    for path in paths:
        try:
            module = importlib.import_module(path)
            register = getattr(module, "register", None)
            if callable(register):
                register()
            logger.info("Loaded anchor module", module=path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load anchor module", module=path, error=str(exc)[:150])


def _ensure_modules_loaded() -> None:
    global _modules_loaded
    if _modules_loaded:
        return
    _modules_loaded = True
    load_anchor_modules()


def _dedupe(anchors: list[Anchor]) -> list[Anchor]:
    """Sin repetir valor: el provider (semántico) gana sobre el genérico."""
    found: list[Anchor] = []
    seen: set[str] = set()
    for anchor in anchors:
        key = anchor.value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(anchor)
    return found


def _codigo(value: str) -> Anchor:
    variants = tuple(dict.fromkeys([value, value.lower()]))
    return Anchor(
        kind="codigo",
        value=value,
        label=f"codigo {value}",
        variants=variants,
        needles=variants,
    )


def _rango(first: str, second: str) -> Anchor:
    value = f"{first}-{second}"
    variants = tuple(
        dict.fromkeys([value, f"{first} {second}", f"{first}–{second}", f"{first} - {second}"])
    )
    needles = tuple(dict.fromkeys([value, f"{first} {second}", f"{first}–{second}"]))
    return Anchor(
        kind="rango",
        value=value,
        label=f"rango {value}",
        variants=variants,
        needles=needles,
    )


def _opaque_anchors(question: str) -> list[Anchor]:
    """Anchors por forma: dígitos largos, códigos mixtos y rangos."""
    text = question or ""
    found: list[Anchor] = []
    for match in _DIGIT_RUN_RE.finditer(text):
        found.append(_codigo(match.group(0)))
    for match in _CODE_RE.finditer(text):
        found.append(_codigo(match.group(0)))
    for match in _RANGE_RE.finditer(text):
        found.append(_rango(match.group(1), match.group(2)))
    return found


def extract_anchors(question: str, *, max_items: int = MAX_ANCHORS) -> list[Anchor]:
    """Anchors de la pregunta: providers de dominio primero, genéricos después."""
    _ensure_modules_loaded()
    found: list[Anchor] = []
    for provider in _providers:
        try:
            found.extend(provider.extract(question or ""))
        except Exception as exc:  # noqa: BLE001 — un provider roto no rompe la búsqueda
            logger.warning("Anchor provider failed", error=str(exc)[:150])
    found.extend(_opaque_anchors(question or ""))
    return _dedupe(found)[:max_items]


def anchor_needles(anchors: list[Anchor] | tuple[Anchor, ...]) -> list[str]:
    """Needles léxicas de todos los anchors, sin repetir."""
    needles: list[str] = []
    for anchor in anchors:
        for needle in anchor.needles:
            if needle and needle not in needles:
                needles.append(needle)
    return needles


def dense_query_rewrite(
    question: str,
    anchors: list[Anchor] | tuple[Anchor, ...] | None = None,
) -> str:
    """Pregunta sin tokens opacos, para el embedding.

    Los tokens estructurados no tienen señal semántica y contaminan el vector;
    viajan por la pata léxica. Si al limpiar no queda texto, se conserva la
    pregunta original: una búsqueda sin query no es una búsqueda.
    """
    text = question or ""
    if not text.strip():
        return text
    cleaned = _DIGIT_RUN_RE.sub(" ", text)
    cleaned = _CODE_RE.sub(" ", cleaned)
    cleaned = _RANGE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 3:
        return text
    return cleaned


def anchor_covered(anchor: Anchor, evidence_text: str) -> bool:
    """¿La evidencia menciona alguna forma del anchor? Contención de texto."""
    from src.intelligence.response.entities import normalize

    haystack = normalize(evidence_text)
    if not haystack:
        return False
    return any(variant and variant in haystack for variant in anchor.variants)


__all__ = [
    "MAX_ANCHORS",
    "Anchor",
    "AnchorProvider",
    "anchor_covered",
    "anchor_needles",
    "anchor_providers",
    "clear_anchor_providers",
    "dense_query_rewrite",
    "extract_anchors",
    "load_anchor_modules",
    "register_anchor_provider",
]
