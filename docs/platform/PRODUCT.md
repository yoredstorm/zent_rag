# Producto Zent (freeze)

Documento canónico de posicionamiento. Las fases 01–14 copian este brief para copy de UI y demos.
No cambia nombres de paquete, API ni SDKs.

Contrato API: `1.0.0` (`/api/v1`). App: `0.1.0`. SDKs: Python `zent`, Node `zent-node`.

---

## 1. Qué es Zent

**Zent es una AI Data Platform / RAG-as-a-Service para empresas.**

Orquesta knowledge, agentes y facturación sobre los datos privados de cada organización, con aislamiento multi-tenant, API, SDKs y MCP — sin que el cliente monte embeddings, vector DB, RBAC ni billing desde cero.

Alineado con el README: *RAG-as-a-Service / AI Agent Platform*. Este brief no renombra el producto ni los clientes `from zent import Zent` / `zent-node`.

---

## 2. Qué no es

Zent **no** es un chatbot genérico con PDFs.

Tampoco es:

- Un wrapper de un único modelo (OpenAI/DeepSeek/Ollama) sin tenancy ni cuotas.
- Un notebook de RAG de laboratorio (chunk → embed → top-k) sin billing, audit ni portal.
- Un “dashboard bonito” desconectado de la API.
- Un panel de super-admin disfrazado de producto de cliente (son **dos** productos).

La diferencia de venta: no vendes “sube un PDF y pregunta”. Vendés **conectar los datos de la empresa y operar agentes de IA** (chat, API, widget) con control de uso y de negocio.

---

## 3. Cadena de valor

```
Data
  SQL · PDF · CSV · Excel · API · Web · S3
        ↓
   Knowledge
        ↓
   AI Agent
        ↓
 Chat  /  API  /  Widget
```

El cliente conecta fuentes, Zent las normaliza e indexa (Postgres + Qdrant), y un agente responde con citas, SQL validado cuando aplica, y límites de plan. La misma API sirve al Customer Portal, al Control Center, a los SDKs y a MCP (`/mcp`).

---

## 4. Dos productos

Un ecosistema, **una** API (`/api/v1`). Dos superficies:

| Producto | Quién | Qué administra |
|---|---|---|
| **Customer Portal** | La empresa cliente (tenant) | Usuarios, fuentes, knowledge bases, prompts, agentes, conversaciones, API keys, consumo, límites, plan, facturación (lectura ahora; checkout en Fase 04), integraciones |
| **Zent Control Center** | El dueño de la plataforma | Clientes/tenants, planes, suscripciones, facturación, consumo, costos de IA, modelos, límites, errores, feature flags, auditoría de plataforma |

El Control Center **no** es el rol `owner` de un tenant. Un `owner` de ACME no entra a `/admin`. El platform admin no se autentica como API key `admin:*` en la UX (esa key sigue existiendo para automatización; la UI de Fase 02 usa sesión de plataforma).

Copy del portal: **español**. La presentación comercial puede ir en inglés.

---

## 5. Glosario

| Término | Significado |
|---|---|
| **Organization** | Tenant = customer. Fila en `organizations`. `organization_id` es la raíz de aislamiento en SQL, Qdrant, Redis y audit. |
| **Platform admin** | Operador de Zent. No es `owner` de un customer. Hoy: scope `admin:*` en API key; Fase 02: sesión `typ=platform`. |
| **Organization admin** | `owner` o `admin` del tenant. Gestiona usuarios, keys, prompts, billing de su org. |
| **Entitlement** | Feature o límite **enforceable** (bool o int). No es el JSON de display `plans.features`. Motor: Fase 03. |
| **Knowledge base** | Colección de conocimiento de una org (`knowledge_bases`). Vectores en Qdrant, filtrados por `organization_id`. |
| **Agent** | Agente configurado (`agents`): prompt, tools, modelo, knowledge. Runtime existente; el builder es Fase 05. |
| **Source** | Fuente de ingestión (`kb_sources`): tipo del registry (`sql`, `file`, `csv`, `excel`, `web`, `s3`, `api`). |
| **Embed** | Widget/iframe público de un agente (Fase 06). No es el chat del portal. |

Roles de sistema del Customer Portal (no confundir con platform admin): `owner`, `admin`, `member`, `viewer`.

---

## 6. Promesa de demo

**Turn your business data into an AI workforce.**

Una plataforma. Cada negocio, su propia IA.

---

## 7. Fuentes: in-scope hoy vs después

**Hoy** (registry [`src/knowledge/connectors/registry.py`](../../src/knowledge/connectors/registry.py)):

| Tipo | Qué cubre |
|---|---|
| `sql` | Tablas relacionales (path SQL / lazy ingestion) |
| `file` | Archivos; normalizadores incluyen PDF, DOCX, HTML, texto |
| `csv` | CSV |
| `excel` | Excel |
| `web` | Sitios |
| `s3` | Object storage compatible S3 |
| `api` | HTTP / APIs |

También hay conectores plugin (`src/connectors/plugin/`) para SQL de varios motores y archivos; no duplicar esa vía en el brief de venta.

**Después (Fase 12 y más):** Google Drive, SharePoint, Notion, Snowflake, BigQuery, Kafka, ERP, CRM, data warehouse. No se prometen en la demo hasta que el conector exista.

Widget embed: Fase 06. No está in-scope de la demo de Fase 01.

---

## Do not contradict

- Seguir llamando al producto **Zent** / RAG-as-a-Service.
- No renombrar `zent`, `zent-node`, prefijos `zent_sk_live`, contrato `/api/v1`.
- Identidad de tenant **solo** del Bearer; nunca `X-Organization-Id` como autoridad.
- Qdrant: colección compartida + filtro `organization_id` (no una colección por tenant en este freeze).
