# Retail Sales Funnel — Gold Workflow (ventas por conversación)

Estado: implementado (migración 158: plantilla `retail_sales_funnel` + producto
de marketplace `retail-sales-funnel`; migración 159: Addon Contract v2).
Fecha: 2026-10-17

## Qué certifica

```
CONVERSATION → DURABLE WORKFLOW → REAL BUSINESS DATA → CART → WAIT/RESUME
→ PAYMENT → VERIFIED EVENT → BUSINESS TRANSACTION → COMPLETION

EXPORT → IMPORT → DEPENDENCY RESOLUTION → RECONFIGURE → EXECUTE
```

Cada eslabón tiene un test de certificación en `tests/certification/workflows/`:

| Eslabón | Qué prueba | Test |
| --- | --- | --- |
| CONVERSATION | el primer mensaje arranca una `WorkflowInstance` durable | `test_gold_sales_funnel.py` |
| DURABLE WORKFLOW | la MISMA instancia sobrevive todos los turnos y el reinicio | `test_gold_sales_funnel.py`, `test_durability_restart.py` |
| REAL BUSINESS DATA | precios/stock del catálogo del tenant (nunca del LLM) | `test_gold_sales_funnel.py`, `test_tenant_isolation.py` |
| CART | el carrito vive en `instance.state` y se cotiza server-side | `test_gold_sales_funnel.py` |
| WAIT/RESUME | cada turno es un WAIT; el mensaje reanuda por señal | `test_gold_sales_funnel.py`, `test_durability_restart.py` |
| PAYMENT | un solo checkout, idempotencia por timeout | `test_gold_sales_funnel.py`, `test_provider_failure.py` |
| VERIFIED EVENT | firma obligatoria; duplicados sin doble efecto | `test_gold_sales_funnel.py` |
| BUSINESS TRANSACTION | una sola venta, un solo descuento de inventario | `test_gold_sales_funnel.py`, `test_durability_restart.py` |
| COMPLETION | la instancia cierra `COMPLETED` una sola vez | `test_gold_sales_funnel.py` |
| EXPORT → EXECUTE | paquete portable → import → deps → reconfigurar → ejecutar | `test_portability.py`, `test_marketplace_dependency_resolution.py` |

## Canvas (nodo ids reales)

Grafo acíclico de 40 nodos y 44 edges; entrypoint `cliente`
(`conversation.message`). Los WAIT se marcan `[WAIT]` y los bucles `[loop→target]`.

### Diagrama A — descubrimiento, selección y carrito

```
cliente ─► buscar ─► encontrado
                       ├─ no ─► preguntar_otra_vez ─► esperar_aclaracion [WAIT]
                       │            └─► reintentar_busqueda [loop→buscar] ─► buscar
                       └─ sí ─► unico
                                  ├─ una sola ─► agregar_directo ─► resumen_carrito
                                  └─ varias ──► guardar_opciones ─► mostrar_opciones ─► esperar_eleccion [WAIT]
                                                                          └─► elegir ─► eleccion_valida
                                                                                          ├─ no ─► no_entendido ─► esperar_reintento_eleccion [WAIT]
                                                                                          │            └─► reintentar_eleccion [loop→elegir] ─► elegir
                                                                                          └─ sí ─► verificar_stock ─► agregar_carrito ─► resumen_carrito
                                                                                                      └─► preguntar_mas ─► esperar_mas [WAIT] ─► nada_mas
                                                                                                                ├─ otro producto ─► volver_al_catalogo [loop→buscar] ─► buscar
                                                                                                                └─ nada más ─► pedir_confirmacion ─► esperar_confirmacion [WAIT]
                                                                                                                                  └─► confirmado
                                                                                                                                        ├─ no ─► confirmar_otra_vez [loop→pedir_confirmacion]
                                                                                                                                        └─ sí ─► (continúa en el diagrama B)
```

### Diagrama B — pago y cierre

```
crear_orden ─► crear_checkout ─► enviar_pago ─► esperar_pago [WAIT payment]
                                                     ├─ out ─────► marcar_pagada ─► confirmar_inventario ─► mensaje_final ─► resultado ─► fin
                                                     └─ timeout ─► pago_no_completado ─► cancelar_orden ─► liberar_inventario ─► fin_pago
```

