# Adaptive Long-Context Engine — evidencia completa, no top-k

ZENT deja de tratar el contexto como «los 20 mejores chunks dentro de 32K
fijos» y pasa a perseguir la evidencia: **start small, find exact signals,
expand around evidence, measure coverage, measure information gain, stop when
complete, use long context when necessary**.

## 1. Qué se conserva (nada se reemplaza)

- `HybridRetriever` (vector + léxica + fusión RRF/weighted), reranker,
  threshold, entity pin, parent expansion, `ContextBuilder`, `EvidenceEvaluator`,
  JEV, `select_evidence`, citations, multi-tenant/ACL, agentes, Knowledge V2.
- Con `RAG_LONG_CONTEXT_MODE=off` (default) el sistema se comporta como antes:
  el engine ni se construye.

## 2. Las tres representaciones de la consulta

`src/rag/longcontext/normalize.py` separa lo que antes era una sola
`normalize_query`:

| Pata | Función | Qué conserva |
|---|---|---|
| exacta | `normalize_for_exact_search` | símbolos, máscaras, mayúsculas (`&&&F`) |
| lexical | `normalize_for_lexical_search` | patrones técnicos (`&*%#._-+/=<>@$`) |
| semántica | `normalize_for_semantic_search` | prosa/unicode; el embedding sigue usando el texto original |

`normalize_query` (compat) ahora delega en la lexical: `FCLAS &&&F` queda
`fclas &&&f`, no `fclas f`.

`views.build_query_views` produce los tres canales en paralelo:

```
consulta si FCLAS &&&F acepta QNNF0SME
  semantic      -> "consulta si FCLAS acepta"   (+ semantic_hint del plugin)
  lexical_terms -> FCLAS, QNNF0SME, ...
  exact_terms   -> FCLAS, &&&F, QNNF0SME
```

El embedding técnico usa `semantic`; la pata léxica suma `lexical_terms`; la
pata exacta usa `exact_terms` sin normalizar. Detección genérica: `&&&F`,
`*F*`, `F%`, `Y??`, `AB###`, `ABC-123`, `ABC_123`, `A1672STO0`,
`R007D03E000`, `CAT31`, `Byte105`, rangos `12-16` y `64/67`.

## 2.b Roles de anchor: regla documentada vs valor del usuario

`src/rag/longcontext/roles.py`. El error que corrige: responder «la
documentación no menciona QNNF0SME» cuando la pregunta era si QNNF0SME cumple
la regla `&&&F` del campo `FCLAS`.

| Rol | Significado | ¿Exige match en fuentes? |
|---|---|---|
| `rule_anchor` | máscara/rango/patrón posicional (`&&&F`) | Sí |
| `field_anchor` | campo/sigla (`FCLAS`) | Sí |
| `reference` | identificador citado (`R007D03E000`) | Sí |
| `entity` | entidad contextual (`record 2`, `byte 105`) | Sí |
| `example_value` | valor del usuario (`QNNF0SME`) | **No**: es input para aplicar la regla |

La clasificación es por forma + pistas de pregunta («¿acepta?», «¿cumple?»).
Un provider de dominio puede fijar `Anchor.role` y `Anchor.semantic_hint`
(«fare class positional mask») y manda sobre la heurística del core.

La suficiencia separa `documentable_requested` de `examples`: los valores de
ejemplo viajan a la búsqueda pero nunca bloquean ni dirigen la expansión.
En «Ver flujo» aparecen como `USER EXAMPLE QNNF0SME (no requiere match en
fuentes)` y `RULE EVIDENCE COMPLETE` sólo cuando la regla/campo están probados.

## 3. Pata exacta (tercera pata) y MUST_KEEP

- `exact_tokens.extract_exact_tokens` une anchors del core, comillas, campos
  (`a.b`, `a_b`), hex (`0x1F`), pares nombre+número («record 2», «byte 105») y
  valores (`15%`).
- `ExactRetriever` corre en paralelo al retrieval principal y usa
  `scan_text_literal` (substring crudo, case-insensitive, HTML desescapado) con
  los mismos filtros ACL/tenant, topes de puntos y ms.
