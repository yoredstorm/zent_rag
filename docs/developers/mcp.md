# MCP Server

Zent expone sus capacidades mediante **Model Context Protocol** (MCP) en
transporte **Streamable HTTP (stateless)**, montado en la misma API bajo
`/mcp`. Clientes como Cursor, Claude Desktop o cualquier SDK MCP pueden
conectarse apuntando a `http://<host>:8000/mcp`.

## Autenticación

Cada request MCP debe incluir la misma identidad que el REST API:

```
Authorization: Bearer zent_sk_live_...
```

- La identidad (tenant/usuario/permisos) se deriva **exclusivamente** del
  token validado por `TenantMiddleware` — nunca de argumentos de la tool.
- La cuota del plan, rate limits globales y el anti-spoofing de headers
  aplican igual que en REST. MCP **no es un camino alternativo**.
- Opcional: header `X-Zent-MCP-Client: <name>/<version>` para identificar
  al cliente en la auditoría (fallback: `User-Agent`).

## Tools

| Tool | Permiso RBAC | Descripción |
|---|---|---|
| `search_knowledge` | `rag:read` | Búsqueda semántica en la knowledge base del tenant (chunks + scores). |
| `query_database` | `rag:read` | Pregunta NL → SQL read-only validado (guardas del SQL Expert intactas). SQL solo visible con rol `admin`. |
| `get_document` | `rag:read` | Fetch de chunks por `document_id` (Qdrant) con verificación estricta de tenant. |
| `execute_agent` | `agents:execute` | Ejecuta un agente configurado (ReAct + allowlist de tools + guardrails + quotas). |
| `get_usage` | `usage:read` | Agregados de uso de la organización (requests, tokens, latencia, costo). |

Rol (`admin`/`customer`): el cliente solo puede **degradar** su rol, jamás
elevarlo. El rol `customer` restringe la visibilidad de vectores (solo
`visibility=public`) y bloquea agregaciones SQL.

## Política por organización

`organizations.config_json["mcp"]` permite deshabilitar MCP o ajustar cada
tool por tenant (defaults: todo habilitado sujeto a RBAC):

```json
{
  "mcp": {
    "enabled": true,
    "tools": {
      "execute_agent":    {"enabled": true, "min_role": "admin", "rpm": 10},
      "search_knowledge": {"enabled": true, "rpm": 60},
      "query_database":   {"enabled": true, "rpm": 20},
      "get_document":     {"enabled": true, "rpm": 60},
      "get_usage":        {"enabled": true, "rpm": 30}
    }
  }
}
```

- `enabled: false` (nivel mcp o tool) → la tool responde error `tool_disabled`.
- `min_role: "admin"` → solo identidades con rol admin.
- `rpm` → requests/minuto por tool y tenant (ventana fija en Redis,
  `mcp:tool:{org}:{tool}`).

## Auditoría y costos

Cada tool call escribe en `audit_logs` (`resource_type=mcp_tool`,
`action=mcp.tool_call`) con metadata: `mcp_client`, `tool`, `tenant`,
`user`, `role`, `execution_latency_ms`, `cost`, `tokens`, `result`
(`ok | denied | error | quota`). Nunca se registra el texto del query.

Las tools con consumo (search/get_document/query_database) escriben
`usage_events` (idempotente por call) + contadores de la Usage Engine.
`execute_agent` registra su propio evento vía el Agent Runtime.

## Configuración

| Variable | Default | Descripción |
|---|---|---|
| `RAG_RAG_MCP_ENABLED` | `true` | Monta el MCP server en `/mcp`. |
| `RAG_RAG_MCP_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*,testserver` | Host header allowlist (DNS-rebinding guard). En producción incluir el dominio público. |
| `RAG_RAG_MCP_DEFAULT_RPM` | `60` | Requests/minuto por defecto por tool (override por org). |

## Ejemplo (SDK Python oficial)

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    headers = {"Authorization": "Bearer zent_sk_live_..."}
    async with streamable_http_client("http://localhost:8000/mcp", headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_knowledge", {"query": "política de reembolsos"})
            print(result)

asyncio.run(main())
```

## Notas

- Transporte stateless: cada request es independiente (sin sesiones
  server-side). No hay endpoint SSE de lectura; solo `POST /mcp`.
- `/mcp` responde 307 a `/mcp/` (los clientes MCP oficiales siguen el
  redirect automáticamente).
- El `clientInfo` del handshake no está disponible por request en modo
  stateless; la identificación del cliente usa `X-Zent-MCP-Client` /
  `User-Agent`.
