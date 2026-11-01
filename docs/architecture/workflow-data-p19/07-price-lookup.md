# P19-07 — Flujo de precio y disponibilidad sobre PostgreSQL externo

- **Estado:** recorrido principal COMPLETADO en local con datos reales de la DB
  externa.
- **Matriz completa de P19-07:** NOT_RUN (faltan 8+ conversaciones, cambio de
  precio entre turnos, duplicados y expiración).

## 1. Grafo ejecutado

```
trigger_webhook (mensaje)
  → intent_route (price_lookup, SKU ARR-001)
  → data_query (p19.external.price, plan get_one)
  → end
```

Configuración:

- `intent_route.text = {{trigger.message}}`.
- `data_query.capability = p19.external.price`.
- `data_query.params.sku = {{nodes.intent.output.entities.sku}}`.
- Plan: `catalog.product_prices`, filtro obligatorio `channel=retail`,
  proyección SKU, nombre, precio, moneda, vigencia.
- Sin SQL en el nodo.

## 2. Evidencia real

Run `succeeded`, 4 nodos, 889 ms totales.

```json
{
  "intent": "price_lookup",
  "confidence": 0.99,
  "entities": {"sku": "ARR-001"},
  "route": "price_lookup"
}
```

```json
{
  "status": "FOUND",
  "found": true,
  "record": {
    "sku": "ARR-001",
    "product_name": "Arroz premium 1 kg",
    "price": "5.00",
    "currency": "PEN",
    "valid_from": "2026-01-01",
    "valid_to": "2026-12-31"
  },
  "source_ref": "catálogo/product_prices",
  "provenance": {"provider_kind": "connected_db"},
  "duration_ms": 179
}
```

El precio `5.00` sale de PostgreSQL externo, no de un LLM. Se conserva como
string decimal para no perder precisión al serializar.

## 3. Reproducción

```powershell
.\.venv\Scripts\python.exe ops\p19-external\create_price_workflow.py
```

Variables opcionales:

- `P19_DEMO_EMAIL`
- `P19_DEMO_PASSWORD`
- `P19_DEMO_WORKSPACE`
- `P19_PORTAL_API`

El script crea un workflow nuevo en el tenant demo y ejecuta:

```
precio del SKU ARR-001
```

## 4. Reglas respetadas

- El mensaje no elige tabla, columnas, conexión ni límite.
- El SKU extraído se valida como parámetro declarado.
- El precio del texto («a 5 soles») no se usa como evidencia.
- `get_one` devuelve 1 fila; 0 sería `NOT_FOUND` y >1 `MULTIPLE_MATCHES`.
- La moneda y vigencia vienen de la fila.
- La salida no incluye SQL ni credenciales.

## 5. Pendiente para cerrar P19-07

- 8+ conversaciones con variantes de producto y SKU inválido.
- Cambio de precio en la DB entre turnos.
- Dos coincidencias de «arroz» y desambiguación.
- Precio expirado y moneda distinta.
- `WAIT` para más instrucciones.
- Prueba de recarga del grafo y regresión de versión publicada.
- Respuesta formateada al cliente; hoy el run devuelve el contrato, no un texto
  conversacional final.

## 6. Veredicto

**P19-07: recorrido principal PASS local con DB externa real.** No se declara la
matriz completa ni GO de producción.
