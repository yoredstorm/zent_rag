# Cognitive Runtime C2 — Representaciones + Entity Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolver menciones a objetos canónicos y ejecutar runners de representación (structured/tabular, graph, temporal) en modo observación, trazados en `flow["cognitive"]`, sin cambiar la respuesta.

**Architecture:** Lecturas nuevas org-scoped en el Knowledge Model repo/service (aliases + nombres + vigencia de assertions); módulos puros en `src/runtime/` (resolver, framework de runners, runners concretos); wiring fail-soft en `RAGOrchestrator` que observa y traza. Señales determinísticas (`entity_resolved`, `exact_lookup_declared`) expuestas al preflight JEV pero **sin consumirse en políticas todavía** (C4).

**Tech Stack:** Python del repo, pytest + pytest-asyncio, Postgres local (migración 136 = head), ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` (etapas S4/S5, §5 JEV, fase C2 §15).

## Global Constraints

- `RAG_COGNITIVE_OS_ENABLED` default `off`; con `off` el runtime actual queda intacto (cero imports de plan/strategy/runners, flow sin bloque `cognitive`).
- C2 es **observación**: los runners ejecutan y se trazan; NO alimentan contexto, retrieval, JEV ni LLM. La respuesta y el número de llamadas LLM no cambian.
- Solo corren las representaciones declaradas por la strategy: `graph`, `temporal`, `structured`. `vector`/`exact` siguen en el retriever canónico.
- Fail-soft obligatorio: timeout (3 s por runner), excepción o resultado vacío jamás rompen el run.
- Org-scoped estricto en toda query; jamás devolver objetos de otro tenant.
- Sin dependencias nuevas. Sin migraciones (tablas 135/132 ya aplicadas). Sin cambios de contrato API.
- Código/comentarios en español, estilo del repo; tests en `tests/test_*.py`.
- Cada tarea termina con tests verdes, lint limpio y commit. Branch `feat/cognitive-runtime-c2` desde `master`.
- DB local en head (`alembic upgrade head`) para los tests de Task 1; el resto usa fakes.

---

### Task 1: Canonical lookup reads (alias + nombres + vigencia)

**Files:**
- Modify: `src/platform/knowledge_model/repository.py` (nuevo `_LOOKUP_KINDS`, `_assertion_row`, `lookup_aliases`, `find_objects_by_names`)
- Modify: `src/platform/knowledge_model/service.py` (passthroughs)
- Test: `tests/test_knowledge_model_lookup.py`

**Interfaces:**
- Consumes: `src.infrastructure.postgres.session.get_async_session`, `normalize_object_type`, tablas `knowledge_canonical_objects` / `knowledge_entity_aliases` / `knowledge_assertions`.
- Produces:
  - `_assertion_row` incluye `valid_from`/`valid_to` (ISO o `None`).
  - `PostgresKnowledgeModelRepository.lookup_aliases(organization_id, normalized: list[str], *, limit=50) -> list[dict]` con `{normalized, alias, confidence, entity_id, name, kind}`.
  - `PostgresKnowledgeModelRepository.find_objects_by_names(organization_id, names: list[str], *, kinds: tuple[str, ...] = _LOOKUP_KINDS, limit=20) -> list[dict]` con `{id, kind, type, natural_key, name, display_name, confidence, status, provenance}`.
  - `KnowledgeModelService.lookup_aliases(...)` / `find_objects_by_names(..., kinds=None)` passthrough.

- [ ] **Step 1: Crear branch y baseline**

```bash
git checkout -b feat/cognitive-runtime-c2
pytest tests/test_knowledge_model.py -q
```

Expected: PASS (baseline verde; DB local en head).

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_knowledge_model_lookup.py`:

```python
# =============================================================================
# Knowledge Model — lecturas para entity resolution (C2).
# =============================================================================
# Alias normalizados, nombres canónicos exactos y vigencia de assertions.
# Postgres real (migración 135): el contrato es SQL, no un fake.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.core.domain.canonical import CanonicalKind, CanonicalObject, entity_natural_key
from src.infrastructure.postgres.canonical import PostgresCanonicalKnowledgeRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_model.repository import (
    PostgresKnowledgeModelRepository,
    _assertion_row,
)


@pytest.fixture
async def org():
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Lookup Org {uuid4().hex[:6]}")


@pytest.mark.asyncio
async def test_lookup_aliases_resuelve_por_alias_normalizado(org) -> None:
    canonical = PostgresCanonicalKnowledgeRepository()
    entity = await canonical.upsert_object(
        CanonicalObject(
            organization_id=org.id,
            kind=CanonicalKind.ENTITY,
            natural_key=entity_natural_key("category 31", "concept"),
            title="Category 31",
        )
    )
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_entity_aliases
                    (organization_id, entity_id, alias, normalized, confidence)
                VALUES (:org, :entity, 'Cat 31', 'cat 31', 0.9)
                """
            ),
            {"org": org.id, "entity": entity.canonical_id},
        )
        await session.commit()
    finally:
        await session.close()

    repo = PostgresKnowledgeModelRepository()
    rows = await repo.lookup_aliases(org.id, ["cat 31"])
    assert len(rows) == 1
    assert rows[0]["entity_id"] == str(entity.canonical_id)
    assert rows[0]["name"] == "Category 31"

    assert await repo.lookup_aliases(uuid4(), ["cat 31"]) == []


@pytest.mark.asyncio
async def test_find_objects_by_names_exacto_y_scoped(org) -> None:
    canonical = PostgresCanonicalKnowledgeRepository()
    entity = await canonical.upsert_object(
        CanonicalObject(
            organization_id=org.id,
            kind=CanonicalKind.ENTITY,
            natural_key=entity_natural_key("category 31", "concept"),
            title="Category 31",
        )
    )
    repo = PostgresKnowledgeModelRepository()
    found = await repo.find_objects_by_names(org.id, ["category 31"])
    assert [item["id"] for item in found] == [str(entity.canonical_id)]
    assert found[0]["name"] == "Category 31"
    assert await repo.find_objects_by_names(uuid4(), ["category 31"]) == []
    assert await repo.find_objects_by_names(org.id, ["cat 31"]) == []


def test_assertion_row_expone_vigencia() -> None:
    row = _assertion_row(
        SimpleNamespace(
            id=uuid4(),
            subject_id=uuid4(),
            subject_label="Rule X",
            predicate="applies_to",
            object_id=None,
            object_value="Category 31",
            assertion_type="rule",
            confidence=0.9,
            confidence_detail=None,
            status="approved",
            provenance="APPROVED",
            method="compiler",
            source_id=None,
            evidence_count=2,
            version=3,
            verified_at=None,
            stale_at=None,
            valid_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2025, 1, 1, tzinfo=timezone.utc),
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
    )
    assert row["valid_from"] == "2024-01-01T00:00:00+00:00"
    assert row["valid_to"] == "2025-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_service_passthrough(org) -> None:
    from src.platform.knowledge_model.service import KnowledgeModelService

    service = KnowledgeModelService(PostgresKnowledgeModelRepository())
    assert await service.lookup_aliases(org.id, ["cat 31"]) == []
    assert await service.find_objects_by_names(org.id, ["no existe"]) == []
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `pytest tests/test_knowledge_model_lookup.py -q`
Expected: FAIL (`AttributeError: 'PostgresKnowledgeModelRepository' object has no attribute 'lookup_aliases'` / `valid_from` ausente).

- [ ] **Step 4: Implementar**

4a. En `src/platform/knowledge_model/repository.py`, junto a `_STALE_DAYS_DEFAULT`:

```python
#: Kinds canónicos resolubles en runtime por nombre exacto (C2).
_LOOKUP_KINDS = ("entity", "concept", "process", "rule", "business_rule", "kpi")
```

4b. En `_assertion_row`, después de `"version": row.version or 1,`:

```python
        "valid_from": _iso(row.valid_from),
        "valid_to": _iso(row.valid_to),
