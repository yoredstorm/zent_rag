# Traceability Schema v2 — una sola verdad canónica

Fase 8. La traza deja de ser la suma de proyecciones independientes (events,
steps, sources, citationes, traceability v1, execution_narrative) y pasa a ser
**una estructura canónica** de la que todo lo demás deriva.

## Principio

`rag_flows.flow` / `agent_runs.flow` sigue siendo la fuente bruta. Sobre ella:

```
flow bruto (steps, events, evidence, citations, timings, jev_preflight, …)
        │
        ▼
Traceability Schema v2   ← ÚNICA interpretación canónica
        ├── execution narrative (compat, derivada)
        ├── vista humana (portal)
        ├── vista técnica (portal)
        └── raw (flow bruto, sin reinterpretar)
```

`build_traceability()` es el único lugar donde se normaliza, deduplica,
interpreta y diagnostica. `build_execution_narrative()` (contrato v1 del
portal) pasa a recibir el trace v2 y proyectarlo, en vez de recalcular.

## Contrato v2 (schema_version = 2)

Entidades separadas, cada una con una definición única:

| Entidad | Qué contiene |
| --- | --- |
| `execution` | kind, id, pregunta, estado, entregada |
| `routing` | ruta elegida, decisor, intención |
| `knowledge` | representación usada, estrategia, rondas |
| `retrieval` | rondas, expansión, skip, motivos |
| `evidence` | `counts` v2, `raw_hits`, `canonical_evidence`, `sources`, `dedup`, `citations` |
| `jev` | `executed`, `checks`, `judgments`, `decisions`, intervención material |
| `generation` | llamadas con `purpose`, tokens, warnings, costo |
| `controls` | eventos de control explicables (guardrails, correcciones, fallbacks) |
| `verification` | estado, checks, impacto de límites de generación |
| `memory` | observada / usada / no disponible (sin ceros inventados) |
| `timing` | `wall_clock_ms` vs `accumulated_ms`, breakdown, paralelismo |
| `cost` | total y desglose medido |
| `fallbacks` | taxonomía, eventos, `material` |
| `diagnostics` | items con severidad, dimensiones, consistencia, invariantes |
| `presentation` | headline, journey, refs de métricas/glosario, explicaciones |

### Contadores (definiciones programáticas)

| Campo | Definición |
| --- | --- |
| `documents_retrieved` | fuentes canónicas distintas tocadas por hits crudos |
| `documents_used` | fuentes canónicas distintas con ≥1 evidencia usada |
| `evidence_retrieved` | hits crudos (antes de deduplicar) |
| `evidence_deduplicated` | hits fusionados por dedup (exacto/solape/semántico) |
| `evidence_unique` | evidencias canónicas (post-dedup) |
| `evidence_selected` | únicas que pasaron selección/reranking |
| `evidence_used` | únicas incluidas materialmente en la construcción |
| `evidence_cited` | únicas con `cited = true` |

`retrieved ≥ unique ≥ used ≥ cited` y `used ≤ selected` no se asumen: se
**verifican** (Invariant Engine). Si el detalle recuperado viene truncado
(`items_detail` limitado), `evidence_unique` queda `null` y se declara
`evidence.collection: "partial"` en vez de inventar.

### Identidad canónica

- `canonical_source_id`: hash estable de la identidad física. Orden:
  tenant + knowledge base + (`original_file_id` → `source_uri`/storage object →
  filename normalizado → content hash → `document_id` → `source_id`).
  `identity_basis` y `weak` declaran de dónde salió.
- `evidence_id`: determinístico:
  `ev_<sha256(canonical_source_id|page|section|text_hash)[:16]>`.
  Fallbacks en orden: chunk_id canónico → evidence_id original. Si no hay
  material: `null` + diagnóstico `EVIDENCE_ID_MISSING`.
- Dedup en 3 capas sobre los hits:
  1. exacta: misma fuente + página + `text_hash`.
  2. solape: misma fuente y página (±1) con containment ≥ 0.8 / Jaccard ≥ 0.7 /
     ratio ≥ 0.85 (difflib).
  3. semántica: misma fuente y sección/ventana con ratio ≥ 0.92 o Jaccard ≥ 0.85.
  Nunca cruza `canonical_source_id`. Cada canónica guarda sus `raw_hits`.

### JEV (semántica, no "intervención" genérica)

```
jev.executed            = hay packs/juicios/decisiones
jev.checks              = nº de juicios observados
jev.material_intervention = alguna decisión aplicada cambió/bloqueó el camino
jev.changed_route       = acción aplicada ∈ {retrieve_more, reconstruct_more,
                          deterministic_answer, ask_user, abstain} o
                          allow_generation=false o revise aplicado
jev.requested_more_evidence = acciones aplicadas de búsqueda/reconstrucción
```

`decision(action=generate, reason=default)` aplicada NO es intervención
material. Cada decisión lleva `material`, `is_default` y `classification`.

### Probabilidad (fin del PROBABILITY_MISMATCH opaco)

Cada juicio `choice` expone:

