# Payment Capabilities (contrato de pago independiente del proveedor)

Estado: implementado (migración 158). Cubre la deuda "capa PAYMENT fuera de
alcance" declarada en `unified-marketplace.md`.
Fecha: 2026-10-16

## Principio

El workflow declara capacidades (`payments.checkout.create`) y eventos
(`payment.succeeded`); **nunca** un proveedor ("Stripe", "IZIPAY"). El binding
del tenant resuelve la capacidad contra el proveedor elegido y el contrato de
entrada/salida es el mismo para todos.

```
el workflow no sabe quién cobra · el tenant elige el proveedor · el contrato es el mismo
```

Reglas duras (verificadas en código):

- El monto es **server-side**: `amount`/`currency` del input se aceptan por
  compatibilidad de forma y se ignoran; el monto sale de la orden persistida.
- Las credenciales viven en el SecretStore, jamás en el workflow ni en un manifest.
- Un webhook externo nunca se convierte en señal sin verificación de firma.
- El tenant se resuelve desde nuestro propio registro (checkout), nunca del payload.

## Capacidades (contrato exacto)

De `contracts.py` (`CAPABILITY_CONTRACTS`). `provider_kind` del binding:
`payment_provider`.

| Capacidad | Entrada (claves) | Salida (claves) | Flags | Idempotencia |
| --- | --- | --- | --- | --- |
| `payments.checkout.create` | `order_id`, `order_number`, `provider`, `ttl_seconds`, `customer`, `amount`\*, `currency`\* | `checkout_id`, `provider`, `status`, `amount`, `currency`, `reference` | `financial` | `required` |
| `payments.qr.create` | `checkout_id`, `reference` | `qr_payload`, `qr_image_url` | `financial` | — |
| `payments.status.get` | `reference`, `order_number`, `checkout_id` | `status`, `provider`, `amount`, `currency` | `read_only`, `financial` | — |
| `payments.cancel` | `checkout_id`, `reference` | `cancelled` | `financial` | `required` |
| `payments.refund` | `reference`, `amount`, `reason` | `refunded` | `financial` | `required` |

\* `amount`/`currency` de `checkout.create` se ignoran: el monto y la moneda se
copian de la orden persistida (`store.create_checkout` → `order["total"]`,
`order["currency"]`).

Implementación:

| Capacidad | Función | Efecto |
| --- | --- | --- |
| `checkout.create` | `payments.create_checkout` | crea o recupera el checkout; pasa la orden a `AWAITING_PAYMENT`; aplica la política de reserva |
| `qr.create` | `payments.create_qr` | devuelve el `qr_payload`/`checkout_url` del checkout local (no llama al proveedor) |
| `status.get` | `payments.payment_status` | estado local (autoridad) + `provider_status` consultivo |
| `cancel` | `payments.cancel_payment` | cancela el checkout, la orden `AWAITING_PAYMENT` → `CANCELLED` y libera reservas |
| `refund` | `payments.refund_payment` | solo sobre un checkout `succeeded`; reembolsa vía adapter y marca el checkout `refunded` |

## Eventos normalizados

De `contracts.py` (`PAYMENT_EVENTS`) y del mapeo de estados de los adapters
(`_event_type_for_status`):

| Evento | Estados del proveedor que lo producen | Efecto local ANTES de la señal |
| --- | --- | --- |
| `payment.pending` | `PENDING`, `RUNNING`, `INITIAL`, `CREATED` | checkout `pending` |
| `payment.succeeded` | `PAID`, `CAPTURED`, `AUTHORISED`, `AUTHORIZED`, `SUCCEEDED` | checkout `succeeded`; **la orden NO se marca PAID aquí** |
| `payment.failed` | `REFUSED`, `FAILED`, `UNPAID`, `REJECTED` | checkout `failed` + `stock_release` + aviso al cliente |
| `payment.expired` | `EXPIRED` | checkout `expired` + `stock_release` + aviso al cliente |
| `payment.refunded` | `REFUNDED`, `PARTIALLY_REFUNDED` | checkout `refunded` |
| `payment.cancelled` | `CANCELLED`, `CANCELED` | checkout `cancelled` + `stock_release` + aviso |

