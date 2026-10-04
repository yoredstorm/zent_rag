# =============================================================================
# Enrichment — conceptos
# =============================================================================
# Fuentes deterministas, en orden:
#   1. definiciones del understanding (term -> definition)
#   2. campos técnicos (name, literal_pattern)
#   3. títulos de sección con forma de término
#   4. columnas tabulares (semantic_type ya inferido)
#   5. literales/códigos de dominio (pack patterns)
#
# Dedupe por nombre normalizado; merge de aliases/identifiers/confianza.
# Cada concepto tiene concept_id determinista (uuid5) y provenance real.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid5

from src.knowledge.enrichment.contracts import SemanticConcept
from src.knowledge.enrichment.normalize import collapse, normalize_key
from src.knowledge.enrichment.profiling import EnrichmentContext, classify_term
from src.knowledge.enrichment.versioning import ENRICHMENT_NAMESPACE, POLICY_VERSION

_NS = UUID(ENRICHMENT_NAMESPACE)

_GENERIC_HEADINGS = frozenset(
    {
        "introduction", "introduccion", "introducción", "overview", "general",
        "contenido", "contents", "index", "índice", "indice", "summary", "resumen",
        "appendix", "anexo", "glossary", "glosario", "revision", "revisión",
        "notas", "notes", "ejemplos", "examples", "chapter", "capítulo", "capitulo",
    }
)

_CONCEPT_ID_FALLBACK = "concept"


def concept_id_for(canonical_name: str, semantic_type: str = "") -> str:
    """Id determinista del concepto de enrichment (no es id canónico)."""
    key = normalize_key(canonical_name)
    return str(uuid5(_NS, f"{_CONCEPT_ID_FALLBACK}:{semantic_type}:{key}"))


class _ConceptAccumulator:
    def __init__(self) -> None:
        self.order: list[str] = []
        self.items: dict[str, SemanticConcept] = {}

    def add(
        self,
        name: str,
        *,
        semantic_type: str,
        source_unit_ids: tuple[str, ...],
        confidence: float,
        derivation: str = "deterministic",
        aliases: tuple[str, ...] = (),
        identifiers: tuple[str, ...] = (),
        metadata: dict | None = None,
    ) -> None:
        cleaned = collapse(name)
        if not cleaned or len(cleaned) > 120:
            return
        key = normalize_key(cleaned)
        if not key:
            return
        existing = self.items.get(key)
        if existing is None:
            concept = SemanticConcept(
                concept_id=concept_id_for(cleaned, semantic_type),
                canonical_name=cleaned,
                semantic_type=semantic_type,
                aliases=aliases,
                identifiers=identifiers,
                source_unit_ids=source_unit_ids,
                confidence=max(0.0, min(1.0, confidence)),
                derivation_method=derivation,
                policy_version=POLICY_VERSION,
                metadata=dict(metadata or {}),
            )
            self.items[key] = concept
            self.order.append(key)
            return
        merged_aliases = tuple(
            dict.fromkeys(
                (*existing.aliases, *aliases, *(a for a in (cleaned,) if a != existing.canonical_name))
            )
        )
        merged_identifiers = tuple(dict.fromkeys((*existing.identifiers, *identifiers)))
        merged_units = tuple(dict.fromkeys((*existing.source_unit_ids, *source_unit_ids)))
        # El semantic_type más específico (no "concept") gana; confianza máxima.
        semantic_type_final = existing.semantic_type
        if existing.semantic_type in ("concept", "domain_term") and semantic_type not in ("concept", "domain_term"):
            semantic_type_final = semantic_type
        self.items[key] = SemanticConcept(
            concept_id=existing.concept_id,
            canonical_name=existing.canonical_name,
            semantic_type=semantic_type_final,
            aliases=merged_aliases,
            identifiers=merged_identifiers,
            source_unit_ids=merged_units,
            confidence=max(existing.confidence, min(1.0, confidence)),
            derivation_method=existing.derivation_method,
            policy_version=existing.policy_version,
            metadata={**existing.metadata, **(metadata or {})},
        )

    def result(self) -> tuple[SemanticConcept, ...]:
        return tuple(self.items[key] for key in self.order)