- Los aciertos se marcan `must_keep=true` + `exact_needle`/`exact_kind`; entran
  **después del umbral** y el reranker no puede expulsarlos. El `ContextBuilder`
  los prioriza como prioridad 0.
- Solamente se excluyen por duplicado exacto/near-duplicate, permisos (store) o
  irrelevancia estructural: nunca por cosine menor.

## 4. Presupuesto adaptativo por modelo

- `registry.resolve_model_capability`: config (`RAG_MODEL_CONTEXT_WINDOWS`) →
  mapa builtin de familias → default configurado. Nunca asume 32K ni 1M.
- `budget.compute_context_budget`:

```
hard_limit    = min(modelo, tenant, request, costo, settings)
usable        = hard_limit - output - system - conversación - tools - safety
tiers         = escalera configurable (4K…512K) recortada a usable
perfil        = economy | balanced | quality | maximum_quality
```

- `maximum_quality` puede escalar más, pero **sigue cortando cuando la evidencia
  está completa** y siempre deduplica/gana-medida.

## 5. Requirements, coverage e information gain

- `requirements.build_requirements`: anchors, entidades, cláusulas y estructura
  pedida (tabla/nota/fórmula). Estados FOUND / PARTIAL / MISSING / CONFLICTING.
- `coverage`: `anchor_coverage`, `anchor_exact_match`, `requirement_coverage`
  sobre `EvidenceQuality` (campos nuevos, opcionales, UNKNOWN != 0).
- `information.snapshot` + `compute_information_gain`: tokens nuevos, documentos,
  secciones, anchors, requirements, confianza, contradicciones y `per_1k_tokens`.
  Si una expansión sólo repite, se corta.

## 6. Expansión progresiva (cada etapa tiene estrategia)

`src/rag/longcontext/expansion.py`, de lo más preciso a lo más amplio:

1. `parent_sections` — sección padre del hit
2. `section_neighborhood` — hermanos exactos (prev/next), sección, rama
3. `exact_anchors` — otros aciertos literales de los anchors faltantes
4. `table_notes` — referencias «Tabla 9» / «Nota 4» del propio fragmento
5. `same_document` — más contexto del documento que ya acierta
6. `cross_document` — retrieval ampliado con términos de requirements
7. `concepts` — términos de expansión de anchors/entidades
8. `document_level` — chunks de nivel documento (`v2_doc`)

El engine sube un tier por expansión con contenido nuevo, re-empaqueta, mide
coverage + gain y decide: `evidence_complete`, `expansion_redundant`,
`max_expansions`, `max_tier_reached`, `long_context_escalated`.

## 7. ContextPackager

- Prioridades: 0 MUST_KEEP, 1 anchor exacto, 2 evidencia de requirement,
  3 padre/sección, 4 apoyo, 5 background. Dentro de la prioridad manda el score.
- Dedupe exacto (sha1), normalizado y near-duplicate (Jaccard 0.85 por scope).
- Reconstrucción de secciones partidas con merge de overlap y dedupe de líneas:
  si N chunks son la misma sección, entra la sección una vez.
- Cada bloque conserva `document_id`, `source_id`, `filename`, `page`,
  `section_path`, `chunk_id`, `parent_id`, `retrieval`, `rerank_score`,
  `exact_anchor`, `must_keep`.

## 7.b Bucle adaptativo (PLAN → RETRIEVE → INSPECT → EXPAND → REPEAT → GENERATE)

El engine ejecuta:

```
retrieve inicial (tier según complejidad del plan)
while not evidence_complete:
    evaluate_evidence()            # requirements + coverage + confidence
    expansion_plan = siguiente estrategia con estrategia propia
    medir information gain         # determinístico, sin LLM
    parar si: requirements completos, confianza >= umbral,
              racha de gain bajo, no hay más fuentes, costo, hard limit,
              o máximo de iteraciones
```

Stop reasons exactos: `evidence_complete`, `evidence_complete_initial`,
`confidence_threshold`, `redundant_streak`, `expansion_redundant`,
`max_expansions`, `max_tier_reached`, `no_more_sources`, `cost_limit_reached`,
`long_context_escalated`.

