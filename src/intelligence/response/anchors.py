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

import html
import importlib
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

MAX_ANCHORS = 8

#: Un run de 7+ dígitos no es prosa: es un identificador (tabla, cuenta, trama).
_MIN_DIGITS = 7
_DIGIT_RUN_RE = re.compile(rf"\b\d{{{_MIN_DIGITS},}}\b")
#: Código mixto (letras + dígitos, 8+ chars): R007D03E000, SKU-1234X.
_CODE_RE = re.compile(r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{8,}\b")
#: Rango numérico: 14-22, 64–67.
_RANGE_RE = re.compile(r"\b(\d{1,4})\s*[-–]\s*(\d{1,4})\b")
#: Sigla: MAYÚSCULAS de 3-8 letras (FCLAS, RBD, TSI). Los acrónimos técnicos
#: genéricos no son señal: están en la stoplist.
_SIGLA_RE = re.compile(r"\b[A-Z]{3,8}\b")
_SIGLA_STOPWORDS = frozenset(
    {
        "PDF", "API", "URL", "URI", "HTTP", "HTTPS", "JSON", "SQL", "LLM",
        "RAG", "ID", "UUID", "CSV", "XML", "HTML", "MCP", "SDK", "CLI",
        "UI", "UX", "OK", "TODO", "NOTA",
    }
)
#: Máscara con comodines: &&&F, *F*, F%, AAA-###. Un `?` de prosa («¿qué?») no cuenta.
_MASK_CHARS = "&*?%#@!~^"
_MASK_RUN_RE = re.compile(r"[A-Za-z0-9&*?%#@!~^][A-Za-z0-9&*?%#@!~^_-]{1,15}")
#: Rango con barra: 64/67.
_SLASH_RANGE_RE = re.compile(r"\b(\d{1,4})\s*/\s*(\d{1,4})\b")
#: Código corto palabra+dígitos pegados: CAT31, Byte105. La parte alfabética
#: necesita una mayúscula: «gpt4» no es señal técnica.
_WORD_DIGIT_RE = re.compile(r"\b([A-Za-zÁÉÍÓÚÑÜáéíóúñü]{2,14})(\d{1,6})\b")
#: Código con guion: ABC-123, A-12 (si hay dígito o la parte previa es sigla).
_HYPHEN_CODE_RE = re.compile(r"\b[A-Za-z]{1,8}-[A-Za-z0-9]{1,12}\b")
#: Código con guion bajo: ABC_123, fare_basis.
_UNDERSCORE_CODE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")


def _clean(question: str) -> str:
    """Pregunta sin entidades HTML: el portal puede guardar `&amp;&amp;&amp;F`."""
    return html.unescape(question or "")


@dataclass(frozen=True)
class Anchor:
    """Identificador estructurado con sus formas de búsqueda y cobertura.

    `role`/`semantic_hint` los puede fijar un provider de dominio (plugin). El
    core no conoce roles de negocio: si vienen vacíos, la capa long-context los
    clasifica por forma (máscara=regla, sigla=campo, código=referencia o valor
    de ejemplo según la pregunta). `must_search_exact` y `must_preserve` nacen
    en True: un token técnico no puede perderse ni normalizarse.
    """

    kind: str
    value: str
    label: str
    variants: tuple[str, ...]
    needles: tuple[str, ...]
    expansion_terms: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 1.0
    #: rol declarado por un plugin de dominio (rule_anchor, field_anchor,
    #: example_value, entity, reference). Vacío = lo clasifica el core.
    role: str = ""
    #: pista semántica de dominio («fare class positional mask»); el core la
    #: suma al canal semántico, nunca la inventa.
    semantic_hint: str = ""
    #: True = el token debe conservarse literal durante TODO el retrieval.
    must_preserve: bool = True
    #: True = la pata exacta lo busca tal cual (sin pasar por tokenizadores).
    must_search_exact: bool = True

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "value": self.value,
            "label": self.label,
            "expansion_terms": list(self.expansion_terms),
        }
        if self.role:
            payload["role"] = self.role
        if self.semantic_hint:
            payload["semantic_hint"] = self.semantic_hint
        if not self.must_preserve:
            payload["must_preserve"] = False
        if not self.must_search_exact:
            payload["must_search_exact"] = False
        return payload


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
    """Sin repetir valor: el provider (semántico) gana sobre el genérico.

    Además descarta sub-tokens contenidos en un anchor más largo («ABC» dentro
    de «ABC-123», «AAA» dentro de «AAA-###»): un fragmento del token no es una
    premisa documental distinta.
    """
    found: list[Anchor] = []
    seen: set[str] = set()
    for anchor in anchors:
        key = anchor.value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(anchor)
    if len(found) < 2:
        return found
    values = [anchor.value.strip().lower() for anchor in found]
    return [
        anchor
        for anchor, key in zip(found, values)
        if not any(key != other and key in other for other in values)
    ]


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
        dict.fromkeys(
            [
                value,
                f"{first} {second}",
                f"{first}/{second}",
                f"{first}–{second}",
                f"{first} - {second}",
            ]
        )
    )
    needles = tuple(
        dict.fromkeys([value, f"{first} {second}", f"{first}/{second}", f"{first}–{second}"])
    )
    return Anchor(
        kind="rango",
        value=value,
        label=f"rango {value}",
        variants=variants,
        needles=needles,
    )


