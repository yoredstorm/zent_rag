# =============================================================================
# SemanticStateSelector — carry-forward relevante, no indiscriminado (§11)
# =============================================================================
# Enviar todo el SemanticState anterior a cada ventana hace crecer el contexto
# sin límite. El selector decide qué información es relevante para la ventana
# siguiente:
#
#   - unresolved references y open continuations (siempre: son continuidad)
#   - definiciones/símbolos/reglas/aliases/conceptos/entidades que aparecen en
#     el texto de la próxima ventana o son adyacentes (recencia <= 1)
#   - topics y temporal recientes
#
# Determinista, con caps por categoría y stats auditables.
# =============================================================================
from __future__ import annotations

from .contracts import (
    STATE_SELECTOR_VERSION,
    SemanticState,
    SemanticStateSlice,
)


class SemanticStateSelector:
    """Selecciona el recorte relevante del estado para la ventana siguiente."""

    version = STATE_SELECTOR_VERSION

    def __init__(
        self,
        *,
        max_references: int = 32,
        max_continuations: int = 32,
        max_glossary: int = 24,
        max_symbols: int = 24,
        max_concepts: int = 32,
        max_entities: int = 32,
        max_rules: int = 24,
        max_aliases: int = 24,
        max_topics: int = 8,
        max_temporal: int = 8,
        max_relationships: int = 24,
        adjacent_window_delta: int = 1,
    ) -> None:
        self._caps = {
            "glossary": max(0, max_glossary),
            "symbols": max(0, max_symbols),
            "concepts": max(0, max_concepts),
            "entities": max(0, max_entities),
            "rules": max(0, max_rules),
            "aliases": max(0, max_aliases),
            "topics": max(0, max_topics),
            "temporal": max(0, max_temporal),
            "relationships": max(0, max_relationships),
        }
        self._max_references = max(0, max_references)
        self._max_continuations = max(0, max_continuations)
        self._adjacent = max(0, int(adjacent_window_delta))

    def select(
        self,
        state: SemanticState | None,
        *,
        window_text: str,
        window_index: int,
        section_id: str | None = None,
    ) -> SemanticStateSlice:
        if state is None:
            return SemanticStateSlice(
                window_index=window_index,
                source_window_index=-1,
                stats={"considered": 0, "selected": 0, "reason": "no_previous_state"},
            )
        haystack = _normalize(window_text)
        tokens = set(haystack.split())
        considered = 0

        def relevant(entry: dict) -> bool:
            label = str(
                entry.get("term")
                or entry.get("symbol")
                or entry.get("label")
                or entry.get("statement")
                or entry.get("alias")
                or entry.get("canonical")
                or ""
            )
            if label and _normalize(label) in haystack:
                return True
            if _recency(entry, state.window_index, self._adjacent):
                return True
            return bool(tokens.intersection(_normalize(label).split())) if label else False

        considered += len(state.active_concepts)
        concepts = [item for item in state.active_concepts if relevant(item)]
        considered += len(state.known_entities)
        entities = [item for item in state.known_entities if relevant(item)]
        considered += len(state.glossary)
        glossary = [item for item in state.glossary if relevant(item)]
        considered += len(state.symbol_definitions)
        symbols = [
            item
            for item in state.symbol_definitions
            if relevant(item) or _normalize(str(item.get("symbol") or "")) in haystack
        ]
        considered += len(state.active_rules)
        rules = [item for item in state.active_rules if relevant(item)]
        considered += len(state.detected_aliases)
        aliases = [item for item in state.detected_aliases if relevant(item)]

        selected_entity_labels = {
            _normalize(str(item.get("label") or item.get("name") or ""))
            for item in entities
        }
        considered += len(state.pending_relationships)
        relationships = []
        for item in state.pending_relationships:
            subject = _normalize(str(item.get("subject") or ""))
            object_name = _normalize(str(item.get("object") or ""))
            if (
                (subject and subject in haystack)
                or (object_name and object_name in haystack)
                or subject in selected_entity_labels
                or object_name in selected_entity_labels
            ):
                relationships.append(item)

        slice_ = SemanticStateSlice(
            window_index=window_index,
            source_window_index=int(state.window_index),
            active_concepts=tuple(concepts[: self._caps["concepts"]]),
            known_entities=tuple(entities[: self._caps["entities"]]),
            glossary=tuple(glossary[: self._caps["glossary"]]),
            symbol_definitions=tuple(symbols[: self._caps["symbols"]]),
            active_rules=tuple(rules[: self._caps["rules"]]),
            unresolved_references=tuple(
                state.unresolved_references[: self._max_references]
            ),
            open_continuations=tuple(
                state.open_continuations[: self._max_continuations]
            ),
            current_topics=tuple(state.current_topics[-self._caps["topics"] :]),
            temporal_context=tuple(state.temporal_context[-self._caps["temporal"] :]),
            detected_aliases=tuple(aliases[: self._caps["aliases"]]),
            pending_relationships=tuple(
                relationships[: self._caps["relationships"]]
            ),
            stats={
                "considered": considered,
                "selected": 0,  # se completa abajo
                "unresolved_references": len(state.unresolved_references),
                "open_continuations": len(state.open_continuations),
            },
        )
        payload = slice_.stats
        payload["selected"] = slice_.total
        return slice_


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _recency(entry: dict, current_window: int, delta: int) -> bool:
    try:
        entry_window = int(entry.get("window_index", -1))
    except (TypeError, ValueError):
        return False
    if entry_window < 0:
        return False
    return 0 <= (int(current_window) - entry_window) <= max(0, int(delta))


__all__ = ["SemanticStateSelector"]
