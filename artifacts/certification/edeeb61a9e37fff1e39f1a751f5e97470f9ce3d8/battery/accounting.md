# Battery — accounting

- SHA: `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8`
- Fecha: 2026-10-14T20:14:37.159537+00:00
- Comando: `D:\zent_RAG\.venv\Scripts\python.exe -m pytest tests/test_certification_accounting_chain.py tests/test_run_accounting.py tests/test_run_accounting_rag.py tests/test_cost_authority.py tests/test_run_budget.py tests/test_budget_stop_reasons.py tests/test_run_metrics.py tests/test_finops.py tests/test_billing_limits_api.py -q --tb=short --timeout=300 --junitxml=artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\battery\junit-accounting.xml`
- Tests: 65 (pass 65 / fail 0 / error 0 / skip 0)
- Escenarios: pass 6 / fail 0 / no demostrados 0

| ID | Escenario | Estado | Tests |
|---|---|---|---|
| I01 | una llamada: cadena completa cuadra | PASS | 1 |
| I02 | retry/fallback visibles sin doble conteo | PASS | 1 |
| I03 | unknown != 0 | PASS | 1 |
| I04 | budget blocking | PASS | 18 |
| I05 | suma de líneas == total | PASS | 6 |
| I06 | reconciliación billing | PASS | 5 |
