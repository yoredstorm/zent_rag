# P19-00 — Matriz antes/después: rutas, nodos, API, permisos, contratos, flags y rollback

Esta matriz es **planificada**. La columna «Después» describe el objetivo de P19,
no un estado implementado. P19-00 no cambia runtime.

## 1. Rutas de ejecución

| Ruta | Antes (AS-IS) | Después (P19) | Fase | Compatibilidad |
|---|---|---|---|---|
| Chat → intención → `query_business_data` | Pregunta libre al pipeline RAG; LLM responde con texto/filas | Se conserva para preguntas semánticas; no se usa como SELECT de negocio | 04/12 | Total; no se reescribe |
| Chat → intención → `data_query` | No existe | Ruta tipada a recurso autorizado con parámetros del slot | 03/04 | Nueva; flag |
| `capability_call` → `managed_db` | SELECT declarativo con override por payload | Legacy deprecado; adaptador solo si cumple plan canónico | 01/12 | Grafos antiguos siguen; sin ampliación |
| `capability_call` → `connected_db` | Se ejecuta contra Managed DB | `PROVIDER_NOT_SUPPORTED` hasta adaptador certificado | 06 | Falla cerrado; no finge soporte |
| `capability_call` → `semantic_query` | Pregunta al pipeline RAG con rol admin | Se mantiene; se corrige rol y se separa de datos transaccionales | 01/12 | Contrato actual conservado |
| `adaptive_route` | Decide ruta/acción policy-driven | Se usa para elegir ruta de intención declarada, no para inventar recursos | 04 | Sin cambio de contrato |
| `wait_event` | WAIT durable | Se añade snapshot de binding/plan al segmento | 12 | Instancias existentes leen snapshot ausente como restrictivo |
| `subworkflow_call` | Snapshot congelado | Sin cambio; el hijo hereda scope y principal | 09/12 | Total |

## 2. Nodos

| Nodo | Antes | Después | Fase |
|---|---|---|---|
| `query_business_data` | Solo `ask`; salida con `sql_query` | Se conserva; salida técnica restringida por rol | 05/12 |
| `capability_call` | `inputs` dict libre; binding vivo | Legacy; valida plan si el binding es nuevo | 01/12 |
| `data_query` «Consultar registros» | No existe | Nuevo nodo IR v1 + editor Simple/Avanzado | 03 |
| `intent_route` «Identificar solicitud» | No existe como contrato de datos | Nuevo contrato `zent.workflow.intent.route/v1` | 04 |
| `ai_decision` | Decisión genérica JEV | Se conserva; no sustituye la intención tipada | 04 |
| `wait_event` | WAIT genérico | Añade correlación de identidad y plan | 09/12 |
| `subworkflow_call` | Snapshot de definición | Añade herencia de scope/principal | 09/12 |

## 3. API

| Endpoint | Antes | Después | Fase |
|---|---|---|---|
| `GET /api/v1/workflows/data-sources` | No existe | Lista conexiones autorizadas con estado/read_only/capabilities | 02 |
| `GET .../data-sources/{ref}/resources` | No existe | Lista tablas/vistas publicadas, paginada | 02 |
| `GET .../resources/{ref}/schema` | No existe | Columnas permitidas, tipos, PK/FK, sensibilidad | 02 |
| `POST .../data-query/preview` | No existe | Preview de plan autorizado, límites severos, redacción | 02 |
| `GET/PUT/DELETE /capability-bindings` | `config` JSON libre | Valida plan, scope, versión y hash; rechaza campos inseguros | 01/12 |
| `GET /node-schemas` | `query_business_data` con `ask` | Incluye `data_query` cuando flag activo | 03 |
| `GET /{id}/data-catalog` | Salidas/samples | Añade contratos de `data_query` y `intent_route` | 05 |
| `GET /{id}/readiness` | Checks generales | Añade checks de recurso, ACL, pinning, frescura | 12 |
| `POST /{id}/publish` | No valida SELECT | Bloquea recursos no expuestos, parámetros sin enlazar, plan no pinneado | 12 |

## 4. Permisos

| Permiso / control | Antes | Después | Fase |
|---|---|---|---|
| `workflows:read` | Ver workflow | Sin cambio | — |
| `workflows:update` | Editar/crear binding | Añade validar plan y scope | 01 |
| `workflows:admin_bindings` | No existe | Requerido para `allowed_workspace_ids=*` y org-level amplio | 01/02 |
| `external_actions:execute` | Requerido por marketplace | Se conserva; no sustituye ACL de datos | 06 |
| ACL de recurso | No existe | Lista positiva por workspace/rol/usuario | 02 |
| Titularidad de fila | No existe | Principal verificado inyectado | 08/09 |
| Rol DB | `query_reader` (read-only) | Se conserva; nunca admin/ingesta | 01/06 |
| Scope de workspace | Fallback org-level libre | Concesión explícita; default deny | 01/02 |
| Pinning | No existe para bindings | Snapshot por instancia + revalidación | 12 |

## 5. Contratos de salida

### `data_query` (nuevo)

