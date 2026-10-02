# Cognitive Runtime C8 — Knowledge Events + Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emitir eventos de conocimiento del brief (NEW_ENTITY, NEW_RULE, RULE_CHANGED, CONFLICT_DETECTED, SOURCE_SUPERSEDED, KNOWLEDGE_GAP_DETECTED, HIGH_IMPACT_CHANGE) desde compiler/materializer, durables en `knowledge_events` + bus Redis `rag:events`, y aceptarlos como triggers de workflows con permisos existentes. Cero acciones automáticas sin trigger configurado.

**Architecture:** Dominio puro `KnowledgeEventType`; un emisor `KnowledgeSystemEventEmitter` que reusa `KnowledgeEventEmitter` (durable `knowledge_events` + publish `knowledge.<type>`, gate realtime por `RAG_KNOWLEDGE_LIVE_EVENTS_ENABLED`) — **sin migración** (la 137 está tomada por otra rama en curso); el pipeline del compiler emite NEW_ENTITY/NEW_RULE/RULE_CHANGED/CONFLICT_DETECTED; el materializer emite KNOWLEDGE_GAP_DETECTED/HIGH_IMPACT_CHANGE (score determinístico por impacto) y el engine emite SOURCE_SUPERSEDED al actualizar versión de documento; el registry de workflows registra los 7 tipos.