Roles de canvas (`metadata.canvas_role`, iconografía): `cliente` trigger;
`buscar`, `elegir`, `verificar_stock`, `agregar_carrito` data; `encontrado`,
`unico`, `eleccion_valida`, `nada_mas`, `confirmado` decision; `esperar_*`
wait (excepto `esperar_pago` = payment); `crear_checkout` payment; `resultado`
business_result; `fin`/`fin_pago` end; el resto action.

### Edges (44)

| Desde | Puerto | Hacia | Etiqueta |
| --- | --- | --- | --- |
| `cliente` | out | `buscar` | |
| `buscar` | out | `encontrado` | |
| `encontrado` | then | `unico` | sí |
| `encontrado` | else | `preguntar_otra_vez` | no |
| `unico` | then | `agregar_directo` | una sola |
| `unico` | else | `guardar_opciones` | varias |
| `agregar_directo` | out | `resumen_carrito` | |
| `guardar_opciones` | out | `mostrar_opciones` | |
| `mostrar_opciones` | out | `esperar_eleccion` | |
| `esperar_eleccion` | out | `elegir` | |
| `preguntar_otra_vez` | out | `esperar_aclaracion` | |
| `esperar_aclaracion` | out | `reintentar_busqueda` | |
| `reintentar_busqueda` | out | `buscar` | |
| `elegir` | out | `eleccion_valida` | |
| `eleccion_valida` | then | `verificar_stock` | sí |
| `eleccion_valida` | else | `no_entendido` | no |
| `no_entendido` | out | `esperar_reintento_eleccion` | |
| `esperar_reintento_eleccion` | out | `reintentar_eleccion` | |
| `reintentar_eleccion` | out | `elegir` | |
| `verificar_stock` | out | `agregar_carrito` | |
| `agregar_carrito` | out | `resumen_carrito` | |
| `resumen_carrito` | out | `preguntar_mas` | |
| `preguntar_mas` | out | `esperar_mas` | |
| `esperar_mas` | out | `nada_mas` | |
| `nada_mas` | then | `pedir_confirmacion` | nada más |
| `nada_mas` | else | `volver_al_catalogo` | otro producto |
| `volver_al_catalogo` | out | `buscar` | |
| `pedir_confirmacion` | out | `esperar_confirmacion` | |
| `esperar_confirmacion` | out | `confirmado` | |
| `confirmado` | then | `crear_orden` | sí |
| `confirmado` | else | `confirmar_otra_vez` | no |
| `confirmar_otra_vez` | out | `pedir_confirmacion` | |
| `crear_orden` | out | `crear_checkout` | |
| `crear_checkout` | out | `enviar_pago` | |
| `enviar_pago` | out | `esperar_pago` | |
| `esperar_pago` | out | `marcar_pagada` | |
| `marcar_pagada` | out | `confirmar_inventario` | |
| `confirmar_inventario` | out | `mensaje_final` | |
| `mensaje_final` | out | `resultado` | |
| `resultado` | out | `fin` | |
| `esperar_pago` | timeout | `pago_no_completado` | sin pago |
| `pago_no_completado` | out | `cancelar_orden` | |
| `cancelar_orden` | out | `liberar_inventario` | |
| `liberar_inventario` | out | `fin_pago` | |

Nota: `resumen_carrito` tiene dos entradas (`agregar_directo` y
`agregar_carrito`); el scheduler la ejecuta cuando la rama tomada resuelve sus
edges.

## El bucle conversacional sin ciclos

El grafo **no tiene ciclos**: los bucles son nodos `loop` y la repetición la
hace la instancia durable. No hay proceso esperando en memoria.

- `_exec_loop` (nodo `loop`): lee/incrementa el contador `__loops.<target>` en
  `instance.state` (CAS), corta en `max_iterations` (clamp 1..100, default 20) y
  devuelve `control="loop_back"` con `{loop, target, iteration, max_iterations}`.
- El runtime (`runtime.py`) trata `loop_back` como cierre de segmento
  (`run_status = "looping"`); `engine.run_workflow` llama a
  `handle_segment_result(..., looping, loop_node_id)`.
- `_continue_loop` (instances.py): valida que el target exista, calcula el
  **cuerpo del bucle** y arranca un segmento nuevo con `trigger="loop"` y el
  `trigger_payload` del segmento anterior (continuidad del mensaje del cliente).