def build_concepts(context: EnrichmentContext) -> tuple[SemanticConcept, ...]:
    accumulator = _ConceptAccumulator()
    understanding = context.understanding

    # 1. Definiciones del understanding.
    for definition in understanding.get("definitions") or ():
        term = collapse(definition.get("term") or "")
        block_id = str(definition.get("block_id") or "")
        units = context.valid_units([block_id])
        if not term or not units:
            continue
        classified = classify_term(term, context.packs)
        semantic_type = classified[1] if classified else "definition"
        canonical = classified[0] if classified else term
        accumulator.add(
            canonical,
            semantic_type=semantic_type,
            source_unit_ids=units,
            confidence=float(definition.get("confidence") or 0.82),
            derivation="deterministic",
            metadata={"definition": collapse(definition.get("definition") or "")[:300]},
        )

    # 2. Campos técnicos.
    for index, field in enumerate(understanding.get("technical_fields") or ()):
        name = collapse(field.get("name") or "")
        block_id = str(field.get("block_id") or "")
        units = context.valid_units([block_id])
        if not name or not units:
            continue
        identifiers: tuple[str, ...] = ()
        pattern = collapse(field.get("literal_pattern") or "")
        if pattern:
            identifiers = (pattern,)
        byte_ref = ""
        start = field.get("start_position")
        end = field.get("end_position")
        if start is not None:
            byte_ref = f"Byte {start}" if end is None or end == start else f"Byte {start}-{end}"
            identifiers = tuple(dict.fromkeys((*identifiers, byte_ref)))
        accumulator.add(
            name,
            semantic_type="field_definition",
            source_unit_ids=units,
            confidence=float(field.get("confidence") or 0.86),
            identifiers=identifiers,
            metadata={
                "field_index": index,
                "start_position": start,
                "end_position": end,
                "format": field.get("format"),
            },
        )

    # 3. Títulos de sección con forma de término.
    for section in context.document.sections:
        heading = collapse(section.heading or "")
        if not heading or len(heading) > 80:
            continue
        if normalize_key(heading) in _GENERIC_HEADINGS:
            continue
        units = context.valid_units([str(section.id), *[str(block_id) for block_id in section.block_ids]])
        if not units:
            continue
        classified = classify_term(heading, context.packs)
        semantic_type = classified[1] if classified else "section_term"
        canonical = classified[0] if classified else heading
        accumulator.add(
            canonical,
            semantic_type=semantic_type,
            source_unit_ids=units,
            confidence=classified[2] if classified else 0.6,
            derivation="structural",
            metadata={"section_id": str(section.id), "section_path": list(section.section_path)},
        )

    # 4. Columnas tabulares (semantic_type ya inferido, sin LLM).
    workbook = context.document.tabular
    if workbook is not None:
        for sheet in workbook.sheets:
            for table in sheet.tables:
                for column in table.columns:
                    name = collapse(column.original_name or column.normalized_name or "")
                    if not name:
                        continue
                    semantic_type = (
                        column.semantic_type.value
                        if hasattr(column.semantic_type, "value")
                        else str(column.semantic_type)
                    )
                    identifiers = tuple(
                        collapse(value)
                        for value in (column.sample_values or ())[:3]
                        if collapse(value)
                    )
                    accumulator.add(
                        name,
                        semantic_type=f"column:{semantic_type}",
                        source_unit_ids=context.valid_units([str(table.id), str(sheet.id)]),
                        confidence=float(column.semantic_confidence or column.type_confidence or 0.5),
                        derivation="structural",
                        aliases=tuple(column.aliases or ()),
                        identifiers=identifiers,
                        metadata={
                            "column_id": str(column.id),
                            "table_id": str(table.id),
                            "sheet": sheet.name,
                            "nullable": bool(column.nullable),
                        },
                    )

    # 5. Términos de dominio detectados por packs sobre literales exactos.
    for literal in understanding.get("exact_literals") or ():
        value = collapse(literal.get("value") or "")
        block_id = str(literal.get("block_id") or "")
        if not value:
            continue
        units = context.valid_units([block_id])
        if not units:
            continue
        classified = classify_term(value, context.packs)
        if classified is None:
            continue
        canonical, semantic_type, confidence = classified
        accumulator.add(
            canonical,
            semantic_type=semantic_type,
            source_unit_ids=units,
            confidence=confidence,
            identifiers=(value,),
            metadata={"pattern_type": literal.get("pattern_type")},
        )

    # 6. Patrones de los profile packs sobre el texto de cada bloque: el pack
    #    aporta el vocabulario de dominio; el core no conoce dominios concretos.
    for block in context.document.blocks:
        units = context.valid_units([str(block.id)])
        text = block.text or ""
        if not units or not text:
            continue
        for pack in context.packs:
            for pattern in pack.patterns:
                found = pattern.match(text)
                if found is None:
                    continue
                canonical, semantic_type, confidence = found
                accumulator.add(
                    canonical,
                    semantic_type=semantic_type,
                    source_unit_ids=units,
                    confidence=confidence,
                    identifiers=(found[0],),
                    metadata={"profile_pack": f"{pack.name}:{pack.version}"},
                )

    return accumulator.result()
