# Connectors

```python
client.connectors.list()
client.connectors.create("ERP", "postgres", config={"host": "db.internal"})
```

```ts
await client.connectors.list();
await client.connectors.create("ERP", "postgres", { config: { host: "db.internal" } });
```

HTTP:

- `GET /api/v1/connectors` — `connectors:read`
- `POST /api/v1/connectors` — `connectors:write` + `Idempotency-Key`
- `POST /connectors/{id}/test` · `/discover` · `GET /capabilities` · `GET /types`

Los secretos van en `secrets` y **nunca** se devuelven en el JSON de respuesta (`has_secrets: true`).
