# =============================================================================
# SemanticState — estado compacto y verificable por ventana (§10)
# =============================================================================
# El estado NO guarda chain-of-thought: guarda conocimiento verificable con
# provenance (conceptos activos, entidades conocidas, glosario, símbolos,
# reglas activas, referencias sin resolver, continuaciones abiertas, topics,
# contexto temporal, aliases, relaciones pendientes, conflictos).
#
# Reglas:
#   - merge determinista con caps (evita crecimiento infinito);
#   - una referencia previa se RESUELVE cuando una ventana posterior define su
#     target (información posterior resuelve unknowns anteriores, §12);
#   - una continuación abierta se cierra cuando la ventana siguiente continúa
#     la misma sección;
#   - nada se auto-promueve a canónico.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.knowledge.compiler.model import normalize_term

from .contracts import SemanticState, SemanticStateSlice, SemanticWindowResult


@dataclass(frozen=True)
class StateCaps:
    """Topes por categoría. Al excederse se descarta lo más viejo."""

    concepts: int = 128
    entities: int = 128
    glossary: int = 64
    symbols: int = 64
    rules: int = 64
    unresolved: int = 64
    resolved: int = 128
    continuations: int = 64
    topics: int = 16
    temporal: int = 16
    aliases: int = 128
    relationships: int = 64
    conflicts: int = 32


def build_state(
    *,
    organization_id: UUID,
    source_id: UUID | None,
    workspace_id: UUID | None,
    document_id: UUID | None,
    window_index: int,
    result: SemanticWindowResult,
    previous: SemanticState | None = None,
    slice_: SemanticStateSlice | None = None,
    caps: StateCaps | None = None,
    window_section_id: str | None = None,
) -> SemanticState:
    """Fusiona el estado previo con el resultado de la ventana actual."""
    limits = caps or StateCaps()
    prev = previous or SemanticState(
        organization_id=organization_id,
        source_id=source_id,
        workspace_id=workspace_id,
        document_id=document_id,
        window_index=-1,
    )
    dropped: dict[str, int] = {}
    resolved_references: list[dict] = list(prev.resolved_references)
    resolved_continuations = 0

    # --- referencias sin resolver + resolución por información posterior ---
    unresolved: list[dict] = [dict(item) for item in prev.unresolved_references]
    new_reference_items = [
        *result.by_kind("definition"),
        *result.by_kind("entity"),
        *result.by_kind("concept"),
        *result.by_kind("symbol"),
        *result.by_kind("rule"),
        *result.topic_signals,
    ]
    resolution_labels = {
        normalize_term(str(item.label)) for item in new_reference_items
    }
    resolution_tokens: set[str] = set()
    for label in resolution_labels:
        resolution_tokens.update(label.split())
    resolution_labels |= {
        normalize_term(str(item.get("term") or ""))
        for item in _glossary_entries(result, window_index)
    }
    for item in result.unresolved_references:
        unresolved.append(
            {
                "key": item.key,
                "label": item.label,
                "target_kind": item.attributes.get("target_kind"),
                "reference_text": item.text,
                "window_index": window_index,
            }
        )
    # Una referencia con resolved_target explícito resuelve la previa homóloga.
    explicit_targets = {
        normalize_term(str(item.attributes.get("resolved_target")))
        for item in result.references
        if item.attributes.get("resolved_target")
    }
    kept: list[dict] = []
    for entry in unresolved:
        label = normalize_term(str(entry.get("label") or ""))
        if label and (
            label in resolution_labels
            or label in explicit_targets
            or (
                len(label.split()) == 1
                and label in resolution_tokens
                and len(label) >= 2
            )
        ):
            resolved_references.append(
                {
                    "key": entry.get("key"),
                    "label": entry.get("label"),
                    "resolved_by_window": window_index,
                }
            )
            continue
        kept.append(entry)
    unresolved = kept

    # --- continuaciones abiertas ---
    continuations: list[dict] = [dict(item) for item in prev.open_continuations]
    if window_section_id is not None:
        remaining = []
        for entry in continuations:
            if str(entry.get("section_id") or "") == str(window_section_id):
                resolved_continuations += 1
                continue
            remaining.append(entry)
        continuations = remaining
    for item in result.continuation_candidates:
        continuations.append(
            {
                "key": item.key,
                "label": item.label,
                "target_hint": item.attributes.get("target_hint"),
                "section_id": item.attributes.get("section_id"),
                "window_index": window_index,
            }
        )

    # --- acumulaciones con dedupe ---
    concepts = _merge(
        prev.active_concepts,
        (
            {
                "label": item.label,
                "concept_id": item.key,
                "window_index": window_index,
            }
            for item in result.concepts
        ),
        key="label",
    )
    entities = _merge(
        prev.known_entities,
        (
            {
                "label": item.label,
                "entity_type": item.attributes.get("entity_type") or "concept",
                "window_index": window_index,
            }
            for item in result.entities
        ),
        key="label",
    )
    glossary = _merge(
        prev.glossary,
        _glossary_entries(result, window_index),
        key="term",
    )
    symbols = _merge(
        prev.symbol_definitions,
        _symbol_entries(result, window_index),
        key="symbol",
    )
    rules = _merge(
        prev.active_rules,
        (
            {
                "key": item.key,
                "statement": item.text or item.label,
                "modality": item.attributes.get("modality"),
                "window_index": window_index,
            }
            for item in result.rules
        ),
        key="key",
    )
    aliases = _merge(
        prev.detected_aliases,
        (
            {
                "alias": item.label,
                "canonical": item.attributes.get("canonical") or "",
                "window_index": window_index,
            }
            for item in result.aliases
        ),
        key="alias",
    )
    conflicts = _merge(
        prev.conflicts,
        (
            {
                "label": item.label,
                "classification": item.attributes.get("classification"),
                "materiality": item.attributes.get("materiality"),
                "window_index": window_index,
            }
            for item in result.by_kind("conflict")
        ),
        key="label",
    )

    # --- relaciones pendientes: se resuelven cuando ambos extremos existen ---
    known_labels = {normalize_term(str(item.get("label") or "")) for item in entities}
    pending: list[dict] = [dict(item) for item in prev.pending_relationships]
    pending_resolved = 0
    for item in result.relationships:
        subject = normalize_term(str(item.attributes.get("subject") or ""))
        object_name = normalize_term(str(item.attributes.get("object") or ""))
        if subject and object_name and subject in known_labels and object_name in known_labels:
            pending_resolved += 1
            continue
        pending.append(
            {
                "key": item.key,
                "subject": item.attributes.get("subject"),
                "object": item.attributes.get("object"),
                "relation_type": item.attributes.get("relation_type")
                or item.label,
                "window_index": window_index,
            }
        )

    topics = list(prev.current_topics) + [
        item.label for item in result.topic_signals if item.label
    ]
    temporal = list(prev.temporal_context) + [
        item.label for item in result.temporal_statements if item.label
    ]

    concepts, dropped["concepts"] = _cap(concepts, limits.concepts)
    entities, dropped["entities"] = _cap(entities, limits.entities)
    glossary, dropped["glossary"] = _cap(glossary, limits.glossary)
    symbols, dropped["symbols"] = _cap(symbols, limits.symbols)
    rules, dropped["rules"] = _cap(rules, limits.rules)
    unresolved, dropped["unresolved_references"] = _cap(unresolved, limits.unresolved)
    resolved_references, dropped["resolved_references"] = _cap(
        resolved_references, limits.resolved
    )
    continuations, dropped["open_continuations"] = _cap(
        continuations, limits.continuations
    )
    aliases, dropped["detected_aliases"] = _cap(aliases, limits.aliases)
    pending, dropped["pending_relationships"] = _cap(pending, limits.relationships)
    conflicts, dropped["conflicts"] = _cap(conflicts, limits.conflicts)
    topics = topics[-limits.topics :] if limits.topics else []
    temporal = temporal[-limits.temporal :] if limits.temporal else []

    return SemanticState(
        organization_id=organization_id,
        source_id=source_id,
        workspace_id=workspace_id,
        document_id=document_id,
        window_index=window_index,
        active_concepts=tuple(concepts),
        known_entities=tuple(entities),
        glossary=tuple(glossary),
        symbol_definitions=tuple(symbols),
        active_rules=tuple(rules),
        unresolved_references=tuple(unresolved),
        resolved_references=tuple(resolved_references),
        open_continuations=tuple(continuations),
        current_topics=tuple(topics),
        temporal_context=tuple(temporal),
        detected_aliases=tuple(aliases),
        pending_relationships=tuple(pending),
        conflicts=tuple(conflicts),
        stats={
            "window_index": window_index,
            "carried_from": int(slice_.source_window_index) if slice_ else -1,
            "carry_selected": int(slice_.total) if slice_ else 0,
            "resolved_references": len(resolved_references),
            "resolved_continuations": resolved_continuations,
            "pending_resolved": pending_resolved,
            "dropped": dropped,
        },
    )


