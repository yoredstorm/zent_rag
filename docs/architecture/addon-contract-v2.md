# Addon Contract v2 (IntegrationManifest)

Estado: implementado (migraciones 089, 111, 113 y **159**: bloque `contract`,
`contract_version` y `applies_to` persistidos y validados). Lo que sigue sin
existir va marcado como **pendiente** en cada tabla.
Fecha: 2026-10-17

## Principio

```
ONE PRODUCT · ONE CATALOG · ONE INSTALLATION · ONE RUNTIME · MANY SURFACES
```

No hay marketplaces paralelos. Un addon **no** trae catálogo propio, instalación
propia ni runtime propio: se declara una sola vez en `integration_manifests`
(IntegrationManifest) y el catálogo global lo proyecta como producto
(`marketplace_products`, slug `product-<slug>`, `product_type=INTEGRATION`).

| Aspecto | Autoridad única |
| --- | --- |
| Declaración | `integration_manifests` + `integration_capabilities` + `integration_actions` |
| Catálogo | `marketplace_products` (proyección idempotente de `factory.sync_catalog_from_assets`) |
| Instalación | `installed_integrations` / `marketplace_product_installations` (+ `integration_credentials`) |
| Ejecución | runtime único: `execute_binding` → `execute_action` (provider kind `marketplace_action`) o los provider kinds `commerce` / `payment_provider` / `conversation` |
| Secretos | SecretStore; el manifest solo declara NOMBRES de claves |

Definición operativa: **un addon es una integración declarada que aporta
capacidades y/o eventos al proceso de negocio, instalable por un tenant y
ejecutada por el runtime existente**. Ni un plugin con proceso propio ni un
módulo con tablas propias.

## Ejemplos en el repo

- `zent-messaging` (migración 158, `messaging_statements`): addon incorporado
  PUBLISHED con la capability `conversation.send` y el evento
  `conversation.message`. Es lo que resuelve la mensajería para todos los
  tenants: `resolve_capability` lo encuentra sin instalación previa.
- IZIPAY: hoy se configura como **proveedor de pago del tenant**
  (`configure_provider` → `commerce_payment_providers` + SecretStore + bindings
  `payment_provider`). No hay todavía un manifest IZIPAY publicado; el ejemplo
  canónico de este contrato está más abajo.

## Contrato v2 — campos

