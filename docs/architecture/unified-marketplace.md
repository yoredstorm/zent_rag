# Unified Marketplace (Marketplace único global)

Estado: implementado (Fase F53). Migración `152_unified_marketplace`.

Regla madre:

```
ONE PRODUCT · ONE CATALOG · ONE INSTALLATION · ONE RUNTIME · MANY SURFACES
```

No existen marketplaces independientes por módulo. Workflows, Agents,
Knowledge y cualquier módulo futuro muestran **vistas contextuales filtradas**
del mismo catálogo global y usan la **misma instalación**.

## Autoridad

| Capa | Autoridad | Rol |
| --- | --- | --- |
| Catálogo | `marketplace_products` (+ `marketplace_product_versions`, `marketplace_product_dependencies`) | Única fuente de verdad de productos, pricing, applies_to, assets incluidos, versiones y dependencias. |
| Instalación | `marketplace_product_installations` | Único registro de instalación por tenant/workspace, con readiness, health, updates y `installed_assets` resueltos. |
| Runtime de ejecución | `integration_manifests` + `installed_integrations` + `runtime.execute_action` | Assets técnicos y ejecución real (credenciales, ledger, budget, evidencia). No hay segundo executor. |
| Assets | `integration_manifests`, `workflow_templates`, `agents` | Lo que un producto instala. NO son catálogo. |
| Legacy congelado | `marketplace_listings`, `marketplace_agents`, `marketplace_installs`, `public_listings`, `marketplace_orders` | Adaptadores de compatibilidad. Se proyectan al catálogo vía sync; sin nuevas superficies. |

Proyección (sync idempotente, `factory.sync_catalog_from_assets`):

- `integration_manifests` → producto `INTEGRATION` (`product-<slug>`), con
  `capabilities` desde `integration_capabilities` y `events` del manifest.
- `workflow_templates` → `WORKFLOW_TEMPLATE` / `BUSINESS_PACK`.
- `marketplace_agents` → `AGENT_TEMPLATE` (al instalar crea el agente con
  prompt/modelo/tools del template, no un agente vacío).
- `public_listings` → `AGENT_TEMPLATE` DRAFT (no se expone hasta revisión).

El sync solo rellena campos vacíos: nunca pisa ediciones manuales del Control
Center. Corre al arranque (`main._run_startup`) y por demanda en
`POST /api/v1/platform/marketplace/sync`.

## Contrato canónico de producto

`marketplace_products` + migración 152:

- `applies_to`: superficies donde el producto aporta funcionalidad.
  Valores: `AGENTS, WORKFLOWS, KNOWLEDGE, DATA, INTEGRATIONS, CHANNELS,
  PAYMENTS, AUTOMATIONS, ANALYTICS, ADMIN`. **No es ownership técnico.**
  Ejemplo: IZIPAY puede aplicar a `WORKFLOWS`, `AGENTS` y `PAYMENTS`.
- `capabilities`: agregado de capacidades reales (`payments.checkout.create`).
- `events`: eventos que proporciona (`payment.succeeded`, ...).
- `included_assets`: `[{kind, ref, alias}]` con kinds `integration`,
  `capability`, `action`, `workflow_template`, `agent`, `semantic`, `product`.
- `dependencies`: refs lógicas (ver capability-first).
- `configuration_schema`, `installation_flow`, `security`, `privacy`,
  `support`, `release_notes`, `rollout`, `certification`, `featured`.

`product_type` sigue siendo la clasificación técnica:
`INTEGRATION, WORKFLOW_TEMPLATE, AGENT_TEMPLATE, INTELLIGENCE_PACK,
BUSINESS_PACK, SEMANTIC_PACK, COMPOSITE_PACK`. No se agregan tipos nuevos sin
justificación arquitectónica.

Las categorías visuales (Ventas, Atención al cliente, Finanzas, Pagos, ...)
viven en `category` con keys en inglés y label en el portal
(`CATEGORY_LABEL` en `portal/src/components/marketplace/model.ts`).

## Pricing

Contrato estándar (validado en `products._validate_pricing_shape`):

- `FREE` — `{ "model": "FREE" }`
- `ONE_TIME` — `{ "model": "ONE_TIME", "amount": 49, "currency": "PEN" }`
- `SUBSCRIPTION` — `{ ..., "interval": "MONTH" }`
- `USAGE` — `{ "model": "USAGE", "unit": "request", "amount": 0.02, ... }`
- `CONTACT_SALES`, `INCLUDED`

`CUSTOM` y los modelos v1 del `cost_model` de manifests (`BYOC_NO_MARKUP`,
`PER_CALL`, `MONTHLY`, ...) se toleran para no romper legacy y se normalizan
con `products.normalize_pricing` al proyectar al catálogo.

Separación de capas: **CATALOG** (producto), **INSTALLATION**
(instalación), **ENTITLEMENT** (`entitlements` del producto + estado en la
instalación), **PAYMENT** (fuera de alcance: Stripe/IZIPAY/etc. se integrarán
sin tocar el catálogo). `MarketplaceProduct` nunca guarda secretos de pago.

## Capability-first

Una dependencia expresa QUÉ necesita, no qué plugin:

```json
{ "kind": "capability", "ref": "payments.checkout.create", "requirement": "required" }
```

Resolución (`src/platform/marketplace/resolver.py`):

```
capability → integration_capabilities → providers publicados
           → instalación existente del tenant (reuso) o provider elegido
           → install_integration (runtime único)
```