def _glossary_entries(result: SemanticWindowResult, window_index: int) -> list[dict]:
    return [
        {
            "term": item.label,
            "definition": item.text,
            "block_id": item.block_ids[0] if item.block_ids else None,
            "window_index": window_index,
        }
        for item in result.definitions
        if item.label
    ]


def _symbol_entries(result: SemanticWindowResult, window_index: int) -> list[dict]:
    definitions = [item for item in result.definitions]
    entries: list[dict] = []
    for item in result.symbols:
        symbol = item.label
        meaning = item.text
        if not meaning:
            meaning = next(
                (
                    definition.text
                    for definition in definitions
                    if symbol in definition.text or symbol in definition.label
                ),
                "",
            )
        entries.append(
            {
                "symbol": symbol,
                "meaning": meaning,
                "field_name": item.attributes.get("field_name"),
                "window_index": window_index,
            }
        )
    return entries


def _merge(existing, new_items, *, key: str) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for item in list(existing or ()) + list(new_items):
        entry = dict(item)
        entry_key = normalize_term(str(entry.get(key) or entry.get("label") or ""))
        if not entry_key:
            continue
        if entry_key not in merged:
            order.append(entry_key)
        merged[entry_key] = entry
    return [merged[entry_key] for entry_key in order]


def _cap(items: list[dict], limit: int) -> tuple[list[dict], int]:
    """Conserva lo más reciente; descarta lo viejo. Devuelve (items, dropped)."""
    if limit <= 0:
        return [], len(items)
    if len(items) <= limit:
        return items, 0
    return items[-limit:], len(items) - limit


__all__ = ["StateCaps", "build_state"]
