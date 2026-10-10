# =============================================================================
# Semantic Window — comprensión local determinista (§9)
# =============================================================================
# Una ventana NO produce solo un resumen: produce un objeto estructurado con
# conceptos, entidades, definiciones, símbolos, aliases, claims, reglas,
# condiciones, excepciones, procedimientos, statements temporales, referencias
# (resueltas y sin resolver), tablas, relaciones, continuaciones, topics y
# conflictos, todos con provenance a bloques de la ventana.
#
# Determinista primero. El LLM (opcional) solo AGREGA items con quote
# verificado; jamás reemplaza lo determinista ni inventa significado.
# =============================================================================
from __future__ import annotations

import re

from src.core.domain.knowledge_v2 import StructuredBlock, StructuredBlockKind
from src.knowledge.compiler.model import normalize_term

from .contracts import WindowItem

_SYMBOL_CHARS = frozenset("&%#?*[]")
_CONDITION = re.compile(r"(?i)\b(if|when|si|cuando)\b")
_EXCEPTION = re.compile(
    r"(?i)\b(except|unless|salvo|excepto|a menos que|with the exception)\b"
)
_RULE_MODAL = re.compile(
    r"(?i)\b(must|shall|required|mandatory|debe|deber[aá]|obligatorio)\b"
)
_TEMPORAL = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"
    r"|\b(?:19|20)\d{2}\b"
)
_SEE_SECTION = re.compile(
    r"\b(?:see|refer to|v[eé]ase)\s+(?:the\s+)?"
    r"([A-Za-z][A-Za-z0-9]+(?:[ \-][A-Za-z0-9]+){0,6})\s+section\b",
    re.IGNORECASE,
)
_FIELD_CELL = re.compile(r"^[A-Za-z][A-Za-z0-9 .#/_-]{1,40}$")
_STEP = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|paso\s+\d+|step\s+\d+)\s+\S", re.IGNORECASE)
_TERMINAL = (".", "!", "?", ";", ":")

#: Orden estable de emisión (más estructural primero).
_KIND_ORDER = {
    "definition": 0,
    "symbol": 1,
    "entity": 2,
    "concept": 3,
    "alias": 4,
    "rule": 5,
    "condition": 6,
    "exception": 7,
    "procedure": 8,
    "claim": 9,
    "temporal": 10,
    "reference": 11,
    "unresolved_reference": 12,
    "table": 13,
    "relationship": 14,
    "continuation": 15,
    "topic": 16,
    "note": 17,
    "conflict": 18,
}


