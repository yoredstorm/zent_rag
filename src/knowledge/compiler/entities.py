# =============================================================================
# Knowledge Compiler — ENTITY DISCOVERY e IDENTIDAD CANÓNICA
# =============================================================================
# Regla dura: NO se fusionan entidades "porque se parecen".
#
# Se fusiona solo con evidencia:
#   R1 · Igualdad exacta normalizada           -> misma entidad (sin merge).
#   R2 · Alias declarado en la fuente con      -> merge con razón y confianza.
#        confianza >= UMBRAL_ALIAS
#   R3 · Sigla/abreviatura que es iniciales    -> merge con confianza media.
#        de un nombre presente en el MISMO documento
#
# Todo lo demás queda como entidad separada. La duda es información, no ruido:
# el conflicto se reporta y lo resuelve un humano.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.compiler.model import (
    AliasType,
    EntityAlias,
    EntityCandidate,
    EntityMerge,
    EntityType,
    EvidenceRef,
    SemanticUnit,
    SemanticUnitKind,
    normalize_term,
)
from src.knowledge.quality.fragments import TextQualityStatus, analyze_text_quality
from src.knowledge.quality.ingestion import QualityCollector, QualityKind

UMBRAL_ALIAS = 0.85
UMBRAL_SIGLA = 0.70
UMBRAL_CONTEXTUAL = 0.72


def _qualifies_one_another(left: str, right: str) -> bool:
    """`atpco record 4` califica a `record 4` (sufijo), no al revés.

    Solo el nombre CALIFICADO (más largo) puede absorber a un nombre que ya
    aparece completo al final. "ATPCO" es prefijo de "ATPCO Record 4", pero no
    es el mismo concepto: no se fusiona. Un pedazo a mitad de palabra
    ("RECORD 2 – CATEG") no califica a nada.
    """
    if not left or not right or left == right:
        return False
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) < 4:
        return False
    if not shorter[:1].isalnum() or not shorter[-1:].isalnum():
        return False
    if not longer.endswith(shorter) or longer[-len(shorter) - 1] not in " ([:,-–—":
        return False
    # El nombre simple debe aparecer como palabra completa en el texto largo.
    before = longer[-len(shorter) - 1]
    return not before.isalnum()

_ALIAS_MARKERS = (
    "also known as",
    "known as",
    "aka",
    "a.k.a.",
    "tambien conocido como",
    "también conocido como",
    "conocido como",
    "se conoce como",
    "tambien llamado",
    "también llamado",
    "se abrevia como",
    "abreviado como",
    "abreviatura",
    "abbr.",
    "sigla",
    "o simplemente",
    "en adelante",
)

_PARENTHETICAL = re.compile(r"^(?P<name>[^()\[\]]+?)\s*[\(\[](?P<alias>[^()\[\]]{2,60})[\)\]]\s*$")
_TRAILING_ALIAS = re.compile(
    r"(?P<name>.{2,120}?)\s*(?:\(|\[)?(?P<marker>"
    + "|".join(re.escape(m) for m in _ALIAS_MARKERS)
    + r")(?:\)|\])?\s*:?\s*(?P<alias>[^.;\n]{2,80})",
    flags=re.IGNORECASE,
)
_NUMBERED = re.compile(
    r"^(?P<prefix>[A-Za-zÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑ _-]{1,40}?)\s*"
    r"(?:n[°º]?\.?\s*)?(?P<number>\d{1,4})$"
)
_CODE_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{2,40}$")

# Qué observación define mejor el tipo lógico de una entidad.
_TYPE_PRIORITY: dict[str, int] = {
    EntityType.UNKNOWN.value: 0,
    EntityType.CODE.value: 1,
    EntityType.COLUMN.value: 2,
    EntityType.FIELD.value: 3,
    EntityType.TABLE.value: 3,
    EntityType.DOCUMENT.value: 3,
    EntityType.CONCEPT.value: 4,
    EntityType.TERM.value: 4,
    EntityType.PROCESS.value: 5,
    EntityType.CATEGORY.value: 5,
    EntityType.RECORD.value: 6,
    EntityType.ORGANIZATION.value: 6,
    EntityType.SOURCE.value: 6,
}


