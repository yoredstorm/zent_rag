# Cognitive Runtime C7 — KnowledgeScope + RBAC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introducir un scope de conocimiento declarativo (`knowledge_scope`) para agentes, workflows y MCP, con enforcement **pre-retrieval** y lectura canónica scoped: el scope **estrecha, nunca amplía**, y sin scope el comportamiento es el de hoy.

**Architecture:** Dominio puro `KnowledgeScope` (`src/core/domain/knowledge_scope.py`) con parse fail-soft y `narrow()` (intersección por campo; vacío = sin restricción). Enforcement: `StructuredRetriever` reenvía `source_ids` (hoy los ignora); `AgentRuntime` resuelve scope efectivo (scope ∩ legacy) y `SearchKnowledgeTool` lo aplica; lecturas canónicas (`find_objects_by_names`/`lookup_aliases`/`object_edges`/`object_assertions`) aceptan `source_ids`; workflows (`kb_query`) y MCP (`search_knowledge`) propagan `source_ids`. RBAC existente se mantiene: el scope solo recorta.

**Tech Stack:** Python del repo, pytest, Postgres/Qdrant ya existentes (tests con fakes), ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` §9 (W4), fase C7 §15.

## Global Constraints

- Sin scope: comportamiento actual intacto (cero filtros nuevos). El scope **nunca amplía** (intersección).
- Enforcement **pre-retrieval** (filtros en Qdrant/SQL/canónico), nunca post-LLM.
- Fail-soft: scope inválido se descarta campo a campo; nunca 500.
- Sin dependencias nuevas, sin migraciones, sin cambios de contrato API salvo campos **aditivos** opcionales (`knowledge_scope` en AgentConfig, `source_ids` en MCP, `source_ids` en nodo kb_query).
- Código/comentarios español; tests `tests/test_*.py`. Cada tarea: tests verdes, ruff, commit. Branch `feat/cognitive-runtime-c7` desde `master`.

---

### Task 1: Dominio `KnowledgeScope`

**Files:**
- Create: `src/core/domain/knowledge_scope.py`
- Test: `tests/test_knowledge_scope.py`

**Interfaces:**
- Produce:
  - `KnowledgeScope(source_ids=(), knowledge_base_ids=(), workspace_ids=(), canonical_kinds=(), domains=(), tags=())` frozen.
  - `from_config(config: Mapping | None) -> KnowledgeScope` (lee `knowledge_scope`; si falta, deriva de `source_ids`/`knowledge_base_ids` legacy; parse fail-soft).
  - `narrow(base, other) -> KnowledgeScope` (intersección por campo; vacío = sin restricción).
  - `is_empty`, `to_public_dict`.

- [ ] **Step 1: Crear branch y baseline**

```bash
git checkout -b feat/cognitive-runtime-c7
pytest tests/test_agent_source_ids.py tests/test_retrieval_engine.py -q
```

- [ ] **Step 2: Test que falla**

`tests/test_knowledge_scope.py`:

```python
# =============================================================================
# KnowledgeScope — scope declarativo, estrecha nunca amplía (C7).
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from src.core.domain.knowledge_scope import KnowledgeScope, from_config, narrow


def test_from_config_lee_scope_y_legacy() -> None:
    org = uuid4()
    scope = from_config(
        {
            "knowledge_scope": {
                "source_ids": [str(org)],
                "knowledge_base_ids": [str(uuid4())],
                "workspace_ids": [str(uuid4())],
                "canonical_kinds": ["rule", "entity"],
                "domains": ["pricing"],
                "tags": ["atpco"],
            }
        }
    )
    assert scope.source_ids == (org,)
    assert scope.canonical_kinds == ("rule", "entity")
    assert scope.domains == ("pricing",)

    legacy = from_config({"source_ids": [str(org)], "knowledge_base_ids": [str(uuid4())]})
    assert legacy.source_ids == (org,)


def test_parse_fail_soft_descarta_invalidos() -> None:
    scope = from_config(
        {
            "knowledge_scope": {
                "source_ids": ["no-uuid", str(uuid4()), 7],
                "canonical_kinds": ["rule", "", 9, "rule"],
                "domains": "pricing",
            }
        }
    )
    assert len(scope.source_ids) == 1
    assert scope.canonical_kinds == ("rule",)
    assert scope.domains == ()