`payment.cancelled` existe como constante (`EVENT_PAYMENT_CANCELLED`) y el
adapter lo normaliza, pero **no** está en la tupla `PAYMENT_EVENTS` que se
declara en el proveedor del tenant (pendiente de decidir si se publica).

Estados locales del checkout: `pending`, `succeeded`, `failed`, `expired`,
`cancelled`, `refunded`. Terminales (`_TERMINAL_CHECKOUT`): todos menos
`pending`. Idempotencia de estado (`_apply_event_state`): repetir el mismo
estado es no-op; un `succeeded` solo puede pasar a `refunded`; un `failed` o
`expired` puede cerrarse en `succeeded` si el cliente reintenta y el proveedor
confirma el pago con el mismo checkout.

`payment.succeeded` **no** cierra la venta: eso es un paso explícito del
workflow (`sales.order.mark_paid`), para que la venta la cree el proceso de
negocio y no un payload externo.

## Binding: capability → provider del tenant

El workflow nunca nombra al proveedor. La resolución:

```
capability (payments.checkout.create)
   │  execute_binding → provider_kind = payment_provider
   ▼
binding del tenant (workflow_capability_bindings.config = {"provider": "...", "mode": "..."})
   │  _execute_payment: si el payload no trae provider, usa el del binding
   ▼
ensure_provider(): input → config del binding → sandbox (default)
   │
   ▼
adapter (build_adapter): izipay | stripe | sandbox
```

- `configure_provider(org, provider, secrets, mode, config)` guarda credenciales
  en el SecretStore, registra el proveedor (`commerce_payment_providers`) y
  bindea las 5 capacidades de pago con `provider_kind="payment_provider"`,
  `config={"provider": ..., "mode": ...}` y `credential_ref`.
- `DEFAULT_PAYMENT_PROVIDER = "sandbox"`: sin binding ni proveedor configurado,
  el camino por defecto es el sandbox determinista (mismos contratos, sin red).
- Un proveedor real sin credenciales falla accionable:
  `NEEDS_CREDENTIALS` ("no tiene configuradas las credenciales: ...").
- API del tenant: `GET/PUT /api/v1/commerce/payments/providers[/{provider}]`.
  La respuesta del PUT nunca incluye secretos (solo `credential_ref`).

## Flujo del provider event adapter

```
pasarela (IZIPAY / Stripe / sandbox)
        │  POST /api/v1/public/payments/{provider}/webhook   (sin sesión; firma obligatoria)
        ▼
1. verificación de firma        adapter.verify_webhook(raw_body, headers)
        │                       se prueban los tenants que tienen ese provider configurado;
        │                       si ninguno valida → 400 SIGNATURE_INVALID (fail closed)
        ▼
2. normalización                NormalizedPaymentEvent
        │                       (event_type canónico, reference, provider_event_id,
        │                        amount, currency, signature_mode, raw)
        ▼
3. dedupe                       INSERT commerce_provider_events (provider, provider_event_id)
        │                       ON CONFLICT DO NOTHING → "duplicate" = fin (cero efectos)
        ▼
4. resolución de tenant         find_checkout_any_tenant(provider, provider_reference)
        │                       o find_checkout_by_reference_any_tenant(reference)
        │                       (NUNCA del payload; sin checkout → "unmatched")
        ▼
5. efectos locales (autoridad)  checkout.status; stock_release; aviso al cliente
        ▼
6. BusinessEvent                payment.succeeded / payment.failed / payment.expired / ...
        ▼
7. señal                        signal_workflow_instance(
        │                         event_type = evento canónico,
        │                         correlation = {"payment_reference": <order_number>},
        │                         external_event_id = "{provider}:{provider_event_id}",
        │                         idempotency_key  = "payevt:{provider}:{provider_event_id}",
        │                         instance_id = checkout.workflow_instance_id)
        ▼
8. resume                       claim WAITING→RUNNING; segmento nuevo desde el WAIT;
                                misma instancia, mismo estado, mismo checkout
```

