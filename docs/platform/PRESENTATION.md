# Presentación Zent (speaker notes)

Outline de 10 slides. No es diseño gráfico: títulos, notas y qué pantalla enseñar.
Copy de slides en inglés (deck comercial). El producto en UI sigue en español.

Brief: [`PRODUCT.md`](PRODUCT.md). Rutas: [`INFORMATION_ARCHITECTURE.md`](INFORMATION_ARCHITECTURE.md).

---

## Slide 1 — Zent

**Turn your business data into an AI workforce.**

Speaker notes:

- Abrir con el outcome, no con el stack (no “tenemos FastAPI y Qdrant”).
- Zent es AI Data Platform / RAG-as-a-Service, no un chatbot con PDFs.
- Una plataforma, dos productos: Customer Portal (el cliente) y Control Center (nosotros).
- Misma API `/api/v1` para portal, SDKs (`zent` / `zent-node`) y MCP.
- Promesa: cada empresa convierte sus datos en agentes que responden y deciden.

**Demo:** logo / home conceptual. No hace falta app.

**Listo para demo hoy:** sí (narrativa).

---

## Slide 2 — The problem

**Las empresas tienen ERP, CRM, SQL, Excel, PDF, APIs — y el conocimiento está fragmentado.**

Speaker notes:

- El dato vive en sistemas que no se hablan; la gente exporta a Excel y pregunta en el chat equivocado.
- Montar RAG “de laboratorio” ignora tenancy, SQL seguro, cuotas y alucinaciones.
- El riesgo real no es “no tener un bot”: es filtrar datos entre clientes o inventar políticas.
- Zent existe para que no reconstruyan embeddings, vector DB, RBAC y billing en cada proyecto.

**Demo:** ninguno, o un diagrama de silos (ERP / CRM / SQL / carpeta de PDFs).

**Listo para demo hoy:** sí (narrativa).

---

## Slide 3 — The solution

```
Your Data → Zent → Knowledge → AI Agents → Answers / Decisions / Automation
```

Speaker notes:

- Data in-scope hoy: SQL, PDF, CSV, Excel, API, web, S3 (registry actual).
- Knowledge = bases aisladas por organización (`organization_id`).
- Agents = instrucciones + knowledge + tools (RAG, SQL), no un prompt suelto.
- Salidas: Chat en el portal, API/SDK, más adelante widget (Fase 06).
- No prometas Drive/SharePoint/ERP hasta Fase 12.

**Demo:** este diagrama. Opcional: 10 s de chat actual `/chat` si hay datos de farmacia demo.

**Listo para demo hoy:** narrativa sí; chat actual sí. Cadena “Agent Builder + widget” no.

---

## Slide 4 — Architecture

**Frontend → API → RAG (SQL / Qdrant / LLM)**

Speaker notes:

- Customer Portal y Control Center son dos UIs; un FastAPI.
- RAG híbrido + SQL Expert (SELECT-only, rol read-only) + agentes con guardrails.
- Aislamiento: identidad solo del Bearer; Qdrant con filtro de organización; audit.
- Billing y usage ya existen (planes, invoices, provider manual). Stripe es Fase 04.
- Observabilidad: Prometheus / Loki / Grafana. Esto es plataforma, no un script.

**Demo:** diagrama (no entrar a Grafana salvo que pregunten ops).

**Listo para demo hoy:** sí (arquitectura real del repo). No enseñar K8s (Fase 14, opcional).

---

## Slide 5 — Customer Experience

**Dashboard · Knowledge · Agent · Chat · Analytics · API**

Speaker notes:

- Recorrido del cliente: entra, ve su plan y cuota, conecta datos, pregunta, usa la API.
- Knowledge Center unifica sources, collections, SQL, jobs y un playground de búsqueda.
- El Agent Builder (crear “Pharmacy Assistant” con KBs y tools) es el salto de valor percibido.
- API keys con scopes; el SDK es `client.chat(...)`.
- Billing en este recorrido es **lectura** de plan/facturas hasta que Stripe esté (Fase 04).

**Qué pantalla enseñar** (rutas objetivo; hoy varias aún no existen — ver tabla de fases abajo):

| Momento | Ruta | Hoy |
|---|---|---|
| Dashboard | `/` | Existe (se profundiza en Fase 01) |
| Chat | `/chat` | Existe |
| Knowledge SQL | `/knowledge/sql` (hoy `/ingestion`) | Existe ingestión |
| Collections | `/knowledge/collections` (hoy `/knowledge-bases`) | CRUD plano |
| Playground | `/knowledge/playground` | Fase 01 |
| Agent builder | `/agents/:id` | Fase 05 (hoy lista CRUD) |
| API keys | `/keys` | Existe |
| Usage | `/usage` | Existe (tablas; charts en 01) |
| Billing lectura | `/billing` | Fase 01 |

