# Zent Learning Loop (FASE 25)

> Observation → Inference → Suggestion → Human Review → Approval →
> Versioned Knowledge → Evaluation Replay → Production.
> Jamás se convierte automáticamente una suposición del LLM en verdad empresarial.

## 1. Pipeline gobernado

```
Abstención/SQL repetido/Schema drift
  → ContextGapAnalyzer / Clusterer / PatternDetector   (Observation + Inference)
  → improvement_items (IN_REVIEW)                       (Suggestion)
  → aprobación humana en Review Queue                   (Human Review)
  → materialización + approval_records                  (Approval + Versioned Knowledge)
  → Evaluation Replay (job eval_replay:*)               (Evaluation Replay)
  → producción
```

## 2. Approval Records — who / when / why / evidencia / versiones

`approval_records` guarda por cada acción:

```json
{
  "knowledge_type": "glossary",
  "knowledge_id": "margen",
  "action": "approve",
  "acted_by": "user-uuid",
  "reason": "revisión humana",
  "source_evidence": ["review queue"],
  "previous_version": {"version": 1},
  "new_version": {"version": 2},
  "replay_id": null
}
```

Se registran en: aprobación de sugerencias (Review Queue), aprobación de
métricas, aprobación de glosario, confirmación de relaciones, configuración
de autoridad. Métricas: `rag_semantic_approvals_total{type}` y
`rag_semantic_rejections_total`.

## 3. Evaluation Replay — antes / después

Al aprobar conocimiento **crítico** (metric / glossary / authority) con
`RAG_LEARNING_REPLAY_REQUIRED=true`, se encola el job durable `eval_replay:*`:

1. Busca golden cases afectados (tokens del concepto en la pregunta o
   `expected_answerability`).
2. `before` = último run de evaluación de los datasets afectados.
3. `after` = `EvalRunner` sobre los casos afectados (juez off → determinista;
   incluye `answerability_accuracy`).
4. Verdict: `pass` (delta ≥ -0.05) · `warn` (-0.15..-0.05) · `fail` (< -0.15) ·
   `unknown` (sin casos).
5. Resultado en `learning_replays` + run persistido en `eval_runs`.

Manual: `POST /api/v1/learning/replay`. Vista: `GET /api/v1/learning/replays`.

## 4. Versioning

- Glosario: `business_definitions.version` (bump en cada upsert) + fechas de
  vigencia + provenance.
- Métricas: `catalog_metrics.version`.
- Enums: `catalog_enum_values.version` (migración 081).
- Los traces históricos (`intelligence_traces.decision`) conservan qué
  conceptos/versiones se usaron; `Why does Zent know this?` expone
  `concept_versions` desde el glosario.

## 5. Continuous Improvement — solo datos reales

`GET /api/v1/learning/improvements/summary` calcula del mes:

```json
{
  "approved_definitions": 14,
  "validated_relationships": 7,
  "new_authoritative_sources": 3,
  "resolved_context_gaps": 31,
  "answerability_delta_pct": 12.0,
  "unsupported_delta_pct": -18.0,
  "current_answerability_rate": 78.0
}
```

## 6. Analytics

`GET /api/v1/learning/analytics?days=30` — answerability/abstention rates,
gap resolution rate, mejoras abiertas, conceptos faltantes más impactantes,
aprobaciones 30d, replays por verdict. Todo derivado de traces/gaps/audit
reales.

## 7. Integración

- Orchestrator: en cada abstención (gate, planner, critic) →
  `ContextGapAnalyzer.analyze_and_record(...)`.
- Worker: dispatch por prefijo `eval_replay:*` / `spider:*`.
- Portal: tab "Mejoras" (Knowledge) + "Context Gaps" e "Impacto" (AI Quality).