La decisión NO mira sólo cosine/reranker: requirements (FOUND/PARTIAL/MISSING/
CONFLICTING), anchor coverage, entity coverage, contradicciones, diversidad de
fuentes y gain.

### Soft limits, no truncation boundaries

Los tiers son SOFT: una unidad semántica (`paragraph`, `table`, `note`,
`section`, `procedure`, `code_block`, `definition`) que no entra en el tier
pero sí en el headroom (siguiente tier o `soft * (1 + unit_headroom_ratio)`)
entra COMPLETA. Hard limits reales: `model_context_limit`, tenant, costo y
ACL. Ejemplo: soft 32K + sección de 11K → 39K coherentes, nunca 32K cortados.

### Contexto dinámico real

El engine reporta los tokens REALES empaquetados (`final_tokens`), no el tier.
Puede cerrar en 17K, 41K, 73K… con headroom explícito
(`usable_context - final_tokens`). El modelo de 1M no se llena por llenar.

### Complejidad inicial (PLAN)

`start_tier_for_complexity` mapea `fast/simple/lookup/technical/reasoning/
multi_document/deep` a un tier INICIAL (4K a 64K+). Es un inicio, no un tope:
el loop puede escalar más si los requirements siguen abiertos.

### Retrieval vs reasoning (modelo)

`adaptive["uncertainty"]` separa los dos problemas. Si falta evidencia
(`retrieval`), el hint de modelo superior NO se aplica: se busca mejor con el
mismo modelo (`fallback: model_escalation_skipped_retrieval_uncertainty`). Si
la evidencia está completa y el razonamiento es complejo, el hint puede
aplicarse.

### Config por tenant

`organization.config_json["adaptive_context"]`:
`enabled`, `quality_profile`, `initial_budget` (`auto`/tokens),
`soft_budget_levels`, `max_context` (`model`/tokens),
`reserve_output_tokens` (`auto`/tokens), `min_information_gain`,
`max_expansion_rounds`, `preserve_semantic_units`, `confidence_min`,
`redundant_streak`.

### Paquete final y «Ver flujo»

Antes de generar: `generation_package` con pregunta, ejemplos del usuario,
anchors exactos, requirements, bloques de contexto, contradicciones,
faltantes, mapa de citas y `ready`/`mode`. En «Ver flujo» el step
`long_context` publica timeline de crecimiento, headroom y stop reason, y el
step `generation_package` publica faltantes y citas:

```
8,240 tokens   initial retrieval
18,901 tokens  expansion exact_anchors
39,442 tokens  expansion parent_sections
61,380 tokens  stop: evidence_complete
MODEL CAPACITY 1,000,000 · USED 61,380 · HEADROOM 938,620
```

### Caché y performance

`ExpansionCache` por run reutiliza needles ya barridos, fetches de sección y
retrieves idénticos; las patas independientes (vector/léxica/exact) siguen en
paralelo y las expansiones son secuenciales (primero se analiza, después se
decide la siguiente).

## 7.c Source routing, per-anchor y estado único (regresión 2026-09)

Correcciones al pipeline técnico detectadas con la pregunta de regresión
«record 2 / FCLAS &&&F / QNNF0SME»:

1. **Aliases estructurales** (`src/intelligence/response/references.py`):
   `record 2` produce `record2`, `rec2`, `record_2`, `rec-2`, `registro 2`… y
   matchea `Rec2_Rules` sin hardcodear nada. Cubre byte/tabla/categoría/
   sección/capítulo/parte/apéndice/campo/figura/ítem.
2. **SourceRouter** (`src/rag/longcontext/source_router.py`): puntúa fuentes
   ANTES del chunk ranking (match de referencia +3, documento de reglas +1.2,
   ejemplos no pedidos -0.8, qualifier extra -1, mismo tipo otro valor -2,
   overlap de términos). `preferred_sources` primero; global sólo si la
   evidencia de regla/campo no aparece.
3. **Exact per-anchor** (`exact_search.py`): cada anchor documentable tiene su
   propio barrido y cupo; preferred por fuente en orden de score; un solo OR
   global ya no puede tapar `&&&F` con 20 hits de `FCLAS`. El valor de ejemplo
   no se barre cuando hay regla/campo.
