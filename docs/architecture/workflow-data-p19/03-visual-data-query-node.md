# P19-03 — Nodo visual «Consultar registros»

- **Estado:** COMPLETADO (backend + editor Simple). E2E real y prueba con
  usuarios: NOT_RUN.
- **Base:** P19-01 (binder canónico) y P19-02 (catálogo de planes publicados).
- **Decisión:** el nodo usa `data_query` como adaptador al binder. No hay motor
  SQL nuevo ni SQL/JSON libre en la configuración.

## 1. Recorrido Simple

1. Añadir «Consultar registros» desde la paleta Consultar.
2. Elegir una consulta publicada (por ejemplo «Buscar un registro ·
   public.p19_prices»).
3. Ver la fuente y los campos que devuelve; llenar solo los parámetros
   declarados.
4. «Probar lectura» y revisar estado, fuente, latencia y filas redactadas.
5. Guardar.

No se escribe SQL, tabla, columnas, `connection_ref` ni límite. Esos valores
viven en el plan del servidor. El usuario no técnico ve 4 decisiones esenciales;
el límite de P19 es 7.

## 2. Contrato del nodo

```json
{
  "type": "data_query",
  "version": 1,
  "config": {
    "capability": "p19.price.lookup",
    "binding_ref": "uuid-del-binding",
    "params": {
      "sku": "{{nodes.intent.output.entities.sku}}"
    }
  }
}
```

- `capability` identifica el binding lógico.
- `binding_ref` detecta cambios de binding: si el output real no coincide, el
  nodo devuelve `status=ERROR`, `reason_code=BINDING_CHANGED`.
- `params` solo contiene nombres declarados; el binder rechaza el resto con
  `UNEXPECTED_PARAMETER`.
- El nodo no guarda `table`, `columns`, `filters`, `limit`, `order_by`,
  `connection_ref` ni `sql`.

## 3. Salida

```json
{
  "status": "FOUND | NOT_FOUND | MULTIPLE_MATCHES | ERROR | SIMULATED",
  "found": true,
  "record": {"sku": "ARR-001", "price": "5.00", "currency": "PEN"},
  "rows": [],
  "columns": [{"name": "sku", "type": "string", "label": "sku"}],
  "row_count": 1,
  "truncated": false,
  "data_as_of": null,
  "source_ref": "public.p19_prices",
  "binding_ref": "uuid",
  "binding_hash": "sha256...",
  "duration_ms": 12,
  "reason_code": null,
  "provenance": {"provider_kind": "managed_db", "queried_at": "..."}
}
```

No incluye `sql_query`, DSN, credenciales ni columnas fuera de la proyección.
`NOT_FOUND` y `MULTIPLE_MATCHES` son estados normales para enrutar con una
condición posterior; no se fuerza un puerto de error en el IR.

## 4. Implementación

| Capa | Archivo | Cambio |
|---|---|---|
| Runtime | `src/platform/workflows/nodes.py` | `_exec_data_query`, registro `data_query` |
| Catálogo de nodos | `src/platform/workflows/node_catalog.py` | metadatos, cuándo usarlo, dependencia `managed_db` |
| Schema de negocio | `src/platform/workflows/parameters.py` | `_data_query_schema`, salidas tipadas |
| API de planes | `src/api/routes/workflows.py` | `GET /data-query/plans` |
| Servicio de planes | `src/platform/workflows/data_sources.py` | `list_data_query_plans` |
| Portal paleta | `portal/src/lib/workflowGraph.ts` | `NODE_LIBRARY.data_query`, grupo Consultar, outputs |
| Editor Simple | `portal/src/components/workflowStudio/DataQueryForm.tsx` | selección, parámetros, preview, estados vacíos |
| Inspector | `portal/src/components/NodeConfigPanel.tsx` | rama `data_query` |
| API de preview | P19-02 | límites severos y redacción |

## 5. UX y accesibilidad

- Estado vacío accionable: «No hay consultas publicadas; pide a un administrador
  que publique una vista o tabla autorizada».
- Estado de carga y error de red visibles, sin trazas SQL.
- Etiquetas con `Field`, `aria-label` en el selector, botón con nombre accesible.
- Vista Avanzada: `binding_ref`, `capability`, `pii_class`; no muestra SQL.
- Responsive: el formulario usa el ancho del rail existente; no se añaden
  pantallas por tabla. Falta medir 390/768/1440 y lector de pantalla real.

## 6. Pruebas

### Backend

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_node.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_node_catalog.py -q
```

Resultados:

- `test_workflow_data_p19_node.py`: **5 passed**.
  - registro del nodo y schema;
  - delegación al binder;
  - `BINDING_CHANGED`;
  - error de permiso como estado tipado;
  - simulación sin ejecutar.
- `test_workflow_node_catalog.py`: **17 passed**. El nodo nuevo está cubierto por
  el contrato de metadata/registry; se añadió a la lista de simulación.

### Portal

```powershell
pnpm --dir portal exec vitest run `
  src/components/workflowStudio/DataQueryForm.test.tsx `
  src/lib/workflowGraph.p19.test.ts
pnpm --dir portal exec tsc --noEmit
```

Resultados:

- **5 passed** (2 del formulario + 3 de la paleta).
- TypeScript sin errores.
- El formulario se probó con planes mock y preview mock; no es E2E contra API
  real.

### Acumulado P19

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_workflow_data_p19_audit.py `
  tests/test_workflow_data_p19_query.py `
  tests/test_workflow_data_p19_query_integration.py `
  tests/test_workflow_data_p19_catalog.py `
  tests/test_workflow_data_p19_node.py `
  tests/test_workflow_node_catalog.py -q
```

Resultado de esta sesión: **58 passed**.

## 7. Seguridad

- El nodo no puede cambiar el recurso: solo envía `params` al binder.
- El binding se resuelve por organización/workspace y plan canónico.
- `binding_ref` detecta drift entre configuración y ejecución.
- Preview usa los mismos límites y redacción de P19-02.
- Planes con ownership no se prueban sin identidad verificada.
- No se escribe SQL en el grafo, logs del nodo ni configuración del portal.

## 8. Límites y deuda

- No hay Data Picker de valores dentro de parámetros; P19-05 lo integra. Hoy se
  puede escribir `{{nodes.X.output.campo}}` en Avanzado, pero no con un clic.
- No hay puertos semánticos separados «Encontrado/No encontrado/Varias/Error».
  Se usa `status` + condición posterior para no forzar un IR que no los soporta.
- No hay `data_as_of` real ni SLA de frescura; P19-07/12.
- No hay pinning de binding en WAIT; P19-12.
- No hay E2E Playwright, capturas, 5 usuarios reales ni prueba 390/768/1440.
- No hay plantilla de precio todavía; P19-07.

## 9. Rollback

- Revertir el registro `data_query`, el ejecutor, el schema de negocio y la
  entrada del portal.
- Los grafos que ya contengan `data_query` fallarían como tipo desconocido si se
  revierte el código; desactivar la creación antes del rollback y conservar los
  grafos. No hay migración de esquema.
- No se modificaron workflows publicados ni instancias.

## 10. Veredicto

**P19-03 COMPLETADO en backend y editor Simple.** Un usuario puede elegir un plan
publicado, llenar un parámetro y probar la lectura sin SQL. No se declara E2E ni
usabilidad certificada: esas pruebas son NOT_RUN.