```

4c. Métodos nuevos en `PostgresKnowledgeModelRepository`, después de `search`:

```python
    async def lookup_aliases(
        self, organization_id: UUID, normalized: list[str], *, limit: int = 50
    ) -> list[dict]:
        """Alias normalizados -> objeto canónico (scoped, determinista)."""
        names = [str(item).strip().lower() for item in normalized if str(item).strip()]
        if not names:
            return []
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT a.normalized, a.alias, a.confidence,
                               o.id AS entity_id, o.name, o.kind
                        FROM knowledge_entity_aliases a
                        JOIN knowledge_canonical_objects o
                          ON o.id = a.entity_id
                         AND o.organization_id = a.organization_id
                        WHERE a.organization_id = :org
                          AND a.normalized = ANY(:names)
                        ORDER BY a.confidence DESC, o.name
                        LIMIT :limit
                        """
                    ),
                    {
                        "org": organization_id,
                        "names": names[:50],
                        "limit": min(max(int(limit), 1), 200),
                    },
                )
            ).fetchall()
            return [
                {
                    "normalized": str(r.normalized),
                    "alias": str(r.alias),
                    "confidence": float(r.confidence or 0.0),
                    "entity_id": str(r.entity_id),
                    "name": str(r.name or ""),
                    "kind": str(r.kind or ""),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def find_objects_by_names(
        self,
        organization_id: UUID,
        names: list[str],
        *,
        kinds: tuple[str, ...] = _LOOKUP_KINDS,
        limit: int = 20,
    ) -> list[dict]:
        """Objetos canónicos por nombre exacto (lower) entre los kinds resolubles."""
        wanted = [str(item).strip().lower() for item in names if str(item).strip()]
        if not wanted:
            return []
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, natural_key, name, display_name,
                               confidence, status, provenance
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND kind = ANY(:kinds)
                          AND lower(COALESCE(
                                NULLIF(name, ''),
                                NULLIF(display_name, ''),
                                title,
                                natural_key
                              )) = ANY(:names)
                        ORDER BY confidence DESC NULLS LAST, name
                        LIMIT :limit
                        """
                    ),
                    {
                        "org": organization_id,
                        "kinds": list(kinds),
                        "names": wanted[:50],
                        "limit": min(max(int(limit), 1), 100),
                    },
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "kind": str(r.kind),
                    "type": normalize_object_type(r.kind),
                    "natural_key": str(r.natural_key),
                    "name": str(
                        r.name or r.display_name or r.natural_key or ""
                    ),
                    "display_name": str(
                        r.display_name or r.name or r.natural_key or ""
                    ),
                    "confidence": r.confidence,
                    "status": r.status,
                    "provenance": r.provenance,
                }
                for r in rows
            ]
        finally:
            await session.close()