def extract_window_items(
    *,
    document,
    window_blocks: list[StructuredBlock],
    window_index: int,
    enrichment=None,
    compiled=None,
    max_items: int = 400,
    section_continues: bool = False,
) -> list[WindowItem]:
    """Items semánticos de una ventana. Puro y determinista."""
    block_ids = [str(block.id) for block in window_blocks]
    id_set = set(block_ids)
    understanding = document.metadata.get("understanding") or {}
    found: dict[tuple[str, str], WindowItem] = {}

    def add(item: WindowItem) -> None:
        key = (item.kind, item.key)
        existing = found.get(key)
        if existing is None or item.confidence > existing.confidence:
            found[key] = item

    # 1. Understanding: definiciones, campos, literales, referencias, relations.
    for definition in understanding.get("definitions") or []:
        block_id = str(definition.get("block_id") or "")
        if block_id not in id_set:
            continue
        term = str(definition.get("term") or "").strip()
        body = str(definition.get("definition") or "").strip()
        if not term or not body:
            continue
        add(
            WindowItem(
                kind="definition",
                key=normalize_term(term),
                label=term,
                text=body,
                confidence=float(definition.get("confidence") or 0.82),
                method="deterministic",
                block_ids=(block_id,),
                attributes={"derived_by": definition.get("derived_by") or "rules"},
            )
        )
    for field in understanding.get("technical_fields") or []:
        block_id = str(field.get("block_id") or "")
        if block_id not in id_set:
            continue
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        add(
            WindowItem(
                kind="entity",
                key=f"field:{normalize_term(name)}",
                label=name,
                text=str(field.get("description") or name),
                confidence=float(field.get("confidence") or 0.84),
                block_ids=(block_id,),
                attributes={
                    "entity_type": "field",
                    "start_position": field.get("start_position"),
                    "end_position": field.get("end_position"),
                    "length": field.get("length"),
                    "literal_pattern": field.get("literal_pattern"),
                },
            )
        )
    for literal in understanding.get("exact_literals") or []:
        block_id = str(literal.get("block_id") or "")
        if block_id not in id_set:
            continue
        value = str(literal.get("value") or "").strip()
        if not value:
            continue
        symbol_like = bool(_SYMBOL_CHARS.intersection(value)) or str(
            literal.get("pattern_type") or ""
        ) == "mask"
        add(
            WindowItem(
                kind="symbol" if symbol_like else "entity",
                key=value if symbol_like else f"literal:{value}",
                label=value,
                text=str(literal.get("parent_definition") or ""),
                confidence=float(literal.get("confidence") or 0.9),
                block_ids=(block_id,),
                attributes={
                    "identifier_type": literal.get("pattern_type"),
                    "field_name": literal.get("field_name"),
                    "relation_target": literal.get("relation_target"),
                    "parent_definition": literal.get("parent_definition"),
                    "section_id": literal.get("section_id"),
                },
            )
        )
    for reference in understanding.get("cross_references") or []:
        block_id = str(reference.get("from_block") or "")
        if block_id not in id_set:
            continue
        target = str(reference.get("target_candidate") or "").strip()
        if not target:
            continue
        resolved = reference.get("resolved_target")
        add(
            WindowItem(
                kind="reference" if resolved else "unresolved_reference",
                key=f"{reference.get('target_kind') or 'ref'}:{normalize_term(target)}",
                label=target,
                text=str(reference.get("reference_text") or ""),
                confidence=float(reference.get("confidence") or 0.6),
                block_ids=(block_id,),
                attributes={
                    "target_kind": reference.get("target_kind"),
                    "resolved_target": resolved,
                    "resolution_window": window_index if resolved else None,
                },
            )
        )
    for relation in understanding.get("relations") or []:
        from_block = str(relation.get("from_block_id") or "")
        to_block = str(relation.get("to_block_id") or "")
        if from_block not in id_set and to_block not in id_set:
            continue
        relation_type = str(relation.get("relation_type") or "RELATED_TO")
        target = str(
            relation.get("target_literal")
            or relation.get("field_name")
            or to_block
            or ""
        )
        add(
            WindowItem(
                kind="relationship",
                key=f"{relation_type}:{normalize_term(target)}",
                label=relation_type,
                text=target,
                confidence=float(relation.get("confidence") or 0.8),
                block_ids=tuple(value for value in (from_block, to_block) if value),
                attributes={
                    "relation_type": relation_type,
                    "field_name": relation.get("field_name"),
                    "target_literal": relation.get("target_literal"),
                    "provenance": relation.get("provenance"),
                },
            )
        )

    # 2. Enrichment derivado (concepts/aliases/identifiers/temporal/refs/rules).
    if enrichment is not None:
        concept_names = {
            concept.concept_id: concept.canonical_name
            for concept in enrichment.concepts
        }
        for concept in enrichment.concepts:
            if not _touches(concept.source_unit_ids, id_set):
                continue
            add(
                WindowItem(
                    kind="concept",
                    key=concept.concept_id or normalize_term(concept.canonical_name),
                    label=concept.canonical_name,
                    text="",
                    confidence=float(concept.confidence or 0.7),
                    block_ids=_blocks_of(concept.source_unit_ids, id_set),
                    attributes={"semantic_type": concept.semantic_type},
                )
            )
        for alias in enrichment.retrieval_aliases:
            if not _touches(alias.source_unit_ids, id_set):
                continue
            add(
                WindowItem(
                    kind="alias",
                    key=normalize_term(alias.value),
                    label=alias.value,
                    text=concept_names.get(alias.target_concept_id or "", ""),
                    confidence=float(alias.confidence or 0.6),
                    block_ids=_blocks_of(alias.source_unit_ids, id_set),
                    attributes={
                        "alias_kind": alias.kind,
                        "canonical": concept_names.get(alias.target_concept_id or ""),
                    },
                )
            )
        for identifier in enrichment.identifiers:
            if not _touches(identifier.source_unit_ids, id_set):
                continue
            value = identifier.value
            symbol_like = bool(_SYMBOL_CHARS.intersection(value))
            add(
                WindowItem(
                    kind="symbol" if symbol_like else "entity",
                    key=value if symbol_like else f"literal:{value}",
                    label=value,
                    text="",
                    confidence=float(identifier.confidence or 0.7),
                    block_ids=_blocks_of(identifier.source_unit_ids, id_set),
                    attributes={"identifier_type": identifier.identifier_type},
                )
            )
        for qualifier in enrichment.temporal_qualifiers:
            if not _touches(qualifier.source_unit_ids, id_set):
                continue
            add(
                WindowItem(
                    kind="temporal",
                    key=normalize_term(qualifier.normalized_value or qualifier.value),
                    label=qualifier.normalized_value or qualifier.value,
                    text=qualifier.value,
                    confidence=float(qualifier.confidence or 0.7),
                    block_ids=_blocks_of(qualifier.source_unit_ids, id_set),
                    attributes={"qualifier_type": qualifier.qualifier_type},
                )
            )
        for reference in enrichment.references:
            if not _touches(reference.source_unit_ids, id_set):
                continue
            resolved = reference.resolved_target
            add(
                WindowItem(
                    kind="reference" if resolved else "unresolved_reference",
                    key=(
                        f"{reference.target_kind}:"
                        f"{normalize_term(reference.target_candidate or reference.reference_text)}"
                    ),
                    label=reference.target_candidate or reference.reference_text,
                    text=reference.reference_text,
                    confidence=float(reference.confidence or 0.6),
                    block_ids=_blocks_of(reference.source_unit_ids, id_set),
                    attributes={
                        "target_kind": reference.target_kind,
                        "resolved_target": resolved,
                        "resolution_window": window_index if resolved else None,
                    },
                )
            )
        for rule in enrichment.possible_rules:
            if not _touches(rule.source_unit_ids, id_set):
                continue
            add(
                WindowItem(
                    kind="rule",
                    key=rule.rule_key or normalize_term(rule.statement),
                    label=rule.statement[:160],
                    text=rule.statement,
                    confidence=float(rule.confidence or 0.65),
                    block_ids=_blocks_of(rule.source_unit_ids, id_set),
                    attributes={
                        "condition": rule.condition,
                        "consequence": rule.consequence,
                    },
                )
            )

    # 3. Vista compilada (candidatos con evidencia en la ventana).
    if compiled is not None:
        for entity in getattr(compiled, "entities", ()) or ():
            block = _evidence_block(entity.evidence, id_set)
            if block is None:
                continue
            add(
                WindowItem(
                    kind="entity",
                    key=f"entity:{normalize_term(entity.name)}",
                    label=entity.name,
                    text=str(entity.description or ""),
                    confidence=float(entity.confidence or 0.7),
                    block_ids=(block,),
                    attributes={"entity_type": entity.entity_type, "source": "compiler"},
                )
            )
        for fact in getattr(compiled, "facts", ()) or ():
            block = _evidence_block(fact.evidence, id_set)
            if block is None:
                continue
            object_value = str(fact.object_value or "")
            statement = f"{fact.subject} {fact.predicate} {object_value}".strip()
            add(
                WindowItem(
                    kind="claim",
                    key=f"claim:{normalize_term(statement)}",
                    label=fact.subject,
                    text=statement,
                    confidence=float(fact.confidence or 0.7),
                    block_ids=(block,),
                    attributes={
                        "subject": fact.subject,
                        "predicate": fact.predicate,
                        "object_value": object_value,
                        "fact_kind": fact.fact_kind,
                    },
                )
            )
        for rule in getattr(compiled, "rules", ()) or ():
            block = _evidence_block(rule.evidence, id_set)
            if block is None:
                continue
            add(
                WindowItem(
                    kind="rule",
                    key=rule.rule_key or normalize_term(rule.statement),
                    label=rule.statement[:160],
                    text=rule.statement,
                    confidence=float(rule.confidence or 0.7),
                    block_ids=(block,),
                    attributes={
                        "modality": rule.modality,
                        "rule_type": rule.rule_type,
                        "source": "compiler",
                    },
                )
            )
        for relationship in getattr(compiled, "relationships", ()) or ():
            block = _evidence_block(relationship.evidence, id_set)
            if block is None:
                continue
            add(
                WindowItem(
                    kind="relationship",
                    key=f"{relationship.predicate}:{normalize_term(relationship.object_name)}",
                    label=relationship.predicate,
                    text=f"{relationship.subject} {relationship.predicate} {relationship.object_name}",
                    confidence=float(relationship.confidence or 0.7),
                    block_ids=(block,),
                    attributes={
                        "subject": relationship.subject,
                        "object": relationship.object_name,
                        "source": "compiler",
                    },
                )
            )
        for conflict in getattr(compiled, "conflicts", ()) or ():
            block = _evidence_block(conflict.evidence, id_set)
            if block is None:
                continue
            add(
                WindowItem(
                    kind="conflict",
                    key=f"conflict:{normalize_term(conflict.subject)}:{normalize_term(conflict.predicate)}",
                    label=conflict.subject,
                    text=f"{conflict.value_a} != {conflict.value_b}",
                    confidence=float(conflict.confidence or 0.5),
                    block_ids=(block,),
                    attributes={
                        "classification": conflict.classification or conflict.conflict_type,
                        "materiality": conflict.materiality,
                    },
                )
            )

    # 4. Heurísticas locales de la ventana (conditions/exceptions/rules/etc.).
    for block in window_blocks:
        block_id = str(block.id)
        text = (block.text or "").strip()
        if not text:
            continue
        role = str(block.metadata.get("role") or "")
        if role in {"note", "footnote", "warning", "example"}:
            add(
                WindowItem(
                    kind="note",
                    key=f"note:{block_id}",
                    label=role,
                    text=text[:400],
                    confidence=0.75,
                    block_ids=(block_id,),
                    attributes={"role": role},
                )
            )
        if block.kind is StructuredBlockKind.HEADING:
            add(
                WindowItem(
                    kind="topic",
                    key=f"topic:{normalize_term(text)}",
                    label=text[:160],
                    text="",
                    confidence=0.9,
                    block_ids=(block_id,),
                    attributes={"heading": True},
                )
            )
        if block.kind is StructuredBlockKind.TABLE:
            add(
                WindowItem(
                    kind="table",
                    key=f"table:{block_id}",
                    label=str(block.metadata.get("table_id") or text[:80]),
                    text=text[:400],
                    confidence=0.85,
                    block_ids=(block_id,),
                    attributes={"table_id": block.metadata.get("table_id")},
                )
            )
            for field_name, quote in _table_field_names(text):
                add(
                    WindowItem(
                        kind="entity",
                        key=f"field:{normalize_term(field_name)}",
                        label=field_name,
                        text=quote,
                        confidence=0.8,
                        block_ids=(block_id,),
                        attributes={
                            "entity_type": "field",
                            "source": "table_header",
                            "quote": quote[:240],
                        },
                    )
                )
        for match in _SEE_SECTION.finditer(text):
            target = " ".join(match.group(1).split())
            if len(target) < 3:
                continue
            add(
                WindowItem(
                    kind="unresolved_reference",
                    key=f"section:{normalize_term(target)}",
                    label=target,
                    text=match.group(0)[:240],
                    confidence=0.7,
                    block_ids=(block_id,),
                    attributes={"target_kind": "section", "source": "see_section"},
                )
            )
        for line in _lines(text):
            if len(line) < 20:
                continue
            if _CONDITION.search(line):
                add(_heuristic("condition", line, block_id, window_index))
            if _EXCEPTION.search(line):
                add(_heuristic("exception", line, block_id, window_index))
            if _RULE_MODAL.search(line):
                add(_heuristic("rule", line, block_id, window_index))
        for match in _TEMPORAL.finditer(text):
            value = match.group(0)
            add(
                WindowItem(
                    kind="temporal",
                    key=f"temporal:{normalize_term(value)}",
                    label=value,
                    text="",
                    confidence=0.6,
                    block_ids=(block_id,),
                    attributes={"source": "regex"},
                )
            )
        if _STEP.search(text):
            for line in _lines(text):
                if _STEP.match(line):
                    add(
                        WindowItem(
                            kind="procedure",
                            key=f"step:{block_id}:{normalize_term(line[:80])}",
                            label=line[:160],
                            text=line,
                            confidence=0.7,
                            block_ids=(block_id,),
                            attributes={"source": "list_step"},
                        )
                    )

    # 5. Continuation candidate: la ventana termina abierta o la sección sigue.
    continuation = _continuation_candidate(
        window_blocks, window_index, section_continues=section_continues
    )
    if continuation is not None:
        add(continuation)

    items = sorted(
        found.values(),
        key=lambda item: (
            _KIND_ORDER.get(item.kind, 99),
            -item.confidence,
            item.key,
        ),
    )
    if max_items > 0 and len(items) > max_items:
        items = items[:max_items]
    return items


