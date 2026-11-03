# P18.4-00 — Auditoría del Workflow Test Studio

- Fecha: 2026-10-29
- Baseline solicitado: `bd142c480219eac56df020ca5a8642d513977fd2`
- HEAD auditado: `bd142c480219eac56df020ca5a8642d513977fd2`
- Rama de trabajo: `p18.4-workflow-test-ux`
- Entorno: local Windows, sin acceso a GitHub CLI

## 1. Estado del baseline

| Dato | Valor |
|---|---|
| Rama base | `master` |
| Working tree | limpio al iniciar |
| Remoto | `master...origin/master` sin divergencia |
| CI remoto | `NOT_VERIFIED`: no hay `gh` instalado; no se consultó el run |
| Capturas baseline | `NOT_RUN`: no existen en el repositorio al iniciar |

No se declara CI, E2E, accesibilidad, proveedor ni producción como PASS.

## 2. Pruebas ejecutadas antes del refactor

| Comando | Resultado |
|---|---|
| `npm --prefix portal run typecheck` | PASS local |
| `npm --prefix portal run lint` | PASS local, 0 errores, 26 warnings preexistentes |
| `npm --prefix portal run test -- src/components/workflowStudio/WorkflowTestPanel.test.tsx` | 13/13 PASS |
| `uv run pytest tests/test_workflow_test_studio.py tests/test_workflow_test_report.py -q` | 10/10 PASS |
| Suite completa portal | `NOT_RUN` |
| `npm --prefix portal run build` | `NOT_RUN` |
| E2E navegador | `NOT_RUN` |

## 3. Mapa de componentes

```text
WorkflowStudioPage
  WorkflowCanvasEditor
    WorkflowCanvas (overlay de run)
    WorkflowContextPanel
  aside (lg)
    WorkflowTestPanel
  Drawer (mobile)
    WorkflowTestPanel
  WorkflowRunInspector
    WorkflowApprovalPanel
```

### Archivos principales

| Archivo | Líneas | Responsabilidad |
|---|---:|---|
| `portal/src/components/workflowStudio/WorkflowTestPanel.tsx` | 674 | chat, niveles, ejemplos, JSON, test, run real, reporte, historial |
| `portal/src/components/workflowStudio/WorkflowTestPanel.test.tsx` | 261 | 13 pruebas del panel |
| `portal/src/pages/WorkflowStudio.tsx` | 1059 | monta dock desktop y drawer móvil |
| `portal/src/components/WorkflowRunInspector.tsx` | 525 | pasos, efectos, contexto y aprobación |
| `portal/src/components/workflowStudio/types.ts` | 221 | `normalizeTestPayload`, `answerFromSteps`, `WorkflowRun` |
| `portal/src/lib/workflowEffects.ts` | 62 | clasificación de efectos previstos |
| `portal/src/lib/workflowErrors.ts` | 72 | traducción de errores operativos |

## 4. Contratos de backend verificados

| Endpoint | Permiso | Semántica |
|---|---|---|
| `POST /api/v1/workflows/{id}/test` | `workflows:run` | Decide nivel efectivo; persiste reporte con hashes, timeline, executed_nodes |
| `POST /api/v1/workflows/{id}/run` | `workflows:run` | Ejecución real con `{payload, simulate:false}` mediante ingress |
| `GET /api/v1/workflows/{id}/runs` | `workflow_runs:read` | Historial del workflow |
| `GET /api/v1/workflows/runs/{run_id}` | `workflow_runs:read` | Detalle de pasos y efectos |
| `GET /api/v1/workflows/{id}/sample-outputs` | `workflow_runs:read` | `run_id`, `trigger_payload`, `nodes` |
| `GET /api/v1/workflows/{id}/test-reports` | `workflow_runs:read` | Reportes persistidos |
| `GET /api/v1/workflows/{id}/readiness` | `workflows:read` | Checklist de grafo; no disponibilidad de proveedor |

Hallazgo preexistente: `GET /runs/{id}` y `GET /sample-outputs` filtran por organización, no por workspace. La UI no debe ampliar ese acceso. Queda como deuda de seguridad de backend.

## 5. Semántica que no se simplifica

1. `requested_level` y `effective_level` son distintos.
2. Sandbox capeado a simulation puede devolver `result=PASSED`; no es un pase sandbox.
3. Provider capeado devuelve `UNVERIFIED`; `provider_verified=false`.
4. `provider_verified=true` solo lo emite el backend con `effective_level=provider` y verificación real.
5. `PASSED` no equivale a publicado, certificado ni proveedor real.
6. `PREVIEW` no ejecuta nodos ni efectos.
7. `DECLARED`, `SIMULATED`, `UNVERIFIED`, `BLOCKED`, `WAITING` conservan su significado.
8. `/test` usa simulación o verificación según nivel efectivo.
9. `/run` es ejecución real, con posibles efectos externos.
10. `onRun` alimenta el overlay; `onSelectNode` selecciona nodo. No hay segundo motor de trazas.

