# Zent Context Advisor (FASE 25)

> Zent no se limita a decir "missing context": diagnostica POR QUÉ no pudo
> responder e indica exactamente cómo mejorar, usando datos reales del
> catálogo y del ciclo de aprendizaje.

## 1. Context Gap Engine — `ContextGapAnalyzer`

Cada consulta no contestable se convierte en un gap estructurado. El mapeo es
**determinista** (decision.status + reason_codes → gap type); el LLM nunca es
la fuente del gap.

| Estado / razón | Gap |
|---|---|
| CONTEXT_MISSING · UNDEFINED_BUSINESS_TERM | MISSING_BUSINESS_TERM |
| DATA_MISSING · NO_SOURCE_AVAILABLE | MISSING_SOURCE |
| DATA_MISSING · NO_SQL_RESULT / NO_RETRIEVAL | MISSING_TABLE |
| DATA_MISSING · hints de campo | MISSING_FIELD |
| SOURCE_CONFLICT · SOURCE_DISAGREEMENT | SOURCE_CONFLICT (+ `source_conflicts`) |
| DATA_QUALITY_LOW · STALE / LOW_DATA_QUALITY | STALE_SOURCE / LOW_DATA_QUALITY |
| ACCESS_BLOCKED · PERMISSION_DENIED | PERMISSION_LIMITATION |
| AMBIGUOUS / CLARIFICATION_REQUIRED | AMBIGUOUS_TERM |
| EXECUTION_FAILED · BUDGET_EXCEEDED | UNSUPPORTED_OPERATION |
| UNDEFINED_ENUM (EnumDiscovery) | UNDEFINED_ENUM |

Cada gap registra: `question`, `evidence_hints`, `impact`
(`query_count_30d`, `users`, `agents` — de datos reales de traces/agentes) y
se agrupa por `(org, gap_type, concept)` incrementando `occurrences`.

Los conflictos se registran **SIEMPRE**, incluso si la autoridad los resolvió
(`resolved_by_authority` en `source_conflicts`).

## 2. ContextAdvisor

`GET /api/v1/learning/advisor?question=&concept=` devuelve:

```json
{
  "question": "¿Cuál es el margen bruto?",
  "available": ["erp.SALES.net_revenue", "erp.SALES.refunds_amt"],
  "missing": ["Definición aprobada de margen", "costo de producto / COGS"],
  "recommendation": "Crear y aprobar la métrica en /catalog/metrics.",
  "estimated_impact": {"query_count_30d": 48, "users": 12, "agents": 3}
}
```

Las recomendaciones son templates deterministas sobre datos del catálogo
(tablas/columnas reales, glosario, enums) — no texto generado por LLM.

## 3. Improvement Queue — `improvement_items`

Backlog centralizado: `priority`, `gap_type`, `title`, `evidence`,
`affected_queries/users/agents/sources`, `recommended_action`,
`estimated_impact`, `status` (OPEN / IN_REVIEW / RESOLVED / DISMISSED /
BLOCKED), `owner`. Estados transicionados con auditoría.

**Priorización determinista** (nunca LLM judgment):

```
score = freq*0.30 + users*0.15 + agents*0.20 + criticality*0.15
      + failure_rate*0.10 + authority*0.05 + eval_failures*0.05
```

- score ≥ 0.75 → CRITICAL · ≥ 0.55 → HIGH · ≥ 0.35 → MEDIUM · resto LOW

## 4. Aprendizaje desde preguntas

- **No contestadas**: `UnansweredClusterer` — normalización (sin diacríticos +
  stopwords) + stem-keys de 5 chars (cliente/clientes, rentable/rentabilidad)
  + overlap coefficient. Las 4 frases del ejemplo forman UN cluster. El
  cluster genera un improvement item `IN_REVIEW` con `suggested_concept` —
  NUNCA crea business concepts automáticamente.
- **Exitosas**: `SqlPatternDetector` — `sql_audit_logs` agrupadas por SQL
  normalizado; ≥ `RAG_LEARNING_PATTERN_MIN_QUERIES` (20) → sugerencia
  "crear métrica reusable" (solo sugerencia; el SQL nunca se convierte en
  definición aprobada).

## 5. API

| Método | Path | Permiso |
|---|---|---|
| GET | `/api/v1/learning/gaps` · POST `/{id}/resolve` | catalog:read/write |
| GET | `/api/v1/learning/advisor?question=` | catalog:read |
| GET/POST | `/api/v1/learning/improvements` + `/{id}/status` | catalog:read/write |
| GET | `/api/v1/learning/clusters?days=` · `/patterns?days=` | catalog:read |
| POST | `/api/v1/learning/replay` · GET `/replays` | catalog:read/write |
| GET | `/api/v1/learning/analytics?days=` · `/improvements/summary` | catalog:read |
| GET/POST | `/api/v1/learning/spider/policies` + `/{id}/run` + GET `/runs` | catalog:read/write |

Org-scoped estricto (404 cross-tenant). Auditoría: `gap.resolved`,
`improvement.status_changed`, `learning.replay_started`,
`spider.policy_configured`, `spider.scan_started`.