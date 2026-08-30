# Information architecture

Árboles de navegación que las fases 01 (Customer Portal) y 02 (Control Center) implementan.
Nombres de menú en **español**. Paths en inglés.

Producto y glosario: [`PRODUCT.md`](PRODUCT.md).

Si en Fase 01 una ruta no tiene API, se documenta el desvío en ese PR; no se reabre este brief.

---

## Rutas públicas (ambos productos)

| Path | Quién | Notas |
|---|---|---|
| `/login` | Customer | Email/password → sesión `rag_sess_…` |
| `/signup` | Customer | Alta + trial |
| `/admin/login` | Platform admin | Fase 02. **No** reutilizar `/login` del tenant |

Un `owner` de tenant que visite `/admin` va a `/admin/login`, no al Control Center.

---

## Customer Portal

Home: **Dashboard** `/` (saludo + plan + cuota + salud). No es un ítem más de “Account”; es la primera pantalla.

### Árbol objetivo (Fase 01)

```
Dashboard                    /
Chat                         /chat
Knowledge
  Sources                    /knowledge/sources
  Collections                /knowledge/collections
  Documents                  /knowledge/documents
  SQL Sources                /knowledge/sql
  Sync Jobs                  /knowledge/jobs
  Search Playground          /knowledge/playground
Workspace
  Projects                   /projects
  Agents                     /agents
  Connectors                 /connectors
  Prompts                    /prompts
Account
  Users                      /users
  API Keys                   /keys
  Usage                      /usage
  Billing                    /billing
  Audit                      /audit
  Settings                   /settings
```

Redirects (conservar bookmarks):

| Desde (hoy) | Hacia |
|---|---|
| `/ingestion` | `/knowledge/sql` |
| `/knowledge-bases` | `/knowledge/collections` |

Rutas que **no** entran en Fase 01 (existen más tarde; no añadirlas al nav ahora):

| Path | Fase |
|---|---|
| `/agents/:id` (builder/playground) | 05 |
| `/evaluation` | 09 |
| embed snippet (no es ruta de portal) | 06 |

### Mapa hoy → objetivo

| Hoy (`App.tsx`) | Objetivo |
|---|---|
| `/` Dashboard | `/` (se profundiza, no se mueve) |
| `/chat` | `/chat` |
| `/ingestion` | `/knowledge/sql` + redirect |
| `/knowledge-bases` | `/knowledge/collections` + redirect |
| `/projects` | `/projects` |
| `/agents` | `/agents` (CRUD hasta Fase 05) |
| `/connectors` | `/connectors` |
| `/prompts` | `/prompts` |
| `/users` | `/users` (+ invites) |
| `/keys` | `/keys` |
| `/usage` | `/usage` |
| `/audit` | `/audit` |
| (no existe) | `/knowledge/sources`, `/documents`, `/jobs`, `/playground` |
| (no existe) | `/billing`, `/settings` |

### APIs que alimentan cada grupo

Identidad siempre del Bearer. Header `X-Organization-Id` no es autoridad.

| UI | API principal (existente salvo nota) |
|---|---|
| Dashboard, Usage | `GET /api/v1/billing/subscription`, `GET /api/v1/billing/usage`, `GET /health` |
| Chat | `POST /api/v1/rag/query`, stream; thumbs `POST /api/v1/eval/feedback` |
| Knowledge sources | `GET/POST /api/v1/sources` |
| Collections | `/api/v1/knowledge-bases` |
| SQL | `/api/v1/ingestion/*` (legacy; no borrar) |
| Jobs | `/api/v1/jobs` |
| Playground | `POST /api/v1/rag/query` (mismo orchestrator que chat) |
| Projects | `/api/v1/projects` |
| Agents | `/api/v1/agents` |
| Connectors | `/api/v1/connectors` |
| Prompts | `/api/v1/admin/prompt` (**org-admin**, no Control Center) |
| Users | `/api/v1/organizations` members; invites **nuevos** en Fase 01 |
| Keys | keys en organizations/billing |
| Billing (lectura) | `GET /api/v1/billing/plans`, `/invoices`, `/subscription` |
| Audit | `GET /api/v1/audit-logs` |
| Settings | `GET/PUT /api/v1/organizations` |

### Roles de UI (Customer)

Roles de sistema: `owner`, `admin`, `member`, `viewer`.

Gating de **nav** (Fase 01; `/auth/me` ya devuelve roles — persistirlos en sesión):

| Ítem | owner | admin | member | viewer |
|---|---|---|---|---|
| Dashboard, Chat, Knowledge (lectura), Usage | sí | sí | sí | sí |
| Workspace (projects, agents, connectors, prompts) | sí | sí | sí (según permiso API) | ocultar si el API 403 de forma sistemática; default: ocultar prompts/connectors write |
| Users, API Keys | sí | sí | no | no |
| Billing, Settings, Audit | sí | sí | no (audit: si tiene `audit:read`) | no Users/Keys/Billing |

Regla mínima innegociable de Fase 01: **viewer no ve Claves ni Usuarios.**

Organization admin = `owner` o `admin`. Eso no abre `/admin`.

---

## Zent Control Center

Shell distinto, token distinto (`rag_platform_token`). Nav **sin** Chat/Knowledge.

### Árbol objetivo (Fase 02)

```
Dashboard                    /admin
Customers                    /admin/customers
  :orgId                     /admin/customers/:orgId
Billing                      /admin/billing
Plans                        /admin/plans
Usage / costs                /admin/usage
Audit (platform)             /admin/audit
```

Acciones **en la ficha** `/admin/customers/:orgId`, no en la nav:

- Change plan
- Pause
- Suspend
- Cancel
- Reset usage
- Impersonate (audit obligatorio)
- View logs / view billing

`/admin/plans` se profundiza en Fase 03 (editor de entitlements). `/admin/usage` se profundiza en Fase 08 (FinOps). En Fase 02 pueden ser listados delgados o enlaces a la ficha; no se inventan métricas.

### Quién entra

Solo `is_platform_admin` (sesión de plataforma o API key `admin:*` para automatización).

Un `owner` de ACME **no** entra a `/admin`.

Rutas `/api/v1/admin/prompt` y el SQL runner del chat son **herramientas de org**, no del Control Center. No moverlas bajo el shell `/admin`.

---

## Principios

- Un app Vite (`portal/`). Dos layouts: customer vs `/admin`.
- No segundo frontend.
- Copy de menús en español.
- No añadir ítems de Fase 05–14 al nav de 01 “por adelantado”.
