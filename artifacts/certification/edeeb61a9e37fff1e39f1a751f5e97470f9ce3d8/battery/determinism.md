# Battery — determinism

- SHA: `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8`
- Fecha: 2026-10-14T20:03:50.557798+00:00
- Comando: `D:\zent_RAG\.venv\Scripts\python.exe -m pytest tests/test_certification_determinism.py tests/test_finalization_golden.py tests/test_adversarial_matrix.py tests/test_conversation_isolation.py -q --tb=short --timeout=300 --junitxml=artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\battery\junit-determinism.xml`
- Tests: 222 (pass 222 / fail 0 / error 0 / skip 0)
- Escenarios: pass 6 / fail 0 / no demostrados 0

| ID | Escenario | Estado | Tests |
|---|---|---|---|
| O01 | tool authorization ×100 | PASS | 1 |
| O02 | tenant authorization ×100 | PASS | 1 |
| O03 | cache isolation ×100 | PASS | 2 |
| O04 | budget blocking ×100 | PASS | 2 |
| O05 | finalization canónica ×100 | PASS | 2 |
| O06 | security guards ×100 | PASS | 5 |
