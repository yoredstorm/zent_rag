# =============================================================================
# Entity Resolution runtime — menciones -> identidad canónica (S4, C2).
# =============================================================================
# Determinista y org-scoped: match exacto por nombre normalizado o alias
# declarado. Nada se fusiona por parecido: la ambigüedad se reporta y decide
# el consumidor (ley del spec: la duda es información).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from src.catalog.entity_resolution import normalize_name

_MAX_MENTIONS = 8


class EntityLookup(Protocol):
    async def lookup_aliases(
        self, organization_id: UUID, normalized: list[str], *, limit: int = 50
    ) -> list[dict]: ...

    async def find_objects_by_names(
        self,
        organization_id: UUID,
        names: list[str],
        *,
        kinds: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[dict]: ...


@dataclass(frozen=True)
class EntityMatch:
    mention: str
    canonical_id: str
    name: str
    kind: str
    match: str  # exact_name | alias
    confidence: float
    alias: str | None = None

    def to_public_dict(self) -> dict:
        payload = {
            "canonical_id": self.canonical_id,
            "name": self.name,
            "kind": self.kind,
            "match": self.match,
            "confidence": round(float(self.confidence), 4),
        }
        if self.alias:
            payload["alias"] = self.alias
        return payload


@dataclass(frozen=True)
class MentionResolution:
    mention: str
    status: str  # resolved | ambiguous | unresolved
    matches: tuple[EntityMatch, ...] = ()

    def to_public_dict(self) -> dict:
        return {
            "mention": self.mention,
            "status": self.status,
            "matches": [match.to_public_dict() for match in self.matches],
        }


@dataclass(frozen=True)
class EntityResolution:
    mentions: tuple[MentionResolution, ...] = ()

    @property
    def resolved(self) -> bool:
        return bool(self.mentions) and all(
            item.status == "resolved" for item in self.mentions
        )

    def to_public_dict(self) -> dict:
        return {
            "mentions": [item.to_public_dict() for item in self.mentions],
            "resolved": self.resolved,
        }


def _clean_mentions(mentions) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in mentions or ():
        value = " ".join(str(raw or "").split())
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
        if len(cleaned) >= _MAX_MENTIONS:
            break
    return cleaned


async def resolve_mentions(
    lookup: EntityLookup,
    organization_id: UUID,
    mentions,
    *,
    per_mention_limit: int = 5,
) -> EntityResolution:
    """Resuelve menciones con evidencia canónica. Nunca inventa matches."""
    cleaned = _clean_mentions(mentions)
    if not cleaned:
        return EntityResolution()
    lowered = [mention.lower() for mention in cleaned]
    normalized = [normalize_name(mention) for mention in cleaned]

    objects = await lookup.find_objects_by_names(organization_id, lowered)
    # El repo compara contra alias.normalized persistido (normalize_term:
    # minúsculas y espacios preservados), por eso se consulta con `lowered`.
    # La comparación fina se hace con normalize_name en ambos lados.
    aliases = await lookup.lookup_aliases(organization_id, lowered)

    by_name: dict[str, list[dict]] = {}
    for obj in objects:
        key = str(obj.get("name") or obj.get("display_name") or "").lower()
        by_name.setdefault(key, []).append(obj)
    aliases_by_normalized: dict[str, list[dict]] = {}
    for row in aliases:
        key = normalize_name(str(row.get("normalized") or ""))
        aliases_by_normalized.setdefault(key, []).append(row)

    resolutions: list[MentionResolution] = []
    for mention, lower, norm in zip(cleaned, lowered, normalized):
        candidates: dict[str, EntityMatch] = {}
        for obj in by_name.get(lower, []):
            canonical_id = str(obj.get("id") or "")
            if not canonical_id:
                continue
            candidates.setdefault(
                canonical_id,
                EntityMatch(
                    mention=mention,
                    canonical_id=canonical_id,
                    name=str(obj.get("name") or mention),
                    kind=str(obj.get("kind") or ""),
                    match="exact_name",
                    confidence=float(obj["confidence"])
                    if obj.get("confidence") is not None
                    else 1.0,
                ),
            )
        for row in aliases_by_normalized.get(norm, []):
            canonical_id = str(row.get("entity_id") or "")
            if not canonical_id:
                continue
            candidates.setdefault(
                canonical_id,
                EntityMatch(
                    mention=mention,
                    canonical_id=canonical_id,
                    name=str(row.get("name") or mention),
                    kind=str(row.get("kind") or ""),
                    match="alias",
                    confidence=float(row["confidence"])
                    if row.get("confidence") is not None
                    else 0.5,
                    alias=str(row.get("alias") or "") or None,
                ),
            )
        ordered_all = sorted(
            candidates.values(),
            key=lambda match: (-match.confidence, match.name, match.canonical_id),
        )
        total = len(ordered_all)
        ordered = tuple(ordered_all[: max(1, int(per_mention_limit))])
        if total == 1:
            status = "resolved"
        elif total > 1:
            status = "ambiguous"
        else:
            status = "unresolved"
        resolutions.append(
            MentionResolution(mention=mention, status=status, matches=ordered)
        )
    return EntityResolution(mentions=tuple(resolutions))
