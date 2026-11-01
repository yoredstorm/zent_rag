# P19-05 — Data Picker tipado entre nodos

- **Estado:** COMPLETADO (conexión de referencias y contratos de salida).
- **Base:** P19-03 (`data_query`) y P19-04 (`intent_route`).
- **Alcance:** un clic desde un campo del nodo anterior al parámetro autorizado.
  No se convierte una referencia en identificador SQL.

## 1. Contratos conectables

`Consultar registros` expone:

- `status`, `found`, `record`, `rows`, `columns`, `row_count`;
- `truncated`, `data_as_of`, `source_ref`;
- `binding_ref`, `binding_hash`, `duration_ms`, `reason_code`, `provenance`.

`Identificar solicitud` expone:

- `intent`, `confidence`, `route`, `decision_source`;
- `entities.product_name`, `entities.sku`, `entities.order_number`;
- `missing_slots`, `reason_codes`, `requires_identity_verification`.

Ambos están en `parameters.py`, `data_catalog.py` y en el mapa de salidas del
canvas. El Data Picker puede mostrar un campo declarado aunque no exista sample;
nunca inventa un valor.

## 2. Flujo de un clic

```
Identificar solicitud → entidades.sku
  └─ Data Picker en «Datos para buscar» de Consultar registros
       └─ escribe {{nodes.intent.output.entities.sku}} en params.sku
```

- El editor no muestra JSON en modo Simple.
- El valor se guarda como referencia IR; el binder lo resuelve en ejecución.
- Si la referencia apunta a una lista o a un objeto incompatible, el binder
  responde `INVALID_PARAMS`; no se usa como identificador SQL.
- La referencia solo puede llegar a un parámetro declarado en el plan. El binder
  rechaza nombres no declarados con `UNEXPECTED_PARAMETER`.

## 3. Implementación

| Capa | Archivo | Cambio |
|---|---|---|
| Runtime | `nodes.py` | resuelve refs y envía solo `params` al binder |
| Contrato | `parameters.py` | salidas de `data_query` e `intent_route` |
| Catálogo | `data_catalog.py` | reutiliza contratos y samples existentes |
| Portal | `DataQueryForm.tsx` | DataPicker por parámetro desde `dataSources` |
| Inspector | `NodeConfigPanel.tsx` | pasa las fuentes del grafo al formulario |
| Canvas | `workflowGraph.ts` | salidas de ambos nodos |

## 4. Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_node.py -q
pnpm --dir portal exec vitest run src/components/workflowStudio/DataQueryForm.test.tsx
```

Resultados:

- Backend: **6 passed**; incluye resolución de
  `{{nodes.intent.output.entities.sku}}` a `ARR-001`.
- Portal: **3 passed**; incluye abrir Data Picker, elegir SKU y verificar que el
  input queda con la referencia canónica.
- `tsc --noEmit`: limpio.

## 5. Validación y límites

Implementado:

- referencia a nodo existente vía catálogo real del grafo;
- tipo de parámetro validado por el plan/binder;
- rechazo de parámetro no declarado;
- listas solo si el operador del plan las admite;
- salida `record` vs `rows` separada;
- `NOT_FOUND`/`MULTIPLE_MATCHES` como estados.

No implementado todavía:

- validación de nulabilidad y sensibilidad en el validador de grafo (solo en
  ejecución);
- chequeo estático de “lista vs registro” antes de ejecutar;
- persistencia de referencias en checkpoints sin datos personales completos;
- prueba E2E de compilación de plan con referencia;
- Data Picker para `intent_route` (sus campos son de entrada, no de salida).

## 6. Rollback

- Revertir `DataQueryForm`, la prop `dataSources` y los contratos de salida.
- Las referencias ya guardadas son strings IR; un workflow sin el nodo destino
  falla cerrado con `INVALID_PARAMS`/`UNEXPECTED_PARAMETER`.
- No hay migración ni cambio de esquema.

## 7. Veredicto

**P19-05 COMPLETADO para el gate de un clic.** Falta el validador estático
completo de tipos/nulabilidad/sensibilidad; se declara como deuda para P19-11/13,
no como PASS.