def _sigla(value: str) -> Anchor:
    variants = tuple(dict.fromkeys([value, value.lower()]))
    return Anchor(
        kind="sigla",
        value=value,
        label=f"sigla {value}",
        variants=variants,
        needles=variants,
    )


def _mascara(value: str) -> Anchor:
    variants = tuple(dict.fromkeys([value, value.lower()]))
    return Anchor(
        kind="mascara",
        value=value,
        label=f"mascara {value}",
        variants=variants,
        needles=variants,
    )


def _es_mascara(token: str) -> bool:
    """Comodines de verdad: 2+ comodines, o 1 con una MAYÚSCULA en el token.

    «&&&F» y «*F*» son máscaras. «2?» de «Record 2?» es prosa: un comodín con
    dígito y sin letra no es un patrón. «FCLAS?» al final de una oración es la
    sigla con signo de pregunta, no una máscara.
    """
    comodines = sum(1 for char in token if char in _MASK_CHARS)
    if not comodines:
        return False
    if comodines >= 2:
        # Una corrida de 2+ comodines es un patrón aunque no tenga alfanuméricos
        # («????», «&&»): no es prosa.
        return True
    if not any(char.isalnum() for char in token):
        return False
    if token.endswith("?") and comodines == 1:
        return False
    if comodines < 2 and not any(char.isupper() for char in token):
        return False
    return True


def _siglas(text: str) -> list[Anchor]:
    return [
        _sigla(match.group(0))
        for match in _SIGLA_RE.finditer(text)
        if match.group(0) not in _SIGLA_STOPWORDS
    ]


def _clean_mask_token(token: str) -> str:
    """Quita el `?` de cierre de oración pegado a la máscara («&&&F?»)."""
    while len(token) > 1 and token.endswith("?") and token[-2].isalnum():
        token = token[:-1]
    return token


def _mascaras(text: str) -> list[Anchor]:
    found: list[Anchor] = []
    for match in _MASK_RUN_RE.finditer(text):
        token = _clean_mask_token(match.group(0))
        if token and _es_mascara(token):
            found.append(_mascara(token))
    return found


def _opaque_anchors(question: str) -> list[Anchor]:
    """Anchors por forma: dígitos, códigos, siglas, máscaras y rangos."""
    text = _clean(question)
    found: list[Anchor] = []
    for match in _DIGIT_RUN_RE.finditer(text):
        found.append(_codigo(match.group(0)))
    for match in _CODE_RE.finditer(text):
        found.append(_codigo(match.group(0)))
    # Formas técnicas genéricas: CAT31, Byte105, ABC-123, ABC_123.
    for match in _WORD_DIGIT_RE.finditer(text):
        if any(char.isupper() for char in match.group(1)):
            found.append(_codigo(match.group(0)))
    for match in _HYPHEN_CODE_RE.finditer(text):
        token = match.group(0)
        if any(char.isdigit() for char in token) or token.split("-")[0].isupper():
            found.append(_codigo(token))
    for match in _UNDERSCORE_CODE_RE.finditer(text):
        found.append(_codigo(match.group(0)))
    found.extend(_siglas(text))
    found.extend(_mascaras(text))
    for match in _RANGE_RE.finditer(text):
        found.append(_rango(match.group(1), match.group(2)))
    for match in _SLASH_RANGE_RE.finditer(text):
        # Evita duplicar cuando la barra ya era parte de un código (ABC/123).
        found.append(_rango(match.group(1), match.group(2)))
    return found


def extract_anchors(question: str, *, max_items: int = MAX_ANCHORS) -> list[Anchor]:
    """Anchors de la pregunta: providers de dominio primero, genéricos después."""
    _ensure_modules_loaded()
    text = _clean(question)
    found: list[Anchor] = []
    for provider in _providers:
        try:
            found.extend(provider.extract(text))
        except Exception as exc:  # noqa: BLE001 — un provider roto no rompe la búsqueda
            logger.warning("Anchor provider failed", error=str(exc)[:150])
    found.extend(_opaque_anchors(text))
    return _dedupe(found)[:max_items]


def anchor_needles(anchors: list[Anchor] | tuple[Anchor, ...]) -> list[str]:
    """Needles léxicas de todos los anchors, sin repetir."""
    needles: list[str] = []
    for anchor in anchors:
        for needle in anchor.needles:
            if needle and needle not in needles:
                needles.append(needle)
    return needles


def _mask_repl(match: re.Match[str]) -> str:
    return " " if _es_mascara(match.group(0)) else match.group(0)


def dense_query_rewrite(
    question: str,
    anchors: list[Anchor] | tuple[Anchor, ...] | None = None,
) -> str:
    """Pregunta sin tokens opacos, para el embedding.

    Los tokens estructurados no tienen señal semántica y contaminan el vector;
    viajan por la pata léxica. Las siglas QUEDAN: son palabra. Si al limpiar no
    queda texto, se conserva la pregunta original: una búsqueda sin query no es
    una búsqueda.
    """
    text = _clean(question)
    if not text.strip():
        return text
    cleaned = _DIGIT_RUN_RE.sub(" ", text)
    cleaned = _CODE_RE.sub(" ", cleaned)
    cleaned = _MASK_RUN_RE.sub(_mask_repl, cleaned)
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
