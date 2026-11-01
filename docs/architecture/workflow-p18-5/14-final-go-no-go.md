# P18.5-14 — Auditoría final, release gates y STOP de expansión

## Identidad

- Rama: `fix/p18-5-security-execution-live-studio`
- Merge a master: `8893fac` (no-ff)
- Commits: `3b859f9`, `e23b2ed`, `732e25e`, `7730264`
- Baseline: `e6c42c2579df0e997ef2a0a0d0916f05dc735bef`

## Resumen de lo corregido

| ID | Defecto | Estado | Evidencia |
|---|---|---|---|
| P0 snapshot | `tools=[]`/`prompt=""` heredaban valores vivos | CLOSED | 6 tests snapshot |
| P0 workspace | `GET /runs/{id}` leía otro workspace | CLOSED | 2 tests + 1 skip |
| P0 aprobación | `approval_ref="approved"` autorizaba un POST | CLOSED | 4 tests aprobación |
| P0 revocación | WAIT/RESUME no aplicaba revocaciones nuevas | CLOSED | 3 tests revocación |
| P0 idempotencia local | Doble POST podía duplicar intención | CLOSED local | 2 tests idempotencia |
| P1 historial | Sin hashes comparables | CLOSED | read model + tests UI |
| P1 test studio vivo | Sin polling de WAIT/RESUME | CLOSED | E2E live resume |
| P1 timeline | `LIMIT 1000` silencioso | CLOSED | 2 tests timeline |
| P2 canvas | Preview estático parecía recorrido | Mitigado | rótulo estructura + inspector |
| P2 accesibilidad | Sin prueba formal | NOT_RUN | — |

## Matriz de decisión

### P0

No quedan P0 de código abiertos según las pruebas ejecutadas. Esto **no**
equivale a certificación de producción: falta E2E adversarial completo,
proveedor sandbox y caos.

### P1

- Cobertura E2E adversarial incompleta (aprobación/replay/workspace/historial).
- No hay prueba de usuario real.
- No hay baseline de rendimiento ni SLO medido.
- No se probó rollback con tráfico real.
- La suite backend completa (6057 tests) no se ejecutó de punta a punta en esta
  sesión; se ejecutaron 150 tests de workflow, todas las suites P18.5 y la suite
  completa del portal. Se declara **NOT_RUN** el agregado, no PASS.

### P2

- Canvas no proyecta aristas ejecutadas/ramas omitidas.
- Polling no implementa reautenticación automática.
- Recursos legacy sin workspace son globales por diseño.
- Firma criptográfica de aprobaciones no implementada.

## Prueba con usuarios

**NOT_RUN.** No se ejecutaron 5 usuarios reales no técnicos. No se simularon con
un LLM. Por tanto no se declara usabilidad certificada.

## GO / NO-GO

**Decisión: GO_LOCAL_DEV.**

- Autorizado: desarrollo local, revisión de código, merge a master como rama de
  estabilización, ejecución con datos sintéticos.
- No autorizado: `GO_STAGING` con datos de clientes, `GO_INTERNAL_PILOT`,
  `GO_CUSTOMER_PILOT`, `GO_GENERAL_AVAILABILITY`, operaciones irreversibles
  reales, cobros, correos o webhooks productivos.

## Checklist de reversión

1. Revertir commits `7730264`, `732e25e`, `e23b2ed` en orden inverso.
2. Migración 177: `alembic downgrade -1` elimina columnas/tabla nuevas; no toca
   `workflow_approvals` existentes ni runs.
3. Instancias WAIT: su `definition_snapshot` y `policy_snapshot` no se
   reescribieron; el backend anterior puede leerlas.
4. Portal: la versión anterior ignora campos nuevos (`instance_id`,
   `durableStatus`, `graph_hash`); no hay migración de localStorage.
5. Verificar que no quedan requests con `Idempotency-Key` apuntando a runs
   duplicados antes de reactivar tráfico real.

## Evidencia

- `evidence-manifest.json`
- `gates.json`
- Suites y comandos en `12-certification.md`
- E2E: `portal/e2e/p18-5-live-resume.spec.ts` (1 passed local y 1 passed
  contra Docker `:8080` con migración 177 aplicada).
- Docker local actualizado: API `rag-api` healthy, portal `rag-portal` healthy,
  worker arriba; `alembic current` = `177 (head)`.

## STOP de expansión

No se autoriza workflow architect IA, nodos conversacionales, depurador de
estados, marketplace único, patrones de ventas ni orquestación avanzada hasta
cerrar P18.5-12/13/14 con infraestructura real de prueba y aceptación explícita
de riesgos.