**Listo para demo hoy:** Chat + dashboard + ingestión + keys. Historia completa de Knowledge Center / billing page / builder: **no** hasta las fases 01 y 05.

---

## Slide 6 — Business Control

**Zent Control Center — customers, subscriptions, revenue, usage, AI costs**

Speaker notes:

- Este slide es para inversores u ops internos: nosotros operamos el SaaS.
- MRR/ARR/customers/agentes/requests/coste LLM/margen: números de base de datos, no un mock.
- Ficha de ACME: plan, estado, usuarios, agentes, requests, coste, margen; acciones pause/suspend/impersonate.
- Impersonate siempre deja audit. Un owner de tenant no ve esta pantalla.
- Planes configurables (entitlements) evitan deploys para cambiar `max_agents`.

**Qué pantalla enseñar:**

| Momento | Ruta | Fase |
|---|---|---|
| Login platform | `/admin/login` | 02 |
| Dashboard plataforma | `/admin` | 02 |
| Lista customers | `/admin/customers` | 02 |
| Ficha ACME | `/admin/customers/:orgId` | 02 |
| Planes / entitlements | `/admin/plans` | 03 (nav en 02) |
| FinOps / costes | `/admin/usage` | 08 (métricas crudas en 02) |

**Listo para demo hoy:** **no.** No hay `/admin`. Hoy solo API `admin:*`. Este slide es narrativo hasta Fase 02 (y 08 para el margen fino).

---

## Slide 7 — AI Economics

**Customer $299 → LLM $38 + Embedding $12 + Infra $16 + Storage $4 = $70. Gross margin 76.6%.**

Speaker notes:

- El ejemplo es **ilustrativo** para el deck. En producto, los números salen de `usage_events` + `pricing_models` + `subscriptions` (Fase 08).
- No uses estos $299/$70 en el Control Center como datos fake.
- La tesis: precio de suscripción vs coste de tokens. Si el margen se cae, cambias plan o modelo (Fase 10 gateway).
- Zent no solo factura requests: ve si el negocio es viable.

**Demo:** tabla del slide. Pantalla `/admin/usage` cuando exista.

**Listo para demo hoy:** narrativa sí. Pantalla con margen real: **Fase 08** (y 02 para MRR aproximado).

---

## Slide 8 — Security

**Multi-tenant · RBAC · Encryption · Audit · API keys · Rate limits · Isolation**

Speaker notes:

- Tenant isolation es el riesgo #1: un usuario solo recupera datos de su organización.
- RBAC: `owner` / `admin` / `member` / `viewer`. Platform admin ≠ organization admin.
- Keys hasheadas (`zent_sk_live`); sesiones portal opacas; no JWT.
- Rate limits, idempotency, SQL read-only, tests de aislamiento en CI.
- Hardening extra (CORS por org, reset password, scanning): Fase 07. SSO no es blocker de la primera venta.

**Demo:** una frase + opcional `tests/test_tenant_isolation.py` si el público es técnico.

**Listo para demo hoy:** sí (capacidad real). Control Center + impersonate audit: Fase 02.

---

## Slide 9 — Scale

**1 customer → 100 → 1,000 → Enterprise**

Speaker notes:

- Hoy: Docker Compose (demo). Producción inicial: Docker + managed PG/Redis/Qdrant (Fase 11).
- Kubernetes solo cuando la carga lo pida (Fase 14). No es un slide de “ya estamos en K8s”.
- Escala de producto: entitlements y billing (03–04), no más réplicas de un chatbot.
- Enterprise: plan custom + provider `manual` + Control Center, no un fork del código.

**Demo:** este funnel. No un cluster.

**Listo para demo hoy:** narrativa sí.

---

## Slide 10 — Close

**One platform. Every business. Its own AI.**

Speaker notes:

- Cerrar con la promesa de la slide 1.
- Recap en una línea: datos → knowledge → agentes → respuestas, con control de negocio.
- CTA: demo del Customer Portal (Fase 01+) y, si el público es interno, Control Center (Fase 02).
- No pedir K8s, Stripe ni Drive para cerrar la primera conversación.

**Demo:** slide de cierre.

**Listo para demo hoy:** sí.

---

## Qué se puede enseñar vs fase

| Slide | Narrativa | Pantalla real |
|---|---|---|
| 1–4, 9, 10 | sí | no requerida |
| 5 Customer | parcial | Completo tras **01** (Knowledge/billing) y **05** (builder) |
| 6 Control Center | sí | **02** (ficha); **03** planes; **08** economics UI |
| 7 Economics | ejemplo del deck | **08** (no usar $299 fake en la app) |
| 8 Security | sí | Extra **02** impersonate, **07** hardening |
| Widget / embed | no en este deck como demo | **06** |

Orden de implementación para una demo “historia completa” (customer + control + margen): **00 (este doc) → 01 → 02 → 05**, y 08 cuando el slide 7 deba ser la UI.