```json
{
  "status": "FOUND | NOT_FOUND | MULTIPLE_MATCHES | ERROR | STALE | TIMEOUT",
  "found": true,
  "record": {"sku": "ARR-001", "price": "5.00", "currency": "PEN"},
  "rows": [],
  "columns": [{"name": "sku", "type": "string", "label": "SKU"}],
  "row_count": 1,
  "truncated": false,
  "data_as_of": null,
  "source_ref": "resource...",
  "binding_ref": "uuid",
  "binding_hash": "sha256:...",
  "duration_ms": 12,
  "reason_code": null,
  "provenance": {"provider_kind": "managed_db", "queried_at": "..."}
}
```

Reglas:

- `data_as_of` solo si el recurso declara vigencia real; nunca inventado.
- `record` solo en `get_one`; `rows` solo en `list`.
- `sql_query` no está en el contrato público; solo en modo técnico autorizado.
- Sin credenciales, DSN, nombres de tablas ocultas ni PII no permitida.

### `intent_route` (nuevo)

```json
{
  "intent": "price_lookup",
  "confidence": 0.92,
  "entities": {"product_name": "arroz", "sku": null},
  "missing_slots": ["sku"],
  "route": "price_lookup",
  "decision_source": "rules | llm",
  "reason_codes": [],
  "requires_identity_verification": false
}
```

### Contratos existentes

| Contrato | Antes | Después |
|---|---|---|
| `query_business_data` | `rows`, `columns`, `sql_query`, `answer`, `answerability`, `evidence` | Se conserva; `sql_query` restringido, sin convertirlo en SELECT |
| `capability_call` | `output`, `capability`, `provider_kind` | Legacy; si usa plan nuevo, añade `status`, `binding_hash`, `provenance` |
| `semantic_query` | `answer`, `rows`, `columns`, `row_count`, `sql_query`, `method` | Se conserva; sin rol admin fijo |
| `wait_event` | `waiting`, `event_type`, `correlation`, `timeout_seconds` | Añade snapshot de plan/identidad en la instancia |

## 6. Flags

| Flag | Default | Propósito | Rollback |
|---|---|---|---|
| `ZENT_WORKFLOW_DATA_NODES_ENABLED` | `false` | Habilita `data_query` en catálogo, editor, validación y runtime | Apagar oculta el nodo y bloquea nuevas consultas; no borra grafos |
| `ZENT_WORKFLOW_DATA_QUERY_PREVIEW` | `false` | Habilita preview de recursos en P19-02 | Apagar solo desactiva preview |
| `ZENT_WORKFLOW_DATA_EXTERNAL_ADAPTERS` | `false` | Habilita adaptadores certificados de P19-06 | Apagar devuelve `PROVIDER_NOT_SUPPORTED` |
| `ZENT_WORKFLOW_DATA_IDENTITY_REQUIRED` | `true` | Exige principal para loyalty/order | No se permite apagar en producción con datos reales |

Regla: un flag no cambia el significado de un workflow publicado; solo habilita
creación/ejecución nueva. Los grafos existentes no se reescriben.

## 7. Publicación, versiones y rollback

| Elemento | Antes | Después | Rollback |
|---|---|---|---|
| Workflow publicado | Snapshot de definición/política/agentes | Añade snapshot de binding/plan de datos | Revertir código; snapshots antiguos se leen restrictivos |
| Instancia WAIT | Sin binding snapshot | `data_binding_snapshot` + `plan_hash` | Si falta, `NEEDS_CONFIGURATION`; no se amplía |
| Migración de esquema | — | Aditiva: columnas/tabla de snapshots; sin borrar | `alembic downgrade -1` solo elimina lo nuevo |
| Binding vivo | Afecta la siguiente ejecución | Afecta solo nuevas instancias; WAIT usa snapshot | Desactivar binding no borra historial |
| Versiones antiguas | Se ejecutan con su snapshot | Se conservan; no se reescriben | Restaurar versión anterior |
| Feature flag | — | Default off | Apagar y reiniciar; sin migración destructiva |

## 8. Matriz de compatibilidad

| Consumidor | Riesgo de ruptura | Estrategia |
|---|---|---|
| Grafos `capability_call` managed_db | Medio | Camino legacy + adaptador; sin reescritura |
| Grafos `query_business_data` | Bajo | Contrato conservado; `sql_query` restringido por rol |
| Clientes del portal | Medio | Nodo nuevo detrás de flag; editor antiguo sigue |
| Instancias WAIT existentes | Alto | Snapshot ausente = restrictivo; no ampliar |
| Paquetes import/export | Medio | Versión de contrato nueva; rechazo explicable |
| Architect/plan compiler | Medio | Recurso no resuelto = checklist, no grafo “listo” |
| Marketplace/acciones | Bajo | Sin cambio de runtime de acciones |
| SDK/API externos | Bajo | Endpoints nuevos aditivos; errores nuevos documentados |

## 9. Criterios de no-regresión

1. Ningún grafo publicado se modifica automáticamente.
2. Ninguna instancia WAIT cambia de binding por una edición viva.
3. `query_business_data` sigue significando pregunta semántica.
4. `capability_call` antiguo sigue ejecutando su contrato, sin ampliar permisos.
5. Apagar el flag no corrompe grafos ni elimina tablas.
6. Un recurso no expuesto no se vuelve accesible por conocer su nombre.
7. Los tests de P19-00 que hoy son xfail deben pasar a PASS en P19-01 sin
   debilitar los asserts.
