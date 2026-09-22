# Zent Learning Engine

Estado: **recomendación gobernada**. No hay mutación autónoma de producción.

```
NO AUTONOMOUS PRODUCTION MUTATION
```

La Fase 4A ([zent-memory.md](zent-memory.md)) observa. Este ciclo convierte
esa telemetría en una decisión humana.

```
RUNTIME
        ↓
Memory Events
        ↓
Learning Engine
        ↓
Finding
        ↓
Hypothesis
        ↓
Experiment Lab
        ↓
Evaluation
        ↓
Recommendation
        ↓
Human Approval
        ↓
Promotion
```

Principio:

```
OBSERVE AUTOMATICALLY
LEARN AUTOMATICALLY
TEST AUTOMATICALLY WHEN SAFE
RECOMMEND AUTOMATICALLY
PROMOTE MANUALLY
```

## Qué se reutiliza

| Pieza existente | Papel |
| --- | --- |
| `MemoryRecord` | Failure memory y success memory. Una firma, un registro |
| `src/runtime/experiments.py` | Experiment Lab de proveedores. `summarize()` sigue siendo la comparación |
| `src/learning` | Cola de gaps, improvements y approvals de contexto. No se reemplaza |
| `KnowledgeLearningEngine` | Pipeline de catálogo. No se reemplaza |
| `src/decision/learning.py` | Reportes de sólo lectura del Judgment Fabric |
| Evidence / Claim Ledger | Conflictos. El documento más nuevo no gana solo |
| Cognitive OS | Especialistas de ejecución. Los analistas de aprendizaje no entran al grafo |

`LearningEngine` coordina. No es un segundo motor de experimentos ni un segundo pipeline de catálogo.

## Qué no hace

No cambia prompts, thresholds, modelos, chunking, retrieval policies, agentes, workflows ni configuración de tenant por su cuenta.

Un experimento automático sólo corre como `golden_set`, `shadow` o `replay`.
`send_email`, pagos, mutaciones de base y acciones destructivas de workflow exigen `mock`, `dry_run` o `simulation`.

`VALIDATED` puede aparecer como señal. El recall del Judgment Fabric sigue exigiendo `ACTIVE`, y las políticas productivas siguen decidiendo la ejecución.

## Ciclo

1. `RunSignal` entra por lote o, si `LEARNING_CYCLE_ENABLED`, desde un decision trace.
2. El análisis corre cada `LEARNING_CYCLE_EVERY_N` eventos o en el job periódico (mínimo 5 minutos). No corre en cada mensaje.
3. Fallos y aciertos con la misma firma actualizan un `MemoryRecord`.
4. El detector usa tasas, umbrales y ventana (`last_hour`, `24h`, `7d`, `30d`, `all_time`). Publica `sample_size`, `window` y `confidence`. Por debajo de `LEARNING_CYCLE_MIN_SAMPLE` no hay finding.
5. Una hipótesis nombra baseline, candidato, métrica, mejora mínima, alcance y guardrails.
6. El candidato se pide al Experiment Lab o a filas golden/shadow/replay. No toca producción.
7. La evaluación guarda medias, tamaño de muestra y el cambio firmado. El éxito es un vector: `quality`, `grounding`, `task_success`, `cost`, `latency`. HTTP 200 no es éxito.
8. Si el candidato es claramente mejor sin bajar grounding ni calidad, la recomendación queda `pending` con acción sugerida `promote`.
9. `promote` exige un actor admin. Queda auditoría: quién, cuándo, experimento, baseline, candidato, métricas. Sin un `ConfigPort` explícito no hay cambio de configuración. Con port, el snapshot permite rollback.
10. Un experimento que falla puede pasar la memoria a `REJECTED`. El ledger no se borra.
11. Una memoria `ACTIVE` que empeora en la ventana reciente pasa a `CONTRADICTED`. Si envejece sin soporte, pasa a `STALE`.

## Knowledge Health

Los componentes llegan medidos: retrievability, freshness, conflict_rate, grounding_success, failed_query_rate, source_coverage, parse_health, structured_parse_health, duplication. El agregado es la media sólo cuando hay al menos dos. Un puntaje bajo muestra el warning que vino con la medición.

## Especialistas

`retrieval_analyst`, `knowledge_analyst`, `decision_analyst`, `agent_analyst` y `finops_analyst` redactan el finding o la recomendación que el código ya calculó. No inventan métricas y no ejecutan tools.