```

4d. En `KnowledgeModelService`, después de `search`:

```python
    async def lookup_aliases(
        self, organization_id: UUID, normalized: list[str], *, limit: int = 50
    ) -> list[dict]:
        return await self._repo.lookup_aliases(
            organization_id, normalized, limit=limit
        )

    async def find_objects_by_names(
        self,
        organization_id: UUID,
        names: list[str],
        *,
        kinds: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        kwargs: dict = {"limit": limit}
        if kinds is not None:
            kwargs["kinds"] = tuple(kinds)
        return await self._repo.find_objects_by_names(
            organization_id, names, **kwargs
        )
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `pytest tests/test_knowledge_model_lookup.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Lint y commit**

```bash
ruff check src/platform/knowledge_model tests/test_knowledge_model_lookup.py
git add src/platform/knowledge_model/repository.py src/platform/knowledge_model/service.py tests/test_knowledge_model_lookup.py
git commit -m "feat(cognitive): lecturas canónicas para entity resolution (C2)"
```

---

### Task 2: Entity resolution en runtime

**Files:**
- Create: `src/runtime/entity_resolution.py`
- Test: `tests/test_entity_resolution_runtime.py`

**Interfaces:**
- Consumes: `src.catalog.entity_resolution.normalize_name` (normalización única compile-time/query-time).
- Produces:
  - Protocolo `EntityLookup` con `lookup_aliases(org, normalized, *, limit=50)` y `find_objects_by_names(org, names, *, kinds=None, limit=20)`.
  - `EntityMatch`, `MentionResolution` (`status`: `resolved|ambiguous|unresolved`), `EntityResolution` con `to_public_dict()` y propiedad `resolved`.
  - `async resolve_mentions(lookup, organization_id, mentions, *, per_mention_limit=5) -> EntityResolution`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_entity_resolution_runtime.py`:

```python
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

    async def find_objects_by_names(self, organization_id, names, *, kinds=None, limit=20):
        self.calls.append(("names", tuple(names)))
        if self.boom:
            raise RuntimeError("db caída")
        found = []
        for wanted in names:
            for key, values in self.names.items():
                if key == wanted:
                    found.extend(values)
        return found[:limit]

    async def lookup_aliases(self, organization_id, normalized, *, limit=50):
        self.calls.append(("aliases", tuple(normalized)))
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
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_entity_resolution_runtime.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.runtime.entity_resolution'`.

- [ ] **Step 3: Implementar**

`src/runtime/entity_resolution.py`:

```python
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
        if len(value) < 2 or key in seen:
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
    aliases = await lookup.lookup_aliases(organization_id, normalized)

    by_name: dict[str, list[dict]] = {}
    for obj in objects:
        key = str(obj.get("name") or obj.get("display_name") or "").lower()
        by_name.setdefault(key, []).append(obj)
    aliases_by_normalized: dict[str, list[dict]] = {}
    for row in aliases:
        aliases_by_normalized.setdefault(str(row.get("normalized") or ""), []).append(row)

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
                    confidence=float(obj.get("confidence") or 1.0),
                ),
            )
        for row in aliases_by_normalized.get(norm, []):
            canonical_id = str(row.get("entity_id") or "")
            if not canonical_id or canonical_id in candidates:
                continue
            candidates[canonical_id] = EntityMatch(
                mention=mention,
                canonical_id=canonical_id,
                name=str(row.get("name") or mention),
                kind=str(row.get("kind") or ""),
                match="alias",
                confidence=float(row.get("confidence") or 0.5),
                alias=str(row.get("alias") or "") or None,
            )
        ordered = tuple(
            sorted(
                candidates.values(),
                key=lambda match: (-match.confidence, match.name, match.canonical_id),
            )[: max(1, int(per_mention_limit))]
        )
        if len(ordered) == 1:
            status = "resolved"
        elif len(ordered) > 1:
            status = "ambiguous"
        else:
            status = "unresolved"
        resolutions.append(
            MentionResolution(mention=mention, status=status, matches=ordered)
        )
    return EntityResolution(mentions=tuple(resolutions))
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_entity_resolution_runtime.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/entity_resolution.py tests/test_entity_resolution_runtime.py
git add src/runtime/entity_resolution.py tests/test_entity_resolution_runtime.py
git commit -m "feat(cognitive): entity resolution runtime determinista (C2)"
```

---

### Task 3: Runner framework (tipos + dispatcher fail-soft)

**Files:**
- Create: `src/runtime/representation_runners.py`
- Test: `tests/test_representation_runners.py`

**Interfaces:**
- Consumes: `EntityResolution` (Task 2), `KnowledgeStrategy` (C1) solo para anotaciones.
- Produces:
  - `RunnerItem(title, summary, refs={}, score=None)` con `to_public_dict()`.
  - `RunnerResult(representation, status, items=(), latency_ms=0.0, error=None)` con `to_public_dict(max_items=5)`.
  - `RunnerContext(query, organization_id, user_id, role, strategy, entities)`.
  - Protocolo `RepresentationRunner` (`representation: str`, `run(ctx) -> RunnerResult`).
  - `RUNNER_TIMEOUT_SECONDS = 3.0`, `MAX_ITEMS_PER_RUNNER = 5`.
  - `async run_representations(ctx, runners, *, representations=None, timeout_seconds=RUNNER_TIMEOUT_SECONDS) -> tuple[RunnerResult, ...]`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_representation_runners.py`:

```python
# =============================================================================
# Runner framework — ejecución fail-soft y acotada de representaciones (C2).
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from src.runtime.representation_runners import (
    RunnerContext,
    RunnerItem,
    RunnerResult,
    run_representations,
)


class FakeRunner:
    def __init__(self, representation: str, *, result=None, error=None, delay=0.0):
        self.representation = representation
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = 0

    async def run(self, ctx):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result or RunnerResult(
            representation=self.representation,
            status="ok",
            items=(RunnerItem(title="t", summary="s"),),
        )


def _ctx() -> RunnerContext:
    return RunnerContext(
        query="q",
        organization_id=uuid4(),
        user_id=None,
        role="admin",
        strategy=None,
        entities=None,
    )


@pytest.mark.asyncio
async def test_solo_corre_representaciones_declaradas() -> None:
    graph = FakeRunner("graph")
    temporal = FakeRunner("temporal")
    results = await run_representations(
        _ctx(), (graph, temporal), representations=("graph",)
    )
    assert [result.representation for result in results] == ["graph"]
    assert graph.calls == 1 and temporal.calls == 0


@pytest.mark.asyncio
async def test_error_no_propaga() -> None:
    boom = FakeRunner("graph", error=RuntimeError("caída"))
    (result,) = await run_representations(_ctx(), (boom,))
    assert result.status == "error"
    assert "caída" in (result.error or "")


@pytest.mark.asyncio
async def test_timeout_acotado() -> None:
    slow = FakeRunner("graph", delay=0.2)
    (result,) = await run_representations(
        _ctx(), (slow,), timeout_seconds=0.01
    )
    assert result.status == "timeout"


@pytest.mark.asyncio
async def test_payload_recorta_items() -> None:
    many = RunnerResult(
        representation="graph",
        status="ok",
        items=tuple(
            RunnerItem(title=f"t{i}", summary="s") for i in range(9)
        ),
    )
    payload = many.to_public_dict(max_items=5)
    assert len(payload["items"]) == 5
    assert payload["count"] == 9
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_representation_runners.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.runtime.representation_runners'`.

- [ ] **Step 3: Implementar**

`src/runtime/representation_runners.py`:

```python
# =============================================================================
# Representation runners — framework de observación multi-representación (S5).
# =============================================================================
# Cada runner declara su representación y devuelve items con refs. El
# dispatcher los corre en orden, con timeout y fail-soft: un runner roto jamás
# cambia la respuesta.
# =============================================================================
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Collection, Protocol, Sequence
from uuid import UUID

if TYPE_CHECKING:  # anotaciones: no importa strategy ni resolution en runtime
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.knowledge_strategy import KnowledgeStrategy

RUNNER_TIMEOUT_SECONDS = 3.0
MAX_ITEMS_PER_RUNNER = 5


@dataclass(frozen=True)
class RunnerItem:
    title: str
    summary: str
    refs: dict = field(default_factory=dict)
    score: float | None = None

    def to_public_dict(self) -> dict:
        payload = {"title": self.title, "summary": self.summary, "refs": dict(self.refs)}
        if self.score is not None:
            payload["score"] = round(float(self.score), 4)
        return payload


@dataclass(frozen=True)
class RunnerResult:
    representation: str
    status: str  # ok | empty | skipped | error | timeout
    items: tuple[RunnerItem, ...] = ()
    latency_ms: float = 0.0
    error: str | None = None

    def to_public_dict(self, *, max_items: int = MAX_ITEMS_PER_RUNNER) -> dict:
        payload: dict = {
            "representation": self.representation,
            "status": self.status,
            "count": len(self.items),
            "items": [item.to_public_dict() for item in self.items[: max(0, max_items)]],
            "latency_ms": round(float(self.latency_ms), 1),
        }
        if self.error:
            payload["error"] = self.error[:200]
        return payload


@dataclass(frozen=True)
class RunnerContext:
    query: str
    organization_id: UUID
    user_id: UUID | None
    role: str
    strategy: "KnowledgeStrategy | None" = None
    entities: "EntityResolution | None" = None


class RepresentationRunner(Protocol):
    representation: str

    async def run(self, ctx: RunnerContext) -> RunnerResult: ...


async def run_representations(
    ctx: RunnerContext,
    runners: Sequence[RepresentationRunner],
    *,
    representations: Collection[str] | None = None,
    timeout_seconds: float = RUNNER_TIMEOUT_SECONDS,
) -> tuple[RunnerResult, ...]:
    """Corre los runners declarados. Nunca lanza; cada resultado se traza."""
    wanted = None if representations is None else {str(rep) for rep in representations}
    results: list[RunnerResult] = []
    for runner in runners:
        representation = str(getattr(runner, "representation", "") or "")
        if not representation:
            continue
        if wanted is not None and representation not in wanted:
            continue
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                runner.run(ctx), timeout=max(0.01, float(timeout_seconds))
            )
            if not isinstance(result, RunnerResult):
                result = RunnerResult(
                    representation=representation,
                    status="error",
                    error="runner devolvió un tipo inválido",
                )
        except asyncio.TimeoutError:
            result = RunnerResult(
                representation=representation,
                status="timeout",
                error=f"timeout tras {timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001 — observación nunca rompe el run
            result = RunnerResult(
                representation=representation,
                status="error",
                error=str(exc)[:200],
            )
        latency_ms = (time.perf_counter() - started) * 1000
        results.append(replace(result, latency_ms=latency_ms))
    return tuple(results)
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_representation_runners.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/representation_runners.py tests/test_representation_runners.py
git add src/runtime/representation_runners.py tests/test_representation_runners.py
git commit -m "feat(cognitive): framework de runners fail-soft (C2)"
```

---

### Task 4: Runners graph + temporal

**Files:**
- Create: `src/runtime/graph_runner.py`, `src/runtime/temporal_runner.py`
- Test: `tests/test_graph_temporal_runners.py`

**Interfaces:**
- Consumes: `RunnerContext/RunnerItem/RunnerResult` (Task 3), `EntityResolution/MentionResolution` (Task 2).
- Produces:
  - `GraphRunner(lookup, *, max_edges=24)` con `representation = "graph"`; lookup duck-typed `object_edges(org, object_id, *, limit=200) -> dict`.
  - `TemporalRunner(lookup, *, max_assertions=20, now=None)` con `representation = "temporal"`; lookup duck-typed `object_assertions(org, object_id, *, limit=100) -> list[dict]`; estado `current|historical|future|unknown`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_graph_temporal_runners.py`:

```python
# =============================================================================
# Runners graph + temporal — observación con refs canónicas (C2).
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.runtime.entity_resolution import (
    EntityMatch,
    EntityResolution,
    MentionResolution,
)
from src.runtime.graph_runner import GraphRunner
from src.runtime.representation_runners import RunnerContext
from src.runtime.temporal_runner import TemporalRunner

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ctx(entities: EntityResolution | None) -> RunnerContext:
    return RunnerContext(
        query="q",
        organization_id=uuid4(),
        user_id=None,
        role="admin",
        strategy=None,
        entities=entities,
    )


def _resolved(canonical_id: str, name: str = "Category 31") -> EntityResolution:
    return EntityResolution(
        mentions=(
            MentionResolution(
                mention=name,
                status="resolved",
                matches=(
                    EntityMatch(
                        mention=name,
                        canonical_id=canonical_id,
                        name=name,
                        kind="entity",
                        match="exact_name",
                        confidence=0.9,
                    ),
                ),
            ),
        )
    )


class FakeEdges:
    def __init__(self, edges, *, boom=False):
        self.edges = edges
        self.boom = boom
        self.calls = 0

    async def object_edges(self, organization_id, object_id, *, limit=200):
        self.calls += 1
        if self.boom:
            raise RuntimeError("caída")
        return {"edges": self.edges, "count": len(self.edges)}


class FakeAssertions:
    def __init__(self, rows, *, boom=False):
        self.rows = rows
        self.boom = boom

    async def object_assertions(self, organization_id, object_id, *, limit=100):
        if self.boom:
            raise RuntimeError("caída")
        return self.rows


@pytest.mark.asyncio
async def test_graph_runner_items_con_refs() -> None:
    edge = {
        "id": str(uuid4()),
        "subject_id": str(uuid4()),
        "object_id": str(uuid4()),
        "subject_name": "Record 4",
        "predicate": "requires",
        "object_name": "Record 2",
        "relationship_type": "depends_on",
        "confidence": 0.8,
    }
    lookup = FakeEdges([edge])
    result = await GraphRunner(lookup).run(_ctx(_resolved(str(uuid4()))))
    assert result.status == "ok"
    assert result.items[0].refs["edge_id"] == edge["id"]
    assert "Record 4" in result.items[0].title
    assert lookup.calls == 1


@pytest.mark.asyncio
async def test_graph_runner_sin_entidades_skip() -> None:
    result = await GraphRunner(FakeEdges([])).run(_ctx(None))
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_graph_runner_ambigua_no_consulta() -> None:
    ambiguous = EntityResolution(
        mentions=(MentionResolution(mention="R", status="ambiguous", matches=()),)
    )
    lookup = FakeEdges([])
    result = await GraphRunner(lookup).run(_ctx(ambiguous))
    assert result.status == "skipped"
    assert lookup.calls == 0


@pytest.mark.asyncio
async def test_temporal_runner_estado_vigencia() -> None:
    rows = [
        {
            "id": str(uuid4()),
            "subject_label": "Rule X",
            "predicate": "applies_to",
            "object_value": "Category 31",
            "confidence": 0.9,
            "valid_from": "2024-01-01T00:00:00+00:00",
            "valid_to": "2025-01-01T00:00:00+00:00",
        },
        {
            "id": str(uuid4()),
            "subject_label": "Rule X",
            "predicate": "applies_to",
            "object_value": "Category 32",
            "confidence": 0.8,
            "valid_from": "2025-06-01T00:00:00+00:00",
            "valid_to": None,
        },
    ]
    runner = TemporalRunner(FakeAssertions(rows), now=lambda: _NOW)
    result = await runner.run(_ctx(_resolved(str(uuid4()))))
    assert result.status == "ok"
    states = [item.refs["validity"] for item in result.items]
    assert states == ["historical", "current"]
    assert result.items[0].refs["assertion_id"] == rows[0]["id"]


@pytest.mark.asyncio
async def test_temporal_runner_sin_ventana_es_empty() -> None:
    rows = [
        {
            "id": str(uuid4()),
            "subject_label": "Rule X",
            "predicate": "applies_to",
            "object_value": "Category 31",
            "confidence": 0.9,
            "valid_from": None,
            "valid_to": None,
        }
    ]
    runner = TemporalRunner(FakeAssertions(rows), now=lambda: _NOW)
    result = await runner.run(_ctx(_resolved(str(uuid4()))))
    assert result.status == "empty"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_graph_temporal_runners.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.runtime.graph_runner'`.

- [ ] **Step 3: Implementar**

`src/runtime/graph_runner.py`:

```python
# =============================================================================
# Graph runner — vecindario canónico de las entidades resueltas (S5, C2).
# =============================================================================
# Lee conocimiento canónico (knowledge_edges), no Qdrant: son hechos ya
# compilados con refs. No alimenta la respuesta todavía; se traza.
# =============================================================================
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.runtime.representation_runners import (
    MAX_ITEMS_PER_RUNNER,
    RunnerContext,
    RunnerItem,
    RunnerResult,
)


class GraphLookup(Protocol):
    async def object_edges(
        self, organization_id: UUID, object_id: UUID, *, limit: int = 200
    ) -> dict: ...


class GraphRunner:
    representation = "graph"

    def __init__(self, lookup: GraphLookup, *, max_edges: int = 24) -> None:
        self._lookup = lookup
        self._max_edges = max(1, int(max_edges))

    async def run(self, ctx: RunnerContext) -> RunnerResult:
        if ctx.entities is None or not ctx.entities.mentions:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="sin_entidades_resueltas",
            )
        items: list[RunnerItem] = []
        resolved = [
            item
            for item in ctx.entities.mentions
            if item.status == "resolved" and item.matches
        ]
        if not resolved:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="menciones_sin_resolver",
            )
        for mention in resolved:
            match = mention.matches[0]
            data = await self._lookup.object_edges(
                ctx.organization_id,
                UUID(match.canonical_id),
                limit=self._max_edges,
            )
            for edge in list(data.get("edges") or ())[: self._max_edges]:
                subject = str(edge.get("subject_name") or "")
                predicate = str(edge.get("predicate") or "")
                obj = str(edge.get("object_name") or "")
                items.append(
                    RunnerItem(
                        title=f"{subject} {predicate} {obj}".strip(),
                        summary=str(edge.get("relationship_type") or predicate),
                        refs={
                            "edge_id": str(edge.get("id") or ""),
                            "canonical_id": match.canonical_id,
                            "subject_id": str(edge.get("subject_id") or ""),
                            "object_id": str(edge.get("object_id") or ""),
                        },
                        score=edge.get("confidence"),
                    )
                )
                if len(items) >= MAX_ITEMS_PER_RUNNER:
                    break
            if len(items) >= MAX_ITEMS_PER_RUNNER:
                break
        status = "ok" if items else "empty"
        return RunnerResult(
            representation=self.representation, status=status, items=tuple(items)
        )
```

`src/runtime/temporal_runner.py`:

```python
# =============================================================================
# Temporal runner — vigencia de assertions canónicas (S5, C2).
# =============================================================================
# Determinista: valid_from/valid_to -> current | historical | future | unknown.
# No resuelve vigencias ni elige "la correcta": las declara.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

from src.runtime.representation_runners import (
    MAX_ITEMS_PER_RUNNER,
    RunnerContext,
    RunnerItem,
    RunnerResult,
)


class TemporalLookup(Protocol):
    async def object_assertions(
        self, organization_id: UUID, object_id: UUID, *, limit: int = 100
    ) -> list[dict]: ...


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def validity_state(
    valid_from: str | None, valid_to: str | None, now: datetime
) -> str:
    """Estado de vigencia medido, nunca inferido."""
    start = _parse(valid_from)
    end = _parse(valid_to)
    if start is None and end is None:
        return "unknown"
    if start is not None and start > now:
        return "future"
    if end is not None and end < now:
        return "historical"
    return "current"


class TemporalRunner:
    representation = "temporal"

    def __init__(
        self,
        lookup: TemporalLookup,
        *,
        max_assertions: int = 20,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._lookup = lookup
        self._max_assertions = max(1, int(max_assertions))
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def run(self, ctx: RunnerContext) -> RunnerResult:
        if ctx.entities is None or not ctx.entities.mentions:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="sin_entidades_resueltas",
            )
        resolved = [
            item
            for item in ctx.entities.mentions
            if item.status == "resolved" and item.matches
        ]
        if not resolved:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="menciones_sin_resolver",
            )
        now = self._now()
        items: list[RunnerItem] = []
        for mention in resolved:
            match = mention.matches[0]
            rows = await self._lookup.object_assertions(
                ctx.organization_id,
                UUID(match.canonical_id),
                limit=self._max_assertions,
            )
            for row in list(rows or ()):
                valid_from = row.get("valid_from")
                valid_to = row.get("valid_to")
                state = validity_state(valid_from, valid_to, now)
                if state == "unknown":
                    continue
                label = f"{row.get('subject_label') or mention.mention} " \
                        f"{row.get('predicate') or ''} " \
                        f"{row.get('object_value') or ''}".strip()
                items.append(
                    RunnerItem(
                        title=label,
                        summary=f"vigencia {state}",
                        refs={
                            "assertion_id": str(row.get("id") or ""),
                            "canonical_id": match.canonical_id,
                            "validity": state,
                            "valid_from": valid_from,
                            "valid_to": valid_to,
                        },
                        score=row.get("confidence"),
                    )
                )
                if len(items) >= MAX_ITEMS_PER_RUNNER:
                    break
            if len(items) >= MAX_ITEMS_PER_RUNNER:
                break
        status = "ok" if items else "empty"
        return RunnerResult(
            representation=self.representation, status=status, items=tuple(items)
        )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_graph_temporal_runners.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/graph_runner.py src/runtime/temporal_runner.py tests/test_graph_temporal_runners.py
git add src/runtime/graph_runner.py src/runtime/temporal_runner.py tests/test_graph_temporal_runners.py
git commit -m "feat(cognitive): runners graph y temporal (C2)"
```

---

### Task 5: Runner estructurado (tabular)

**Files:**
- Create: `src/runtime/tabular_runner.py`
- Test: `tests/test_tabular_runner.py`

**Interfaces:**
- Consumes: `TabularQueryService.try_answer(org, question, *, source_ids=None, knowledge_base_id=None, role="admin", user_id=None) -> SqlQueryResult | None`; `RunnerContext/RunnerItem/RunnerResult`.
- Produces: `TabularRunner(tabular_query, *, max_rows=3)` con `representation = "structured"`. No expone SQL crudo (solo `table` de metadata).

- [ ] **Step 1: Escribir el test que falla**

`tests/test_tabular_runner.py`:

```python
# =============================================================================
# Runner estructurado — consulta tabular exacta en observación (C2).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.ports.sql_expert import SqlQueryResult
from src.runtime.representation_runners import RunnerContext
from src.runtime.tabular_runner import TabularRunner


class FakeTabular:
    def __init__(self, answer=None, *, boom=False):
        self.answer = answer
        self.boom = boom
        self.calls: list[dict] = []

    async def try_answer(self, organization_id, question, **kwargs):
        self.calls.append({"organization_id": organization_id, "question": question, **kwargs})
        if self.boom:
            raise RuntimeError("lazy caído")
        return self.answer


def _ctx() -> RunnerContext:
    return RunnerContext(
        query="¿Cuál es el total de la columna 7?",
        organization_id=uuid4(),
        user_id=None,
        role="admin",
        strategy=None,
        entities=None,
    )


@pytest.mark.asyncio
async def test_tabular_runner_item_con_columnas_y_filas() -> None:
    answer = SqlQueryResult(
        sql="SELECT sum(col7) FROM t",
        columns=["total"],
        rows=[["1284"]],
        row_count=1,
        metadata={"table": "sheet_1", "strategy": "aggregation"},
    )
    fake = FakeTabular(answer)
    result = await TabularRunner(fake).run(_ctx())
    assert result.status == "ok"
    item = result.items[0]
    assert "total" in item.summary
    assert item.refs["table"] == "sheet_1"
    assert "SELECT" not in item.summary  # nunca SQL crudo en la traza
    assert fake.calls[0]["role"] == "admin"


@pytest.mark.asyncio
async def test_tabular_runner_sin_match_skip() -> None:
    result = await TabularRunner(FakeTabular(None)).run(_ctx())
    assert result.status == "skipped"
    assert result.error == "sin_match_tabular"


@pytest.mark.asyncio
async def test_tabular_runner_error_capturado_por_dispatcher() -> None:
    from src.runtime.representation_runners import run_representations

    (result,) = await run_representations(_ctx(), (TabularRunner(FakeTabular(boom=True)),))
    assert result.status == "error"
    assert "lazy" in (result.error or "")
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_tabular_runner.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.runtime.tabular_runner'`.

- [ ] **Step 3: Implementar**

`src/runtime/tabular_runner.py`:

```python
# =============================================================================
# Tabular runner — representación estructurada en observación (S5, C2).
# =============================================================================
# Usa el servicio tabular ya productivo (lookup/agregación exactos). Solo
# observa y traza: el resultado no entra al contexto en C2.
# =============================================================================
from __future__ import annotations

from typing import Protocol

from src.runtime.representation_runners import (
    RunnerContext,
    RunnerItem,
    RunnerResult,
)


class TabularQuery(Protocol):
    async def try_answer(
        self,
        organization_id,
        question: str,
        *,
        source_ids=None,
        knowledge_base_id=None,
        role: str = "admin",
        user_id=None,
    ): ...


def _format_cell(value) -> str:
    text = "" if value is None else str(value)
    return text[:120]


class TabularRunner:
    representation = "structured"

    def __init__(self, tabular_query: TabularQuery, *, max_rows: int = 3) -> None:
        self._tabular = tabular_query
        self._max_rows = max(1, int(max_rows))

    async def run(self, ctx: RunnerContext) -> RunnerResult:
        answer = await self._tabular.try_answer(
            ctx.organization_id,
            ctx.query,
            role=ctx.role,
            user_id=ctx.user_id,
        )
        if answer is None:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="sin_match_tabular",
            )
        columns = [str(column) for column in (getattr(answer, "columns", None) or ())]
        rows = list(getattr(answer, "rows", None) or ())
        table = str((getattr(answer, "metadata", None) or {}).get("table") or "")
        header = " | ".join(columns[:8])
        preview = "\n".join(
            " | ".join(_format_cell(cell) for cell in row[:8])
            for row in rows[: self._max_rows]
        )
        summary = header if not preview else f"{header}\n{preview}"
        item = RunnerItem(
            title="Consulta tabular exacta",
            summary=summary[:800],
            refs={
                "table": table,
                "row_count": int(getattr(answer, "row_count", 0) or 0),
            },
            score=1.0,
        )
        return RunnerResult(
            representation=self.representation, status="ok", items=(item,)
        )
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_tabular_runner.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Lint y commit**

```bash
ruff check src/runtime/tabular_runner.py tests/test_tabular_runner.py
git add src/runtime/tabular_runner.py tests/test_tabular_runner.py
git commit -m "feat(cognitive): runner estructurado tabular (C2)"
```

---

### Task 6: Wiring de observación + traza + señales JEV

**Files:**
- Modify: `src/runtime/cognitive_state.py` (campos `entities`, `runners`; `jev_signals()`; `to_public_dict`)
- Modify: `src/agents/runtime/orchestrator.py` (constructor `knowledge_model`; `_observe_cognitive`; `_build_cognitive_runners`; `_preflight_gate` con `cognitive_signals`; call sites)
- Modify: `src/decision/preflight.py` (`DeterministicSignals` + `to_public_dict`)
- Modify: `src/api/deps.py` (inyectar `knowledge_model=get_knowledge_model_service()`)
- Modify: `tests/test_cognitive_state.py` (tests de `jev_signals`)
- Modify: `tests/test_cognitive_runtime_shadow.py` (fakes canónicos + escenarios de observación)

**Interfaces:**
- Consumes: Task 2–5 (`resolve_mentions`, `run_representations`, runners) y `get_knowledge_model_service()`.
- Produces:
  - `CognitiveTurn.entities: EntityResolution | None`, `CognitiveTurn.runners: tuple[RunnerResult, ...]`, `CognitiveTurn.jev_signals() -> {"entity_resolved": bool|None, "exact_lookup_declared": bool}`, y `to_public_dict()` con `entities`/`runners`/`signals`.
  - `RAGOrchestrator(knowledge_model=...)`; `_observe_cognitive(...)` fail-soft.
  - `DeterministicSignals.entity_resolved` / `.exact_lookup_declared` (defaults `None`) y en `to_public_dict`.
  - `_preflight_gate(..., cognitive_signals: dict | None = None)`; ambos call sites pasan `cognitive_signals`.

- [ ] **Step 1: Escribir los tests que fallan**

1a. Extender `tests/test_cognitive_state.py` con:

```python
def test_jev_signals_sin_entidades(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    query = "¿Aplica la regla 12?"
    turn = CognitiveTurn(query=query, plan=build_cognitive_plan(query))
    assert turn.jev_signals() == {
        "exact_lookup_declared": False,
        "entity_resolved": None,
    }


def test_jev_signals_entidad_resuelta(monkeypatch) -> None:
    from src.runtime.entity_resolution import (
        EntityMatch,
        EntityResolution,
        MentionResolution,
    )

    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    query = "¿Qué significa el Byte 105?"
    turn = CognitiveTurn(query=query, plan=build_cognitive_plan(query))
    turn.entities = EntityResolution(
        mentions=(
            MentionResolution(
                mention="Byte 105",
                status="resolved",
                matches=(
                    EntityMatch(
                        mention="Byte 105",
                        canonical_id="c1",
                        name="Byte 105",
                        kind="entity",
                        match="exact_name",
                        confidence=1.0,
                    ),
                ),
            ),
        )
    )
    signals = turn.jev_signals()
    assert signals["exact_lookup_declared"] is True
    assert signals["entity_resolved"] is True
```

1b. Extender `tests/test_cognitive_runtime_shadow.py`: ampliar `_build` con `knowledge_model=None, tabular_query=None` y agregar fakes + escenarios:

```python
class FakeKnowledgeModel:
    """Lookup canónico en memoria para observar runners."""

    def __init__(self, *, names=None, aliases=None, edges=None, assertions=None, boom=False):
        self.names = names or {}
        self.aliases = aliases or []
        self.edges = edges or {}
        self.assertions = assertions or {}
        self.boom = boom

    async def find_objects_by_names(self, organization_id, names, *, kinds=None, limit=20):
        if self.boom:
            raise RuntimeError("db caída")
        found = []
        for wanted in names:
            found.extend(self.names.get(wanted, []))
        return found[:limit]

    async def lookup_aliases(self, organization_id, normalized, *, limit=50):
        if self.boom:
            raise RuntimeError("db caída")
        return [row for row in self.aliases if row["normalized"] in normalized][:limit]

    async def object_edges(self, organization_id, object_id, *, limit=200):
        return {"edges": self.edges.get(str(object_id), [])[:limit]}

    async def object_assertions(self, organization_id, object_id, *, limit=100):
        return self.assertions.get(str(object_id), [])[:limit]


class FakeTabular:
    def __init__(self, answer=None):
        self.answer = answer
        self.calls = 0

    async def try_answer(self, organization_id, question, **kwargs):
        self.calls += 1
        return self.answer


def _build(
    *,
    organization: Organization,
    llm: FakeLLM,
    vector_store: FakeVectorStore,
    knowledge_model: Any = None,
    tabular_query: Any = None,
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=vector_store,
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        knowledge_model=knowledge_model,
        tabular_query=tabular_query,
    )
```

Escenarios nuevos:

```python
@pytest.mark.asyncio
async def test_shadow_resuelve_entidades_y_traza_grafo(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={
            "category 31": [
                {
                    "id": canonical_id,
                    "kind": "entity",
                    "name": "Category 31",
                    "display_name": "Category 31",
                    "confidence": 0.9,
                }
            ]
        },
        edges={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_name": "Category 31",
                    "predicate": "requires",
                    "object_name": "Record 4",
                    "confidence": 0.8,
                }
            ]
        },
    )
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=model,
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué relación tiene Category 31?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["entities"]["resolved"] is True
    graph = [r for r in cognitive["runners"] if r["representation"] == "graph"]
    assert graph and graph[0]["status"] == "ok"
    assert len(llm.calls) == 1  # observación: la generación no cambió