- `_loop_body(graph, target, loop_node_id)` = nodos alcanzables desde `target`
  ∩ nodos que vuelven al nodo `loop`. Ese conjunto queda **fuera** del preload:
  `preload_scope = preload_completo − cuerpo`. El resto del proceso (carrito,
  orden, contexto, datos ya resueltos) se conserva y no se re-ejecuta.
- `load_instance_preload(..., scope)` acota el checkpoint acumulado a ese scope;
  `run_workflow` re-deriva los edges de los nodos preloaded
  (`resolve_preload_edges`) y continúa exactamente desde el próximo nodo.
- Trazabilidad: evento `loop_reentered` con `{target, iteration, reset_nodes,
  segment_seq}` en el timeline de la instancia.

Bucles del embudo:

| Nodo `loop` | Target | `max_iterations` | Uso |
| --- | --- | --- | --- |
| `reintentar_busqueda` | `buscar` | 12 | el cliente reformula el producto |
| `reintentar_eleccion` | `elegir` | 12 | la selección no se entendió |
| `volver_al_catalogo` | `buscar` | 20 | el cliente pide otro producto |
| `confirmar_otra_vez` | `pedir_confirmacion` | 3 | el cliente no confirmó |

El contador vive en `instance.state` (`__loops.<target>`), así que un bucle no
se "pierde" entre segmentos ni con la API caída.

## WAIT como checkpoint

- Preset `message` → evento `conversation.message`; correlación por
  `conversation_id` (la instancia lo aporta).
- Preset `payment` (`esperar_pago`) → evento `payment.succeeded`; correlación
  declarada `payment_reference = {{nodes.crear_orden.output.order_number}}`;
  timeout `payment_timeout` (ISO 8601, default `PT30M`) con
  `on_timeout: "branch"` (rama `timeout` → cierre sin pago).
- Los 6 WAIT del canvas: `esperar_eleccion`, `esperar_aclaracion`,
  `esperar_reintento_eleccion`, `esperar_mas`, `esperar_confirmacion`
  (timeout 24h, `on_timeout: "expire"`) y `esperar_pago`.
- Cada WAIT libera el worker: el segmento termina y la reanudación llega por
  señal (mensaje del cliente, webhook del proveedor, timeout del scheduler).

## Autoridad LLM vs determinismo

El LLM **no participa en ninguna ruta de dinero**:

| Decisión | Autoridad |
| --- | --- |
| Intención/entidades del mensaje (producto, cantidad, unidad) | parser determinista `textparse.parse_order_line` (stopwords, unidades, números) |
| ¿Encontró producto? / ¿una sola opción? | condiciones sobre `{{nodes.buscar.output.count}}` |
| Selección del cliente | `catalog.product.get` con similitud determinista (`token_score`) |
| Precio, stock, total | `store` (catálogo + inventario persistidos) |
| Monto del cobro | orden persistida (`order["total"]`); `amount` del input se ignora |
| Estado de la orden y del pago | `commerce_orders` / `checkout` locales |
| Mensajes con montos | formateados server-side (`format_money`, `CURRENCY_SYMBOLS`) |

Puntos de intención deterministas del canvas:

- `nada_mas`: `{{trigger.text}}` `contains` `{{variables.closer_markers}}`
  (default `"nada"`).
- `confirmado`: `{{trigger.text}}` `{{variables.affirmative_operator}}`
  `{{variables.affirmative_marker}}` (default `not_contains` `"no"`).

En Studio esos puntos se pueden sustituir por un nodo de IA (`ai_decision`) sin
tocar el resto del proceso: la única regla es que el LLM puede proponer la
lectura de una frase ambigua, nunca fijar el número que termina en una orden o
un cobro.

## Parámetros configurables

`DEFAULT_PARAMETERS` viaja en `graph.variables` y en el
`configuration_schema` del producto:

