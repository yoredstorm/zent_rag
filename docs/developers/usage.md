# Usage

Scope: `usage:read`.

```python
print(client.usage.get(days=30))
```

```ts
await client.usage.get(30);
```

```bash
curl http://localhost:8000/api/v1/billing/usage?days=30 \
  -H "Authorization: Bearer zent_sk_live_..."
```

También: `/billing/usage/agents`, `/api-keys`, `/storage`, `/alerts`. Las mutaciones de billing (upgrade, cancel, alerts POST) siguen exigiendo admin de organización.

`GET /api/v1/billing/usage` incluye (additive):

- `totals.errors` — eventos `usage_events.status <> completed`
- `totals.estimated_cost`
- `top_users` — hasta 5 `{ user_id, requests }` desde `usage_logs`
- `top_queries` — hasta 5 previews desde `query_audit_log` (vacío si no hay filas)

## Entitlements vs cuota de requests

`GET /api/v1/billing/entitlements` (permiso `billing:read`) devuelve el plan actual y un mapa `entitlements` (`max_agents`, `embed_widget`, `monthly_requests`, …). Esa tabla `plan_entitlements` es lo que el backend **enforza** al crear recursos. `plans.features` es solo display.

La **puerta de requests** sigue siendo el middleware de cuota (`request_quota` + `plans.requests_per_month` / entitlement `monthly_requests`). Cambiar `monthly_requests` en Control Center (`PUT /api/v1/platform/plans/{id}/entitlements`) actualiza el número; no sustituye el contador mensual.

`GET /api/v1/billing/plans` incluye `entitlements` de forma aditiva y conserva `features`.

