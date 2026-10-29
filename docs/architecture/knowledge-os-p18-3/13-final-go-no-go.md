# P18.3-13 — Release Gate final, canario, rollback y decisión GO/NO-GO

- Fecha: 2026-10-29
- Baseline: `3c97dfb4149e61a540641a69d86f676be883bee9`
- Código candidato: `d0b3b6750f8dbcb6810355f88d86662ab663a0d8`
- Rama: `master`
- Entorno evaluado: staging local con tenants sintéticos
- Manifiesto: `artifacts/certification/p18-3/release_manifest.json`

## 1. Decisión

| Destino | Decisión | Condición |
|---|---|---|
| Staging interno | **GO_STAGING** | Solo pruebas; no es producción |
| Piloto interno | **CONDITIONAL** | Requiere gold set humano, benchmark de 40 y UX |
| Piloto con cliente | **NO_GO** | Faltan puertas P0/P1 y autorización de legado |
| GA / producción | **NO_GO** | Faltan evaluación humana, caos/carga y vertical completo |

No se autootorga ningún PASS. Las puertas no ejecutadas se mantienen
`NOT_RUN`/`BLOCKED`. Un CI verde no sustituye la evaluación humana.

## 2. Matriz de puertas

| Puerta | Estado | Evidencia | Bloqueante |
|---|---|---|---|
| Corpus y ACL | PASS acotado | Tests de aislamiento + E2E | Sí; falta matriz adversarial completa |
| Citas / 40 casos | NOT_RUN | Harness listo; gold set draft | Sí |
| Fuentes históricas | BLOCKED | Plan + herramienta; sin autorización real | Sí para legado |
| Wizard y worker | PASS | E2E PDF/CSV, MIME, sesión, Explorer | Sí |
| Calidad semántica | BLOCKED | 40 casos sin revisión humana | Sí para GA |
| Agente → conocimiento | FAIL | `CONDITIONAL_REAL_PROVIDER`, 1/5 partial | Sí |
| Agente pinneado | PASS | Tests A→B y workflow publicado | Sí |
| Workflow WAIT/RESUME | PASS | Suites de durabilidad e idempotencia | Sí; vertical completo NOT_RUN |
| Proveedor real | FAIL | Primario 403; fallback real | Según capacidad vendida |
| UX cinco usuarios | NOT_RUN | Sin participantes | Sí para piloto autoservicio |
| Observabilidad y rollback | PASS acotado | Migraciones y rollback de backfill | Falta drill de caos |

## 3. Correcciones P0 entregadas

1. **Paginación de evidencia**: cursor tipado/versionado, NULL y empates
   resueltos, índice, endpoint y pruebas de 10.001 filas.
2. **Legado sin corpus**: plan dry-run, checksum, CAS, journal y rollback. No
   se aplicó nada sin autorización.
3. **Agente pinneado**: snapshot ejecutable por instancia, huellas en el
   certificado, rechazo `agents_stale` y uso de A aunque Agent Studio tenga B.
4. **Verificación honesta**: un Answer Gate skipped ya no convierte una
   narrativa verificada en `blocked`.

## 4. Evidencia ejecutada

- P18.3 suite: **38 passed**.
- Workflow regression: **59 passed**.
- Agent flow/verification regression: **77 passed**.
- E2E P18.3 PDF/CSV/sesión/Explorer: **1 passed (5,0 m)**.
- E2E P18.2 Explorer: **1 passed (50,2 s)**.
- Agent knowledge real: **CONDITIONAL_REAL_PROVIDER**; 5 casos, streaming 25
  eventos, citas válidas, sin fuga entre fuentes.
- Proveedor efectivo: fallback `openai/deepseek-ai/DeepSeek-V4.1-Flash`.
  Primario `403 NOT_ENOUGH_BALANCE`.

## 5. Bloqueos y desbloqueo

### BLOCKED_HUMAN_REVIEW

Dos anotadores independientes, árbitro y `--strict-human`. Sin esto no se
declara calidad semántica ni se ejecuta el benchmark de 40 como certificado.

### BLOCKED_AUTHORIZATION

El titular del tenant debe autorizar el backfill del caso histórico real o una
copia fidedigna. El plan sintético no sustituye esa autorización.

### NOT_RUN — vertical comercial

Crear `sales_vertical_e2e.spec.ts` con cinco turnos, WAIT/RESUME, carrito,
aprobación, sandbox de pedido, deduplicación y reinicio de worker/API. No se
puede reemplazar por tests de motor.

### NOT_RUN — caos/carga

Ventana aprobada, contenedores aislados y métricas p50/p95/máximo con n. No se
reutiliza el p95 in-process de 78–93 ms.

### NOT_RUN — cinco usuarios

Reclutar cinco participantes no técnicos, congelar guion y medir task
completion, errores críticos y comprensión de «propuesto» vs «verificado».

## 6. Canario

No se habilita canario de producción. Si en una fase posterior se autoriza:

1. flag por tenant/workspace, no global;
2. lote inicial de un tenant sintético;
3. métricas segmentadas de error, abstención, citas y latencia;
4. rollback automático si una cita fabricada, fuga ACL o efecto duplicado
   aparece una sola vez;
5. responsable on-call y ventana firmada.

## 7. Rollback

- Código: revertir el commit candidato; no hay migración destructiva.
- Migraciones 175/176: aditivas; `downgrade` elimina índice/tabla de journal.
- Backfill: `rollback --plan-id --approve`; solo revierte si `corpus_id` y
  `updated_at` no cambiaron desde el apply.
- Workflow: las instancias usan snapshot; volver a la versión publicada
  anterior no requiere reescribir historial.
- Datos: no se borraron fuentes, documentos, evidencias, embeddings, objetos ni
  sesiones durante la certificación.

## 8. Runbook de incidente

1. Congelar promoción y canario.
2. Identificar `request_id`, `source_id`, `session_id`, `agent_run_id`,
   `workflow_instance_id`, `effect_id`, modelo y `version_hash`.
3. Si hay cita fabricada o fuga ACL: deshabilitar la ruta/corpus afectado,
   preservar evidencia y notificar al responsable de seguridad.
4. Si el agente no corresponde al snapshot: detener instancias del workflow y
   re-certificar; no “arreglar” en caliente.
5. Si el worker falla: dejar la fuente en estado no listo; no habilitar chat
   con HTTP 201.
6. Restaurar desde backup verificado y comprobar deduplicación de efectos.

## 9. Capacidades realmente vendibles

- **Se puede ofrecer en staging interno**: ingesta PDF/CSV con worker real,
  sesión durable, Explorador con pasajes, chat con fallback real y agente con
  citas en un corpus sintético.
- **No se puede ofrecer como certificado**: proveedor primario, comprensión
  semántica humana, legado de un tenant real, workflow comercial completo,
  SLA de latencia/caos o usabilidad validada con cinco usuarios.
- Cualquier material comercial debe decir «fallback real» y «gold set draft»,
  no «modelo primario certificado» ni «comprensión certificada».

## 10. Deuda no bloqueante para staging

- Añadir aserción de página resaltada del PDF en Playwright.
- Medir latencia con DB real y n≥30 por familia.
- Limpiar la cola local de jobs `dead` antes de una nueva corrida E2E.
- Documentar el mapa de `source_ref` para el benchmark de 40.
