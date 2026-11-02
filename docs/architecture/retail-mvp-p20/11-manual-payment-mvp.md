# P20-11 MVP — Nodo temporal de validación manual de pago

- **Estado:** IMPLEMENTED como nodo temporal de MVP. **NO es cobro real.**
- **Nodo:** `manual_payment_validation`
- **Label:** «Validación manual de pago (MVP temporal)»
- **Eliminación:** borrar `src/platform/workflows/manual_payment.py`, quitar la
  llamada `register_manual_payment_node(registry)` de `nodes.py`, quitar su
  metadata de `node_catalog.py` y sus tests. Reemplazar por
  `payments.checkout.create` + webhook firmado de Stripe/PSP.

## Qué hace

1. Exige `order_id`, `amount`, `currency` y `payment_reference` resueltos por
   el workflow. No acepta SQL, precio ni “ya pagué” del texto del cliente.
2. En simulación devuelve `status=pending`, `provider=manual_mvp`,
   `temporary=true` y `control=wait_approval`.
3. En ejecución real crea una aprobación humana verificable
   (`payments.manual.validate`) con expiración. El run queda
   `pending_approval`; no hay worker esperando.
4. Cuando un administrador autorizado aprueba, el motor reanuda el run. El
   nodo resuelve la aprobación y devuelve `status=paid`,
   `provider=manual_mvp`, `verified_by` y `validated_at`.
5. En `RAG_ENVIRONMENT=production` falla con
   `MANUAL_PAYMENT_DISABLED_IN_PRODUCTION`.

## Configuración

```json
{
  "order_id": "{{nodes.crear_orden.output.order_id}}",
  "amount": "{{nodes.resumen_carrito.output.total}}",
  "currency": "PEN",
  "payment_reference": "SIMULADO-001",
  "expires_minutes": 1440,
  "instructions": "Verifica el abono sandbox y aprueba este paso."
}
```

## Autoridad y límites

- El nodo **no cobra**, no crea órdenes, no modifica stock y no escribe en
  `commerce_orders` ni `bodega.orders`.
- La aprobación manual es una decisión del operador; no es un evento de pago
  de un proveedor. No debe usarse para producción.
- `marcar_pagada` y el cierre de orden siguen siendo responsabilidad de la
  capacidad de commerce existente. El nodo solo aporta
  `payment_reference` y el estado `paid` del MVP.
- La aprobación queda auditada en `workflow_approvals`; el correo/acción del
  cliente no autoriza nada.
- `self_approval` se rechaza salvo el break-glass de owner documentado por la
  plataforma.

## Prueba ejecutada

`tests/test_p20_manual_payment.py`:

- registro del nodo con label temporal y riesgo crítico;
- simulación devuelve `wait_approval`;
- sin aprobación crea solicitud y espera;
- con aprobación verificada devuelve `paid`, `provider=manual_mvp`;
- producción bloqueada;
- falta de `order_id` falla cerrado.

## Integración en el embudo

El embudo `retail_sales_funnel` sigue usando el camino de proveedor por
defecto. Para una demo MVP, en Workflow Studio se reemplaza el tramo
`crear_checkout → enviar_pago → esperar_pago` por
`manual_payment_validation`, y se conecta su salida a `marcar_pagada` con
`payment_reference = {{nodes.validar_pago_manual.output.payment_reference}}`.
No se modifica el grafo de 40 nodos por defecto para no romper la
certificación existente.

## Pendiente

- Integración Stripe/PSP real con webhook firmado, dedupe y conciliación.
- UI específica de “pagos manuales pendientes”; hoy se usa la bandeja de
  aprobaciones existente.
- Reemplazo del nodo por checkout sandbox del proveedor real.
