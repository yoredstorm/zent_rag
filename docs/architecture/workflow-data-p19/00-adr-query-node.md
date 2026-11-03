# P19-00 — ADR: consulta de datos como capacidad de primera clase

- **Estado:** Aprobada. ADR-001/002 implementadas parcialmente en P19-01
  (`data_query` backend: `get_one`, `list`, `count`). El nodo visual llega en
  P19-03.
- **Fase:** P19-00 (decisión). Habilita P19-01.
- **Decisores requeridos:** Principal Workflow Architect, Security Architect,
  Data Platform Lead.
- **Contexto reproducible:** `00-audit-baseline.md`, tests
  `tests/test_workflow_data_p19_audit.py`.

## ADR-001 — Tipo IR `data_query` y ejecutor canónico único

### Contexto

Hoy existen tres caminos que pueden devolver datos:

1. `query_business_data`: pregunta en lenguaje natural al pipeline RAG.
   Devuelve `rows`, `columns`, `sql_query`, `answerability` y evidencia.
2. `capability_call` con binding `managed_db`/`connected_db`: SELECT declarativo
   construido en `_execute_managed_select`, con el defecto P0 de fusión
   `binding.config + payload`.
3. `api_call`/`rest_api`: datos de una API, no SQL.

El canvas solo expone el camino 1 con un campo de texto. No hay forma de elegir
conexión, recurso, operación ni columnas. Tampoco hay contrato de recurso
autorizado: el binding guarda `table` y `columns` como JSON libre.

### Decisión

Se introduce un **tipo IR nuevo `data_query` (versión 1)** para representar una
consulta declarativa autorizada. El nodo visual «Consultar registros» compila a
ese tipo. **No se crea un segundo motor SQL**: el runtime del nodo es un adaptador
fino sobre un único ejecutor canónico en `src/platform/workflows/bindings.py`.

```
data_query (IR + UX)
  └─ data_query_plan_ref (binding persistido + versión + hash)
       └─ execute_data_query_plan()   ← único generador/ejecutor SQL
            └─ Managed DB reader / ReadOnlyQueryAdapter
```

`capability_call` sigue existiendo para capacidades lógicas
(`catalog.products.search`, `loyalty.balance.read`). No se sobrecarga su contrato
con campos de tabla, columnas o SQL. `query_business_data` conserva su semántica
de pregunta y no se convierte silenciosamente en SELECT.

### Alternativas evaluadas

| Alternativa | Veredicto | Razón |
|---|---|---|
| Extender `capability_call` con `mode: select` | Rechazada para P19 | Mezcla capacidad lógica con recurso concreto; obliga a validar dos contratos en un nodo y facilita que un payload active el modo SELECT por accidente |
| Nuevo engine `data_query_engine` | Rechazada | Duplica ejecución, permisos, auditoría y observabilidad; viola el invariante de una sola autoridad |
| `data_query` como adaptador al binder | **Elegida** | UX explícita, contrato propio, reutiliza binder, runtime, instancias y auditoría |
| Reutilizar `query_business_data` con más campos | Rechazada | Rompe la semántica de pregunta y los grafos publicados; el LLM seguiría siendo el camino de datos |

### Contrato IR propuesto (P19-01)

```json
{
  "type": "data_query",
  "version": 1,
  "config": {
    "plan_ref": "uuid-del-binding",
    "plan_version": 3,
    "plan_hash": "sha256:...",
    "operation": "get_one",
    "params": {
      "sku": "{{nodes.intent.output.entities.sku}}"
    }
  }
}
```

El `config` del nodo **no** contiene `table`, `schema`, `connection_ref`,
`columns`, `filters`, `order_by`, `limit` ni SQL. Esos campos viven en el plan
persistido y versionado del servidor. `params` solo puede contener nombres
declarados en el plan; cualquier otro nombre produce `UNEXPECTED_PARAMETER`.

### Migración y compatibilidad

- Grafos existentes con `capability_call` + `managed_db` siguen ejecutándose por
  el camino legacy, marcado `deprecated` y sin ampliar permisos.
