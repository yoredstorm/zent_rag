# Quickstart

Un desarrollador registrado puede ejecutar `client.chat()` en menos de 5 minutos.

Stack local con Docker: `docker compose up -d --build` (portal en `:8080`, API en `:8000`).

## 1. Crea tu trial

Portal: `/signup` (email + contraseña). Al terminar verás **tu API key una sola vez**.

O por API:

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Acme","email":"dev@acme.com","password":"secure-pass-123"}'
```

La respuesta incluye `api_key` (`zent_sk_live_…`) y `access_token` (sesión del portal). Guarda la key; no se vuelve a mostrar.

## 2. Instala el SDK

```bash
pip install -e sdk/python
# o
cd sdk/node && npm install
```

## 3. Primer chat

```python
from zent import Zent

client = Zent(api_key="zent_sk_live_...")  # o zent_sk_test_... en desarrollo
print(client.chat("What is our refund policy?").answer)
```

```ts
import { Zent } from "zent-node";

const client = new Zent({ apiKey: process.env.ZENT_API_KEY! });
const res = await client.chat("What is our refund policy?");
console.log(res.answer);
```

```bash
curl -X POST http://localhost:8000/api/v1/rag/query \
  -H "Authorization: Bearer zent_sk_live_..." \
  -H "Content-Type: application/json" \
  -d '{"query":"What is our refund policy?"}'
```

Base URL por defecto: `http://localhost:8000/api/v1` (override `ZENT_BASE_URL`).

Siguiente: [authentication](authentication.md) · [chat](chat.md)
