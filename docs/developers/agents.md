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