- Un tenant puede crear un `data_query` nuevo; no se reescribe ningún grafo
  publicado ni instancia.
- El adaptador de compatibilidad acepta un binding legacy **solo** si su config
  cumple el plan canónico; si no, `NEEDS_CONFIGURATION` con checklist.
- Flag `ZENT_WORKFLOW_DATA_NODES_ENABLED` (default `false`) habilita el tipo en
  catálogo, validación, editor y runtime. Apagarla no borra grafos ni migra datos.
- Versiones publicadas: el nuevo tipo se introduce en una versión nueva; las
  versiones anteriores no se reescriben.

### Consecuencias

Positivas: una sola autoridad SQL, UX explícita, compatibilidad hacia atrás,
posibilidad de pinning por plan. Negativas: un tipo IR más que mantener y una
migración de UI; requiere tests de compatibilidad de grafos antiguos.

## ADR-002 — Agregados como AST tipado, no SQL libre ni capabilities ad hoc

### Decisión

Las operaciones permitidas se implementan en este orden:

1. `get_one` (0 → `NOT_FOUND`, >1 → `MULTIPLE_MATCHES`, 1 → `record`).
2. `list` (filas + `truncated` + cursor).
3. `count` (entero, sin filas).
4. `aggregate` con un **AST cerrado**: función permitida (`sum`, `avg`, `min`,
   `max`, `count`), campo permitido, `group_by` permitido, predicados del plan.
   Sin expresiones, aritmética, subconsultas, `HAVING` libre ni `ORDER BY` libre.

No se usan capabilities predefinidas por agregado porque obligarían a crear una
capacidad por tabla/métrica y trasladarían la configuración del recurso al
catálogo de capacidades. El AST se valida contra el snapshot del recurso y se
compila con el generador SQL autorizado. P19-01 implementa `get_one`, `list` y
`count`; `aggregate` queda detrás de flag hasta P19-03.

### Invariantes

- Ninguna operación acepta SQL, `raw`, `expression` o `formula`.
- `count` no revela filas ni PII; solo un entero autorizado.
- `get_one` nunca devuelve la primera fila arbitraria.
- Los agregados respetan los mismos predicados obligatorios y ownership.

## ADR-003 — Herencia org-level: default deny y concesión explícita

### Contexto

`resolve_binding` cae de workspace a org-level sin comprobar concesión. Además,
si el run no tiene workspace, `open_managed_query_session` elige la última Managed
DB de la organización. Eso puede leer el workspace equivocado.

### Decisión

El binding declara `scope`:

```json
{
  "scope": "workspace",
  "workspace_id": "uuid"
}
```

o

```json
{
  "scope": "organization",
  "allowed_workspace_ids": ["uuid-a", "uuid-b"]
}
```

Reglas:

- `scope=workspace`: solo ese workspace.
- `scope=organization`: solo workspaces listados; `allowed_workspace_ids=[]`
  significa deny, no “todos”.
- `*` o “todos” requiere permiso `workflows:admin_bindings` y queda auditado.
- Un `data_query` sin `workspace_id` en runtime falla con
  `NEEDS_CONFIGURATION`/`WORKSPACE_REQUIRED`; nunca abre “la última DB”.
- El binding se resuelve por organización + workspace + scope; la ausencia de
  concesión es `PERMISSION_DENIED` interna y `RESOURCE_NOT_EXPOSED` externa.

Esta decisión convierte el hallazgo P19-00-P0-05 en test PASS y cierra P0-06.

## ADR-004 — Identidad y titularidad fuera del LLM y del payload

### Decisión

El plan declara `principal`:

```json
{
  "principal": {
    "required": true,
    "source": "session",
    "claim": "customer_ref",
    "predicate_field": "customer_id"
  }
}
```

El runtime obtiene el principal de la sesión autenticada, token de cliente o
aserción firmada del canal. Nunca de `params`, del texto del mensaje ni de una
afirmación del LLM. El valor se inyecta como predicado obligatorio y no puede ser
reemplazado por un filtro opcional.