| Parámetro | Default | Consumido por el grafo |
| --- | --- | --- |
| `currency` | `PEN` | `crear_orden` (`{{variables.currency}}`) |
| `reservation_policy` | `checkout` | `crear_orden` (metadata de la orden → `_maybe_reserve`) |
| `payment_timeout` | `PT30M` | `esperar_pago` (timeout ISO 8601) |
| `confirmation_message` | `¿Confirmas el pedido?` | `pedir_confirmacion` |
| `completion_message` | `¡Pago confirmado! Tu pedido está en preparación.` | `mensaje_final` |
| `closer_markers` | `nada` | `nada_mas` (condition `contains`) |
| `affirmative_operator` | `not_contains` | `confirmado` |
| `affirmative_marker` | `no` | `confirmado` |
| `maximum_cart_items` | `20` | declarado; hoy el grafo no lo lee (pendiente) |
| `allow_alternatives` | `true` | declarado; hoy el grafo no lo lee (pendiente) |
| `allow_cross_sell` | `false` | declarado; hoy el grafo no lo lee (pendiente) |
| `require_stock` | `true` | declarado; hoy el grafo no lo lee (pendiente) |

El timeout de los WAIT de conversación es fijo (`conversation_wait = 86400s` en
`build_graph`), no un parámetro.

## Dependencias y readiness

`DEPENDENCIES` del paquete (capability-first):

- capacidades: `catalog.products.search`, `catalog.product.get`,
  `sales.cart.quote`, `inventory.stock.get`, `sales.order.create`,
  `sales.order.mark_paid`, `inventory.commit`, `payments.checkout.create`,
  `conversation.send`.
- eventos: `payment.succeeded`, `conversation.message`.

Readiness (`sales_funnel.readiness_items()` →
`GET /api/v1/commerce/sales-funnel/readiness`), checklist ✓/!:

| Ítem | Capacidades | Estado |
| --- | --- | --- |
| Catálogo | `catalog.products.search`, `catalog.product.get` | ✓ si hay binding |
| Inventario | `inventory.stock.get`, `inventory.commit`, `inventory.release` | ✓ si hay binding |
| Ventas | `sales.order.create`, `sales.order.mark_paid`, `sales.cart.quote` | ✓ builtin (Zent crea la venta) |
| Mensajería | `conversation.send`, `conversation.message` | ✓ builtin (addon `zent-messaging`) |
| Pago | `payments.checkout.create`, `payment.succeeded` | ✓ si el proveedor está configurado |

