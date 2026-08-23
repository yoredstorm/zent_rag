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
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'
```

- Crear agente: permiso `agents:write` (sesión portal) + `Idempotency-Key`.
- Ejecutar: scope `agents:execute`. Stream: `POST /agents/{id}/run/stream`.
