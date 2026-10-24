# 08 — P06: contexto, RAG y memoria consentida

Fecha: `2026-10-23`. Base: `0cbb494ce4` + P00–P05.

## 1. Una sola memoria

Se reutiliza `memory_records`, `memory_events`, `MemoryFoundationService` y
`MemoryRecallService`. No hay store, índice vectorial ni modelo paralelo. La
migración aditiva **168** agrega:

- `workspace_id`, `subject_id`, `scope`;
- `consent_at`, `expires_at`, `deleted_at`.

Las filas históricas conservan `scope='tenant'`, `workspace_id=NULL`. El índice
de patrón vivo ahora incluye workspace y sujeto para que dos ámbitos no
colisionen.

## 2. Política por rol

`MemoryPolicy` admite:

`none`, `session`, `participant`, `workspace`, `durable_business_state`,
`long_term_consent` (y `long_term` legado).

`context_service.py` es la única política de lectura:

- `none` no lee nada;
- `session` exige conversación y solo ve recuerdos de esa sesión;
- `participant` exige sujeto;
- `workspace` ve workspace propio y registros tenant-globales explícitos;
- `durable_business_state` ve estado de negocio del workspace;
- `long_term_consent` exige sujeto, `consent_at`, expiración vigente y
  `deleted_at` nulo.

Siempre se verifica organización, workspace, sujeto, conversación, estado
`active`, expiración y borrado. Un dato que no cumple se omite con motivo
auditable; no se inventa continuidad.

Plantillas Gold:

| Rol | Política |
|---|---|
| mentor, tutor | `long_term_consent`, consentimiento y 365 días |
| sales, support, auditor | `durable_business_state` |
| wellness | `session`, PII enmascarada, retención 0 |

## 3. Ensamblado real

`assemble_memory_context` entrega items acotados al prompt del agente. El nodo
`llm` ya recibe `context["memory"]` con solo `memory_id`, tipo, título, scope,
confianza y procedencia; con `pii_masking=true` no incluye descripción. La
lectura se registra como `memory.used` cuando el run no es simulación, con
idempotencia por `run_id`.

`data_mapper.py` queda expuesto en una ruta real:
`GET /api/v1/workflows/{workflow_id}/data-mapping` devuelve inventario de
planos, mapping declarativo y errores. El mapping ya se valida al crear o
actualizar el grafo.

## 4. Consentimiento, revocación y borrado

- `POST /api/v1/memory/{id}/consent/revoke`: retira consentimiento, expira y
  excluye de recall; conserva auditoría.
- `DELETE /api/v1/memory/{id}`: borra título/descripción/metadata sensible,
  marca `deleted_at` y bloquea recall.
- `GET /api/v1/memory`, `GET /api/v1/memory/{id}` y el contexto por agente
  respetan `X-Workspace-Id`; un registro de otro workspace responde 404.
- `GET /api/v1/memory/agents/{agent_id}/context` es “lo que el agente sabe:
  política, incluidas, omitidas y revisadas.

UI: drawer **Memoria** en Workflow Studio (`AgentMemoryPanel`), con selector de
agente y explicación de inclusiones/omisiones. No edita ni activa memoria.

## 5. Pruebas

| Comando | Resultado |
|---|---|
| `pytest tests/test_context_service.py tests/test_memory_context_api.py` | **10 passed** |
| Suite P06 backend (contexto, API, memoria, roles, migraciones, agente, solución, mapping) | **68 passed** (`junit-p06.xml`) |
| `ruff check` P06 | OK |
| Portal `npm run typecheck` | OK |
| Portal `AgentMemoryPanel.test.tsx` + `types.test.ts` | **15 passed** |
| Portal `npm run lint` | 0 errores (warnings preexistentes) |

Cubre: none, session ligada a conversación, participant, workspace,
durable_business_state, long_term_consent, consentimiento ausente, expiración,
sujeto distinto, workspace distinto, borrado/revocación, prompt del agente y
mapping real.

## 6. Límites

- El borrado/revocación exige owner/admin (`require_organization_admin`); un
  flujo de autoservicio del sujeto requiere identidad de participante en P12.
- `memory_events` es append-only: el borrado no elimina eventos históricos, solo
  el contenido y el acceso.
- No se midió recall/calidad RAG con proveedor real ni carga multi-tenant.
- La UI no permite editar la política desde el drawer; se edita en el rol.
- `pii_masking` omite la descripción, pero el título puede contener PII si la
  ingesta lo permite; la sanitización de títulos queda como deuda de P07/P12.
- El downgrade 168→167 no se ejecutó en este corte; el SQL es aditivo y
  reversible, pero la app nueva requiere las columnas.
- El test E2E de conversación completa (canal real) queda para P12.

## 7. Rollback

1. Revertir código de `context_service`, hook en `nodes.py`, endpoints y UI.
2. `alembic downgrade 167` elimina solo las columnas/índices nuevos 168.
3. El rollback de código debe ejecutarse antes o junto con el downgrade; el
   repositorio nuevo espera las columnas.
4. No se modificaron filas históricas.

## 8. Dictamen

**GO P06 para staging controlado.** La memoria es una sola, por rol, workspace,
sujeto y consentimiento; con revocación/borrado y lectura visible. **NO-GO
release:** autoservicio del sujeto, prueba de carga y certificación horizontal
P12 siguen pendientes.
