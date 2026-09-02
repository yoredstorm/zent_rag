# Agents

CRUD de agentes: `POST/GET/PUT/DELETE /api/v1/agents`. Ejecución:

```python
agent = client.agents.create("Soporte", tools=["search_knowledge"])
result = client.agents.run(agent["id"], "¿Hay stock del producto X?")
print(result["answer"])
```

```ts
await client.agents.run(agentId, "¿Hay stock del producto X?");
```

```bash
curl -X POST http://localhost:8000/api/v1/agents/$ID/run \
  -H "Authorization: Bearer zent_sk_live_..." \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type": application/json" \
  -d '{"message":"hola"}'
```

- Crear agente: permiso `agents:write` (sesión portal) + `Idempotency-Key`.
- Ejecutar: scope `agents:execute`. Stream: `POST /agents/{id}/run/stream`.
- El playground del portal (`/agents/:id?tab=playground`) llama ese stream. El chat genérico `/chat` sigue siendo RAG, no el Agent Runtime.
- Campo `model`: alias de gateway (`zent-cheap`, `zent-default`, `zent-quality`) o un modelo real del provider. Ver [GATEWAY.md](../platform/GATEWAY.md). Usage registra el modelo real.

## `config` / `config_json`

Create y update aceptan un objeto `config` validado. GET/list lo devuelven parseado (defaults si la fila es vieja o malformada):

```json
{
  "purpose": "Consultar stock y productos",
  "temperature": 0.2,
  "tone": "professional",
  "knowledge_base_ids": ["uuid-de-kb-del-mismo-tenant"],
  "limits": {
    "max_steps": 6,
    "max_tokens": 4000,
    "max_cost_usd": 0.5
  },
  "security": {
    "sql_enabled": false,
    "api_calls_enabled": false
  }
}
```

- `tone`: `professional` | `friendly` | `concise`.
- `knowledge_base_ids` de otra organización → `404`.
- El runtime filtra retrieval a esas KBs (si la lista está vacía, el RAG sigue siendo org-wide).
- Tools reales del registry: `search_knowledge`, `query_database`, `call_api`. `security.sql_enabled=false` bloquea SQL aunque esté en `tools`.
- `limits` anidados recortan el loop (también se leen `max_steps` / `max_tokens` top-level en filas antiguas).

Límite de plan: entitlement `max_agents` (Fase 03) en el create.

## Versionado, entornos y deployments (F1)

Ciclo de vida enterprise: el agente (`agents`) es la identidad; su configuración
se congela en snapshots inmutables (`agent_versions`) y se despliega por entorno.

```text
agents ──snapshot──▶ agent_versions (draft → ready → staging → production)
                        │
              environments (development | staging | production)
                        │
              deployments { version, env, slug, status, rollback }
```

Endpoints:

| Endpoint | Permiso | Descripción |
|---|---|---|
| `POST /api/v1/agents/{id}/versions` | `agents:version` | Snapshot del estado actual (draft) |
| `GET /api/v1/agents/{id}/versions` | `agents:read` | Lista de versiones |
| `POST /api/v1/agents/{id}/versions/{vid}/promote` | `agents:version` | Transición de estado (409 si inválida) |
| `GET /api/v1/environments` | `deployments:read` | Entornos (auto-crea dev/staging/prod) |
| `POST /api/v1/deployments` | `deployments:write` | Despliega versión en entorno (pending→deploying→healthy) |
| `POST /api/v1/deployments/{id}/rollback` | `deployments:write` | Revierte al último deployment bueno (rollback_from_id) |
| `GET /api/v1/deployments` | `deployments:read` | Historia de deployments |

Reglas:

- El snapshot congela prompt, modelo, tools y `config` (temperature, tone, kb ids,
  limits, security) como JSONB. `resolve_agent(agent, snapshot)` materializa un
  `Agent` para el runtime — el Agent Runtime no conoce versiones.
- Solo se despliegan versiones `ready | staging | production`. `draft` → 409.
- Al promover a `production`, las otras versiones production del mismo agente
  pasan a `ready` (histórico reusable para rollback).
- Rollback crea un NUEVO deployment apuntando a la versión anterior; la historia
  queda intacta (`rollback_from_id` referencia el deployment actual).
- El `slug` del deployment (`<agente>-<entorno>`, único por org) queda reservado
  para la API pública `/api/v1/deployments/{slug}/query` (fase F2).
- Aislamiento: todo endpoint exige pertenencia al tenant autenticado (404 cross-org).

## Workspaces (PROMPT 02)

Jerarquía: `Tenant → Workspace → {Agents, Knowledge Bases, Connectors}`.

- `GET/POST /api/v1/workspaces` · `GET/PUT/DELETE /api/v1/workspaces/{id}`
  (permisos `workspaces:read/write`). El workspace `default` se auto-crea por org.
- `agents`, `knowledge_bases` y `connectors` aceptan `workspace_id` (validado
  contra la org autenticada; 404 cross-org). Filtro `GET /api/v1/agents?workspace_id=`.

## Ciclo de vida del agente

`agents.status`: `draft → configured → evaluating → ready → deployed → archived`
(computado por el servicio; archive manual vía `POST /api/v1/agents/{id}/archive`).
`draft` sin modelo/prompt; `configured` con ambos; `ready` con versión lista;
`deployed` con deployment healthy.

## Readiness

`GET /api/v1/agents/{id}/readiness` → score 0-100 + checklist (model 15, prompt 15,
knowledge 20, datasource 10, eval dataset 10, security 10, version 10, deployment 10).

## Retrieval y Output por agente

- `config.retrieval`: `{strategy, top_k, score_threshold}` — `search_knowledge`
  aplica los overrides en runtime (fallback al comportamiento por defecto).
- `config.output_schema`: JSON Schema para respuestas estructuradas (validación
  en API pública, fase F2).
- El snapshot de versiones (schema_version 2) congela ambos campos.

## Go Live (PROMPT 05)

- **DeploymentEvents**: cada transición registra historial (`GET /api/v1/deployments/{id}/events`):
  created → deploying → healthy | failed, y en rollback: rolled_back (+ rolled_back_to del nuevo).
- **Permisos granulares**: `deployments:deploy` (crear), `deployments:rollback`,
  `deployments:promote` (promover versión a production). owner/admin los tienen;
  `member` solo lectura.
- **Readiness Go Live**: el checklist incluye items informativos `rate_limits` y
  `observability` (peso 0, no afectan el score).
- **UI**: botón "Go live (production)" en el Agent Builder despliega la última
  versión lista al entorno production; cada deployment muestra su timeline de eventos.
