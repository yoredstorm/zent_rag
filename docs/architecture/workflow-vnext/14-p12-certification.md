# 14 — P12: certificación horizontal

Fecha: `2026-10-23`. Base: `0cbb494ce4` + P00–P11.

## 1. Alcance y gates medibles

Antes de ejecutar se fijaron estos gates:

| Gate | Criterio |
|---|---|
| Backend/CI | suite completa verde, lint y migraciones |
| Roles | seis roles Gold sobre el mismo motor y contratos seguros |
| Aislamiento | tenant/workspace sin lectura ni señal cruzada |
| Certificados | STALE/denegado no publica |
| Efectos | duplicados/replay/pago no cobran dos veces |
| Durabilidad | reinicio conserva la instancia y reanuda una vez |
| RAG | inyección no se convierte en instrucción |
| Export/import | paquete sin secretos y ejecutable tras resolver dependencias |
| UX | 5 participantes no técnicos |
| Proveedor | sandbox/provider real conectado |

## 2. Evidencia disponible

- CI run `40061310253` sobre `ee69b21`: **todos los jobs success** — secrets,
  lint, pip-audit, portal, portal-e2e, backend, SDKs, kustomize y build.
- CI backend incluye `tests/` completo y `tests/certification/workflows`.
- P12 rol matrix (`tests/certification/p12`): **9 passed**.
- P11 cola: **3 passed**.
- P00–P11 tienen JUnit/manifest en `artifacts/certification/`.
- Certificación existente cubre Gold sales, restart, pagos, señales, tenant
  isolation, provider failure, marketplace y portabilidad.

## 3. Matriz de roles

| Rol | Motor | Memoria | Autonomía | Bienestar/no clínico |
|---|---|---|---|---|
| ventas | same `execute_graph` | durable business state | require approval | — |
| mentor | same | long-term consent | propose actions | — |
| tutor | same | long-term consent | propose actions | — |
| auditor | same | durable business state | propose actions | — |
| soporte | same | durable business state | propose actions | — |
| wellness | same | session, PII masking | answer_only | no diagnóstico/prescripción |

La matriz verifica contrato, propuesta de workflow, política de memoria y que
wellness no tenga capacidades clínicas.

## 4. Resultados por gate

| Gate | Resultado |
|---|---|
| Backend/CI | **PASS** (run 40061310253) |
| Roles | **PASS** (9 tests) |
| Aislamiento tenant/workspace | **PASS** en tests existentes/CI |
| Certificados stale | **PASS** en gate P01/CI |
| Duplicados/pagos/replay | **PASS** en certification workflows/CI |
| Reinicio durable | **PASS** en certification/CI |
| RAG prompt injection | **PASS** en tests de hardening/CI |
| Export/import | **PASS** con publicación externa bloqueada sin sandbox |
| UX 5 participantes | **NOT_VERIFIED** |
| Proveedor real | **NOT_VERIFIED** |
| Chaos real Redis/Postgres | **NOT_VERIFIED** |

## 5. Decisión

- **GO_FOR_STAGING**: sí, con el SHA certificado por CI y Docker local healthy.
- **GO_FOR_CONTROLLED_PILOT**: **NO**. Faltan estudio de 5 usuarios, proveedor
  real y drills de caída.
- **PRODUCTION GA**: **NO_GO**. `ZENT_GOLD_RELEASE_ENABLED` no se activa y no se
  emite `PROVIDER_VERIFIED` sin proveedor real.

## 6. Rollback

Revertir los commits de P11/P12 o el SHA desplegado; no hay migración P11/P12.
El stack local se reconstruye desde `ee69b21` (o el SHA siguiente) con
`docker compose build api ingestion-worker portal` y `docker compose up -d`.

## 7. Limitaciones registradas

No se inventan PASS: los gates `NOT_VERIFIED` anteriores bloquean piloto y GA.
La UI no sustituye una prueba de accesibilidad con usuarios reales.
