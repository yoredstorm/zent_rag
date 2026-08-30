# Fase 05 — AI Agent Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Vender “Create your AI Agent”, no “RAG”: un builder con instructions, knowledge, tools, model, security, limits, analytics y playground, reutilizando el Agent Runtime y `POST /api/v1/agents/{id}/run`.

**Architecture:** Profundizar `agents` + `agents.config_json` (ya existe). No segundo runtime. UI: rutas `/agents/:id` con tabs. Entitlement `max_agents` (Fase 03) ya enforca el create. Playground llama run/stream existente.

**Tech Stack:** React, FastAPI, `src/agents/runtime/`, SSE existente, pytest.

## Global Constraints

- No reescribir orchestrator / tools / SQL Expert.
- Identidad de tenant solo del Bearer.
- API `1.0.0` additive only.
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- Migraciones: evitar si `config_json` basta; si hace falta `knowledge_base_ids` column, additive.
- No embed widget (Fase 06). No gateway router (Fase 10) salvo selector de `model` string ya soportado.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations
7. Add tests
8. Update API
9. Update frontend
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- Tabla `agents`: `system_prompt`, `tools JSONB`, `model`, `config_json`, `is_active` ([`05-platform-resources.sql`](../../../src/infrastructure/db_init/05-platform-resources.sql)).
- API: [`src/api/routes/agents.py`](../../../src/api/routes/agents.py) — CRUD; [`agent_runs.py`](../../../src/api/routes/agent_runs.py) — run, stream, traces.
- Runtime: [`src/agents/runtime/`](../../../src/agents/runtime/).
- Tools: `rag`, SQL expert, guards en [`src/agents/tools/`](../../../src/agents/tools/).
- Portal: [`portal/src/pages/Agents.tsx`](../../../portal/src/pages/Agents.tsx) — create con `tools: ["rag"]` hardcoded.
- Usage: `GET /api/v1/billing/usage/agents`.
- Docs: [`docs/developers/agents.md`](../../developers/agents.md).
- Tests: `tests/test_agent_api.py`, `tests/test_agent_security.py`.

## Gaps

- UI no edita prompt, tools, KBs, temperature, tone.
- Create ignora knowledge.
- Playground no existe en portal (el chat genérico no es el agente).
- Analytics de un agente no están en su ficha.

## Contrato `config_json` (congelar)

```python
{
  "purpose": str,
  "temperature": float,          # 0–1
  "tone": str,                   # professional | friendly | concise
  "knowledge_base_ids": [str],   # UUIDs de KBs del mismo org
  "limits": {
    "max_steps": int,
    "max_tokens": int,
    "max_cost_usd": float
  },
  "security": {
    "sql_enabled": bool,
    "api_calls_enabled": bool
  }
}
```

Tools allowlist existente: alinear checkboxes UI con tools reales del registry (inspeccionar `src/agents/tools`). **No** inventar `API Calls` si no hay tool; si `call_api` existe, el checkbox lo enciende y el entitlement puede limitar después.

Runtime: al `run`, el orchestrator debe **usar** `system_prompt`, `model`, `tools`, y filtrar retrieval a `knowledge_base_ids` si el retrieval ya soporta KB filter. Si hoy el RAG es org-wide, añadir filtro KB **additive** en retrieval (test de que KB de otra org 404).

---

### Task 1: Persistencia y run respectan config

**Files:**

- Modify: `CreateAgentRequest` / `UpdateAgentRequest` en `agents.py` — campos planos **o** `config` dict validado Pydantic
- Modify: orchestrator / retrieval para `knowledge_base_ids`
- Test: `tests/test_agent_api.py`, `tests/test_agent_security.py`

**Interfaces:**

```python
class AgentConfig(BaseModel):
    purpose: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=1)
    tone: str = Field(default="professional")
    knowledge_base_ids: list[UUID] = []
    limits: dict | None = None
    security: dict | None = None
```

GET agent incluye `config` parseado (no string crudo solamente).

- [ ] **Step 1: Test** update tools `["rag"]` sin SQL; run no ejecuta SQL Expert.

- [ ] **Step 2: Test** `knowledge_base_ids` de otra org → 400/404 en update.

- [ ] **Step 3: Test** temperature se pasa al LLM provider (mock).

- [ ] **Step 4: Implementar** mínimo. Reusar guards de tools.

- [ ] **Step 5: pytest** agent_* -q — PASS.

---

### Task 2: Builder UI

**Files:**

- Create: `portal/src/pages/AgentBuilder.tsx` (o carpeta `portal/src/pages/agents/`)
- Modify: `Agents.tsx` — lista + CTA “Crear agente” + link a `/agents/:id`
- Modify: `App.tsx` — `/agents/:id` tabs:

```
Instructions | Knowledge | Tools | Model | Security | Limits | Analytics | Playground
```

Create wizard (puede ser modal o `/agents/new`): Name, Purpose, knowledge checkboxes (KBs del tenant), capabilities (semantic search / SQL), model, temperature, tone.

- [ ] **Step 1: Lista** deja de ser el único CRUD; delete/active quedan.

- [ ] **Step 2: Playground** — input + `POST /api/v1/agents/{id}/run/stream` (mismo patrón que Chat SSE). No usar solo `/rag/query`.

- [ ] **Step 3: Analytics tab** — `GET /billing/usage/agents` filtrado al id.

- [ ] **Step 4: Entitlement** — si `max_agents` alcanzado, CTA create explica el plan.

---

### Task 3: Docs

- [`docs/developers/agents.md`](../../developers/agents.md) — config_json schema, playground, KB filter.
- Bruno collection si el repo ya tiene Agents (añadir update config).

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_agent_api.py tests/test_agent_security.py tests/test_entitlements.py tests/test_tenant_isolation.py -q
```

Expected: PASS

---

## Criterios de aceptación

- Un tenant crea “Pharmacy Assistant” con KBs Products+Inventory, tools RAG+SQL, model, temperature 0.2, y prueba en playground.
- El chat genérico `/chat` no se rompe.
- Un agente no lee KBs de otro tenant.
- Límites de plan siguen aplicando.

## Fuera de alcance

Marketplace de agentes, multi-agente planner, embed (06), custom fine-tunes.

## Riesgos residuales

- Chat vs Agent: dos UIs. Documentar cuándo usar cada uno. No fusionar en esta fase.
- `config_json` malformado en filas viejas: parser con defaults.
- SQL checkbox vs tool name mismatch — alinear con registry, test de nombres.