**Tech Stack:** Python del repo, pytest, Postgres/Redis ya existentes (tests con fakes), ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` §10 (W5), fase C8 §15.

## Global Constraints

- Sin migraciones (reuso `knowledge_events` 094 + bus `rag:events`). Sin dependencias nuevas.
- Emisión **fail-soft**: nunca rompe ingesta ni materialización.
- `HIGH_IMPACT_CHANGE` es determinístico (conteos/umbrales), nunca LLM.
- Eventos se emiten por default; **cero acciones automáticas** sin trigger + permisos (`workflow_events:subscribe` existente).
- Payload mínimo: ids (`object_id`/`rule_key`/`source_id`/`document_id`), `diff` resumido, `confidence`, `requires_review`.
- Código/comentarios español; tests `tests/test_*.py`. Cada tarea: tests verdes, ruff explícito, commit. Branch `feat/cognitive-runtime-c8` (worktree `.worktrees/cognitive-c8`).

---

### Task 1: Dominio de eventos de conocimiento

**Files:**
- Create: `src/core/domain/knowledge_events.py`
- Test: `tests/test_knowledge_events.py`

**Interfaces:**
- `KnowledgeEventType` (StrEnum): `NEW_ENTITY="new_entity"`, `NEW_RULE="new_rule"`, `RULE_CHANGED="rule_changed"`, `CONFLICT_DETECTED="conflict_detected"`, `SOURCE_SUPERSEDED="source_superseded"`, `KNOWLEDGE_GAP_DETECTED="knowledge_gap_detected"`, `HIGH_IMPACT_CHANGE="high_impact_change"`.
- `KnowledgeSystemEvent(type, organization_id, payload, confidence=None, requires_review=False, source_id=None, document_id=None, object_id=None, rule_key=None)` frozen + `event_name` (`knowledge.<type>`) + `to_public_dict()`.
- `requires_review` default True para RULE_CHANGED/CONFLICT_DETECTED/SOURCE_SUPERSEDED/KNOWLEDGE_GAP_DETECTED/HIGH_IMPACT_CHANGE; False para NEW_ENTITY/NEW_RULE (vía `default_requires_review(type)`).

- [ ] **Step 1: branch + baseline**

```bash
git checkout feat/cognitive-runtime-c8
pytest tests/test_knowledge_compiler.py -q
```

- [ ] **Step 2: test que falla** (`tests/test_knowledge_events.py`): tipos exactos (7), `event_name` con prefijo `knowledge.`, `requires_review` por tipo, payload serializable, fail-soft con payload None.
- [ ] **Step 3: ver fallar** → `ModuleNotFoundError`.
- [ ] **Step 4: implementar** el módulo puro (dataclass frozen + enum + helper `default_requires_review`; `to_public_dict` con `type`, `event`, ids no nulos, `payload`, `confidence`, `requires_review`).
- [ ] **Step 5: pasa** (≥5 tests). Lint + commit `feat(cognitive): dominio de knowledge events (C8)`.

---

### Task 2: Emisor durable + bus

**Files:**
- Create: `src/platform/knowledge_events/__init__.py`, `src/platform/knowledge_events/emitter.py`
- Test: `tests/test_knowledge_events_emitter.py`

**Interfaces:**
- Consume: `KnowledgeEventEmitter` (`src/platform/knowledge_learning/events.py`, `emit(organization_id, type, ..., payload=...)` durable+publish) y `KnowledgeSystemEvent`.
- Produce: `KnowledgeSystemEventEmitter(inner: object)` con `async emit(event: KnowledgeSystemEvent) -> None`:
  - `await inner.emit(organization_id=event.organization_id, type=event.event_name, category="knowledge", severity=..., message=..., payload=event.to_public_dict(), source_id=..., ...)` (ajustar a la firma real de `emit`; el implementer la lee).
  - Fail-soft: excepción → warning, nunca propaga.
  - No publica si `RAG_KNOWLEDGE_LIVE_EVENTS_ENABLED=false` (ya lo maneja el inner).

- [ ] **Step 1: test que falla** con `FakeInner` que registra kwargs: emite `knowledge.new_rule`, payload con `requires_review`, fallo del inner no propaga.
- [ ] **Step 2: ver fallar.**
- [ ] **Step 3: implementar** (leer la firma real de `KnowledgeEventEmitter.emit` y mapear; si `category`/`severity` no son parámetros, van dentro del payload).
- [ ] **Step 4: pasa.** Lint + commit `feat(cognitive): emisor de knowledge events (C8)`.

---

### Task 3: Emisión desde el compiler

**Files:**
- Modify: `src/knowledge/compiler/pipeline.py` (observador: mapear señales existentes a eventos de sistema)
- Modify: `src/knowledge/compiler/store.py` (nuevo `existing_rule_keys(organization_id) -> dict[str, str]` subject→rule_key, Postgres + protocolo)
- Modify: `src/knowledge/engine/service.py` (inyectar el emisor de sistema en el observer del job)
- Test: `tests/test_knowledge_compiler.py`

**Reglas:**
- `ENTITY_DISCOVERED` (known_before=False) → `NEW_ENTITY` (`object_id`, confidence).
- `RULE_DISCOVERED` con `rule_status=="created"` → `NEW_RULE`; si existe OTRA regla con el mismo `subject` y distinto `rule_key` (vía `existing_rule_keys`) → `RULE_CHANGED` (payload `previous_rule_key`, `rule_key`, `subject`, `requires_review=True`).
- `CONFLICT_DETECTED` → `CONFLICT_DETECTED` (payload `conflict_type`, ids).
- Emisión fail-soft, best-effort, sin cambiar el flujo del pipeline; el emisor es opcional (`observer` ya es opcional).

- [ ] **Step 1: tests que fallan** con `FakeCompilerStore` extendido (subject→keys) + `FakeSystemEmitter` que registra eventos: pipeline con entidad nueva/regla nueva/regla cambiada/conflicto emite los 4 tipos; sin emisor no cambia nada.
- [ ] **Step 2: ver fallar.**
- [ ] **Step 3: implementar** (mapear en el observer del engine o dentro de `pipeline`; `existing_rule_keys` con `SELECT DISTINCT subject, rule_key FROM <tabla reglas> WHERE organization_id=:org`; fake en memoria).
- [ ] **Step 4: pasa** (`tests/test_knowledge_compiler.py tests/test_knowledge_v2_ingestion.py`). Lint + commit `feat(cognitive): compiler emite knowledge events (C8)`.

---

### Task 4: Emisión desde materializer y engine

**Files:**
- Modify: `src/platform/knowledge_model/materializer.py` (`_generate_gaps` → `KNOWLEDGE_GAP_DETECTED` por gap nuevo; post-materialización → `HIGH_IMPACT_CHANGE`)
- Modify: `src/knowledge/engine/service.py` (al registrar versión con `change_kind=="updated"` → `SOURCE_SUPERSEDED` con versión previa/actual)
- Modify: `src/core/config.py` (`RAG_KNOWLEDGE_HIGH_IMPACT_MIN_REFS: int = 5` — umbral determinístico)
- Tests: `tests/test_knowledge_model.py`, `tests/test_knowledge_v2_ingestion.py`

**Reglas:**
- `KNOWLEDGE_GAP_DETECTED`: por cada gap **nuevo** (`occurrences==1` tras upsert; si el repo no lo expone, `created` del upsert), cap 10, payload `gap_type/concept/priority`.
- `HIGH_IMPACT_CHANGE`: para reglas/entidades cambiadas (cap 5), `impact = repo.impact(org, object_id)["count"]`; si `impact >= RAG_KNOWLEDGE_HIGH_IMPACT_MIN_REFS` → emitir con `count`, `threshold`, `requires_review=True`.
- `SOURCE_SUPERSEDED`: payload `document_id`, `previous_version`, `current_version`, `change_kind`; emitido solo cuando la versión previa existe y `change_kind=="updated"`.

- [ ] **Step 1: tests que fallan** con emisor fake: gap nuevo emite 1 evento; impacto alto emite HIGH_IMPACT_CHANGE (y bajo no); versión actualizada emite SOURCE_SUPERSEDED.
- [ ] **Step 2: ver fallar.**
- [ ] **Step 3: implementar** (el materializer ya tiene `_emit_event` de learning: inyectar el emisor de sistema opcional en su constructor; engine: hook donde registra versiones).
- [ ] **Step 4: pasa.** Lint + commit `feat(cognitive): materializer y engine emiten knowledge events (C8)`.

---

### Task 5: Triggers de workflows

**Files:**
- Modify: `src/platform/workflows/event_registry.py` (7 tipos, categoría knowledge; `knowledge.changed` queda deprecado pero registrado)
- Test: `tests/test_workflow_graph.py` o `tests/test_living_workflows.py`

**Reglas:**
- Los 7 `knowledge.<tipo>` registrados → `create_event_trigger` los acepta y `list_catalog` los muestra.
- `dispatch_event_to_workflows` con un evento `knowledge.new_rule` dispara el workflow con trigger configurado (test con runner fake).
- Sin trigger configurado: no corre nada (test).

- [ ] **Step 1: tests que fallan** (registry contiene los 7; trigger aceptado; dispatch con fake).
- [ ] **Step 2: ver fallar.**
- [ ] **Step 3: implementar** (entradas en `_EVENTS` con `category="knowledge"`, descripción y payload esperado).
- [ ] **Step 4: pasa** (`tests/test_workflow_graph.py tests/test_living_workflows.py`). Lint + commit `feat(cognitive): triggers de knowledge events en workflows (C8)`.

---

### Task 6: Docs + verificación final

**Files:**
- Modify: `docs/architecture/cognitive-runtime.md` (§15 fila C8 + nota: durable vía `knowledge_events`, bus `knowledge.<tipo>`, HIGH_IMPACT umbral `RAG_KNOWLEDGE_HIGH_IMPACT_MIN_REFS`, sin migración nueva).

- [ ] **Step 1: docs** (fila C8 shipped + link plan).
- [ ] **Step 2: verificación**:

```bash
pytest tests/test_knowledge_events.py tests/test_knowledge_events_emitter.py tests/test_knowledge_compiler.py tests/test_knowledge_model.py tests/test_knowledge_v2_ingestion.py tests/test_workflow_graph.py tests/test_living_workflows.py tests/test_knowledge_sessions.py tests/test_knowledge_learning.py tests/test_architecture.py -q
ruff check src/core/domain/knowledge_events.py src/platform/knowledge_events src/knowledge/compiler/pipeline.py src/knowledge/compiler/store.py src/platform/knowledge_model/materializer.py src/knowledge/engine/service.py src/platform/workflows/event_registry.py tests/test_knowledge_events.py tests/test_knowledge_events_emitter.py
```

- [ ] **Step 3: commit** `docs(cognitive): C8 knowledge events shipped`.

---

## Criterios de salida C8

- [ ] Los 7 tipos existen y se emiten desde compiler/materializer/engine (tests con fakes).
- [ ] Durable en `knowledge_events` + bus `knowledge.<tipo>` (realtime gateado por `RAG_KNOWLEDGE_LIVE_EVENTS_ENABLED`); sin migración nueva.
- [ ] `HIGH_IMPACT_CHANGE` determinístico con umbral configurable.
- [ ] Workflows aceptan los 7 tipos; sin trigger configurado no corre nada; permisos existentes.
- [ ] Emisión fail-soft; sin deps; `ruff` limpio en archivos C8.