def test_narrow_intersecta_y_vacio_no_restringe() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    base = KnowledgeScope(source_ids=(a, b), canonical_kinds=("rule", "entity"))
    other = KnowledgeScope(source_ids=(b, c), canonical_kinds=("entity",))
    result = narrow(base, other)
    assert result.source_ids == (b,)
    assert result.canonical_kinds == ("entity",)

    assert narrow(KnowledgeScope(), base).source_ids == (a, b)
    assert narrow(base, KnowledgeScope()).source_ids == (a, b)
    assert narrow(KnowledgeScope(source_ids=(a,)), KnowledgeScope(source_ids=(b,))).source_ids == ()


def test_payload_publico() -> None:
    scope = KnowledgeScope(source_ids=(uuid4(),), tags=("atpco",))
    payload = scope.to_public_dict()
    assert payload["source_ids"]
    assert payload["tags"] == ["atpco"]
    assert payload["knowledge_base_ids"] == []
```

- [ ] **Step 3: Ver fallar** → `ModuleNotFoundError`.

- [ ] **Step 4: Implementar** `src/core/domain/knowledge_scope.py`:

```python
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
        text = str(item or "").strip()[: _MAX_LEN]
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
```

- [ ] **Step 5: Pasa** → `4 passed`. Lint + commit `feat(cognitive): dominio knowledge scope (C7)`.

---

### Task 2: `StructuredRetriever` reenvía `source_ids`

**Files:**
- Modify: `src/rag/retrieval/structured.py`
- Test: `tests/test_structured_retriever.py`

**Interfaces:**
- Consume: `RetrievalQuery.source_ids`.
- Produce: los canales `search_hybrid`/`vector.search`/`search_sparse` y la expansión de parents reciben `source_ids` cuando la query los trae (hoy se ignoran).

- [ ] **Step 1: Test que falla** (agregar a `tests/test_structured_retriever.py`, usando el `FakeVectorStore` del archivo que graba kwargs):

```python
@pytest.mark.asyncio
async def test_structured_retriever_reenvia_source_ids() -> None:
    source_id = uuid4()
    store = FakeVectorStore(...)  # el fake del archivo
    retriever = StructuredRetriever(vector_store=store, lexical_store=None)
    query = RetrievalQuery(
        query="q",
        organization_id=uuid4(),
        role="admin",
        source_ids=[source_id],
        query_embedding=[0.1] * 8,
    )
    await retriever.retrieve(query)
    calls = [call for call in store.calls if call.get("source_ids")]
    assert calls and calls[0]["source_ids"] == [source_id]
