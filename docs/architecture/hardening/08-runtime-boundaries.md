# F8 — Fronteras del AgentRuntime (auditoría, sin rewrite)

Estado: **auditoría medida (F8)**. Este documento clasifica los bloques
restantes del runtime por frontera y LOC para decidir extracciones; NO se
reescribe el ReAct. La regla del programa: dividir solo cuando
`responsabilidad A != responsabilidad B`, no por tamaño.

Medición: `agent_runtime.py` 5.841 líneas; `orchestrator.py` 7.131;
`narrative_fast_path.py` 1.343; `finalizer.py` 448; `enforcement.py` 126;
`prompt_assembly.py` 335; `run_metrics.py` 116; `failure_taxonomy.py` 406.

---

## 1. Clasificación de funciones

| Clase | Dónde vive hoy | Ejemplos (LOC medidos) | Estado |
|---|---|---|---|
| CORE LOOP | `agent_runtime` | `run` (547), `_run_loop` (166 + closures), `_skip` (closure narrativa) | **no extraer**: orquesta el ciclo; se busca legibilidad, no tamaño |
| POLICY | `src/runtime` | `finalization_policy`, `enforcement`, `run_guards`, `run_state` | extraído (F0–F3) |
| RETRIEVAL | `agent_runtime` + `narrative_fast_path` | `_execute_jev_retrieval` (154), `_resolve_narrative_search_plan` (84), `narrative_fast_path` (9 pasos) | extraído en su mayoría (V2 + F4) |
| TOOLS | `agent_runtime` | `_effective_tools`, `_filter_tools_by_sources`, `_classify_tool_failure` | se queda: es política de agente (config), no un motor propio |
| PROVIDER | `agent_runtime` | `_circuit_check`, `_stream_response`, `_generate` (87) | se queda: el router/proveedor vive en `infrastructure/llm` |
| PROMPT | `src/runtime` | `prompt_assembly` (F4), `compose_agent_instructions`, `_render_context_block` (delegado) | extraído (F4) |
| FINALIZATION | `agent_runtime` + `finalizer` | `_gate_draft` (295), `_finalize_with_authority`, `_apply_derived_guard` (128), `_try_finalize_answer` (≈160 con closures) | **primitivas extraídas** (V2); la orquestación del cierre sigue en el runtime |
| OBSERVABILITY | `src/runtime` + `agent_runtime` | `run_metrics` (F7), `story_view`, `_record_fast_path_metric`, publicadores de steps | extraído (F7) |
| COMPATIBILITY | `src/runtime` + `orchestrator` | `_adaptive_write/_publish` (proyección), `_early_run_state`, fallbacks de estado | proyección única documentada; sin writers directos |

## 2. Extracciones hechas por el programa

1. Narrative fast path: 9 pasos → `src/runtime/narrative_fast_path.py`.
2. Finalizer: presupuesto, prompt, citas, generación, cierre determinista →
   `src/runtime/finalizer.py`.
3. Enforcement del cierre y scopes → `src/runtime/enforcement.py` (F2).
4. Guards consultables y shadow → `agent_runtime` (helpers de módulo) +
   `src/runtime/run_guards.py` (F3).
5. Prompt assembly → `src/runtime/prompt_assembly.py` (F4).
6. Métricas run-level → `src/runtime/run_metrics.py` (F7).

## 3. Candidato restante (con criterio)

`_try_finalize_answer` (≈160 líneas de orquestación: presupuesto del cierre,
streaming vs generate, polish, fact-retry, gate final, entrega). Su extracción
a `finalizer.py` exige pasar 12+ dependencias del runtime (scratch, polish,
draft_gate, helpers de figuras, settings, streaming).

Recomendación: **no extraer con parámetros posicionales**. Si se hace, hacerlo
con un objeto explícito de dependencias (`FinalizeContext` con campos
nombrados) y con la suite completa como red. Beneficio: legibilidad del método;
riesgo: medio; valor operacional: bajo frente a F9–F13 (perf/CI/alertas).

`run` (547) y `_gate_draft` (295) quedan igual por la misma razón: son
orquestación con dependencias amplias; dividirlos hoy agregaría un objeto de
contexto sin reducir el número de caminos.

## 4. Criterio de cierre de F8

- Cada módulo extraído se describe en una frase (ver tablas de
  `prompt-assembly.md`, `failure-taxonomy.md`, `finalization-policy.md`).
- `adaptive`: writers directos = 0 fuera de la proyección (test de writers).
- El método principal se lee por etapas nombradas (lifecycle documentado en
  `_run_loop`).
- Deuda declarada: la orquestación del cierre permanece en el runtime hasta que
  exista una razón de negocio para el objeto de contexto.
