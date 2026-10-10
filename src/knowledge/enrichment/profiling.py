# =============================================================================
# Enrichment — profiling de dominio extensible (packs)
# =============================================================================
# El core NO conoce dominios concretos. Los packs aportan:
#   - patterns: regex -> semantic_type (+ canonical propuesto)
#   - term_map: alias -> término canónico preferido
#   - term_types: término -> semantic_type
#
# Se cargan por settings (comma-separated module paths) o por registro
# explícito. Un pack nunca crea items sin provenance: solo etiqueta.
# =============================================================================
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from src.core.domain.knowledge_v2 import StructuredDocument
from src.infrastructure.observability.logging_config import get_logger

from .normalize import collapse, normalize_key

logger = get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ProfilePattern:
    """Patrón determinista: si matchea, asigna semantic_type."""

    regex: re.Pattern
    semantic_type: str
    confidence: float = 0.7
    canonical_template: str = "{match}"
    name: str = ""

    def match(self, value: str) -> tuple[str, str, float] | None:
        found = self.regex.search(collapse(value))
        if not found:
            return None
        groups = found.groups()
        try:
            canonical = self.canonical_template.format(
                found.group(0), *groups, match=found.group(0)
            )
        except (IndexError, KeyError):
            canonical = found.group(0)
        return collapse(canonical), self.semantic_type, self.confidence


@dataclass(frozen=True, kw_only=True)
class EnrichmentProfilePack:
    """Vocabulario de dominio enchufable (sin estado, sin I/O)."""

    name: str
    version: str = "1"
    description: str = ""
    patterns: tuple[ProfilePattern, ...] = ()
    term_map: Mapping[str, str] = field(default_factory=dict)
    term_types: Mapping[str, str] = field(default_factory=dict)
    #: Alias conocidos 1:N (término del usuario -> términos del documento).
    #: Es metadata de dominio del pack, no una regla de la lógica genérica.
    alias_map: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def canonicalize(self, value: str) -> str | None:
        return self.term_map.get(normalize_key(value))

    def semantic_type(self, value: str) -> str | None:
        return self.term_types.get(normalize_key(value))

    def classify(self, value: str) -> tuple[str, str, float] | None:
        for pattern in self.patterns:
            found = pattern.match(value)
            if found is not None:
                return found
        return None


_REGISTRY: dict[str, EnrichmentProfilePack] = {}
_LOADED_MODULES: set[str] = set()


def register_profile_pack(pack: EnrichmentProfilePack, *, replace: bool = False) -> None:
    key = f"{pack.name}:{pack.version}"
    if key in _REGISTRY and not replace:
        return
    _REGISTRY[key] = pack


def generic_profile_pack() -> EnrichmentProfilePack:
    """Pack genérico: vocabulario documental/técnico, ningún dominio concreto."""
    return EnrichmentProfilePack(
        name="generic",
        version="2",
        description="Patrones documentales genéricos (categorías, bytes, registros, códigos).",
        patterns=(
            ProfilePattern(
                name="category_number_full",
                regex=re.compile(
                    r"\b(?:category|categor[ií]a)\s*#?\s*(\d{1,3})\b", re.IGNORECASE
                ),
                semantic_type="domain_category",
                confidence=0.85,
                canonical_template="Category {1}",
            ),
            ProfilePattern(
                # Abreviatura "Cat N": se conserva la superficie, NO se expande
                # a "Category" sin que la fuente use la forma completa.
                name="category_number_short",
                regex=re.compile(r"\bcat\s*#?\s*(\d{1,3})\b", re.IGNORECASE),
                semantic_type="domain_category_candidate",
                confidence=0.55,
                canonical_template="Cat {1}",
            ),
            ProfilePattern(
                name="byte_position",
                regex=re.compile(r"\bbytes?\s*(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?\b", re.IGNORECASE),
                semantic_type="field_position",
                confidence=0.86,
                canonical_template="Byte {1}",
            ),
            ProfilePattern(
                name="record_number",
                regex=re.compile(r"\b(?:record|registro|table|tabla)\s*#?\s*(\d{1,4})\b", re.IGNORECASE),
                semantic_type="data_record",
                confidence=0.7,
                canonical_template="Record {1}",
            ),
            ProfilePattern(
                name="iso_date",
                regex=re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
                semantic_type="date",
                confidence=0.95,
            ),
            ProfilePattern(
                name="exchange_code",
                regex=re.compile(r"\b[A-Z]{2,6}\d{1,4}[A-Z]?\b"),
                semantic_type="domain_code",
                confidence=0.55,
            ),
        ),
        term_map={
            "cat": "category",
            "cats": "category",
            "nro": "record",
            "num": "number",
        },
        term_types={
            "status": "attribute",
            "estado": "attribute",
            "carrier": "organization_code",
            "airline": "organization_code",
            "date": "temporal",
            "fecha": "temporal",
            "amount": "money",
            "importe": "money",
            "fare": "money",
            "tarifa": "money",
            "byte": "field_position",
            "record": "data_record",
            "registro": "data_record",
        },
    )


