# Workflow AI Production Certification — Go/No-Go (Prompt 08)

**Fecha:** 2026-10-20  
**SHA de código auditado:** `a826d8c`  
**Entorno de evidencia:** Windows local, PostgreSQL/Redis/Qdrant reales vía Docker Compose,
LLM real autorizado del gateway configurado, tenant aislado de certificación.  
**Alcance:** AI Workflow Studio, ejecución durable, pagos, seguridad, reinicio real,
evaluación de IA y CI.  
**Resultado global: NO-GO para producción general.**

No se declara este sistema listo para producción. La ausencia de fallos unitarios no
sustituye la evidencia E2E, de carga, de proveedores reales ni de calidad del LLM.

## 1. Funcionalidades certificadas

| Capacidad | Estado | Evidencia |
|---|---|---|
| Catálogo, stock, carrito, órdenes y checkout sandbox | PASS en tenant aislado | `tests/certification/workflows` hasta el escenario 19; Gold sales funnel durable |
| WAIT/RESUME durable y misma `WorkflowInstance` | PASS | `test_gold_sales_funnel.py`, `test_durability_restart.py` |
| Reinicio real de proceso API | PASS | `tests/certification/restart` con `RAG_CERT_REAL_RESTART=1`; uvicorn terminado y levantado; 1 passed, 3m42s |
| Duplicado de webhook pagado | PASS | `test_gold_duplicate_webhook_has_single_business_effect` |
| Firma sandbox inválida | PASS | `test_gold_invalid_signature_is_rejected` |
| Firma de tenant B contra checkout de tenant A | PASS (fix P0) | `test_signed_webhook_from_other_tenant_cannot_pay_foreign_checkout` |
| Evento incompleto recuperable | PASS (fix P0) | `test_incomplete_provider_event_is_recovered_without_duplicate_effect` |
| Monto/moneda incorrectos | PASS (fix P0) | `test_signed_event_with_wrong_amount_or_currency_does_not_sell` |
| Referencia de pago desconocida | PASS | `test_unknown_payment_reference_is_unmatched_and_has_no_effect` |
| Estados Stripe async | PASS de contrato | `tests/test_commerce_payment_providers.py` (18 tests) |
| Firma IZIPAY V4 IPN | PASS de contrato | HMAC-SHA256 hex de `kr-answer` con PASSWORD; docs oficiales V4 |
| Webhook legacy de facturación sin firma | PASS (desactivado) | `tests/test_invoices.py`; respuesta 410, factura no pagada |
| Planner real Gold desde cero | **FAIL** | `tests/certification/ai/test_real_llm_gold.py`; artifact `artifacts/certification/ai/gold-real-llm.json` |
| Eval real de >=100 requerimientos | **BLOCKED** | No se ejecutó; Gold real ya bloquea FASE G |
| Carga/concurrencia de producción | **NO EJECUTADO** | No hay evidencia de load test en este SHA |
| IZIPAY/Stripe sandbox real | **NO EJECUTADO** | Sin credenciales sandbox externas en este entorno |
| Worker reiniciado | **NO EJECUTADO** | El reinicio real cubre proceso API; worker separado sigue pendiente |

## 2. Defectos P0 encontrados y corregidos

### P0-1 — Webhook legacy de facturación sin autenticación

`POST /api/v1/payments/webhook` aceptaba `payment_intent.succeeded` sin firma y podía
marcar una factura como pagada. Se reemplazó por una respuesta `410 LEGACY_WEBHOOK_DISABLED`;
no procesa payload. El endpoint de simulación de facturación queda autenticado y bloqueado
en `ENVIRONMENT=production`.

### P0-2 — Firma válida con checkout de otro tenant

El webhook comercial verificaba la firma con las credenciales de los tenants candidatos y
luego buscaba el checkout globalmente. Una firma válida de B podía resolver el checkout de
A. Se corrigió para que el checkout deba pertenecer al tenant cuya credencial firmó. También
se corrigió `find_checkout(provider_reference=...)`, que ignoraba `organization_id`.

### P0-3 — Stripe `checkout.session.completed` tratado como fondos confirmados

Un Checkout Session puede completarse con `payment_status=unpaid` en métodos asíncronos.
Ahora `completed+unpaid` produce `payment.pending`; `async_payment_succeeded` produce
`payment.succeeded`; `async_payment_failed` produce `payment.failed`.
`payment_intent.succeeded` y `payment_intent.payment_failed` se mapean explícitamente.

### P0-4 — Moneda no correlacionada

El webhook validaba monto pero no moneda. Ahora una moneda distinta del checkout registrado
se rechaza con `CURRENCY_MISMATCH`, sin señal y sin efectos de negocio.

### P0-5 — Evento incompleto quedaba terminalmente duplicado

Si una caída ocurría después de registrar el evento y antes de aplicar efectos, el reintento
devolvía `duplicate` y el efecto no se recuperaba. Los estados `received`, `processing` y
`failed` ahora se reprocesan de forma idempotente; solo `processed` es terminal. Los fallos
quedan en `failed` para reintento.

### P0-6 — Parser del planner destruía acciones válidas con DSML

El modelo real devolvió una acción JSON válida seguida de markup `<|DSML|...` de tool calling.
El regex greedy capturaba ambos y rechazaba la acción. Ahora se extrae el primer objeto JSON
completo con `json.JSONDecoder.raw_decode`.

### P0-7 — Presupuesto y contratos del planner demasiado estrechos