def infer_entity_type(name: str) -> str:
    """Tipo lógico deducido del propio nombre (nunca de una suposición)."""
    text = (name or "").strip()
    lowered = text.lower()
    if not text:
        return EntityType.UNKNOWN.value
    if lowered.startswith(("record ", "registro ")):
        return EntityType.RECORD.value
    if lowered.startswith(("category ", "categoria ", "categoría ", "cat ")):
        return EntityType.CATEGORY.value
    if lowered.startswith(("byte ", "campo ", "field ")):
        return EntityType.FIELD.value
    if lowered.startswith(("columna ", "column ")):
        return EntityType.COLUMN.value
    if lowered.startswith(("tabla ", "table ", "hoja ", "sheet ")):
        return EntityType.TABLE.value
    if lowered.startswith(("proceso ", "process ", "procedimiento ")):
        return EntityType.PROCESS.value
    if _CODE_TOKEN.match(text):
        return EntityType.CODE.value
    return EntityType.CONCEPT.value


def _numbering_key(name: str) -> str | None:
    match = _NUMBERED.match((name or "").strip())
    if match is None:
        return None
    return normalize_term(match.group("prefix"))


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[\s_\-]+", name) if w]
    return "".join(word[0] for word in words if word[:1].isalnum()).lower()


def _alias_type_for(alias: str, canonical: str) -> str:
    alias_key = normalize_term(alias)
    canonical_key = normalize_term(canonical)
    if alias_key == canonical_key:
        return AliasType.SYNONYM.value
    if alias.isupper() and len(alias) <= 12 and " " not in alias:
        if _initials(canonical).startswith(alias_key):
            return AliasType.ACRONYM.value
        return AliasType.ABBREVIATION.value
    if alias_key.replace(" ", "") == canonical_key.replace(" ", ""):
        return AliasType.ALTERNATE_SPELLING.value
    if _numbering_key(alias) == _numbering_key(canonical) and _numbering_key(alias):
        return AliasType.CONTEXTUAL_NAME.value
    if _CODE_TOKEN.match(alias.strip()):
        return AliasType.CODE.value
    return AliasType.SYNONYM.value


def split_declared_alias(label: str) -> tuple[str, str | None]:
    """`Category 31 (Cat 31)` -> ("Category 31", "Cat 31")."""
    match = _PARENTHETICAL.match((label or "").strip())
    if match is None:
        return label.strip(), None
    name = match.group("name").strip()
    alias = match.group("alias").strip()
    if len(name) < 2 or len(alias) < 2 or name == alias:
        return label.strip(), None
    return name, alias


def _aliases_in(text: str, canonical: str) -> list[tuple[str, str, float, str]]:
    """(alias, tipo, confianza, razón) declarados explícitamente en el texto."""
    found: list[tuple[str, str, float, str]] = []
    if not text:
        return found
    first_line = text.strip().splitlines()[0].strip()
    parenthetical = _PARENTHETICAL.match(first_line)
    if parenthetical and len(parenthetical.group("name").strip()) >= 2:
        declared = parenthetical.group("name").strip()
        alias = parenthetical.group("alias").strip()
        if normalize_term(declared) != normalize_term(alias):
            found.append(
                (
                    alias,
                    _alias_type_for(alias, declared),
                    0.9,
                    "'X (Y)' declarado en la fuente",
                )
            )
    for match in _TRAILING_ALIAS.finditer(text):
        alias = match.group("alias").strip(" .,;:")
        if len(alias) < 2:
            continue
        if normalize_term(alias) == normalize_term(canonical):
            continue
        found.append(
            (
                alias,
                _alias_type_for(alias, match.group("name").strip()),
                0.88,
                f"marcador explícito: '{match.group('marker')}'",
            )
        )
    return found