def _table_field_names(text: str) -> list[tuple[str, str]]:
    """Nombres de columna de la tabla. El quote es la fila, no un alias inventado."""
    line = ""
    for candidate in (text or "").splitlines():
        if "|" in candidate:
            line = candidate
            break
    if not line and "|" in (text or ""):
        line = (text or "")[:500]
    quote = " ".join(line.split())[:240]
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for cell in line.split("|"):
        name = " ".join(cell.split()).strip(" .")
        if not name or not _FIELD_CELL.match(name):
            continue
        if sum(char.isalpha() for char in name) < 2:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append((name, quote or name))
        if len(found) >= 16:
            break
    return found


def _heuristic(kind: str, line: str, block_id: str, window_index: int) -> WindowItem:
    return WindowItem(
        kind=kind,
        key=f"{kind}:{normalize_term(line[:120])}",
        label=line[:160],
        text=line,
        confidence=0.65,
        block_ids=(block_id,),
        attributes={"source": "heuristic", "window_index": window_index},
    )


def _continuation_candidate(
    window_blocks: list[StructuredBlock],
    window_index: int,
    *,
    section_continues: bool = False,
) -> WindowItem | None:
    for block in reversed(window_blocks):
        text = (block.text or "").strip()
        if not text:
            continue
        if block.kind is StructuredBlockKind.HEADING:
            return None
        if section_continues:
            return WindowItem(
                kind="continuation",
                key=f"continuation:{window_index}:section:{block.metadata.get('parent_section_id')}",
                label=text[-160:],
                text=text[-160:],
                confidence=0.7,
                block_ids=(str(block.id),),
                attributes={
                    "target_hint": "same_section",
                    "section_id": block.metadata.get("parent_section_id"),
                    "source": "section_continues",
                },
            )
        last_line = _lines(text)[-1] if _lines(text) else text
        if len(last_line) < 12:
            return None
        if last_line.endswith(_TERMINAL):
            return None
        return WindowItem(
            kind="continuation",
            key=f"continuation:{window_index}:{normalize_term(last_line[:80])}",
            label=last_line[:160],
            text=last_line,
            confidence=0.6,
            block_ids=(str(block.id),),
            attributes={
                "target_hint": "next_window",
                "section_id": block.metadata.get("parent_section_id"),
                "source": "open_ending",
            },
        )
    return None


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _touches(source_unit_ids, id_set: set[str]) -> bool:
    if not source_unit_ids:
        return False
    return any(str(value) in id_set for value in source_unit_ids)


def _blocks_of(source_unit_ids, id_set: set[str]) -> tuple[str, ...]:
    return tuple(
        str(value) for value in (source_unit_ids or ()) if str(value) in id_set
    )


def _evidence_block(evidence, id_set: set[str]) -> str | None:
    for item in evidence or ():
        locator = getattr(item, "locator", None)
        block_id = getattr(locator, "block_id", None) if locator else None
        if block_id is not None and str(block_id) in id_set:
            return str(block_id)
    return None


__all__ = ["extract_window_items"]