Sin UUIDs portables hardcodeados. Si la capability no tiene provider publicado
la instalación falla completa y explicada (sin estados parciales).

## Flujo de instalación

```
Marketplace / vista contextual
        │
        ▼
Product detail → Install (o Install desde canvas/agente/fuente)
        │
        ▼
factory.install_product
  1. reuso: (org, workspace, producto) existente → misma instalación
  2. dependencias capability-first (capability/integration/action)
  3. assets incluidos (integration/workflow_template/agent/semantic/product)
  4. reescritura de refs tipados dependency.* / answers.*
  5. rollback de workflows/agentes creados si hay pendientes (integración
     instalada se conserva: es reusable y no se destruyen credenciales)
        │
        ▼
readiness + health persistidos en la instalación
```

Readiness: `READY`, `NEEDS_CONFIGURATION`, `NEEDS_CREDENTIALS`,
`MISSING_DEPENDENCY`, `INCOMPATIBLE`, `DISABLED`, `ERROR` (más `installed`
legacy). `health` guarda hijos, uso (workflows/agentes) y `last_used_at` real
desde `integration_usage_ledger`. Nunca se inventan métricas.

Actualizaciones: `product.version` > `installation.product_version` →
`GET /api/v1/products/updates`; aplicar con
`POST /api/v1/products/installs/{id}/update` (re-ejecuta assets con reuso).

Desinstalación: `GET .../installs/{id}/impact` muestra workflows, agentes y
productos que la usan antes de borrar. `DELETE ...?cascade=false` libera solo
la instalación; `cascade=true` libera integraciones hijas únicamente si nadie
más las referencia. Nunca borra workflows ni agentes del tenant.

## API

Canónica (tenant): `/api/v1/products`

- `GET /` — catálogo con filtros `product_type`, `applies_to`, `category`,
  `pricing_model`, `q`.
- `GET /categories` — facetas reales (categorías, superficies, precios, tipos).
- `GET /{product_id|slug}` — detalle con assets, capabilities, events.
- `POST /{product_id}/install` — instalación única (resuelve dependencias).
- `GET /installs`, `GET /updates`, `GET /installs/{id}` (refresca salud),
  `GET /installs/{id}/impact`, `POST /installs/{id}/update`,
  `DELETE /installs/{id}?cascade=`.

Vistas contextuales (mismo catálogo, filtrado):

- Workflows: `GET /api/v1/workflows/marketplace/context` (disponibles con
  `applies_to` WORKFLOWS + info de producto), `POST
  /api/v1/workflows/marketplace/install` acepta `product_slug` (nuevo) o
  `integration_slug` (compat).
- Agents: `GET /api/v1/products?applies_to=AGENTS` (Agent Studio / Copilot).
- Knowledge: `GET /api/v1/products?applies_to=KNOWLEDGE` (Sources).

Control Center (mismo marketplace, otra superficie):
`/api/v1/platform/marketplace/*` — overview, CRUD de productos, versiones,
transiciones (publishing gate), rollout, impact, analytics, test lab, `sync`.

## Seguridad

- Secretos solo en SecretStore (`src/infrastructure/secrets`); los productos
  no admiten credenciales en `pricing` (validación explícita).
- Cross-tenant: toda instalación/impacto/desinstalación filtra por
  `organization_id`; instalar en otra org devuelve 404/403.
- Permisos: `marketplace_products:read` (tenant), `marketplace:install`,
  `marketplace:manage`, `marketplace_factory:manage` (CC).
- Pausar (`PAUSED`) saca al producto del catálogo visible y bloquea instalar.

## Backward compatibility

- Migración 152 es aditiva (columnas + índices + backfill). No elimina nada.
- Legacy congelado con adaptadores; se elimina solo tras demostrar cero uso:
  - `EcosystemMarketplace` (UI) retirada; `/products` redirige a `/marketplace`.
  - `/api/v1/marketplace` (listings/órdenes) y `/api/v1/copilot/marketplace`
    siguen existiendo como compatibilidad, sin nuevas superficies.
  - `admin/Marketplace` (listings 037) marcado legacy con banner.
- El runtime de ejecución, SecretStore, ledger, budget y evidencia no cambian.
- Invariantes en `tests/test_unified_marketplace.py`: tabla o router de
  catálogo paralelo nuevo rompe el test a propósito.

## Deprecaciones

| Superficie | Estado | Reemplazo |
| --- | --- | --- |
| `/marketplace` (EcosystemMarketplace) | Retirada | `/marketplace` unificado |
| `/products` (MarketplaceProducts) | Retirada | `/marketplace` (+ redirect) |
| `GET /api/v1/copilot/marketplace*` | Congelado | `GET /api/v1/products?applies_to=AGENTS` |
| `GET/POST /api/v1/marketplace*` (ecosystem) | Congelado | Catálogo único; órdenes/payouts fase de pagos |
| `admin/Marketplace` listings | Legacy | Marketplace Factory (productos) |
| `marketplace_agents` / `marketplace_installs` | Legacy | `AGENT_TEMPLATE` en el catálogo |

## Pendiente (fuera de esta fase)

- Pagos reales (Stripe/IZIPAY): capa PAYMENT separada de CATALOG/ENTITLEMENT.
- Reviews: solo con datos reales; hoy no se muestran estrellas.
- Migración de órdenes legacy (`marketplace_orders`) a entitlements.