```
selected                  = decisión
selected_probability      = P(selected) de la propia distribución
runner_up / runner_up_probability
margin                    = selected_probability − runner_up_probability
entropy                   = normalizada 0..1 (si viene medida)
confidence                = magnitud derivada reportada por JEV
certainty                 = magnitud separada (noul)
band                      = high|medium|low
```

La UI muestra `selected_probability` como probabilidad y `confidence` como
confianza derivada, cada una etiquetada. `PROBABILITY_MISMATCH` sólo se emite
cuando dos magnitudes homónimas se contradicen (`question.confidence` vs
`distribution.confidence/P(selected)`) y explica cuál es cuál.

### Límites y controles

Taxonomía de fallback: `warning`, `recoverable_event`, `retry`, `continuation`,
`provider_fallback`, `model_fallback`, `retrieval_fallback`, `material_fallback`,
`fatal_error`. Cada control:

```
control_code, severity (INFO|NOTICE|WARNING|ERROR|CRITICAL), trigger,
action_taken, recovered, material_effect, source_event_ids
```

`MAX_TOKENS_REACHED` se evalúa antes de aceptar el `VERIFIED` declarado:
`RECOVERED_NO_IMPACT` | `MINOR_DEGRADATION` | `POSSIBLY_INCOMPLETE` |
`MATERIAL_ERROR`. Sólo los dos últimos tienen `material_effect = true` y
degradan la verificación (PARTIALLY_VERIFIED / UNVERIFIED) con explicación.

### Tiempo

`wall_clock_ms` (percibido) nunca se mezcla con `accumulated_ms` (trabajo
medido). Si `accumulated > wall_clock`, es información (`parallel: true`), no
error.

### Diagnóstico

Cada item responde 3 preguntas vía códigos + params:
`meaning_code` (qué significa), `impact_code` (afectó la respuesta),
`fix_code` (qué corregir). El código técnico es secundario en la UI.

Dimensiones: `execution`, `evidence`, `jev`, `generation`, `verification`,
`metadata`, `consistency` con estado `ok|notice|warning|error|unknown`.
`consistency` separa higiene de telemetría de calidad de respuesta.

Invariantes verificados (violación → diagnóstico, nunca sólo JSON):

1. `evidence_used ≤ evidence_unique`
2. `evidence_cited ≤ evidence_used`
3. `evidence_selected ≤ evidence_unique`
4. `documents_used ≤ documents_retrieved`
5. `retrieved == unique + deduplicated` (cuando la colección es completa)
6. `answer_calls ≤ model_calls`
7. `material_fallback = true` ⇒ evento material de recuperación
8. `VERIFIED` no convive con degradación material sin resolver
9. toda cita apunta a un `evidence_id` canónico
10. toda evidencia tiene `canonical_source_id`
11. probabilidades en rango y coherentes con su distribución
12. el journey no duplica el mismo propósito visible (model call ≠ generación)

### Compatibilidad

- v2 conserva las llaves v1 (`counts`, `evidence.documents/items`,
  `decisions`, `judgments`, `timeline`, `verification`, `retrieval`,
  `diagnostics.invariants/gaps/sources`) derivadas de la misma estructura.
- `upgrade_traceability_v1()` adapta traces históricos en lectura
  (`GET /executions/{kind}/{id}/flow`); marca `upgraded_from_schema: 1` y
  declara fidelidad parcial en diagnóstico.

## Presentación

Tres vistas, un dato (§29):

| Vista | Consume | Para |
| --- | --- | --- |
| Normal | hero + journey + evidencia + JEV + diagnóstico | negocio |
| Técnica | tarjetas semánticas + "¿Qué significa?" + raw JEV | ingeniería |
| Raw | `flow` bruto (`TechnicalValueTree`) | debug |

Textos centralizados en `portal/src/pages/chat/traceabilityCatalog.ts`
(métricas, glosario, explicaciones por código). Los componentes no hardcodean
frases de diagnóstico ni significados de métricas.

## Archivos

Backend:

- `src/rag/trace_identity.py` — identidad y nombres.
- `src/rag/trace_evidence.py` — hits, dedup, documentos, citas.
- `src/rag/trace_jev.py` — juicios interpretados + decisiones + semántica.
- `src/rag/trace_controls.py` — taxonomía, controles, evaluación max_tokens.
- `src/rag/trace_diagnostics.py` — severidades, invariantes, dimensiones.
- `src/rag/trace_metrics.py` — definiciones de métricas (códigos).
- `src/rag/traceability.py` — orquestador v2 + adapter v1.
- `src/rag/execution_narrative.py` — proyección desde v2.
- `src/api/routes/executions.py` — upgrade en lectura.

Portal:

- `portal/src/pages/chat/traceabilityV2.ts` — tipos/parser/derivaciones.
- `portal/src/pages/chat/traceabilityCatalog.ts` — textos centrales.
- `portal/src/pages/chat/story/TraceV2Story.tsx` — vista normal.
- `portal/src/pages/chat/story/TraceV2Technical.tsx` — vista técnica.
- `portal/src/pages/chat/story/ExecutionStoryView.tsx` — conmutador.