Notas del flujo:

- La correlación canónica es `payment_reference` y es exactamente la que declara
  el WAIT del embudo (`payment_reference = order_number`), sin heurísticas.
- El webhook responde `{status: processed|duplicate|unmatched, event_type,
  matched, signal: {...}}`; `SIGNATURE_INVALID`/`PROVIDER_UNKNOWN` → 400, otros
  errores de proveedor → 422.
- El evento de proveedor queda auditado en `commerce_provider_events`
  (`verified`, `signature_mode`, `processing_status` ∈
  `received|processed|duplicate|unmatched|rejected`).
- **Un payload externo nunca elige organización ni instancia**: la organización
  sale del checkout encontrado por `provider_reference` (o por nuestra
  `reference`); si no hay checkout, el evento queda `unmatched` sin señal.

### Dos guardas que impiden que un evento externo cambie el negocio

1. **El evento debe ser el que la instancia espera.** `signal_workflow_instance`
   valida, en el camino directo por `instance_id`, que
   `event_type == waiting_event_type` (además de la correlación). Un
   `payment.failed` **no** despierta un WAIT de `payment.succeeded`: si lo
   hiciera, un rechazo del proveedor terminaría en una venta. La señal queda en
   el inbox (`status: event_mismatch`) y el proceso sigue esperando.
   El evento interno `workflow.wait.timeout` está exento (lo emite el sweep).
2. **El monto del evento debe coincidir con el checkout.** Si el evento
   normalizado trae importe y no es igual al monto persistido, se registra como
   `amount_mismatch` y se responde 422 sin tocar la orden ni el workflow: el
   dinero no se mueve por un payload con otro importe.

## Idempotencia extremo a extremo

Identidad financiera estable (`store.stable_operation_key`):

```
idempotency_key = sha256(organization_id | workflow_instance_id | node_id | business_operation_id)[:80]
```

- `business_operation_id = "checkout:{order_number}"` lo fija
  `create_checkout`; `workflow_instance_id` y `node_id` llegan del runtime
  (`_exec_capability_call` → `execute_binding(instance_id, node_id)`).
- El **attempt no forma parte de la identidad**. El runtime usa
  `"{correlation_id}:{node_id}:{attempt}"` como clave de nodo, pero la operación
  financiera se identifica con la clave estable: un retry por timeout repite la
  MISMA operación lógica y devuelve el mismo checkout.
- Constraint real: `commerce_checkout_sessions` UNIQUE
  `(organization_id, idempotency_key)` + `ON CONFLICT DO NOTHING`; antes de
  crear, `create_checkout` busca por `idempotency_key` y devuelve el existente.
- Idempotencia de las otras capas:

| Capa | Constraint | Efecto del duplicado |
| --- | --- | --- |
| Orden | `commerce_orders` UNIQUE parcial `(organization_id, business_operation_id)` | devuelve la MISMA orden |
| Checkout | `commerce_checkout_sessions` UNIQUE `(organization_id, idempotency_key)` | devuelve el MISMO checkout |
| Evento de proveedor | `commerce_provider_events` UNIQUE `(provider, provider_event_id)` | `duplicate`, cero efectos |
| Señal | `workflow_signals` uniques parciales por `(org, event_type, external_event_id)` y `(org, idempotency_key)` | `duplicate`, no reanuda |
| Reservas | `_settle_reservations` solo mueve filas `held` | repetir release/commit no vuelve a mover stock |

Escenarios certificados (`tests/certification/workflows/test_provider_failure.py`):

| Escenario | Resultado |
| --- | --- |
| Timeout del proveedor al crear checkout + retry | no deja checkout huérfano; el retry devuelve el MISMO checkout; nunca dos cobros |
| Webhook duplicado (mismo `provider_event_id`) | `duplicate`; una sola venta y un solo descuento de stock |
| `payment.failed` + reintento del cliente | la instancia sigue viva; al pagar, venta única con el mismo checkout |
| Reinicio de la API entre checkout y webhook | la instancia vive en Postgres; el webhook la reanuda (`test_durability_restart.py`) |

