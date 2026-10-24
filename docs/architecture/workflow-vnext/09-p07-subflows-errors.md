# 09 — P07: subflujos, routing adaptativo y errores tipados

Fecha: `2026-10-23`. Base: `0cbb494ce4` + P00–P06.

## 1. SubflowDefinition publicada y versionada

`SubflowDefinition` envuelve las definiciones portables existentes con:

- nombre, versión y estado (`draft`, `published`, `deprecated`);
- snapshot congelado con hash;
- puertos de salida tipados;
- `durable` y `runnable_inline`;
- `node_config` listo para insertar, con `registry_refs` y snapshot.

Solo `published` se ejecuta. `prepare_subworkflow_call` rechaza `draft` y
`deprecated`. No hay un store nuevo: la definición se resuelve sobre
`portable_subflow`, `freeze_snapshot` y el mismo `execute_graph`.

Los subflujos con WAIT, LOOP o aprobación se bloquean inline con mensaje
explícito. No se crea un runtime hijo ni se simula un WAIT anidado: viven en el
proceso padre (`WorkflowInstance`).

`GET /api/v1/workflows/subflows/library` publica las definiciones; el drawer
**Subflujos** del Workflow Studio inserta un `subworkflow_call` con snapshot
congelado, sin pedir JSON.

## 2. Router adaptativo

`adaptive_route` sigue siendo determinista:

- la propuesta del LLM se normaliza;
- solo se acepta una transición presente en la allowlist congelada;
- la capacidad debe estar en `registry_refs` y en los permisos efectivos;
- una transición a otra capacidad queda bloqueada;
- la decisión es `transition`, `clarification`, `wait`, `intervention`,
  `compensation` o `halt` y lleva `typed_port`.

No hay ejecución de herramientas por el LLM ni transición a una ruta no
compilada.

## 3. Contrato de salida tipado

`error_contract.py` define los puertos estables:

`success`, `not_found`, `invalid_input`, `timeout`, `retryable_error`,
`unauthorized`, `needs_human`, `compensated`.

Cada fallo incluye `typed_port` y `error_contract` con `code`, `message`,
`retryable` y `requires_human`. El runtime agrega el puerto también a
`result.errors` para que la UI no infiera desde el texto. Timeout, skip y
UNVERIFIED no se convierten en `success`.

## 4. Límites e idempotencia

- profundidad de subflujos: hard 8, default 3;
- reintentos: hard 5;
- fan-out: hard 20, default 10; `fanout_plan` devuelve `dropped`/`truncated`;
- timeout por subflujo validado y acotado;
- clave de idempotencia obligatoria y ledger de efectos (`started`, `applied`,
  `incomplete`, `failed`); un efecto incompleto no se reejecuta;
- compensación: `saga_compensation_plan` invierte el orden y genera claves
  propias; `typed_port=compensated`.

## 5. Pruebas

| Comando | Resultado |
|---|---|
| `pytest tests/test_workflow_error_contract.py tests/test_workflow_composition.py tests/test_workflow_simulation.py tests/test_workflow_plan.py tests/test_workflow_architect.py tests/test_workflow_architect_canonical.py tests/test_workflow_patches.py tests/test_policy_enforcement.py -q` | **95 passed** (`junit-p07.xml`) |
| Portal `SubflowLibraryPanel` + ajustes de drawer | **17 passed** (con memoria/tipos) |
| `ruff check` P07 | OK |
| Portal `npm run typecheck` | OK |
| Portal `npm run lint` | 0 errores |

Cubre: los 8 puertos, timeout/unauthorized/needs_human/compensated, draft
rechazado, durable bloqueado, fan-out y profundidad, orden de compensaciones,
biblioteca API y snapshots.

## 6. Límites

- `SubflowDefinition` se deriva de las definiciones portables del producto; no
  se añadió un CRUD de subflujos en base de datos.
- El subflujo durable no crea una instancia hija: se bloquea inline por diseño.
  La ejecución durable de hijos queda para una fase con contrato de child
  instance explícito.
- La compensación planifica y expone el contrato; la ejecución real de cada
  compensación usa `capability_call`/acciones existentes. No hay saga
  transaccional distribuida ni exactly-once.
- El router no sustituye el planner ni crea rutas: solo elige entre transiciones
  ya compiladas.
- Sin prueba con proveedor real ni carga de fan-out.

## 7. Rollback

1. Revertir `error_contract.py`, `SubflowDefinition`, la biblioteca y el drawer.
2. Revertir el `typed_port` en runtime/engine y los ajustes de simulación.
3. No hay migración nueva en P07.
4. Los grafos existentes conservan `out`; los puertos tipados son un campo
   adicional del resultado.

## 8. Dictamen

**GO P07 para staging controlado.** Subflujos publicados/versionados con snapshot,
bloqueo durable explícito, router cerrado, puertos tipados y límites. **NO-GO
release:** instancia hija durable, saga distribuida y certificación P12 siguen
pendientes.