@pytest.mark.asyncio
async def test_shadow_runner_temporal(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={
            "category 31": [
                {
                    "id": canonical_id,
                    "kind": "entity",
                    "name": "Category 31",
                    "display_name": "Category 31",
                    "confidence": 0.9,
                }
            ]
        },
        assertions={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_label": "Category 31",
                    "predicate": "valid_for",
                    "object_value": "2024",
                    "confidence": 0.9,
                    "valid_from": "2024-01-01T00:00:00+00:00",
                    "valid_to": "2025-01-01T00:00:00+00:00",
                }
            ]
        },
    )
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=model,
    )
    result = await _execute(
        orchestrator, organization.id, "¿La Category 31 sigue vigente?"
    )
    temporal = [
        r for r in result.flow["cognitive"]["runners"]
        if r["representation"] == "temporal"
    ]
    assert temporal and temporal[0]["items"][0]["refs"]["validity"] == "historical"


@pytest.mark.asyncio
async def test_shadow_runner_tabular(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    answer = SqlQueryResult(
        sql="SELECT sum(col7) FROM t",
        columns=["total"],
        rows=[["1284"]],
        row_count=1,
        metadata={"table": "sheet_1"},
    )
    tabular = FakeTabular(answer)
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
        tabular_query=tabular,
    )
    result = await _execute(
        orchestrator, organization.id, "¿Cuál es el total de la columna 7?"
    )
    structured = [
        r for r in result.flow["cognitive"]["runners"]
        if r["representation"] == "structured"
    ]
    assert structured and structured[0]["status"] == "ok"
    assert tabular.calls == 1


