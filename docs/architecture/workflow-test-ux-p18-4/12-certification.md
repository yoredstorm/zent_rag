# P18.4-12 — Gate de release

- Fecha: 2026-10-30
- Rama: `p18.4-workflow-test-ux`
- Baseline: `bd142c480219eac56df020ca5a8642d513977fd2`
- Entorno evaluado: staging local, tenant demo, build de producción servido con `vite preview`

## 1. Decisión

| Destino | Decisión | Condición |
|---|---|---|
| Staging interno | `GO_STAGING` | Panel nuevo, pruebas locales y E2E de flujo principal verdes |
| Piloto interno | `CONDITIONAL` | Faltan teclado/lector de pantalla, cinco usuarios, hash de historial y suite completa limpia |
| Piloto con cliente | `NO_GO` | P18.3 sigue con bloqueos de proveedor, gold set y seguridad |
| Producción | `NO_GO` | P18.3 y evaluación humana pendientes |

No se autootorga PASS de proveedor, accesibilidad total, estudio humano ni producción.

## 2. Matriz de regresión

| Área | Estado | Evidencia |
|---|---|---|
| `/test` conserva `requested_level` y escenario | PASS local | Test unitario y E2E |
| `/run` conserva payload y `simulate:false` | PASS local | Test unitario y E2E de efectos |
| Preview no llama `/run` | PASS local | Test unitario y E2E de modos |
| Sandbox/provider capeado no finge PASS | PASS local | Test unitario + reporte real |
| `provider_verified` solo backend | PASS local | Presentación y test |
| Save-before-run bloquea ejecución | PASS local | Test de fallo de guardado |
| Confirmación real | PASS local | `ConfirmDialog` con texto `EJECUTAR`; E2E de cancelación y de efecto |
| `onRun`/`onSelectNode` | PASS local | Test y E2E |
| Respuesta, recorrido y verificación | PASS acotado | Tests y capturas |
| Historial | PASS acotado | Lista y resultado histórico; falta comparación de hash |
| WAIT/RESUME | PASS acotado | `wait_event` espera y una señal reanuda la instancia |
| Aprobación humana | PASS acotado | `human_approval` real queda en “Esperando aprobación” |
| Efectos reales | PASS acotado | `notify` in-app real, solo tras `EJECUTAR` |
| Accesibilidad axe del panel | PASS acotado | 1440 setup/result y 390 setup sin serious/critical |
| Teclado y lector de pantalla | `NOT_RUN` | Sin ejecución completa |
| Cinco usuarios | `NOT_RUN` | Sin participantes |
| CI remoto | `NOT_VERIFIED` | Sin `gh` |

## 3. Evidencia ejecutada

- Panel: 27/27 tests.
- Inspector: 1/1.
- Reducer y presentación: 20/20.
- Backend test studio/report: 10/10.
- E2E workflow studio: 2/2 contra build real final.
- Captura visual: 1/1.
- Drawer móvil: 1/1.
- Modos preview/provider/cancelación: 1/1.
- Aprobación humana: 1/1.
- `wait_event` + señal: 1/1.
- Efecto real `notify` in-app: 1/1.
- Build final: PASS.
- Axe del panel: PASS acotado.

## 4. Bloqueos

### P0 P18.3

`src/platform/deployments/versions.py::resolve_agent`:

```python
tools=list(snapshot.get("tools") or agent.tools or []),
```

Un snapshot con `tools=[]` cae a herramientas vivas. No se corrige en P18.4. Bloquea efectos sensibles y cualquier afirmación de producción.

### Proveedor real

En el entorno local:

```text
requested_level=provider
effective_level=simulation
provider_verified=false
result=UNVERIFIED
capped_reason=provider_adapter_unavailable
```

La UI muestra “Proveedor no conectado” y no emite sello.

### Evaluación humana

No hay cinco participantes. No se declara que la UX sea comprensible para no técnicos.

### Accesibilidad

Axe del panel pasó con scope en 1440 setup/result y 390 setup. La página completa conserva una violación preexistente en los puertos del canvas, fuera del panel. La navegación con lector de pantalla no se ejecutó.

### Suite completa

La suite completa se intentó de nuevo con `--maxWorkers=2`, pero el reinicio del entorno la canceló. Se conserva la primera pasada: 619 PASS y 22 errores de shutdown de workers. `NOT_CLEAN`; no se declara verde.

## 5. Rollback

- Revertir los commits de P18.4.
- Sin migraciones ni cambios de datos.
- El backend, runs, reportes y certificados no se tocaron.
- El rollback no desactiva RBAC, confirmación ni enforcement de backend.
- `WorkflowTestPanel` anterior se conserva en el historial de git.

## 6. Recomendación

Mantener `GO_STAGING` para revisión interna. No promover a piloto con cliente ni producción hasta:

1. Corregir el P0 de `resolve_agent`.
2. Completar teclado y lector de pantalla; axe del panel ya pasó con scope.
3. Completar cinco usuarios no técnicos con las metas congeladas.
4. Resolver la comparación de hash del historial.
5. Repetir la suite completa sin errores de workers.
