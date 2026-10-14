# Battery — security

- SHA: `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8`
- Fecha: 2026-10-14T19:52:03.249620+00:00
- Comando: `D:\zent_RAG\.venv\Scripts\python.exe -m pytest tests/test_certification_security.py tests/test_agent_security.py tests/test_prompt_assembly.py tests/test_prompt_block_headers.py tests/test_knowledge_adversarial.py tests/test_adaptive_passages_claims.py tests/test_evidence_assembly.py tests/test_tenant_isolation.py tests/test_conversation_isolation.py tests/test_certification_tenant_stress.py tests/test_identity_hardening.py tests/test_organization_filter_injection.py tests/test_sql_security.py tests/test_security_hardening.py tests/test_admin_sql.py tests/test_connector_security.py tests/test_connector_api.py tests/test_openapi_connector.py tests/test_authorized_scope.py tests/test_knowledge_scope.py tests/test_agent_source_ids.py tests/test_rbac_matrix.py tests/test_action_plane_authority.py tests/test_workflow_node_catalog.py tests/test_data_onboarding.py -q --tb=short --timeout=300 --junitxml=artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\battery\junit-security.xml`
- Tests: 350 (pass 350 / fail 0 / error 0 / skip 0)
- Escenarios: pass 22 / fail 0 / no demostrados 0

| ID | Escenario | Estado | Tests |
|---|---|---|---|
| G01 | prompt injection del usuario | PASS | 3 |
| G02 | prompt injection en documento recuperado | PASS | 2 |
| G03 | prompt injection en tool observation | PASS | 2 |
| G04 | fake system instruction dentro de knowledge | PASS | 4 |
| G05 | cross-tenant retrieval attempt | PASS | 13 |
| G06 | cross-tenant cache key attempt | PASS | 3 |
| G07 | model-proposed organization_id | PASS | 11 |
| G08 | model-proposed user_id | PASS | 1 |
| G09 | tool no autorizada | PASS | 4 |
| G10 | SQL no autorizado | PASS | 3 |
| G11 | SQL mutación con read-only | PASS | 22 |
| G12 | SSRF a endpoints internos | PASS | 10 |
| G13 | redirect-based SSRF | PASS | 3 |
| G14 | exfiltración de credenciales/headers | PASS | 18 |
| G15 | path traversal en connectors/files | PASS | 2 |
| G16 | payload sobredimensionado | PASS | 1 |
| G17 | tool argument smuggling | PASS | 5 |
| G18 | metadata OpenAPI maliciosa | PASS | 2 |
| G19 | knowledge_scope escape | PASS | 46 |
| G20 | conversation isolation | PASS | 11 |
| G21 | RBAC downgrade | PASS | 9 |
| G22 | workflow privilege escalation | PASS | 30 |