| Campo | Dónde vive | Estado | Notas |
| --- | --- | --- | --- |
| identity: `slug`, `name`, `provider`, `version` | `integration_manifests` | implementado | `slug` UNIQUE ≤80 (letras/números/-/_); `provider` es el publisher; `version` arranca en 1 |
| `description`, `category`, `logo_ref`, `countries` | `integration_manifests` | implementado | `category` determina el `applies_to` por defecto al proyectar |
| `applies_to` | `integration_manifests.applies_to` (migración 159) | implementado (v2) | se usa el declarado por el manifest al proyectar; si falta, cae a `default_applies_to("INTEGRATION", category)`. Valores: `ADDON_APPLIES_TO` |
| `auth_modes` | `integration_manifests` | implementado | `BYOC`, `OAUTH`, `ZENT_MANAGED`, `PARTNER_MANAGED`, `API_KEY`, `CERT`, `MTLS`, `NONE` |
| `scopes` | `integration_manifests` | declarativo | se guardan y se exponen; sin enforcement verificado en el runtime |
| `capabilities[]` | `integration_capabilities` | implementado | slug canónico (`payments.checkout.create`); ≥1 requerida |
| `actions[]` | `integration_actions` | implementado | `action_id` UNIQUE ≤120 con prefijo `{slug}.` / `{capability}.` / `demo.`; schemas JSON Schema object |
| campos de acción: `risk_level`, `read_only`, `requires_approval`, `contains_personal_data`, `sensitive_data_classes`, `retention_policy`, `cache_policy`, `timeout_ms`, `retry_policy`, `cost_model`, `provider_config`, `version`, `status` | `integration_actions` | implementado | validados por `validate_action_manifest`; `provider_config.kind` ∈ `rest` / `demo_echo` / `public_rest` |
| `events[]` (`id`, `business_name`, `event_schema`, `delivery_mode`) | `integration_manifests.events` | implementado (v2, migración 111) | `delivery_mode` ∈ `webhook` / `polling` / `internal`; el id exige prefijo `{slug}.` |
| `credentials` (NOMBRES de claves) | `integration_manifests.contract.credentials` (migración 159) | implementado (v2) | solo `{key, label, required}`; `validate_integration_manifest` rechaza `value`/`secret`/`token`/`api_key`… Los valores SOLO en SecretStore |
| `permissions` | contrato v2 + paquete portable + nodos | implementado | el manifest declara `permissions`; el paquete portable declara `external_actions:execute`; el runtime aplica permisos por nodo |
| approval requirements | `integration_actions.requires_approval` + `installed_integrations.auto_use_policy` + `contract.approval` | implementado | policies `NEVER_AUTO` / `AUTO_READ_ONLY` / `REQUIRE_APPROVAL` / `WORKFLOW_ONLY` |
| `idempotency_support` | `integration_actions.idempotency_support` + `contract.capabilities[].idempotency_support` | implementado | por acción y por capacidad |
| `idempotency_scope` | `contract.capabilities[].idempotency_scope` / `contract.idempotency.scope` | implementado (v2) | `action` / `operation` / `tenant` / `none`; en pagos la identidad estable real es `stable_operation_key` (ver `payment-capabilities.md`) |
| `rate_limits` | `integration_manifests.rate_limits` + `contract.capabilities[].rate_limits` | implementado | `requests_per_minute` / `requests_per_day` aplicados por `runtime._enforce_rate_limits` (fail-open) |
| `cost_model` | `integration_actions.cost_model` + `manifest.pricing` + `contract.cost_model` | implementado | `COST_MODELS`; el catálogo normaliza a `PRICING_MODELS` (`normalize_pricing`) |
| health check | `contract.health_check` (migración 159) | implementado (v2) | `kind` ∈ `http` / `none`; `http` exige `url` https; el circuit breaker por acción y el `health` del proveedor de pago siguen siendo el runtime real |
| webhook configuration | `events[].webhook` (`path`, `signature`, `replay_window_seconds`) | implementado (v2) | `signature` ∈ `hmac-sha256` / `stripe-signature` / `kr-hash` / `shared-secret` / `none`; `path` debe empezar por `/`; adapter de polling pendiente |
| sandbox support | `contract.sandbox` (migración 159) | implementado (v2) | `{supported, mode}` con `mode` ∈ `test` / `live` / `both`; en pagos además `mode`+`sandbox` del proveedor del tenant |
| compatibility | `contract.compatibility` | implementado (v2) | `min_zent_version`, `contract_version`; el paquete portable trae `metadata.min_zent_version` y el import reporta `VERSION_MISMATCH` |
| documentation | `contract.documentation` | implementado (v2) | `url`, `setup_url`, `support_url`; el producto de catálogo mantiene su propio campo `documentation` |

## Regla dura: NUNCA secretos en el manifest

- El manifest declara **nombres de claves** (`credentials.required_keys` en el
  contrato v2; `PROVIDER_SECRET_KEYS` para pagos), jamás valores.
- Los valores van al SecretStore:
  - `runtime.set_credentials` (instalación de integración) escribe el blob en el
    SecretStore y guarda solo `installed_integrations.credential_ref`.
  - `payments.configure_provider` (proveedor de pago) guarda los secretos en el
    SecretStore bajo un connector UUID determinista y devuelve solo
    `credential_ref`.
- Denylists reales que lo vigilan:
  - `packages.scan_security` (paquete portable): claves prohibidas
    (`password`, `api_key`, `secret`, `token`, ...), referencias de tenant y
    DSNs → estado `UNSAFE` y el import responde 409.
  - `products._validate_pricing_shape`: `pricing` con claves que suenen a
    secreto (`_SECRET_KEY_HINTS`) es error de producto.
- Corolario: un manifest con credenciales embebidas no es un addon válido,
  aunque el JSON "funcione" en local.

## Ejemplo canónico: addon IZIPAY

Forma v2 completa del manifest (el bloque `credentials` son NOMBRES de claves):

