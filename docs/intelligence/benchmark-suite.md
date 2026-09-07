# Intelligence Benchmark Suite

Phase 30A gold cases for answerability evaluation.

## Module

`src/intelligence/benchmark.py`

- `IntelligenceBenchmarkCase`
- Categories: Simple RAG, Complex RAG, Text-to-SQL, Multi-table SQL, Legacy DB SQL,
  Business Metrics, Ambiguous Terms, Missing Data, Missing Context, Source Conflicts,
  Cross-source Questions, Temporal Questions, Entity Resolution, Analytical Questions,
  Adversarial Questions, Permission Tests
- `IntelligenceBenchmarkRunner.run(predict)` compares expected vs actual answerability

Use default suite via `IntelligenceBenchmarkRunner.default_suite()`.