def discover_entities(
    units: list[SemanticUnit],
    *,
    document: StructuredDocument,
    quality: QualityCollector | None = None,
) -> list[EntityCandidate]:
    """Entidades nombradas por la fuente, cada una con su evidencia.

    La identidad es por nombre normalizado: el mismo nombre en un PDF y en un
    Excel es la misma entidad. El tipo lógico se queda con la observación más
    semántica (una definición describe mejor que una cabecera de columna).

    Un nombre que es fragmento de otro texto de la misma fuente NO se convierte
    en entidad: se registra en la cola de calidad de ingesta.
    """
    from src.knowledge.compiler.extract import _reference_corpus

    document_domain = _domain_from(document)
    references = _reference_corpus(document)
    entities: dict[str, EntityCandidate] = {}
    unit_index: dict[str, SemanticUnit] = {}

    def _reject(
        name: str,
        status: str,
        *,
        evidence=None,
        detail: dict | None = None,
    ) -> None:
        if quality is None:
            return
        kind = {
            TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value: (
                QualityKind.FRAGMENT_OF_EXISTING_TEXT.value
            ),
            TextQualityStatus.TRUNCATED_WORD.value: QualityKind.TRUNCATED_WORD.value,
            TextQualityStatus.LAYOUT_ARTIFACT.value: QualityKind.LAYOUT_ARTIFACT.value,
            TextQualityStatus.SENTENCE_FRAGMENT.value: (
                QualityKind.SENTENCE_FRAGMENT.value
            ),
            TextQualityStatus.TOO_LONG_FOR_TERM.value: (
                QualityKind.TOO_LONG_FOR_TERM.value
            ),
        }.get(status, QualityKind.LOW_QUALITY_EXTRACTION.value)
        quality.add(
            kind,
            name,
            detail={"quality_status": status, "stage": "entity_discovery", **(detail or {})},
            evidence=evidence,
            source_id=document.source_id,
            document_id=document.id,
        )

    def _usable(name: str) -> bool:
        stripped = (name or "").strip()
        if stripped.isdigit() or not any(char.isalpha() for char in stripped):
            _reject(stripped, TextQualityStatus.LOW_QUALITY_EXTRACTION.value)
            return False
        verdict = analyze_text_quality(
            stripped,
            references=references,
            min_length=3,
            allow_code=True,
            max_words=16,
            max_length=160,
        )
        if not verdict.ok:
            _reject(name, verdict.status)
            return False
        return True

    def entity_for(name: str, entity_type: str) -> EntityCandidate:
        key = normalize_term(name)
        candidate = entities.get(key)
        if candidate is None:
            candidate = EntityCandidate(
                name=name.strip(),
                entity_type=entity_type,
                domain=document_domain,
            )
            entities[key] = candidate
        elif _TYPE_PRIORITY.get(entity_type, 0) > _TYPE_PRIORITY.get(
            candidate.entity_type, 0
        ):
            candidate.entity_type = entity_type
        return candidate

    def add_alias(entity: EntityCandidate, alias: EntityAlias) -> None:
        normalized = alias.normalized
        if not normalized or normalized == normalize_term(entity.name):
            return
        verdict = analyze_text_quality(
            alias.alias,
            references=references,
            min_length=3,
            allow_code=True,
            max_words=12,
            max_length=160,
        )
        if not verdict.ok:
            _reject(
                alias.alias,
                verdict.status,
                evidence=alias.evidence,
                detail={"stage": "alias", "canonical": entity.name},
            )
            return
        for known in entity.aliases:
            if known.normalized == normalized:
                if alias.confidence > known.confidence:
                    known.confidence = alias.confidence
                    known.reason = alias.reason or known.reason
                return
        entity.aliases.append(alias)

    for unit in units:
        label = (unit.label or "").strip()
        if len(label) < 2:
            continue
        if unit.kind == SemanticUnitKind.DEFINITION.value:
            primary_name, declared_alias = split_declared_alias(label)
            if len(primary_name) < 2 or not _usable(primary_name):
                continue
            entity_type = infer_entity_type(primary_name)
            entity = entity_for(primary_name, entity_type)
            entity.description = entity.description or unit.text
            entity.confidence = max(entity.confidence, unit.confidence)
            entity.evidence.append(unit.evidence)
            unit_index[entity.natural_key] = unit
            if declared_alias:
                add_alias(
                    entity,
                    EntityAlias(
                        alias=declared_alias,
                        alias_type=_alias_type_for(declared_alias, primary_name),
                        confidence=0.9,
                        reason=f"'{primary_name} ({declared_alias})' declarado en la fuente",
                        evidence=unit.evidence,
                    )
                )
            declared_in_unit = str(unit.attributes.get("declared_alias") or "").strip()
            if declared_in_unit:
                add_alias(
                    entity,
                    EntityAlias(
                        alias=declared_in_unit,
                        alias_type=_alias_type_for(declared_in_unit, primary_name),
                        confidence=0.85,
                        reason="alias declarado en el encabezado de la fuente",
                        evidence=unit.evidence,
                    )
                )
            for alias, alias_type, confidence, reason in _aliases_in(unit.text, label):
                add_alias(
                    entity,
                    EntityAlias(
                        alias=alias,
                        alias_type=alias_type,
                        confidence=confidence,
                        reason=reason,
                        evidence=unit.evidence,
                    )
                )
            continue
        if unit.kind == SemanticUnitKind.FIELD.value:
            if not _usable(label):
                continue
            entity = entity_for(label, EntityType.FIELD.value)
            entity.description = entity.description or unit.text
            entity.confidence = max(entity.confidence, unit.confidence)
            entity.evidence.append(unit.evidence)
            continue
        if unit.kind == SemanticUnitKind.TABLE.value:
            if not _usable(label):
                continue
            entity = entity_for(label, EntityType.TABLE.value)
            entity.confidence = max(entity.confidence, unit.confidence)
            entity.evidence.append(unit.evidence)
            continue
        if unit.kind == SemanticUnitKind.COLUMN.value:
            if not _usable(label):
                continue
            table_reference = str(unit.attributes.get("table") or "").strip()
            entity_type = (
                EntityType.COLUMN.value if not table_reference else EntityType.COLUMN.value
            )
            entity = entity_for(label, entity_type)
            entity.confidence = max(entity.confidence, unit.confidence)
            entity.evidence.append(unit.evidence)
            entity.domain = entity.domain or document_domain
            for alias in unit.attributes.get("aliases") or ():
                alias_text = str(alias or "").strip()
                if len(alias_text) < 2 or normalize_term(alias_text) == normalize_term(label):
                    continue
                add_alias(
                    entity,
                    EntityAlias(
                        alias=alias_text,
                        alias_type=AliasType.ALTERNATE_SPELLING.value,
                        confidence=0.75,
                        reason="alias de columna declarado por el schema tabular",
                        evidence=unit.evidence,
                    )
                )
            continue
        if unit.kind in {
            SemanticUnitKind.PROCEDURE_STEP.value,
            SemanticUnitKind.SECTION.value,
        }:
            if not _usable(label):
                continue
            entity = entity_for(label, EntityType.PROCESS.value)
            entity.confidence = max(entity.confidence, unit.confidence)
            entity.evidence.append(unit.evidence)

    return list(entities.values())