- `price_lookup` puede ser público y no requerir principal.
- `loyalty_balance` y `order_status` requieren principal verificado.
- Un teléfono, correo o DNI escrito en el chat no verifica titularidad.
- `NOT_FOUND` y `UNAUTHORIZED` se muestran igual al usuario; la diferencia queda
  en auditoría interna.

## ADR-005 — Taxonomía de errores y no filtración

### Decisión

Códigos externos estables:

| Código | Cuándo |
|---|---|
| `NEEDS_CONFIGURATION` | falta binding/plan/workspace; checklist accionable |
| `PERMISSION_DENIED` | actor o workspace sin concesión |
| `RESOURCE_NOT_EXPOSED` | recurso no publicado para el scope |
| `INVALID_PARAMS` | parámetro no declarado, tipo/operador inválido, wildcard excesivo |
| `UNEXPECTED_PARAMETER` | payload intenta enviar table/columns/sql/limit/order_by |
| `NOT_FOUND` | 0 filas en `get_one` |
| `MULTIPLE_MATCHES` | >1 fila en `get_one` |
| `STALE_DATA` | freshness SLA incumplido |
| `TIMEOUT` | presupuesto de tiempo agotado |
| `CONNECTION_FAILED` | credencial/red/TLS/servidor |
| `PROVIDER_NOT_SUPPORTED` | dialecto/capacidad no certificada |

Regla de no filtración: el cliente recibe un código y un mensaje accionable; el
`reason_code` interno y la traza auditada distinguen cross-tenant, recurso
inexistente y recurso no expuesto. Nunca se devuelve SQL, DSN, credenciales ni
nombres de tablas ocultas.

## ADR-006 — Un solo generador SQL

### Decisión

`bindings._execute_managed_select` se reemplaza por
`execute_data_query_plan(plan, params, principal, scope)`. `data_mapper.declarative_select`
no se conecta al runtime; si se conserva, se marca como preview de catálogo sin
autoridad y se elimina o se hace delegar en el mismo generador.

Prohibiciones:

- concatenar identificadores que no estén en el snapshot del plan;
- `SELECT *`;
- `LIKE`/`ILIKE` con patrones generados por el cliente sin escape y límite;
- `ORDER BY`, `LIMIT`, `JOIN` o `WHERE` fuera del plan;
- usar credenciales admin para consultas;
- reutilizar la sesión de ingesta para lectura en vivo.

## ADR-007 — Pinning y cambio de binding en WAIT/RESUME

### Decisión

Cada instancia durable guarda, al iniciar el segmento, un `data_binding_snapshot`
con `plan_ref`, `plan_version`, `plan_hash`, `resource_hash`, `scope` y
`principal_requirement`. Al reanudar:

- si el snapshot no existe → `NEEDS_CONFIGURATION`;
- si el binding vivo cambió a más permisos → se usa el snapshot y se audita
  `binding_drift`;
- si cambió a menos permisos o fue revocado → se aplica lo más restrictivo y se
  deniega si el snapshot ya no es válido;
- nunca se amplía silenciosamente un permiso.

P19-12 implementa el snapshot y los checks de readiness. P19-00 solo documenta la
decisión y el riesgo actual.

## Consecuencias y preguntas abiertas

1. ¿El primer release de `data_query` soporta joins preaprobados o solo una
   vista? Propuesta: solo vistas y joins registrados en el plan; nada ad hoc.
2. ¿`data_as_of` se toma del recurso, del plan o de la fila? Propuesta: solo si
   el recurso declara una columna de vigencia; nunca inventar timestamp.
3. ¿La UI Simple muestra `count`? Sí, como «Contar», solo si el plan lo permite.
4. ¿Qué pasa con tenants que ya tienen `capability_call` managed_db? Siguen por
   compatibilidad; se les ofrece migración asistida, no automática.

## Rollback

Apagar `ZENT_WORKFLOW_DATA_NODES_ENABLED` oculta el nodo y bloquea nuevas
consultas `data_query`; los grafos quedan persistidos. Revertir el código de
P19-01 restaura el camino legacy sin borrar tablas ni snapshots. Ninguna versión
publicada se reescribe.