## 6. Matriz de estados

| Estado | Fuente de verdad | Acción permitida | Riesgo |
|---|---|---|---|
| Sin input | `raw` local | Preview; simulación deshabilitada | CTA vacío |
| Input texto | `normalizeTestPayload` | Probar según modo | Perder `{message,query}` |
| Input JSON | `normalizeTestPayload` | Run real con payload completo; test con texto de escenario | Cambiar forma del payload |
| Grafo sin agente | `issues` | Aviso; ir al nodo; permitir eco | Ocultar eco |
| Grafo con efectos | `effectLabels` | Aviso; confirmación | Efecto silencioso |
| Dirty | `dirty` | Guardar antes de probar | Versión vieja |
| Save fallido | `save() === false` | No ejecutar; reintentar | Resultado obsoleto |
| Preview | reporte `PREVIEW` | Mostrar “no ejecutó” | Falso PASSED |
| Simulation | `effective=simulation` | Mostrar límites | Confundir con proveedor |
| Sandbox capeado | `requested=sandbox`, `effective=simulation` | Mostrar ambos niveles | PASSED falso de sandbox |
| Provider capeado | `requested=provider`, `effective=simulation`, `UNVERIFIED` | Mostrar no conectado | Sello falso |
| Provider verificado | `provider_verified=true` | Mostrar verificado, no publicado | Confundir con publicación |
| BLOCKED | `result=BLOCKED` | Ir al nodo | Ocultar bloqueo |
| Run exitoso | `RunDetail.status=succeeded` | Respuesta, recorrido, verificación | Leer como test seguro |
| Run fallido | `status=failed` | Error humano; nodo | Ocultar efecto parcial |
| WAITING | `status` waiting | Esperando mensaje/aprobación | Prometer respuesta |
| Pending approval | `pending_approval` | Mostrar aprobación real | Aprobación ficticia |
| Run histórico | historial | Resultado histórico; avisar hash | Creer que es el grafo actual |
| Sesión expirada | `ApiError` 401 | Reautenticar | Perder borrador |
| 403 | `ApiError` 403 | Explicar permiso | Saltar RBAC |
| 409 | `ApiError` 409 | Conflicto de edición | Sobrescribir |
| 429/503/timeout | `ApiError.retryable` | Reintento seguro | Duplicar efectos |

## 7. Hallazgos críticos

1. Footer inicial con 14 controles interactivos y CTA principal solo icono.
2. “Ejecutar de verdad” compite visualmente con “Probar”.
3. Confirmación real solo si `effectLabels.length > 0`; usa `window.confirm`.
4. Sandbox/provider se etiquetan “no conectado” de forma estática, pero igual se solicita `/test`.
5. `/test` no usa `normalizeTestPayload`; JSON se envía como mensaje de escenario. `/run` sí usa payload completo.
6. `executeTest` no limpia el run anterior al iniciar; un fallo deja overlay viejo.
7. Guard `busy` no es síncrono; doble clic puede duplicar.
8. Sin token de operación; una respuesta tardía puede contaminar otro workflow.
9. `preview`, `passed`, `unverified`, `blocked`, `waiting` no tienen metadatos en `StatusBadge`.
10. Resultado, reporte, pasos e historial compiten en un solo scroll tipo chat.
11. Historial no marca “resultado histórico” ni compara hash.
12. Móvil cierra el drawer al seleccionar nodo y pierde estado.
13. `Generar ejemplo` no inspecciona trigger ni inputs.
14. `Usar último` sustituye el input sin restaurar.
15. `provider_verified` no se muestra explícitamente.
16. `capped_reason` se muestra como código crudo.
17. No hay `aria-live` para el resultado.
18. No hay tabs semánticas de Resultado.

## 8. Gate P18.3

`src/platform/deployments/versions.py::resolve_agent` conserva:

```python
tools=list(snapshot.get("tools") or agent.tools or []),
```

Un snapshot certificado con `tools=[]` cae a las herramientas vivas. Es un P0 independiente. P18.4 no lo corrige ni lo tapa. Con este gate abierto, el máximo es `GO_STAGING` y los efectos sensibles quedan limitados a sandbox autorizado.

## 9. Propuesta de migración reversible

- Rama `p18.4-workflow-test-ux`.
- Sin cambios de backend ni de permisos.
- Componentes nuevos pequeños y reducer puro.
- Tests caracterizadores antes del refactor.
- Rollback: revertir commits de P18.4; no hay migraciones ni datos.
- Conservar `?panel=test`, overlays, inspector, historial y versión guardada.