```json
{
  "slug": "izipay",
  "name": "IZIPAY Payments",
  "provider": "IZIPAY",
  "version": 1,
  "description": "Cobra por QR o link de pago con IZIPAY (Lykke / micuentaweb V4).",
  "category": "finance",
  "logo_ref": null,
  "countries": ["PE"],
  "auth_modes": ["BYOC"],
  "scopes": ["payments:charge"],
  "status": "PUBLISHED",
  "applies_to": ["WORKFLOWS", "AGENTS", "PAYMENTS"],
  "pricing": {"model": "FREE"},
  "rate_limits": {"requests_per_minute": 60, "requests_per_day": 5000},
  "data_policy": {"contains_personal_data": true, "purpose_required": true},
  "support": {"level": "partner", "contact": "soporte@izipay.pe"},
  "certification": "partner",
  "credentials": {
    "auth_mode": "BYOC",
    "required_keys": ["merchant_code", "api_key", "hash_key"],
    "storage": "secret_store",
    "reference": "credential_ref"
  },
  "capabilities": [
    {
      "slug": "payments.checkout.create",
      "name": "Crear checkout",
      "description": "Crea la sesión de pago de una orden con el monto de la orden persistida.",
      "actions": [
        {
          "action_id": "izipay.checkout.create",
          "display_name": "Crear checkout IZIPAY",
          "description": "CreatePayment (micuentaweb V4): devuelve formToken y URL de pago.",
          "input_schema": {
            "type": "object",
            "required": ["order_id"],
            "properties": {
              "order_id": {"type": "string"},
              "order_number": {"type": "string"},
              "ttl_seconds": {"type": "integer"},
              "customer": {"type": "object"}
            }
          },
          "output_schema": {
            "type": "object",
            "properties": {
              "checkout_id": {"type": "string"},
              "provider": {"type": "string"},
              "status": {"type": "string"},
              "amount": {"type": "number"},
              "currency": {"type": "string"},
              "reference": {"type": "string"}
            }
          },
          "risk_level": "critical",
          "read_only": false,
          "requires_approval": false,
          "contains_personal_data": false,
          "timeout_ms": 20000,
          "retry_policy": {"max_attempts": 2, "backoff_seconds": 1},
          "idempotency_support": true,
          "idempotency_scope": "operation",
          "cost_model": {"model": "BYOC_NO_MARKUP"},
          "provider_config": {
            "kind": "rest",
            "base_url": "https://api.micuentaweb.pe",
            "path_template": "/api-payment/V4/Charge/CreatePayment",
            "method": "POST"
          }
        }
      ]
    },
    {
      "slug": "payments.qr.create",
      "name": "Crear QR",
      "description": "QR o link de pago del checkout.",
      "actions": [
        {
          "action_id": "izipay.qr.create",
          "display_name": "QR / link IZIPAY",
          "input_schema": {"type": "object", "properties": {"checkout_id": {"type": "string"}}},
          "output_schema": {"type": "object", "properties": {"qr_payload": {"type": "string"}}},
          "risk_level": "normal",
          "read_only": false,
          "idempotency_support": false,
          "cost_model": {"model": "BYOC_NO_MARKUP"}
        }
      ]
    },
    {
      "slug": "payments.status.get",
      "name": "Consultar pago",
      "description": "Estado del pago en IZIPAY (consultivo: la autoridad es el registro local).",
      "actions": [
        {
          "action_id": "izipay.status.get",
          "display_name": "Estado del pago IZIPAY",
          "input_schema": {"type": "object", "properties": {"reference": {"type": "string"}}},
          "output_schema": {"type": "object", "properties": {"status": {"type": "string"}}},
          "risk_level": "info",
          "read_only": true,
          "idempotency_support": false,
          "cost_model": {"model": "BYOC_NO_MARKUP"}
        }
      ]
    }
  ],
  "events": [
    {
      "id": "payment.succeeded",
      "business_name": "Pago confirmado",
      "delivery_mode": "webhook",
      "event_schema": {
        "type": "object",
        "properties": {
          "payment_reference": {"type": "string"},
          "amount": {"type": "number"},
          "currency": {"type": "string"},
          "status": {"type": "string"}
        }
      }
    },
    {
      "id": "payment.failed",
      "business_name": "Pago rechazado",
      "delivery_mode": "webhook",
      "event_schema": {
        "type": "object",
        "properties": {
          "payment_reference": {"type": "string"},
          "status": {"type": "string"}
        }
      }
    },
    {
      "id": "payment.expired",
      "business_name": "Pago expirado",
      "delivery_mode": "webhook",
      "event_schema": {
        "type": "object",
        "properties": {
          "payment_reference": {"type": "string"},
          "status": {"type": "string"}
        }
      }
    }
  ],
  "health_check": {"kind": "api_status", "timeout_ms": 5000},
  "webhook": {"delivery_mode": "webhook", "signature": "kr-hash", "replay_guard": "provider_event_id"},
  "sandbox": {"supported": true, "mode": "test"},
  "compatibility": {"min_zent_version": null},
  "documentation": {"summary": "Integración IZIPAY (micuentaweb V4)", "docs_url": null}
}
```

