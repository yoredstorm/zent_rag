# Battery — chaos

- SHA: `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8`
- Fecha: 2026-10-14T20:02:42.577940+00:00
- Comando: `D:\zent_RAG\.venv\Scripts\python.exe -m pytest tests/test_chaos_resilience.py tests/test_provider_attempts.py tests/test_llm_stream_fallback.py tests/test_llm_embed_fallback.py tests/test_llm_embed_retry.py tests/test_model_health.py tests/test_budget_stop_reasons.py tests/test_db_lifecycle.py tests/test_answer_state_texts.py tests/test_evidence_semantics.py tests/test_certification_accounting_chain.py tests/test_certification_security.py -q --tb=short --timeout=300 --junitxml=artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\battery\junit-chaos.xml`
- Tests: 115 (pass 115 / fail 0 / error 0 / skip 0)
- Escenarios: pass 17 / fail 0 / no demostrados 0

| ID | Escenario | Estado | Tests |
|---|---|---|---|
| F01 | primary LLM hard failure | PASS | 3 |
| F02 | primary LLM 429 | PASS | 2 |
| F03 | primary LLM timeout | PASS | 2 |
| F04 | fallback LLM failure | PASS | 1 |
| F05 | embedding provider unavailable | PASS | 16 |
| F06 | reranker unavailable | PASS | 1 |
| F07 | JEV unavailable | PASS | 1 |
| F08 | Redis unavailable | PASS | 1 |
| F09 | Qdrant unavailable / retrieval failure | PASS | 1 |
| F10 | PostgreSQL transient disconnect | PASS | 2 |
| F11 | tool timeout | PASS | 1 |
| F12 | tool hard failure (5xx/permanente) | PASS | 1 |
| F13 | malformed tool output | PASS | 1 |
| F14 | circuit breaker abierto | PASS | 1 |
| F15 | partial streaming failure | PASS | 1 |
| F16 | dependency recovery (circuito se cierra) | PASS | 2 |
| F17 | retry amplification acotada | PASS | 2 |