4. **Niveles MUST_KEEP**: rule en prioridad 0, requirement 1, field 2,
   supporting exact 4. Un hit de FCLAS ya no pesa como uno de &&&F.
5. **Estado único de evidencia** (`coverage.build_evidence_state`):
   `coverage_note` y el agent runtime consumen roles; `QNNF0SME` (EXAMPLE_VALUE)
   jamás aparece como evidencia faltante.
6. **Fuentes finales**: `_build_flow` usa la selección de evidencia; el agent
   flow descarta `status=CANDIDATE`. Un candidato que no resolvió nada no se
   cita.

Tests: `tests/test_source_routing_regression.py` (aliases, router, starvation
con semántica real del store, example value, PASS A con comportamiento, fuentes
finales).

## 8. Ingestión: vecindad estructural

El chunker V2 (`src/knowledge/structure/chunker.py`) guarda por hermano
`chunk_index`, `prev_chunk_id` y `next_chunk_id`; el payload V2 los persiste.
Los documentos indexados antes se reprocesan con:

```
python -m src.scripts.backfill_chunk_neighbors --org <uuid> --dry-run
python -m src.scripts.backfill_chunk_neighbors --org <uuid>
```

## 9. Observabilidad («Ver flujo»)

El step `long_context` publica en la fase de evidencia:

- modelo y `model_context_limit` (con `source` del registry)
- `initial_tokens` / `final_tokens` / `usable_context`
- anchors encontrados/faltantes y coverage de requirements
- una fila por expansión: estrategia, motivo, tokens agregados, information gain
- `stop_reason` y `mode` (`shadow` no altera la respuesta)

Métricas Prometheus: `zent_long_context_total`, `zent_long_context_tokens`,
`zent_long_context_expansions`.

## 10. Configuración

`.env.example` documenta todas las claves `RAG_RAG_EXACT_SEARCH*`,
`RAG_RAG_LONG_CONTEXT_*`, `RAG_RAG_CONTEXT_*` y `RAG_RAG_MODEL_CONTEXT_WINDOWS`.
Rollout sugerido: `off` → `shadow` (mide) → `canary` → `active`, con
`economy/balanced` primero y `quality/maximum_quality` cuando el costo esté
medido.

## 11. Tests

- `tests/test_longcontext_exact.py` — TEST 1-3: `&&&F` intacto, normalize,
  must_keep sobre umbral/rerank/presupuesto.
- `tests/test_longcontext_budget.py` — TEST 4/8/10: tiers chicos, 500K no se
  usan, techo 128K, registry y perfiles.
- `tests/test_longcontext_engine.py` — TEST 5-9: chunk siguiente, tabla+nota,
  multi-documento, escalado 32K→64K, anchor solo no alcanza.
- `tests/test_longcontext_structural.py` — padre, vecindad prev/next, tabla/nota,
  must_keep.
- `tests/test_longcontext_orchestrator.py` — active aplica, shadow no altera,
  y `anchor_roles` en el flow con USER EXAMPLE separado.
- `tests/test_longcontext_benchmark.py` — métricas antes/después offline.
- `tests/test_longcontext_roles.py` — detección técnica genérica, roles,
  tres canales, coverage role-aware, summary del flow.
- `tests/test_longcontext_critical_question.py` — regresión de la pregunta
  «record 2 / FCLAS &&&F / QNNF0SME»: el pipeline completa la evidencia sin que
  QNNF0SME exista en las fuentes, y NO completa si falta el campo.
- `tests/test_longcontext_adaptive_loop.py` — soft limits con headroom,
  integridad de unidades, stop conditions (confidence, racha, costo),
  complejidad inicial, tenant overrides, timeline/headroom, caché de run y
  paquete final de generación.

### Cobertura de regresión del caso crítico

```
consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir que el
farebasis debe ser de ese tamaño? en el boleto viene asi QNNF0SME cumplira?
```

| Token | Rol | Exigido en fuentes |
|---|---|---|
| Record 2 | entity | sí |
| FCLAS | field_anchor | sí |
| &&&F | rule_anchor | sí |
| QNNF0SME | example_value | no (input a evaluar) |