```

(Ajustar al fake real del archivo; si graba distinto, assertar sobre lo que grabe.)

- [ ] **Step 2: Ver fallar.**

- [ ] **Step 3: Implementar**: en `_candidates` (los 3 canales) y `_expand_parents`, agregar `**({"source_ids": list(query.source_ids)} if query.source_ids else {})` a las llamadas al store (mismo patrón que `workspace_id`). Revisar `_expand_parents`: si fetch por ids no acepta source_ids, filtrar post-fetch por payload `metadata.source_id` cuando el scope venga.

- [ ] **Step 4: Pasa** (archivo completo). Lint + commit `fix(retrieval): structured retriever reenvía source_ids (C7)`.

---

### Task 3: Scope en agentes (config + runtime + tool)

**Files:**
- Modify: `src/api/routes/agents.py` (`AgentConfig.knowledge_scope` + validación en `_apply_source_config`)
- Modify: `src/agents/runtime/agent_runtime.py` (scope efectivo)
- Modify: `src/agents/tools/tools_builtin.py` (`SearchKnowledgeTool`: workspace del scope)
- Test: `tests/test_agent_source_ids.py`

**Interfaces:**
- Consume: `KnowledgeScope`, `from_config`, `narrow`.
- Produce: `AgentConfig.knowledge_scope: dict | None = None`; `config_json["knowledge_scope"]` normalizado; `org_config["knowledge_workspace_ids"]`; `SearchKnowledgeTool` usa workspace único del scope.

- [ ] **Step 1: Tests que fallan** (agregar a `tests/test_agent_source_ids.py`):
  - API: crear agente con `knowledge_scope` válido → `config_json["knowledge_scope"]["source_ids"]` presente; fuente foránea dentro del scope → 404 (mismo helper que legacy).
  - Runtime: agente con `knowledge_scope.source_ids=[s]` y legacy `source_ids=[s2]` → el retriever capturado recibe `[s]` ∩ `[s2]` (si difieren → lista vacía = deny total? Definir: intersección vacía de dos no-vacíos = **deny** (sin fuentes) y el tool devuelve vacío, no busca global). Test: mismo id en ambos → pasa.
  - Tool: scope con `workspace_ids=[w]` → `RetrievalQuery.workspace_id == w`.

- [ ] **Step 2: Ver fallar.**

- [ ] **Step 3: Implementar**:
  - `AgentConfig`: `knowledge_scope: dict[str, Any] | None = None` + caps (delegar validación al dominio en `_apply_source_config`: parse → si `is_empty` y venía data inválida → warning; validar ownership de `source_ids`/`knowledge_base_ids` del scope con el mismo código legacy y descartar foráneos; persistir `config_json["knowledge_scope"] = scope.to_public_dict()` cuando no vacío).
  - `AgentRuntime` (junto a 1541-1547): `scope = from_config(config_json)`; `legacy = KnowledgeScope(source_ids=..., knowledge_base_ids=...)`; `effective = narrow(scope, legacy) if (scope.source_ids or legacy.source_ids) else scope`; `org_config["source_ids"] = [str(s) for s in effective.source_ids]`; idem kb; `org_config["knowledge_workspace_ids"] = [...]`.
    **Regla deny**: si ambos lados traen source_ids no vacíos y la intersección queda vacía → `source_ids=[]` (el tool no busca; no cae a global).
  - `SearchKnowledgeTool`: leer `workspace_ids`; si len==1 → `workspace_id=...` en `_build_query`; si >1 → no soportado, no setear (documentado).
  - `_agent_source_types` sin cambios.

- [ ] **Step 4: Pasa** (`tests/test_agent_source_ids.py tests/test_agent_security.py tests/test_search_knowledge_tool.py`). Lint + commit `feat(cognitive): scope de conocimiento en agentes (C7)`.

---

### Task 4: Lecturas canónicas scoped

**Files:**
- Modify: `src/platform/knowledge_model/repository.py` + `service.py` (`source_ids` opcional)
- Modify: `src/runtime/entity_resolution.py` (`resolve_mentions(..., source_ids=None)`)
- Modify: `src/runtime/representation_runners.py` (`RunnerContext.source_ids`)
- Modify: `src/runtime/graph_runner.py` / `temporal_runner.py` (pasar `source_ids`)
- Tests: `tests/test_knowledge_model_lookup.py`, `tests/test_entity_resolution_runtime.py`, `tests/test_graph_temporal_runners.py`

**Interfaces:**
- Regla NULL: un objeto/alias/edge/assertion sin `source_id` cuenta como org-level (permitido); con `source_ids` presente, `source_id = ANY(...) OR source_id IS NULL`.
- `resolve_mentions(lookup, organization_id, mentions, *, per_mention_limit=5, source_ids=None)`.
- `RunnerContext(..., source_ids: tuple[UUID, ...] = ())`.

- [ ] **Step 1: Tests que fallan**:
  - DB: dos entidades, una con `source_id=s1`, otra `s2`; `find_objects_by_names(..., source_ids=[s1])` devuelve solo la de s1 (la NULL también pasa). Idem `lookup_aliases` (filtra por `o.source_id`).
  - Unit resolver: `FakeLookup` registra `source_ids` recibido.
  - Runners: `FakeEdges` registra `source_ids` cuando ctx los trae.

- [ ] **Step 2: Ver fallar.**

- [ ] **Step 3: Implementar**:
  - Repo: en cada método agregar `source_ids: tuple[UUID, ...] | None = None` y, si viene no vacío, `AND (x.source_id = ANY(:source_ids) OR x.source_id IS NULL)` (param `source_ids=[...]`). En `find_objects_by_names`/`lookup_aliases` usar `o.source_id`; en `object_edges`/`object_assertions` usar `e.source_id`/assertion `source_id`.
  - Service passthroughs con `source_ids=None`.
  - `resolve_mentions`: pasar `source_ids` a ambas llamadas.
  - `RunnerContext.source_ids`; `GraphRunner.run` → `object_edges(..., source_ids=ctx.source_ids or None)`; `TemporalRunner` idem.
  - Orquestador `_observe_cognitive`: `source_ids=()` por ahora (sin scope en el path plano); el executor/workflows lo usarán cuando exista.

- [ ] **Step 4: Pasa** (4 archivos). Lint + commit `feat(cognitive): lecturas canónicas scoped por fuente (C7)`.

---

### Task 5: Workflows + MCP

**Files:**
- Modify: `src/platform/workflows/nodes.py` (`kb_query` config `source_ids` → `_kb_retrieve`; `_cognitive_scope` ya lo lee)
- Modify: `src/platform/cognitive/executor.py` (`_handle_retrieval` reenvía `source_ids` del scope)
- Modify: `src/mcp_server/tools.py` (`search_knowledge` acepta `source_ids`)
- Tests: `tests/test_workflow_knowledge_modes.py`, `tests/test_cognitive_execution.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Nodo `kb_query`: `source_ids: list[str]` opcional en config; `_kb_retrieve` setea `RetrievalQuery.source_ids` (UUIDs válidos; inválidos se descartan).
- Executor: `RetrievalQuery(..., source_ids=list(state.scope.source_ids))` cuando el scope los trae.
- MCP: `search_knowledge(query, top_k, role, filters, knowledge_base_id, source_ids=None)`; UUIDs inválidos se descartan.

