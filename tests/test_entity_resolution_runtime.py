# =============================================================================
# Entity resolution runtime — menciones -> objetos canónicos (C2).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.runtime.entity_resolution import resolve_mentions


class FakeLookup:
    """Lookup canónico en memoria: nombres exactos + alias."""

    def __init__(self, *, names=None, aliases=None, boom=False) -> None:
        self.names = names or {}
        self.aliases = aliases or []
        self.boom = boom
        self.calls: list[tuple] = []

    async def find_objects_by_names(self, organization_id, names, *, kinds=None, limit=20, source_ids=None):
        self.calls.append(("names", tuple(names), source_ids))
        if self.boom:
            raise RuntimeError("db caída")
        found = []
        for wanted in names:
            for key, values in self.names.items():
                if key == wanted:
                    found.extend(values)
        return found[:limit]

    async def lookup_aliases(self, organization_id, normalized, *, limit=50, source_ids=None):
        self.calls.append(("aliases", tuple(normalized), source_ids))
        if self.boom:
            raise RuntimeError("db caída")
        return [row for row in self.aliases if row["normalized"] in normalized][:limit]


def _object(name: str, kind: str = "entity", confidence: float = 0.9) -> dict:
    return {
        "id": str(uuid4()),
        "kind": kind,
        "name": name,
        "display_name": name,
        "confidence": confidence,
        "status": "observed",
        "provenance": "OBSERVED",
    }


@pytest.mark.asyncio
async def test_resuelve_nombre_exacto() -> None:
    obj = _object("Category 31")
    lookup = FakeLookup(names={"category 31": [obj]})
    resolution = await resolve_mentions(lookup, uuid4(), ["Category 31"])
    assert resolution.resolved is True
    assert resolution.mentions[0].status == "resolved"
    assert resolution.mentions[0].matches[0].canonical_id == obj["id"]
    assert resolution.mentions[0].matches[0].match == "exact_name"


@pytest.mark.asyncio
async def test_resuelve_por_alias() -> None:
    obj = _object("Category 31")
    lookup = FakeLookup(
        aliases=[
            {
                "normalized": "cat 31",
                "alias": "Cat 31",
                "confidence": 0.9,
                "entity_id": obj["id"],
                "name": obj["name"],
                "kind": obj["kind"],
            }
        ]
    )
    resolution = await resolve_mentions(lookup, uuid4(), ["Cat 31"])
    assert resolution.mentions[0].status == "resolved"
    assert resolution.mentions[0].matches[0].match == "alias"
    assert resolution.mentions[0].matches[0].alias == "Cat 31"


@pytest.mark.asyncio
async def test_ambigua_no_fusiona() -> None:
    first, second = _object("Record 4", "entity"), _object("Record 4", "process")
    lookup = FakeLookup(names={"record 4": [first, second]})
    resolution = await resolve_mentions(lookup, uuid4(), ["Record 4"])
    assert resolution.mentions[0].status == "ambiguous"
    assert resolution.resolved is False


@pytest.mark.asyncio
async def test_sin_match_es_unresolved() -> None:
    lookup = FakeLookup()
    resolution = await resolve_mentions(lookup, uuid4(), ["No Existe"])
    assert resolution.mentions[0].status == "unresolved"
    assert resolution.mentions[0].matches == ()


@pytest.mark.asyncio
async def test_dedupe_y_cap_de_menciones() -> None:
    lookup = FakeLookup()
    resolution = await resolve_mentions(
        lookup, uuid4(), ["A", "a", "B", "C", "D", "E", "F", "G", "H", "I"]
    )
    mentions = [item.mention for item in resolution.mentions]
    assert mentions == ["A", "B", "C", "D", "E", "F", "G", "H"]
    assert lookup.calls


@pytest.mark.asyncio
async def test_ambigua_no_se_oculta_por_limite() -> None:
    first, second = _object("Record 4"), _object("Record 4", "process")
    lookup = FakeLookup(names={"record 4": [first, second]})
    resolution = await resolve_mentions(
        lookup, uuid4(), ["Record 4"], per_mention_limit=1
    )
    assert resolution.mentions[0].status == "ambiguous"
    assert len(resolution.mentions[0].matches) == 1


@pytest.mark.asyncio
async def test_resolve_mentions_reenvia_source_ids() -> None:
    source = uuid4()
    obj = _object("Category 31")
    lookup = FakeLookup(names={"category 31": [obj]})
    resolution = await resolve_mentions(
        lookup, uuid4(), ["Category 31"], source_ids=(source,)
    )
    assert resolution.resolved is True
    assert lookup.calls == [
        ("names", ("category 31",), (source,)),
        ("aliases", ("category 31",), (source,)),
    ]

    unscoped = FakeLookup(names={"category 31": [obj]})
    await resolve_mentions(unscoped, uuid4(), ["Category 31"])
    assert unscoped.calls == [
        ("names", ("category 31",), None),
        ("aliases", ("category 31",), None),
    ]


@pytest.mark.asyncio
async def test_resolve_mentions_scope_vacio_es_org_level() -> None:
    obj = _object("Category 31")
    lookup = FakeLookup(names={"category 31": [obj]})
    resolution = await resolve_mentions(lookup, uuid4(), ["Category 31"], source_ids=())
    assert resolution.resolved is True
    assert lookup.calls[0][2] == ()