@pytest.mark.asyncio
async def test_shadow_observacion_falla_no_rompe_el_run(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=FakeKnowledgeModel(boom=True),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué relación tiene Category 31 con Record 4?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["entities"] is None
    assert all(
        runner["status"] in {"skipped", "error"} for runner in cognitive["runners"]
    )
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_shadow_expone_signals(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué significa el Byte 105?"
    )
    signals = result.flow["cognitive"]["signals"]
    assert signals["exact_lookup_declared"] is True
    assert signals["entity_resolved"] is None
```

1c. Agregar a `tests/test_jev_preflight.py` (o al final de `test_jev_preflight_flow.py`) un test unitario:

```python
def test_signals_cognitivas_son_opcionales() -> None:
    from src.decision.preflight import DeterministicSignals

    base = DeterministicSignals()
    assert base.entity_resolved is None
    assert base.exact_lookup_declared is None
    payload = base.to_public_dict()
    assert payload["entity_resolved"] is None
    assert payload["exact_lookup_declared"] is None
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py -q`
Expected: FAIL (`AttributeError: 'CognitiveTurn' object has no attribute 'entities'` / `TypeError: _build() got an unexpected keyword argument 'knowledge_model'` / `KeyError: 'signals'`).

- [ ] **Step 3: Implementar**

3a. `src/runtime/cognitive_state.py`: agregar imports TYPE_CHECKING y campos:

```python
if TYPE_CHECKING:
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.representation_runners import RunnerResult
```

```python
@dataclass
class CognitiveTurn:
    query: str
    plan: CognitivePlan | None = None
    strategy: KnowledgeStrategy | None = None
    entities: "EntityResolution | None" = None
    runners: tuple["RunnerResult", ...] = ()
    notes: list[dict] = field(default_factory=list)

    def jev_signals(self) -> dict:
        """Señales determinísticas para el preflight JEV (C2: se exponen, no deciden)."""
        from src.runtime.cognitive_plan import KnowledgeNeed

        exact = bool(self.plan and KnowledgeNeed.EXACT_LOOKUP in self.plan.needs)
        entity_resolved: bool | None = None
        if self.entities is not None and self.entities.mentions:
            entity_resolved = all(
                item.status == "resolved" for item in self.entities.mentions
            )
        return {
            "exact_lookup_declared": exact,
            "entity_resolved": entity_resolved,
        }

    def to_public_dict(self) -> dict:
        payload: dict = {
            "mode": cognitive_runtime_mode(),
            "notes": list(self.notes),
            "signals": self.jev_signals(),
        }
        if self.plan is not None:
            payload["plan"] = self.plan.to_public_dict()
        if self.strategy is not None:
            payload["strategy"] = self.strategy.to_public_dict()
        payload["entities"] = (
            self.entities.to_public_dict() if self.entities is not None else None
        )
        payload["runners"] = [
            runner.to_public_dict() for runner in self.runners
        ]
        return payload
```

3b. `src/agents/runtime/orchestrator.py`:

- Constructor: agregar `knowledge_model: object | None = None,` al final de la firma y `self._knowledge_model = knowledge_model` junto a `self._preflight_hook`.
- Imports: agregar bajo `if TYPE_CHECKING:` en el módulo:

  ```python
  if TYPE_CHECKING:
      from src.runtime.representation_runners import RepresentationRunner
  ```

  Nada eager: los runners se importan lazy dentro de los métodos.
- En `execute`, **inmediatamente después** del bloque `if cognitive_runtime_mode() != "off": ... except ...` (fuera del try, con `cognitive_turn` ya resuelto), agregar:

```python
        if cognitive_turn is not None:
            await self._observe_cognitive(
                cognitive_turn,
                organization_id=organization_id,
                user_id=user_id,
                role=role,
            )
```

- Métodos nuevos (cerca de `_run_knowledge_retrieve`):

```python
    def _build_cognitive_runners(self) -> tuple[RepresentationRunner, ...]:
        """Runners disponibles según dependencias inyectadas (C2: observación)."""
        runners: list[object] = []
        if self._knowledge_model is not None:
            from src.runtime.graph_runner import GraphRunner
            from src.runtime.temporal_runner import TemporalRunner

            runners.append(GraphRunner(self._knowledge_model))
            runners.append(TemporalRunner(self._knowledge_model))
        if self._tabular_query is not None:
            from src.runtime.tabular_runner import TabularRunner

            runners.append(TabularRunner(self._tabular_query))
        return tuple(runners)

    async def _observe_cognitive(
        self,
        turn: CognitiveTurn,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str,
    ) -> None:
        """Resuelve entidades y corre runners declarados. Nunca lanza (C2)."""
        try:
            from src.runtime.entity_resolution import resolve_mentions

            mentions = (
                tuple(turn.strategy.entity_mentions) if turn.strategy else ()
            )
            if mentions and self._knowledge_model is not None:
                turn.entities = await resolve_mentions(
                    self._knowledge_model, organization_id, mentions
                )
        except Exception as exc:  # noqa: BLE001 — observación fail-soft
            logger.warning(
                "Cognitive entity resolution failed", error=str(exc)[:200]
            )
        try:
            runners = self._build_cognitive_runners()
            if not runners or turn.strategy is None:
                return
            from src.runtime.representation_runners import (
                RunnerContext,
                run_representations,
            )

            declared = tuple(
                item.representation for item in turn.strategy.representations
            )
            wanted = tuple(
                rep for rep in declared if rep in {"structured", "graph", "temporal"}
            )
            if not wanted:
                return
            ctx = RunnerContext(
                query=turn.query,
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                strategy=turn.strategy,
                entities=turn.entities,
            )
            turn.runners = await run_representations(
                ctx, runners, representations=wanted
            )
        except Exception as exc:  # noqa: BLE001 — observación fail-soft
            logger.warning("Cognitive runners failed", error=str(exc)[:200])
```

- `_preflight_gate`: agregar parámetro keyword-only `cognitive_signals: dict | None = None,` y en `DeterministicSignals(...)`:

```python
            entity_resolved=(
                None
                if not cognitive_signals
                else cognitive_signals.get("entity_resolved")
            ),
            exact_lookup_declared=(
                None
                if not cognitive_signals
                else cognitive_signals.get("exact_lookup_declared")
            ),
```

- Ambos call sites (líneas ~3101 y ~3147) agregan:

```python
                            cognitive_signals=(
                                cognitive_turn.jev_signals()
                                if cognitive_turn is not None
                                else None
                            ),
```

3c. `src/decision/preflight.py` `DeterministicSignals`: campos nuevos con default `None` y en la tupla de `to_public_dict`:

```python
    entity_resolved: bool | None = None
    exact_lookup_declared: bool | None = None
```

3d. `src/api/deps.py`, en `RAGOrchestrator(...)`:

```python
            knowledge_model=get_knowledge_model_service(),
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py -q`
Expected: todos PASS (state 6 tests, shadow 13 tests; ningún fallo).

- [ ] **Step 5: Regresión**

Run:

```bash
pytest tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_jev_preflight.py tests/test_jev_preflight_flow.py tests/test_architecture.py -q
ruff check src tests
```

Expected: PASS + `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add src/runtime/cognitive_state.py src/agents/runtime/orchestrator.py src/decision/preflight.py src/api/deps.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_jev_preflight.py
git commit -m "feat(cognitive): observación multi-representación y señales JEV (C2)"
```

---

### Task 7: Docs + estado de fase + verificación final

**Files:**
- Modify: `docs/architecture/cognitive-runtime.md` (fila C2 de §15)
- Test: suite completa de C1+C2

- [ ] **Step 1: Marcar C2**

En `docs/architecture/cognitive-runtime.md` §15, fila C2: modo `shadow (default off) — **shipped**` y Plan: link a `docs/superpowers/plans/2026-10-01-cognitive-runtime-c2-representations.md`.

- [ ] **Step 2: Verificación final**

```bash
pytest tests/test_knowledge_model_lookup.py tests/test_entity_resolution_runtime.py tests/test_representation_runners.py tests/test_graph_temporal_runners.py tests/test_tabular_runner.py tests/test_cognitive_plan.py tests/test_knowledge_strategy.py tests/test_cognitive_state.py tests/test_cognitive_runtime_shadow.py tests/test_architecture.py tests/test_jev_preflight.py tests/test_jev_preflight_flow.py tests/test_retrieval_planner.py -q
ruff check src tests
```

Expected: todos PASS + `All checks passed!`.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/cognitive-runtime.md
git commit -m "docs(cognitive): C2 observación multi-representación shipped"
```

---

## Criterios de salida C2

- [ ] `off`: runtime intacto; cero llamadas nuevas a lookup/runners.
- [ ] `shadow`: `flow["cognitive"]` con `entities` (resolución canónica exacta/alias/ambigua/no resuelta), `runners` (structured/graph/temporal solo si la strategy los declara) y `signals` (`entity_resolved`, `exact_lookup_declared`).
- [ ] Observación fail-soft: error/timeout/vacío se trazan y no rompen el run; `n` de llamadas LLM no cambia.
- [ ] Las señales llegan a `DeterministicSignals` sin alterar políticas de decisión (consumo en C4).
- [ ] Lecturas canónicas org-scoped con test de aislamiento cross-tenant.
- [ ] Sin dependencias, migraciones ni cambios de contrato API; `ruff check src tests` limpio.