- [ ] **Step 1: Tests que fallan**:
  - Workflow: `_FakeStructuredRetriever` captura `RetrievalQuery`; nodo con `source_ids=[s]` → query.source_ids == [s].
  - Executor: `FakeRetriever` (ya existe) captura `source_ids` del scope.
  - MCP: tool con `source_ids` → `FakeRetriever` lo recibe.

- [ ] **Step 2: Ver fallar.**

- [ ] **Step 3: Implementar** (edits directos por archivo, siguiendo el patrón de los fakes existentes). En MCP documentar que el scope MCP solo puede **recortar** (parámetro explícito del caller autorizado); no se amplía nada.

- [ ] **Step 4: Pasa** (3 archivos). Lint + commit `feat(cognitive): scope en workflows y MCP (C7)`.

---

### Task 6: Docs + verificación final

**Files:**
- Modify: `docs/architecture/cognitive-runtime.md` (§15 fila C7 + nota de alcance: workspaces múltiples y tags se parsean pero no se enforce hoy; canónico NULL = org-level).

- [ ] **Step 1: Docs** (fila C7 shipped + link del plan + nota).
- [ ] **Step 2: Verificación**:

```bash
pytest tests/test_knowledge_scope.py tests/test_structured_retriever.py tests/test_agent_source_ids.py tests/test_agent_security.py tests/test_search_knowledge_tool.py tests/test_knowledge_model_lookup.py tests/test_entity_resolution_runtime.py tests/test_graph_temporal_runners.py tests/test_workflow_knowledge_modes.py tests/test_cognitive_execution.py tests/test_mcp_server.py tests/test_architecture.py -q
ruff check src tests
```

- [ ] **Step 3: Commit** `docs(cognitive): C7 knowledge scope shipped`.

---

## Criterios de salida C7

- [ ] Sin scope: comportamiento actual intacto (tests viejos verdes; cero filtros nuevos).
- [ ] Scope en agentes/scope legacy/workflows/MCP: `source_ids`/`kb`/workspace(single) llegan al retrieval; `StructuredRetriever` los reenvía; intersección vacía = deny (no cae a búsqueda global).
- [ ] Lecturas canónicas (nombres/alias/edges/assertions) aceptan `source_ids` con regla NULL=org-level.
- [ ] El scope nunca amplía: `narrow` intersecta; RBAC existente manda.
- [ ] Sin dependencias/migraciones; `ruff check src tests` limpio.