def load_profile_packs(modules: str | Iterable[str] | None = None) -> list[EnrichmentProfilePack]:
    """Carga packs externos por ruta de módulo (fail-soft, una vez por módulo)."""
    if modules is None:
        modules = _setting_pack_modules()
    if isinstance(modules, str):
        paths = [item.strip() for item in modules.split(",") if item.strip()]
    else:
        paths = [str(item).strip() for item in modules if str(item).strip()]

    import importlib

    for path in paths:
        if path in _LOADED_MODULES:
            continue
        try:
            module = importlib.import_module(path)
            packs = getattr(module, "PROFILE_PACKS", None) or getattr(
                module, "profile_packs", None
            )
            if callable(packs):
                packs = packs()
            for pack in packs or ():
                register_profile_pack(pack)
            _LOADED_MODULES.add(path)
        except Exception as exc:  # noqa: BLE001 — un pack roto no frena el pipeline
            logger.warning("Enrichment profile pack load failed", module=path, error=str(exc)[:200])
    return active_profile_packs()


def active_profile_packs() -> list[EnrichmentProfilePack]:
    if not _REGISTRY:
        register_profile_pack(generic_profile_pack())
    # Genérico primero; el resto por orden de registro.
    packs = list(_REGISTRY.values())
    packs.sort(key=lambda pack: (pack.name != "generic", pack.name, pack.version))
    return packs


def expand_aliases(
    value: str,
    packs: Iterable[EnrichmentProfilePack] | None = None,
) -> tuple[str, ...]:
    """Aliases conocidos del término según los packs (1:N).

    Ej.: un pack ATPCO mapea «cambio de fechas» a Eff Date/Disc Date. La
    lógica genérica no conoce dominios: sólo consulta el vocabulario cargado.
    """
    key = normalize_key(value)
    if not key:
        return ()
    selected = packs if packs is not None else load_profile_packs()
    found: list[str] = []
    seen: set[str] = set()
    for pack in selected:
        for alias in pack.alias_map.get(key, ()):
            text = " ".join(str(alias or "").split())
            folded = text.casefold()
            if text and folded not in seen:
                seen.add(folded)
                found.append(text)
    return tuple(found)


def classify_term(value: str, packs: Iterable[EnrichmentProfilePack]) -> tuple[str, str, float] | None:
    """(canonical, semantic_type, confidence) usando packs; None si no hay match."""
    for pack in packs:
        found = pack.classify(value)
        if found is not None:
            canonical, semantic_type, confidence = found
            mapped = pack.canonicalize(canonical) or pack.canonicalize(value)
            return (mapped or canonical, semantic_type, confidence)
        mapped = pack.canonicalize(value)
        if mapped:
            return mapped, pack.semantic_type(mapped) or "domain_term", 0.6
    return None


def _setting_pack_modules() -> str:
    try:
        from src.core.config import get_settings

        return str(getattr(get_settings(), "KNOWLEDGE_ENRICHMENT_PROFILE_PACKS", "") or "")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Contexto del documento (unidades reales para validar provenance)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EnrichmentContext:
    """Vista determinista del documento entendido para los enrichers."""

    document: StructuredDocument
    unit_ids: frozenset[str]
    block_text: dict[str, str]
    section_titles: dict[str, str]
    packs: tuple[EnrichmentProfilePack, ...] = ()

    def block_of(self, unit_id: str) -> str:
        return self.block_text.get(str(unit_id), "")

    def has_unit(self, unit_id: str) -> bool:
        return str(unit_id) in self.unit_ids

    def valid_units(self, values: Iterable[str]) -> tuple[str, ...]:
        return tuple(str(value) for value in values if value and str(value) in self.unit_ids)

    @property
    def understanding(self) -> dict:
        return self.document.metadata.get("understanding") or {}


def build_context(
    document: StructuredDocument,
    *,
    packs: Iterable[EnrichmentProfilePack] | None = None,
) -> EnrichmentContext:
    unit_ids: set[str] = set()
    block_text: dict[str, str] = {}
    for block in document.blocks:
        key = str(block.id)
        unit_ids.add(key)
        block_text[key] = block.text or ""
    for section in document.sections:
        unit_ids.add(str(section.id))
    section_titles = {str(section.id): section.heading for section in document.sections}
    understanding = document.metadata.get("understanding") or {}
    for unit in understanding.get("retrieval_units") or ():
        for block_id in unit.get("block_ids") or ():
            unit_ids.add(str(block_id))
        if unit.get("unit_id"):
            unit_ids.add(str(unit["unit_id"]))
        if unit.get("primary_block_id"):
            unit_ids.add(str(unit["primary_block_id"]))
    # Unidades tabulares reales: workbook/sheet/table/column son provenance
    # válida (sin esto, un concepto de columna quedaba huérfano).
    workbook = document.tabular
    if workbook is not None:
        unit_ids.add(str(workbook.id))
        for sheet in workbook.sheets:
            unit_ids.add(str(sheet.id))
            for table in sheet.tables:
                unit_ids.add(str(table.id))
                for column in table.columns:
                    unit_ids.add(str(column.id))
    return EnrichmentContext(
        document=document,
        unit_ids=frozenset(unit_ids),
        block_text=block_text,
        section_titles=section_titles,
        packs=tuple(packs if packs is not None else active_profile_packs()),
    )