## Secretos por proveedor

| Proveedor | Claves declaradas (`PROVIDER_SECRET_KEYS`) | `required_secrets` del adapter | Firma de webhook | QR |
| --- | --- | --- | --- | --- |
| `izipay` | `merchant_code`, `api_key`, `hash_key` | `merchant_code`, `api_key` (`hash_key` opcional: si falta se usa `api_key`) | KR-Hash (HMAC-SHA256) | sí |
| `stripe` | `secret_key`, `webhook_secret` | `secret_key`, `webhook_secret` | `Stripe-Signature` (`t`/`v1`) | no (`supports_qr = False`) |
| `sandbox` | `webhook_secret` | `webhook_secret` | `X-Zent-Signature: sha256=` | sí |

Almacenamiento:

- SecretStore (`src/infrastructure/secrets`), connector UUID determinista por
  `(organización, proveedor)`:
  `credential_connector_id = uuid5(namespace, "{organization_id}:{provider}")`.
- `commerce_payment_providers.credential_ref` y el `credential_ref` del binding
  apuntan a ese connector; `ensure_provider` lo lee en cada operación.
- `health()` del adapter reporta `{provider, ready, missing_credentials, mode}`.
- Sandbox sin secreto configurado usa el fallback local
  `"zent-sandbox-payment-secret"` (solo dev/CI; el Gold Test configura su propio
  secreto).

## Firma de webhooks (algoritmo exacto)

### Stripe

1. Header `Stripe-Signature`, formato `t=<timestamp>,v1=<hex>` (partes separadas
   por coma).
2. Ventana anti-replay: `abs(now - t) > 300s` → `SIGNATURE_INVALID`.
3. `expected = HMAC-SHA256(webhook_secret, f"{t}." + raw_body)`; comparación con
   `hmac.compare_digest`.
4. `body.id` es obligatorio (`event id requerido`).
5. Mapeo de tipos: `checkout.session.completed` / `payment_intent.succeeded` →
   `payment.succeeded`; `checkout.session.expired` → `payment.expired`;
   `payment_intent.payment_failed` → `payment.failed`; `charge.refunded` →
   `payment.refunded`; fallback por `payment_status`/`status`.

### IZIPAY (Lykke / micuentaweb V4)

1. Body JSON **o** `application/x-www-form-urlencoded` con `kr-answer` (JSON
   serializado como string), `kr-hash` (HMAC-SHA256 hex) y `kr-hash-key`.
2. `kr-hash-key == "password"` → la llave es `api_key`; en cualquier otro caso
   `hash_key` (con fallback a `api_key`).
3. `expected = HMAC-SHA256(llave, kr-answer)`; comparación con `hmac.compare_digest`
   (`KR-Hash inválido` si no coincide).
4. `provider_event_id` = uuid de la primera transacción, o `orderId`, o
   `orderId:orderStatus`; `reference` = `orderDetails.orderId`.
5. Estado → evento con `_event_type_for_status` (`orderStatus`).

### Sandbox

1. Header `X-Zent-Signature: sha256=<hex>` (obligatorio).
2. `expected = HMAC-SHA256(webhook_secret, raw_body)`; comparación con
   `hmac.compare_digest`.
3. `event_id` obligatorio; `status` default `"paid"`; acepta `event_type`
   explícito o lo deriva de `status`.

## Política de reserva de inventario

Configurable por workflow (`variables.reservation_policy`; default `checkout`):

| Política | Comportamiento implementado |
| --- | --- |
| `checkout` (default) | reserva al crear el checkout (`ttl_seconds`, default 1800s); sin stock → checkout `failed` y error `STOCK_INSUFFICIENT_STOCK` (el checkout no debe existir sin reserva posible) |
| `none` | sin reserva al crear checkout; el `commit` al pagar no mueve stock (no hay reservas `held`) |
| `payment` | declarada en el contrato; hoy `_maybe_reserve` no reserva en el pago (pendiente de implementar) |

