# 05 — P03: Solution Compiler

Fecha: `2026-10-23`.
Base: `0cbb494ce4` + P00/P01/P02.

## 1. Decisión

`src/platform/studio/solution_compiler.py` es una capa de composición sobre las
autoridades existentes:

- `role_profiles` y `role_profile_versions`;
- tabla `agents` y el repositorio de agentes existente;
- `WorkflowGraph` v2 y `create_workflow`;
- `workflow_capability_bindings` y knowledge bases del tenant;
- `studio_solutions` para el blueprint portable;
- `release_policy` para certificar/publicar (no se auto-publica).

No crea otro runtime, planner, registro de agentes, tienda ni memoria. La
materialización vive en `studio_solution_materializations` (migración 167).

## 2. Contrato de compilación

`POST /api/v1/studio/solutions/compile` (dry-run, no escribe):

`brief` → `role template` → `blueprint` portable → `plan` de recursos →
`requirements` resueltos → `blockers` → `scenarios` → `graph_preview`.

- El blueprint usa referencias lógicas (`role_ref`, `agent_ref`,
  `workflow_ref`, `source_1`) y excluye IDs físicos, credenciales y secretos.
- `compilation_hash` cubre brief, template, workspace, fuentes y agente elegido.
- La respuesta separa `available`, `missing`, `needs_source`,
  `optional_missing`, `agent_unavailable` y `workspace_mismatch`.
- Si falta una capacidad dura (catálogo Postgres) o dos fuentes de auditoría,
  el estado es `NEEDS_CONFIGURATION`; no se inventa una conexión.

`POST /api/v1/studio/solutions/materialize` exige `confirm=true` y una clave de
idempotencia (o usa el hash). Crea o reutiliza:

1. rol activo desde la plantilla;
2. agente activo con herramientas recortadas por el rol;
3. workflow draft con grafo v2, `agent_id` real en cada nodo `llm` y metadata
   `solution_ref`.

`studio_solutions` guarda el blueprint; la materialización guarda artefactos,
estado, compilación y requisitos. Repetir la misma clave no duplica rol, agente,
workflow ni solución.

## 3. Estados

`IN_PROGRESS`, `READY`, `NEEDS_CONFIGURATION`, `FAILED`, `ROLLED_BACK`.

`READY` solo si existe workflow draft y todos los nodos `llm` apuntan a un
agente activo. `NEEDS_CONFIGURATION` conserva los recursos creados y devuelve
los bloqueos para continuar. Nunca se declara listo un flujo con eco o agente
vacío.

## 4. Plantillas y Gold

| Misión | Resultado P03 |
|---|---|
| Mentor de Python con progreso y ejercicios | rol mentor, agente activo, workflow con LLM + state_append + WAIT, escenarios de dos días |
| Vender arroz de catálogo Postgres | sin binding → `NEEDS_CONFIGURATION`; con binding `catalog.products.search` → workflow con capability_call + aprobación |
| Auditar dos fuentes y aprobar | sin 2 fuentes → bloqueo; con 2 knowledge bases → dos `kb_query` + LLM + `human_approval` |
| Repetir la misma petición | misma solución/rol/agente/workflow; sin duplicados |
| Tenant B con agente de A | `agent_unavailable`; no reutiliza el ID físico |

La conversación real del mentor queda `NOT_VERIFIED` sin proveedor LLM: se
verificó el grafo con agente activo y el workflow persistido, no una respuesta
de proveedor.

## 5. API y UI

| Ruta | Permiso | Uso |
|---|---|---|
| `POST /studio/solutions/compile` | `workflows:read` | Dry-run y plan |
| `POST /studio/solutions/materialize` | `workflows:create` | Escritura confirmada e idempotente |
| `GET /studio/solutions/{id}/materialization` | `workflows:read` | Estado y artefactos |
| `POST /studio/solutions/{id}/materialization/rollback` | `workflows:create` | Deshacer solo recursos nuevos y no usados |

Portal: `/solutions/new` permite escribir la misión, preparar, revisar
recursos/bloqueos, confirmar y abrir el proceso. Role Studio enlaza a esa página
con la misión propuesta. No se muestran UUID/JSON/SQL en el flujo normal.

## 6. Pruebas

| Comando | Resultado |
|---|---|
| `pytest tests/test_solution_compiler.py -q` | **9 passed** (89.64 s) con `junit-solution-compiler.xml` |
| `pytest tests/test_role_profiles.py tests/test_studio_migrations.py tests/test_workflow_publication_gate.py -q` | **32 passed** (167.62 s) |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0, 0 errores, 22 warnings preexistentes |
| `npm test -- SolutionBuilder.test.tsx RoleStudio.test.tsx` | **3 passed** |
| `alembic upgrade head` | 163→164→165→166→167 aplicado en local |

## 7. Límites

- La plantilla y el parser son determinísticos; una misión ambigua puede caer
  en otra plantilla. La UI permite elegir plantilla y el resultado siempre
  exige revisión.
- No se ejecutó un LLM real ni una conversación end-to-end del mentor. El
  workflow está persistido con agente activo y puede probarse/certificarse.
- El catálogo de ventas se valida por binding; no se ejecutó contra una tabla
  de productos real en esta corrida.
- La auditoría usa knowledge bases existentes; no se cargaron documentos
  reales en P03.
- No hay rollback de bindings ni de knowledge bases preexistentes (correcto:
  no se crean en P03).
- P03 materializa un rol, un agente primario y un workflow por solución. El
  contrato `SolutionV1` ya soporta N:M; exponer varios agentes/workflows y sus
  bindings independientes queda para P04/P09.
- La edición colaborativa Architect/Canvas sobre una misma revisión queda para
  P09; P03 crea el borrador y no reescribe diseños existentes.
- P05 cerró workspace en listados/signals y el PEP transversal
  (`07-p05-policy-enforcement.md`).

## 8. Rollback

1. Revertir `solution_compiler.py`, rutas `/solutions/*` y la UI.
2. `alembic downgrade 166` elimina `studio_solution_materializations`.
3. Los recursos creados por una materialización se pueden deshacer con el
   endpoint de rollback mientras no tengan runs/instancias; nunca se borran
   recursos preexistentes.
4. Mantener `ZENT_GOLD_RELEASE_ENABLED=false`; P03 no publica ni activa.

## 9. Dictamen

**GO P03 para staging controlado.** Una misión se convierte en blueprint,
rol, agente activo y workflow draft ejecutable, con materialización idempotente
y bloqueos explícitos. **NO-GO release:** falta conversación real de proveedor,
auditoría con documentos reales y las fases P05/P08/P12.