Proyección esperada al catálogo (lo que `sync_catalog_from_assets` produce para
un manifest PUBLISHED; `applies_to` exacto requiere fijarlo explícito en el
producto porque el default de `finance` incluye `ANALYTICS`):

```json
{
  "slug": "product-izipay",
  "product_type": "INTEGRATION",
  "status": "PUBLISHED",
  "applies_to": ["WORKFLOWS", "AGENTS", "PAYMENTS", "ANALYTICS"],
  "capabilities": ["payments.checkout.create", "payments.qr.create", "payments.status.get"],
  "events": ["payment.succeeded", "payment.failed", "payment.expired"],
  "included_assets": [{"kind": "integration", "ref": "izipay", "alias": "izipay"}],
  "pricing": {"model": "FREE"},
  "legacy_source": "integration_manifest",
  "legacy_ref": "izipay"
}
```

### Qué acepta hoy el validador de este ejemplo

- ✓ Estructura del manifest: `slug`, `name`, `status`, `auth_modes`,
  `category`, `capabilities` y `pricing` pasan `validate_integration_manifest`.
- ✓ Acciones: los `action_id` `izipay.*` cumplen la regla de prefijo; schemas,
  `risk_level`, `timeout_ms` y `cost_model` son válidos.
- ! Eventos: `validate_event_manifest` exige que el id empiece por `izipay.`
  (o `demo.`). Los eventos canónicos `payment.*` hoy se registran en
  `workflow_event_contracts` (migración 158) y viajan en el producto de
  catálogo; declararlos en el manifest es exactamente el hueco v2 pendiente.
- ! Campos v2 que el validador todavía ignora (no rompen, no se persisten):
  `applies_to`, `credentials`, `health_check`, `webhook`, `sandbox`,
  `compatibility`, `documentation`, `idempotency_scope`.
- Nota de runtime: las capacidades de pago no se ejecutan por
  `marketplace_action` sino por el provider kind `payment_provider`
  (adapters + SecretStore + bindings). Ver `payment-capabilities.md`.

## Cómo se valida

- `validate_integration_manifest(manifest)` → lista de errores (vacía = ok).
  Reglas: slug válido y ≤80, `name`, `status` ∈ `PUBLISHING_STATES`,
  `auth_modes`, `category`, ≥1 capability (o `pricing._pack_kind`), actions de
  cada capability, events, `pricing.model` ∈ `COST_MODELS`.
- `validate_action_manifest(action, slug, capability_slug)`: `action_id` con
  prefijo, `display_name`, `input_schema`/`output_schema` JSON Schema object,
  `risk_level` ∈ `info|normal|elevated|critical`, `timeout_ms` 100..120000,
  `cost_model.model`, `provider_config` (`rest` exige `path_template`;
  `public_rest` exige `base_url` https + `path_template`).
- `validate_event_manifest(event, slug)`: id con prefijo, `business_name`,
  `event_schema` object, `delivery_mode` ∈ `webhook|polling|internal`.
