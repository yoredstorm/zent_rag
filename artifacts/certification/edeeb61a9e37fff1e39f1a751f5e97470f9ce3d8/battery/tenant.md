# Battery — tenant

- SHA: `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8`
- Fecha: 2026-10-14T20:09:56.386686+00:00
- Comando: `D:\zent_RAG\.venv\Scripts\python.exe -m pytest tests/test_certification_tenant_stress.py tests/test_tenant_isolation.py tests/test_conversation_isolation.py tests/test_knowledge_scope.py tests/test_authorized_scope.py tests/test_workspace_isolation.py -q --tb=short --timeout=300 --junitxml=artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\battery\junit-tenant.xml`
- Tests: 49 (pass 49 / fail 0 / error 0 / skip 0)
- Escenarios: pass 6 / fail 0 / no demostrados 0

| ID | Escenario | Estado | Tests |
|---|---|---|---|
| H01 | retrieval con mismo texto/filename | PASS | 1 |
| H02 | cache con misma query/conversación | PASS | 1 |
| H03 | usage/billing por tenant | PASS | 1 |
| H04 | knowledge scope disjunto | PASS | 1 |
| H05 | aislamiento de vectores por KB | PASS | 1 |
| H06 | aislamiento de conversaciones | PASS | 8 |