Respuesta: `{title: "Configura tu embudo", ready: bool, items: [...]}`. Un ítem
en `attention` trae el CTA `{kind: "marketplace", filter: "payments", label:
"Configurar medio de pago"}` — es la vista del **Marketplace global** filtrada
en pagos; el hint es humano ("IZIPAY está disponible; configura tus
credenciales para cobrar."), sin nombres técnicos de capacidades.

Certificado en `test_marketplace_dependency_resolution.py`: con el tenant
limpio, catálogo/inventario/pago están en `attention`, ventas/mensajería en
`ok`, y tras configurar todo el checklist queda `ready: true`.

## Escenario del Gold Test paso a paso

`tests/certification/workflows/test_gold_sales_funnel.py`
(`test_gold_retail_sales_funnel_end_to_end`). Tenant con catálogo real
(Arroz Costeño 5.90, Arroz Paisana 5.50, Arroz Integral 7.20, Leche Gloria
4.20), bindings `commerce` + `conversation` y sandbox de pagos firmado.

| Turno | Mensaje | Nodo donde queda el WAIT | Qué se verifica |
| --- | --- | --- | --- |
| 1 | "quiero 1 kilo de arroz" | `esperar_eleccion` | MISMA instancia desde el arranque; `buscar` ejecutado exactamente 1 vez; opciones reales en `state.catalog.options` con precios 5.90 / 5.50 / 7.20 |
| 2 | "mejor integral" | `esperar_mas` | `run_seq >= 2` (mismo proceso, segundo segmento); carrito con 1 línea: Arroz Integral, cantidad 1.0, unit_price 7.20; NO se repite `buscar` |
| 3 | "también una leche" | `esperar_mas` | el loop `volver_al_catalogo` re-ejecuta el cuerpo: `buscar` acumula 2 ejecuciones; carrito con 2 líneas {Arroz Integral, Leche Gloria}; el arroz NO se duplica |
| 4 | "no, nada más" | `esperar_confirmacion` | resumen y pedido de confirmación |
| 5 | "sí" | `esperar_pago` | 1 sola orden `AWAITING_PAYMENT`, total 11.40 PEN, `workflow_instance_id` = la instancia; 1 solo checkout `pending` con `qr_payload` y monto server-side |
| webhook | `payment.succeeded` firmado (sandbox) | — | `processed` + `matched` + `signal.resumed`; instancia `COMPLETED`; `marcar_pagada`/`confirmar_inventario`/`mensaje_final`/`resultado` ejecutados 1 vez cada uno; orden `PAID` con `paid_at` y `payment_provider=sandbox`; stock 14/29 disponible y 0 reservado (un solo descuento); timeline con ≥4 `wait_entered` y exactamente 1 `instance_completed` |

Otros escenarios del mismo archivo:

- **Cambio de opinión** (`test_gold_change_of_mind_keeps_same_instance_and_empty_cart`):
  tras ver las opciones el cliente dice "no quiero ese" → no es un producto, el
  carrito queda vacío y el embudo vuelve a preguntar (`esperar_reintento_eleccion`);
  en el siguiente turno "mejor integral" entra al carrito en la MISMA instancia y
  el proceso llega a cobrar (7.20).
- **Webhook duplicado** (`test_gold_duplicate_webhook_has_single_business_effect`):
  el mismo `event_id` dos veces → primero `processed`, segundo `duplicate`; una
  sola orden `PAID`, un solo descuento de stock, instancia `COMPLETED`.
- **Firma inválida** (`test_gold_invalid_signature_is_rejected`): secreto
  incorrecto → 400 con `details.code == SIGNATURE_INVALID`; la orden sigue
  `AWAITING_PAYMENT`, la instancia sigue `WAITING` y la reserva sigue viva
  (stock 15, reserved 1). Sin firma válida no hay señal, ni siquiera con payload
  correcto.

### Escenario de portabilidad (EXPORT → EXECUTE)

`test_portability.py::test_export_import_dependency_resolution_and_execution`:

1. **EXPORT** (tenant A): `GET /api/v1/workflows/{id}/export` → paquete
   `zent.workflow.package/v1` con `security.contains_secrets = false` y las
   dependencias capability-first (`catalog.products.search`,
   `inventory.stock.get`, `payments.checkout.create`, `payment.succeeded`,
   `conversation.message`, `conversation.send`).
2. **IMPORT** (tenant B limpio): `POST /api/v1/workflows/import/inspect` reporta
   `MISSING` para catálogo/inventario/pago y `RESOLVED` para mensajería
   (la provee el addon builtin); con bloqueos, `POST /api/v1/workflows/import`
   responde 409 (sin estados parciales).
3. **DEPENDENCY RESOLUTION**: se bindean catálogo, inventario, ventas,
   conversación y se configura el sandbox de pagos → todo `RESOLVED`,
   `blocking: 0`.
4. **RECONFIGURE**: import → workflow draft → `POST /{id}/publish`.
5. **EXECUTE**: el flujo importado corre con los datos de B ("Arroz del Sur"
   6.10) y el carrito del tenant B.

También certifica que un paquete con secretos (`contains_secrets: true` o clave
`api_key`) es `UNSAFE` y el import responde 409.

### Escenario de marketplace

`test_marketplace_dependency_resolution.py`: el producto `retail-sales-funnel`
está PUBLISHED en el catálogo global (`WORKFLOW_TEMPLATE`, `applies_to`
WORKFLOWS/AGENTS, capabilities y `payment.succeeded`, pricing `FREE`);
instalar sin dependencias no deja un workflow publicado; una capability se
resuelve por el binding del tenant (`provider_kind = commerce` con su contrato);
`conversation.send` lo provee el addon builtin `zent-messaging`.

## Tests de certificación y cómo correrlos

`tests/certification/workflows/`:

| Archivo | Qué certifica |
| --- | --- |
| `test_gold_sales_funnel.py` | end-to-end + webhook duplicado + firma inválida + cambio de opinión del cliente |
| `test_durability_restart.py` | reinicio lógico, sweep idempotente, expiración del WAIT sin efectos |
| `test_payment_failures.py` | `payment.failed`/`expired` liberan reserva, orden no pagada, cliente informado, reintento; rama timeout del checkout |
| `test_provider_failure.py` | timeout del proveedor + retry = mismo checkout; circuit breaker; monto server-side |
| `test_portability.py` | export/import, resolución de dependencias, reconfiguración y ejecución en otro tenant |
| `test_marketplace_dependency_resolution.py` | producto global, readiness con CTA, instalación sin deps, capability-first, addon builtin |
| `test_tenant_isolation.py` | aislamiento de instancias, catálogo, órdenes, checkout, webhook y bindings |
| `test_addon_contracts.py` | Addon Contract v2: manifest completo, rechazo de secretos en claro, superficies/riesgo/webhook válidos, persistencia y proyección |

Comando (misma DB local del stack de test; el cliente habla con la app por
ASGITransport, sin servidor HTTP real):

```bash
# Windows (venv del repo)
.venv\Scripts\python.exe -m pytest tests/certification/workflows -q --timeout=300

# Unix / uv (como el resto de la suite)
uv run --frozen --no-sync pytest tests/certification/workflows -q --timeout=300
```

Prerrequisitos: Postgres local con las migraciones aplicadas (la suite también
crea DDL idempotente de paridad); Redis según los defaults de
`tests/conftest.py`. Un solo archivo:

```bash
.venv\Scripts\python.exe -m pytest tests/certification/workflows/test_gold_sales_funnel.py -q --timeout=300
```

## Operación

### Reinicio de la API

- Nada vive en memoria: la instancia está en `workflow_instances` con su
  `definition_snapshot` congelado, el estado de negocio en `instance.state` y el
  inbox en `workflow_signals`.
- `test_durability_restart.py` simula el reinicio con un cliente nuevo: la
  instancia sigue `WAITING` en `esperar_pago`, el snapshot viaja con ella, el
  webhook la reanuda y el cierre ejecuta un segmento nuevo (`runs + 1`), no una
  re-ejecución. Una sola venta, un solo checkout, una reserva confirmada por
  línea.
- El scheduler único (`workflow_v2_scheduler_loop`, cada 60s) corre
  `sweep_waiting_instances`: timeouts de WAIT (idempotentes, un solo timeout por
  `wait_seq`), expiración global, reaper (RUNNING > 6h → FAILED `stale_segment`)
  y retención (señales > 30 días, instancias terminales > 180 días).
- Métricas Prometheus: `workflow_instance_transitions_total{status}` y
  `workflow_instance_signals_total{status}`.

### Reintentos

| Qué | Mecanismo | Garantía |
| --- | --- | --- |
| Mensaje del cliente repetido | `workflow_signals` unique por `(org, event_type, external_event_id)` / `(org, idempotency_key)` | `duplicate`; no reanuda dos veces |
| Webhook repetido | `commerce_provider_events` unique `(provider, provider_event_id)` | `duplicate`; cero efectos |
| Timeout al crear checkout | `stable_operation_key` estable (attempt fuera de la identidad) | mismo checkout; nunca dos cobros |
| `payment.failed` | la instancia sigue viva; el cliente reintenta con el mismo checkout | una venta al confirmarse el pago |
| Timeout del WAIT de pago | rama `timeout` → `cancelar_orden` + `liberar_inventario` | cierre limpio sin venta |
| Re-entrada de bucle | contador `__loops.<target>` + `max_iterations` | el bucle no es infinito |

### KPIs

`GET /api/v1/commerce/kpis` (opcional `?workflow_id=`):

- `instances`: `active`, `waiting_customers`, `completed`, `failed`, `expired`,
  `cancelled`, `by_status`.
- `orders`: `draft`, `awaiting_confirmation`, `awaiting_payment`, `paid`,
  `fulfilled`, `cancelled`, `expired`, `abandoned` (= awaiting_payment +
  expired), `by_status`.
- `sales.revenue_paid`: suma de órdenes `PAID` + `FULFILLED` por moneda.
- `average_completion_seconds`: promedio real de instancias `COMPLETED`.

### Re-publicar la plantilla

Cuando cambia el grafo, `python scripts/seed_sales_funnel.py` vuelve a publicar
la plantilla, el producto y el addon de mensajería sin tocar workflows ya
creados: las instancias vivas siguen con su snapshot congelado.

## Referencias

- `docs/architecture/durable-business-workflows.md` — WorkflowInstance, WAIT,
  señales, timeouts y operación.
- `docs/architecture/payment-capabilities.md` — checkout, webhooks firmados e
  idempotencia financiera.
- `docs/architecture/unified-marketplace.md` — catálogo global y capability-first.
- `src/platform/commerce/sales_funnel.py` — grafo, paquete y readiness.