- `register_manifest(manifest, ...)`: valida, aplica la transición de estado
  (`can_transition`), persiste el manifest + capabilities + actions. Un manifest
  con `organization_id` es privado de ese tenant (import API); el slug queda
  reservado por tenant y `list_catalog`/`get_manifest` filtran por organización.

## Estados de publicación

`PUBLISHING_STATES` = `DRAFT`, `SUBMITTED`, `SECURITY_REVIEW`, `APPROVED`,
`PUBLISHED`, `SUSPENDED`, `DEPRECATED`. Transiciones permitidas
(`ALLOWED_PUBLISH_TRANSITIONS`; el no-op al mismo estado también es válido):

| Estado | Transiciones |
| --- | --- |
| `DRAFT` | `SUBMITTED` |
| `SUBMITTED` | `SECURITY_REVIEW`, `DRAFT` |
| `SECURITY_REVIEW` | `APPROVED`, `SUBMITTED`, `SUSPENDED` |
| `APPROVED` | `PUBLISHED`, `SUSPENDED` |
| `PUBLISHED` | `DEPRECATED`, `SUSPENDED` |
| `SUSPENDED` | `APPROVED`, `DRAFT` |
| `DEPRECATED` | `SUSPENDED` (`END_OF_LIFE` no está en `PUBLISHING_STATES`) |

Solo `PUBLISHED` y `DEPRECATED` son visibles/instalables por el resolver.

## Proyección al catálogo

- `factory.sync_catalog_from_assets` corre al arranque (`main._run_startup`) y
  por demanda (`POST /api/v1/platform/marketplace/sync`).
- Manifiestos → `product-<slug>` `INTEGRATION`; **solo rellena campos vacíos**:
  nunca pisa ediciones manuales del Control Center.
- Mapeo de estado: `PUBLISHED`→`PUBLISHED`, `DEPRECATED`→`DEPRECATED`, resto→`DRAFT`.
- `applies_to`: se usa el declarado por el manifest (`integration_manifests.applies_to`);
  si el manifest no declara ninguno, cae a `default_applies_to("INTEGRATION", category)`.
- `included_assets`: `[{kind: "integration", ref: slug, alias: slug}]`.

## Persistencia y validación

- `integration_manifests.contract` (JSONB) guarda el bloque normalizado
  (`models.normalize_contract`): identidad, superficies, capacidades con
  esquemas, eventos con webhook, credenciales por nombre, riesgo, permisos,
  aprobación, idempotencia, rate limits, coste, health check, sandbox,
  compatibilidad y documentación.
- `contract_version` distingue v1 de v2. Un manifest **sin** `contract_version`
  pero con campos v2 (identidad, credenciales, sandbox, compatibilidad…) se
  trata como v2: la versión describe lo que el addon declara, no una etiqueta
  que se pueda omitir.
- `validate_integration_manifest` rechaza valores secretos en `credentials`,
  superficies fuera de `ADDON_APPLIES_TO`, `risk` inválido, firmas de webhook
  desconocidas, ventanas anti-replay fuera de rango, `idempotency.scope`
  inválido y `health_check` http sin `https`.
- Pruebas: `tests/certification/workflows/test_addon_contracts.py`.

## Qué falta (honesto)

- Enforcement de `scopes` en el runtime (hoy son declarativos).
- Polling event adapter (`delivery_mode: "polling"` declarado, sin adapter).
- Eventos canónicos (`payment.succeeded`) como `id` de un manifest de terceros:
  la regla de prefijo (`<slug>.`) lo impide a propósito; los eventos canónicos
  viven en `workflow_event_contracts` y en el producto de catálogo, y el addon
  los mapea en su `webhook` normalizado.
- `END_OF_LIFE` para manifiestos: la transición desde `DEPRECATED` cae hoy a
  `SUSPENDED` porque el estado no está en `PUBLISHING_STATES`.
- Firma de publisher en el paquete de workflow y en el manifest (evolución).

## Referencias

- `docs/architecture/unified-marketplace.md` — catálogo único, capability-first,
  flujo de instalación y readiness.
- `docs/architecture/payment-capabilities.md` — el addon de pagos en runtime.
- `docs/architecture/integration-experience.md` — import OpenAPI, manifests
  privados por tenant, rate limits y pendientes del connector.