def _domain_from(document: StructuredDocument) -> str | None:
    path = getattr(document, "metadata", {}).get("folder_path")
    if isinstance(path, str) and path.strip():
        return path.strip().strip("/").split("/")[0][:120]
    profile = (document.metadata.get("understanding") or {}).get("profile")
    if isinstance(profile, dict):
        value = profile.get("domain") or profile.get("document_type")
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return None


@dataclass
class ResolutionOutcome:
    """Resultado de resolver un candidato contra lo ya conocido."""

    canonical_name: str
    natural_key: str
    entity_type: str
    merged: bool = False
    merge: EntityMerge | None = None
    aliases_added: list[EntityAlias] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "canonical_name": self.canonical_name,
            "natural_key": self.natural_key,
            "entity_type": self.entity_type,
            "merged": self.merged,
            "merge": (
                {
                    "canonical_name": self.merge.canonical_name,
                    "merged_alias": self.merge.merged_alias,
                    "alias_type": self.merge.alias_type,
                    "reason": self.merge.reason,
                    "confidence": round(self.merge.confidence, 4),
                }
                if self.merge
                else None
            ),
            "aliases_added": [a.to_dict() for a in self.aliases_added],
        }


class EntityResolver:
    """Identidad canónica estable: un nombre normalizado, una entidad.

    El resolver es determinista y sin estado compartido: se reconstruye desde
    los alias persistidos en cada corrida, de modo que dos documentos
    consecutivos consolidan la misma entidad.
    """

    def __init__(self, known: dict[str, str] | None = None) -> None:
        # normalized alias/name -> canonical name
        self._index: dict[str, str] = dict(known or {})
        # normalized canonical name -> candidates seen in THIS compilation
        self._seen: dict[str, EntityCandidate] = {}

    @staticmethod
    def index_key(name: str) -> str:
        return normalize_term(name)

    def seed(self, aliases: dict[str, str]) -> None:
        """Carga alias persistidos: {alias_normalizado: nombre_canónico}."""
        for alias, canonical in (aliases or {}).items():
            key = self.index_key(alias)
            if key:
                self._index[key] = canonical

    def resolve(self, candidate: EntityCandidate) -> ResolutionOutcome:
        """Resuelve identidad sin fusionar agresivamente."""
        normalized = self.index_key(candidate.name)
        aliases_added: list[EntityAlias] = []

        for alias in candidate.aliases:
            alias_key = self.index_key(alias.alias)
            if not alias_key or alias_key == normalized:
                continue
            known = self._index.get(alias_key)
            if known and self.index_key(known) != normalized:
                # Alias ya asignado a otra entidad: no se reasigna en silencio.
                continue
            self._index[alias_key] = candidate.name
            aliases_added.append(alias)

        canonical = self._index.get(normalized, candidate.name)
        merged = self.index_key(canonical) != normalized
        merge: EntityMerge | None = None
        if merged:
            merge = EntityMerge(
                canonical_name=canonical,
                merged_alias=candidate.name,
                alias_type=AliasType.SYNONYM.value,
                reason=f"alias previamente vinculado a '{canonical}' con evidencia",
                confidence=0.85,
            )

        self._index[normalized] = canonical
        winner = self._seen.get(self.index_key(canonical))
        if winner is None or candidate.confidence > winner.confidence:
            self._seen[self.index_key(canonical)] = candidate

        return ResolutionOutcome(
            canonical_name=canonical,
            natural_key=candidate.natural_key,
            entity_type=candidate.entity_type,
            merged=merged,
            merge=merge,
            aliases_added=aliases_added,
        )

    def consolidate(self, candidates: list[EntityCandidate]) -> tuple[
        list[EntityCandidate], list[EntityMerge]
    ]:
        """Aplica las reglas R1-R3 dentro de una misma compilación.

        Devuelve las entidades resultantes (con alias absorbidos) y los merges
        aplicados, cada uno con su razón.
        """
        by_key: dict[str, EntityCandidate] = {}
        merges: list[EntityMerge] = []
        pending: list[tuple[EntityCandidate, EntityCandidate, EntityMerge]] = []

        for candidate in candidates:
            key = self.index_key(candidate.name)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = candidate
                continue
            _absorb(existing, candidate)
            merges.append(
                EntityMerge(
                    canonical_name=existing.name,
                    merged_alias=candidate.name,
                    alias_type=AliasType.ALTERNATE_SPELLING.value,
                    reason="R1: igualdad exacta normalizada en la misma fuente",
                    confidence=1.0,
                )
            )

        # R2 · alias declarado
        for candidate in list(by_key.values()):
            for alias in candidate.aliases:
                if alias.confidence < UMBRAL_ALIAS or not alias.reason:
                    continue
                target_key = self.index_key(alias.alias)
                target = by_key.get(target_key)
                if target is None or target is candidate:
                    continue
                pending.append(
                    (
                        target,
                        candidate,
                        EntityMerge(
                            canonical_name=target.name,
                            merged_alias=candidate.name,
                            alias_type=alias.alias_type,
                            reason=(
                                f"R2: alias '{alias.alias}' declarado en la fuente "
                                f"({alias.reason})"
                            ),
                            confidence=alias.confidence,
                        ),
                    )
                )

        # R3 · sigla/iniciales del mismo nombre en el MISMO documento
        for candidate in list(by_key.values()):
            if candidate.entity_type != EntityType.CONCEPT.value:
                continue
            for other in list(by_key.values()):
                if other is candidate or other.entity_type != EntityType.CONCEPT.value:
                    continue
                short = normalize_term(other.name)
                if (
                    " " not in short
                    and 2 <= len(short) <= 8
                    and other.name.isupper()
                    and _initials(candidate.name) == short
                ):
                    pending.append(
                        (
                            candidate,
                            other,
                            EntityMerge(
                                canonical_name=candidate.name,
                                merged_alias=other.name,
                                alias_type=AliasType.ACRONYM.value,
                                reason=(
                                    f"R3: '{other.name}' son las iniciales de "
                                    f"'{candidate.name}' en el mismo documento"
                                ),
                                confidence=UMBRAL_SIGLA,
                            ),
                        )
                    )

        # R4 · nombre calificado dentro del MISMO documento:
        # "ATPCO Record 4" (observado en este documento) y "Record 4" (definido
        # aquí) apuntan al mismo concepto. El nombre simple es el canónico y el
        # calificado queda como alias contextual, con la razón por escrito.
        # Nunca aplica a columnas/tablas/códigos: ahí un sufijo suele ser un
        # corte de layout, no un nombre calificado.
        _R4_EXCLUDED_TYPES = {
            EntityType.COLUMN.value,
            EntityType.TABLE.value,
            EntityType.FIELD.value,
            EntityType.CODE.value,
        }
        for candidate in list(by_key.values()):
            if candidate.entity_type in _R4_EXCLUDED_TYPES:
                continue
            folded = self.index_key(candidate.name)
            for other in list(by_key.values()):
                if other is candidate or other.entity_type in _R4_EXCLUDED_TYPES:
                    continue
                other_folded = self.index_key(other.name)
                if len(other.name) > 120 or "|" in other.name or "\n" in other.name:
                    continue
                if not _qualifies_one_another(other_folded, folded):
                    continue
                short, long = (
                    (candidate, other) if len(folded) <= len(other_folded) else (other, candidate)
                )
                if self.index_key(short.name) not in by_key:
                    continue
                if self.index_key(long.name) not in by_key:
                    continue
                pending.append(
                    (
                        short,
                        long,
                        EntityMerge(
                            canonical_name=short.name,
                            merged_alias=long.name,
                            alias_type=AliasType.CONTEXTUAL_NAME.value,
                            reason=(
                                f"R4: '{long.name}' es el nombre calificado de "
                                f"'{short.name}' en el mismo documento"
                            ),
                            confidence=UMBRAL_CONTEXTUAL,
                        ),
                    )
                )

        for target, absorbed, merge in pending:
            target_key = self.index_key(target.name)
            absorbed_key = self.index_key(absorbed.name)
            if absorbed_key not in by_key or target_key not in by_key:
                # Ya absorbida por una regla anterior: no se re-fusiona.
                continue
            _absorb(target, absorbed)
            target.aliases.append(
                EntityAlias(
                    alias=absorbed.name,
                    alias_type=merge.alias_type,
                    confidence=merge.confidence,
                    reason=merge.reason,
                    evidence=(absorbed.evidence[0] if absorbed.evidence else None),
                )
            )
            merges.append(merge)
            del by_key[absorbed_key]

        return list(by_key.values()), merges


def _absorb(target: EntityCandidate, other: EntityCandidate) -> None:
    """Enriquecer sin perder nada: descripción, evidencia y alias se suman."""
    if not target.description and other.description:
        target.description = other.description
    if not target.domain and other.domain:
        target.domain = other.domain
    target.confidence = max(target.confidence, other.confidence)
    target.evidence.extend(other.evidence)
    seen = {a.normalized for a in target.aliases}
    for alias in other.aliases:
        if alias.normalized not in seen:
            target.aliases.append(alias)
            seen.add(alias.normalized)


def entity_evidence_pairs(
    entities: list[EntityCandidate],
) -> dict[str, list[EvidenceRef]]:
    return {entity.natural_key: list(entity.evidence) for entity in entities}
