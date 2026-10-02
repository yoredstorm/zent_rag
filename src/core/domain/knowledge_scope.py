# =============================================================================
# KnowledgeScope — alcance declarativo del conocimiento autorizado (C7, W4).
# =============================================================================
# El scope SIEMPRE estrecha: `narrow` intersecta por campo y un campo vacío
# significa "sin restricción". Nunca amplía permisos ni fuentes.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping
from uuid import UUID

_MAX_IDS = 500
_MAX_VALUES = 50
_MAX_LEN = 64


def _uuid_tuple(value: Any) -> tuple[UUID, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[UUID] = []
    for item in value:
        try:
            parsed = UUID(str(item))
        except (TypeError, ValueError):
            continue
        if parsed not in out:
            out.append(parsed)
        if len(out) >= _MAX_IDS:
            break
    return tuple(out)


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()[: _MAX_LEN]
        if not text or text in out:
            continue
        out.append(text)
        if len(out) >= _MAX_VALUES:
            break
    return tuple(out)


@dataclass(frozen=True, kw_only=True)
class KnowledgeScope:
    """Vista autorizada del Knowledge OS. Vacío = sin restricción."""

    source_ids: tuple[UUID, ...] = ()
    knowledge_base_ids: tuple[UUID, ...] = ()
    workspace_ids: tuple[UUID, ...] = ()
    canonical_kinds: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.source_ids
            or self.knowledge_base_ids
            or self.workspace_ids
            or self.canonical_kinds
            or self.domains
            or self.tags
        )

    def to_public_dict(self) -> dict:
        return {
            "source_ids": [str(item) for item in self.source_ids],
            "knowledge_base_ids": [str(item) for item in self.knowledge_base_ids],
            "workspace_ids": [str(item) for item in self.workspace_ids],
            "canonical_kinds": list(self.canonical_kinds),
            "domains": list(self.domains),
            "tags": list(self.tags),
        }


def from_config(config: Mapping | None) -> KnowledgeScope:
    """Lee `knowledge_scope`; si falta, deriva del scope legacy del agente."""
    data = config if isinstance(config, Mapping) else {}
    raw = data.get("knowledge_scope")
    if not isinstance(raw, Mapping):
        raw = {}
    return KnowledgeScope(
        source_ids=_uuid_tuple(raw.get("source_ids"))
        or _uuid_tuple(data.get("source_ids")),
        knowledge_base_ids=_uuid_tuple(raw.get("knowledge_base_ids"))
        or _uuid_tuple(data.get("knowledge_base_ids")),
        workspace_ids=_uuid_tuple(raw.get("workspace_ids")),
        canonical_kinds=_str_tuple(raw.get("canonical_kinds")),
        domains=_str_tuple(raw.get("domains")),
        tags=_str_tuple(raw.get("tags")),
    )


def _narrow_values(base: tuple, other: tuple) -> tuple:
    if not base:
        return other
    if not other:
        return base
    return tuple(item for item in base if item in set(other))


def narrow(base: KnowledgeScope, other: KnowledgeScope) -> KnowledgeScope:
    """Intersección campo a campo; vacío = sin restricción (nunca amplía)."""
    return replace(
        base,
        source_ids=_narrow_values(base.source_ids, other.source_ids),
        knowledge_base_ids=_narrow_values(
            base.knowledge_base_ids, other.knowledge_base_ids
        ),
        workspace_ids=_narrow_values(base.workspace_ids, other.workspace_ids),
        canonical_kinds=_narrow_values(base.canonical_kinds, other.canonical_kinds),
        domains=_narrow_values(base.domains, other.domains),
        tags=_narrow_values(base.tags, other.tags),
    )
