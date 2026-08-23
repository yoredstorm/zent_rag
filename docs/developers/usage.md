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
