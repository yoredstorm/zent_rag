# Validación contable / FinOps (Parte I)

Evidencia: `artifacts/certification/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/battery/accounting.json`.

| Dato | Valor |
|---|---|
| SHA | `edeeb61` |
| Fecha | 2026-10-14 |
| Entorno | DB scratch `rag_cert_battery`; writers reales (`run_accounting`, `RunBudgetLedger`, usage engine, `reconcile`, `run_metrics`) con precio determinista inyectado |
| Comando | `python -m src.scripts.certification_battery --suite accounting` |
| Resultado | **6/6 escenarios PASS · 65 tests · 0 fail** (172,6 s) |

## 1. Invariante central

```
ledger total == usage total == billing input == observability total
```

Verificado en `tests/test_certification_accounting_chain.py::test_ledger_usage_billing_observability_chain`
con matemática conocida (precio inyectado):

| Componente | Valor |
|---|---|
| Tokens prompt / completion / embedding | 1000 / 500 / 4 |
| Precio (por 1k) in/out/embedding | 0.001 / 0.002 / 0.0005 |
| **Costo esperado (a mano)** | **0.002002 USD** |
| Ledger (`RunBudgetLedger`) | 0.002002 |
| Evento de usage (`_build_usage_event`, LEE el ledger) | 0.002002 (estimated == actual) |
| Fila en `usage_events` + `reconcile(org)` | `usage_cost` 0.002002 |
| Counter Prometheus `zent_run_cost_usd_total{path="rag"}` | +0.002002 exacto |

## 2. Escenarios cubiertos

| # | Escenario | Resultado |
|---|---|---|
| I01 | una llamada: cadena completa cuadra | PASS |
| I02 | retry/fallback visibles sin doble conteo (`provider_attempt` sin tokens ni costo) | PASS |
| I03 | unknown != 0 (línea sin `cost`, flag + razón + counter separado) | PASS |
| I04 | budget blocking (STEP/TOOL/TOKEN/COST/TIME/PROVIDER_FAILURE + overrun determinista) | PASS (18 tests) |
| I05 | suma de líneas == total del ledger (llm/embedding/rerank/charge/jev) | PASS |
| I06 | reconciliación billing (usage vs invoices vs payments) | PASS |

## 3. Límites y hallazgos

- **Límite del reporte**: `reconcile` redondea a centavos (`round(x, 2)`), así que
  deltas sub-centavo aparecen como 0.00. Documentado en el test (P3-1).
- **Precio por defecto**: `run_budget.usage_cost` / `pricing.estimate_cost` tienen
  tarifas hardcodeadas como último recurso; si el registry de precios falla, el
  costo puede pasar de "unknown" a "conocido con tarifa default" aguas abajo
  (P2-6). El test I03 fuerza el fallo del registry para verificar que la línea y
  la métrica marcan `unknown`.
- **Intentos del loop de candidatos**: el router emite `provider_attempt` (visible,
  costo unknown); el loop de candidatos del runtime deja un step `router_fallback`
  sin línea contable (P2-7). No hay doble conteo, pero tampoco visibilidad total.
- **Presupuesto**: el bloqueo es determinista (test O04 ×100) y el overrun se
  detecta post-cobro; el diseño documenta que el presupuesto por respuesta es un
  *target*, no un techo paralelo (`src/runtime/run_budget.py`).
- **Ingesta**: `knowledge_usage` (embeddings de ingesta) es otra tabla y otra
  unidad de facturación (P3-2).

## 4. Para producción

1. Correr `python -m src.scripts.billing_reconcile.py --days 30` a diario y
   alertar si `delta_usage_vs_invoiced != 0` (hoy no hay métrica; P2-8).
2. Cargar tarifas reales por modelo en `pricing_models` (P2-6).
3. Extender la emisión de `provider_attempt` al loop de candidatos (P2-7).
