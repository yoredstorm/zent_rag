# Workflow vNext — programa de madurez universal

Este directorio es el registro de ejecución del programa que lleva ZENT de
capacidades funcionales a una plataforma de soluciones creables, probables,
publicables y operables. No es una segunda arquitectura ni una segunda autoridad
de runtime.

## Documentos

| Archivo | Propósito |
|---|---|
| `00-baseline.md` | Corte verificado: SHA, árbol, migración, flags, CI, comandos y resultados del baseline |
| `01-gap-register.md` | Brechas revalidadas en el HEAD, con evidencia, prioridad y prueba que las reproduce |
| `02-execution-paths.md` | Recorrido real descripción → rol → solución → diseño → publicación → ejecución → WAIT/RESUME |
| `03-p01-release-gate.md` | P01: gate único, certificados persistidos, rutas y evidencia |
| `04-p02-durable-ingress.md` | P02: ingress durable, inbox idempotente y rutas |
| `05-p03-solution-compiler.md` | P03: misión → blueprint → recursos reales, UI y evidencia |
| `06-p04-planner.md` | P04: presupuesto, fases, caché, clarificaciones y evaluación |
| `07-p05-policy-enforcement.md` | P05: PEP, rol, bienestar y aislamiento workspace |
| `08-p06-context-memory.md` | P06: contexto, memoria consentida, revocación y UI |
| `09-p07-subflows-errors.md` | P07: subflujos publicados, router y puertos tipados |
| `10-p08-test-studio.md` | P08: niveles, reporte persistido, hashes y UI |
| `11-p09-solution-workspace.md` | P09: workspace único, modos, gate, copiloto y undo/redo |
| `12-p10-marketplace.md` | P10: catálogo único, discovery y retorno seguro |
| `13-p11-operations.md` | P11: cola de operación, timeline y runbook |
| `14-p12-certification.md` | P12: certificación horizontal y gates |

## Autoridades que este programa NO reemplaza

- Motor de workflows: `WorkflowGraph` v2 + `execute_graph` (`src/platform/workflows/ir.py`, `runtime.py`).
- Procesos durables: `WorkflowInstance` (`src/platform/workflows/instances.py`, migración 153).
- Inbox de señales: `workflow_signals` (migración 154).
- Roles y soluciones: `role_profiles`, `studio_solutions` (migración 163).
- Catálogo y marketplace: `/api/v1/products` (`src/platform/marketplace/`).
- RBAC y permisos: `src/platform/rbac/policy.py`.
- Memoria y contexto: `src/platform/workflows/context_store.py` y `src/memory/`.

## Relación con la documentación existente

`docs/architecture/universal-studio/` y `docs/architecture/ai-workflow-studio/`
siguen siendo la documentación de diseño y auditorías previas. Este directorio
solo agrega el corte de release y la evidencia de cada fase. Cuando una
afirmación de esos documentos no coincide con el HEAD, manda el código y la
prueba registrada aquí; no se copian matrices sin revalidar.

## Reglas de evidencia

1. Cada afirmación de estado cita `archivo:línea`, comando o artefacto.
2. `PASS`, `FAIL`, `BLOCKED`, `NOT_VERIFIED` y `SKIPPED` son estados distintos.
   Un skip, timeout o `xfail` no cuenta como pase.
3. Los tests rojos de P00 viven en `tests/red/` con `xfail(strict=True)`. Se
   demuestran con `pytest tests/red --runxfail`.
4. Nada de credenciales reales, pagos productivos ni activación de
   `ZENT_GOLD_RELEASE_ENABLED`.
5. Las migraciones son aditivas y reversibles cuando sea viable; los históricos
   no se reescriben para aparentar compatibilidad.