Qué pasa en `payment.failed` / `payment.expired` / `payment.cancelled`:

1. `stock_release`: reservas `held` → `released` (stock `reserved` baja).
2. La orden **no** pasa a `PAID`: sigue `AWAITING_PAYMENT`.
3. Aviso determinista al cliente (`_notify_customer` → notificación `in_app` con
   el evento; no depende del LLM ni del workflow).
4. La instancia sigue viva: puede reintentar con el mismo checkout. Al llegar el
   `payment.succeeded`, el workflow marca la orden `PAID` y confirma inventario
   (`inventory.commit`).

Cierre sin pago (timeout del WAIT): la rama `timeout` del embudo pasa por
`pago_no_completado` → `cancelar_orden` (orden `CANCELLED`) → `liberar_inventario`.

## Seguridad

- **Monto server-side**: `_CHECKOUT_CREATE_INPUT` acepta `amount`/`currency` pero
  `create_checkout` usa `order["total"]`/`order["currency"]`. Certificado en
  `test_provider_failure.py::test_amount_is_server_side_and_ignored_from_input`
  (input `amount=0.01, currency=USD` → checkout `11.40 PEN`).
- **Sin credenciales en el workflow**: el grafo solo nombra capacidades; los
  secretos los resuelve `ensure_provider` desde el SecretStore.
- **Sin monto controlado por el LLM**: el LLM no participa en ninguna ruta de
  dinero (precio, total, cobro y estado salen de `store` y de los adapters).
- **Webhook fail-closed**: sin firma válida no hay normalización, ni dedupe
  `verified`, ni señal; el evento rechazado queda auditado como `rejected`.
- **Tenant desde nuestro registro**: `find_checkout_any_tenant` /
  `find_checkout_by_reference_any_tenant`; el payload no puede elegir
  organización ni instancia (certificado en `test_tenant_isolation.py`).
- **Circuit breaker por tenant** (`service.py`): 5 fallos consecutivos abren el
  circuito 60s; mientras está abierto, `create_checkout` falla rápido con
  `PROVIDER_CIRCUIT_OPEN` (sin martillar la pasarela). Un cobro sano lo cierra
  (`failures = 0`). Estado en `commerce_payment_providers.health.circuit`.

## Pendiente declarado

- **Refunds reales requieren credenciales**: `payments.refund` sobre IZIPAY/Stripe
  exige `merchant_code`/`api_key` o `secret_key`; sin ellas el adapter responde
  `NEEDS_CREDENTIALS`. El sandbox reembolsa siempre.
- **El estado remoto es consultivo; el local es la autoridad**: `payment_status`
  devuelve el estado del checkout local y añade `provider_status`; si el
  proveedor no responde, `provider_status = "unavailable:{code}"` y la respuesta
  sigue siendo válida. El sandbox responde `PROVIDER_STATUS_LOCAL` ("el estado
  local es la autoridad").
- `payments.qr.create` es local: devuelve el `qr_payload` del checkout; para
  IZIPAY/sandbox es la URL de pago y `qr_image_url` es `null` hoy.
- `payments.refund` acepta `amount` opcional del input (a diferencia de
  `checkout.create`, donde el monto se ignora siempre).
- Política de reserva `payment` sin implementación (declarada en el contrato).
- `payment.cancelled` no está en `PAYMENT_EVENTS` (sí se normaliza y aplica).
- No hay anti-replay propio para IZIPAY/sandbox más allá del dedupe por
  `provider_event_id`; Stripe aporta la ventana de 300s.

## Referencias

- `src/platform/commerce/contracts.py` — capacidades, eventos, estados,
  proveedores y claves de secreto.
- `src/platform/commerce/payments/service.py` — checkout, ingestión y señal.
- `src/platform/commerce/payments/providers.py` — adapters y firmas.
- `src/platform/commerce/store.py` — tablas `commerce_*` e idempotencia.
- `docs/architecture/sales-funnel-gold-workflow.md` — el embudo que consume
  estas capacidades.
- `docs/architecture/addon-contract-v2.md` — declaración del addon IZIPAY.