El Gold real truncaba `UNDERSTAND` con `max_tokens=1200` (luego 2600), fallaba por
`goal` de más de 800 caracteres y por `missing_information` con más de 10 ítems. Se añadió
normalización de la especificación, contrato de 30 faltantes, budget de 120k tokens / 20 pasos
/ 12 llamadas / 600s y cierre de descubrimiento tras 5 herramientas. También se aceptan
acciones JSON con markup DSML posterior y llamadas DSML puras. El Gold real sigue fallando
por salida vacía/inválida del modelo; esto no se declara resuelto.

### P0-8 — Sandbox de pagos disponible en producción

`ensure_provider` caía a `sandbox` cuando el tenant no tenía proveedor. En producción eso
permitía checkouts y webhooks de prueba como si fueran dinero real. Ahora `configure_provider`,
`ensure_provider` e `ingest_provider_webhook` rechazan `sandbox` con `SANDBOX_DISABLED` cuando
`ENVIRONMENT=production`. Stripe/IZIPAY deben estar configurados y autorizados.

## 3. Evidencia de pruebas

| Comando / suite | Resultado |
|---|---|
| `pytest tests/test_commerce_payment_providers.py` | **19 passed** |
| `pytest tests/test_invoices.py::test_payment_webhook_marks_paid_and_dedupes` | 1 passed |
| `pytest tests/certification/workflows/test_signals.py::test_incomplete_provider_event_is_recovered...` | 1 passed |
| `pytest tests/certification/workflows/test_tenant_isolation.py::test_signed_webhook_from_other_tenant...` | 1 passed |
| `pytest tests/certification/workflows/test_payment_failures.py -k 'wrong_amount or unknown_payment'` | 2 passed |
| `pytest tests/certification/restart` con `RAG_CERT_REAL_RESTART=1` | **1 passed** |
| `pytest tests/test_workflow_planner_agentic.py tests/test_workflow_architect_eval.py tests/test_workflow_architect.py` | **38 passed** |
| `pytest tests/test_workflow_planner_agentic.py::test_parser_ignores_dsml...` | 2 parser tests passed |
| Gate combinado pagos + planner + architect patch | **59 passed** |
| `npm run typecheck` + `ArchitectAskZent.test.tsx` | typecheck OK; 9 passed |
| `ruff src tests` | OK |
| Suite completa `tests/certification/workflows` | 19 escenarios pasaron; luego timeout ambiental en `test_payment_failures` y se ejecutaron escenarios críticos por separado. No se cuenta como suite verde completa. |
| `pytest tests/certification/ai/test_real_llm_gold.py` con LLM real | **FAILED**: `planner.invalid_llm_output`; no hay workflow generado |

El artifact del Gold real contiene la respuesta completa, el estado `BLOCKED`, la traza y el
uso de tokens. No se transformó ese fallo en un PASS.

## 4. FASE G — Evaluación de LLM real

**Estado: BLOCKED.** No se ejecutó el dataset de 100 requerimientos porque FASE A no produjo
un workflow válido con el modelo real. No se reportan métricas de interpretación, selección
de capacidades, latencia o costo como si fueran resultados certificados. El dataset de 50
casos existente usa un provider determinista y **no cuenta** como calidad de modelo real.

Umbrales solicitados: no evaluados. No hay base para afirmar ≥90% de interpretación ni ≥95%
de selección de capacidades.

## 5. Observabilidad, CI y rollout

- CI PR mantiene la suite hermética y la certificación de workflows como pasos obligatorios.
- `pip-audit` ya no tiene `continue-on-error`.
- Nightly incorpora el reinicio real de proceso API (`RAG_CERT_REAL_RESTART=1`).
- La evaluación con LLM real requiere un workflow/job controlado con presupuesto y secretos;
  no está certificada en este SHA.
- No hay evidencia de carga/backpressure para este SHA.
- Rollback de la creación con IA: `WORKFLOW_ARCHITECT_ENABLED=false`; los workflows
  existentes y sus instancias no se tocan. El rollback de pagos debe deshabilitar proveedores
  y usar el webhook firmado, nunca el legacy.

## 6. GO / NO-GO por dominio

| Dominio | Recomendación |
|---|---|
| Motor de workflows y durabilidad | **GO condicionado a staging/tenant controlado**. Reinicio real y WAIT/RESUME pasan; falta load/backpressure y worker restart. |
| Constructor inteligente (AI Workflow Studio) | **NO-GO**. El Gold real desde cero no genera un plan y no hay eval de 100 casos. |
| Workflows conversacionales de venta | **NO-GO**. Dependen de la generación IA no certificada; el Gold existente instala la plantilla y no demuestra creación desde cero. |
| Capacidades financieras | **NO-GO**. Los P0 de webhook/firma/tenant/moneda están corregidos y probados, pero no hay sandbox IZIPAY/Stripe real ni carga concurrente. |
| Marketplace y proveedores externos | **NO-GO**. Sin E2E de proveedores reales ni certificación de contratos de todos los addons. |

## 7. Recomendación final

**NO-GO global.** Bloquear creación/publicación con IA para tenants productivos. Mantener
workflows existentes y ejecución durable en staging controlado. Antes de reevaluar:

1. Corregir el bucle/salida del planner real en el Gold y ejecutar la conversación completa.
2. Ejecutar el dataset de 100 requerimientos con métricas y modelos/versiones separados.
3. Repetir reinicio real incluyendo worker y chaos de caída durante reanudación.
4. Ejecutar sandbox real de IZIPAY y Stripe, incluyendo estados asíncronos y cross-tenant.
5. Ejecutar carga concurrente, dos clientes por el último producto y presupuesto/costos.
6. Incorporar la certificación persistida al gate de publicación.
