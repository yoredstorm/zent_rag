# P15 — Evidencia

Fecha: `2026-10-26`.

## 1. Pruebas deterministas

```powershell
uv run --frozen --no-sync pytest tests/test_p15_intent_identity.py -q
```

Resultado: **12 passed**.

```powershell
uv run --frozen --no-sync pytest tests/test_p15_intent_identity.py \
  tests/test_response_profiles_v2.py tests/test_turn_intent.py \
  tests/test_response_intelligence.py tests/test_response_presentation.py \
  tests/test_response_composer.py -q
```

Resultado: **170 passed** en la matriz amplia; el archivo P15 aislado suma
**12 passed** con el test de flujo y gate.

Cobertura P15:

- intención genérica: valoración, interpretación, recomendación, comparación,
  creación, enseñanza;
- `rules_turn_intent` marca la valoración como evaluativa con evidencia;
- blueprint `interpretive_valuation`, nunca `technical_explanation` por defecto;
- identidad extraída de lenguaje natural;
- los ocho perfiles conservan identidad y valoración;
- conflicto de ejemplos declarado y resuelto sin borrar la voz;
- claims interpretativos separados de hechos no respaldados;
- `keep_evaluative_answer` evita la negativa mecánica con evidencia;
- preview y comparador publican identidad, intención y calidad;
- el flujo publica `response_quality` sin fingir validación semántica.

Portal:

```powershell
cd portal
npm run typecheck
npx vitest run src/pages/AgentStudio.test.tsx \
  src/components/agentStudio/AgentTestChat.test.tsx \
  src/components/agentStudio/agentModes.test.ts \
  src/components/agentStudio/types.test.ts
```

Resultado: **76 passed**; typecheck OK; lint 0 errores (1 warning preexistente
de `AgentSourcePicker.tsx`).

## 2. Matriz real de LLM

Script: `scripts/p15_real_llm_matrix.py`.
Artefacto: `artifacts/certification/p15/real-matrix.json`.

- 6 dominios: literatura, educación, comercial, auditoría, soporte y técnico.
- 8 perfiles: balanced, precise, clear_didactic, technical_detailed, executive,
  concise, analytical, evidence_first.
- Total: **48 llamadas reales**, **0 errores**, temperatura 0.
- Evidencia congelada por dominio; sin retrieval ni herramientas.
- Resultado determinista global: 48/48 `intent_fulfilled`, 48/48
  `persona_preserved`, 0 rechazos, 0 metadatos internos.

El proveedor primario devolvió `403 NOT_ENOUGH_BALANCE`; todas las llamadas
completaron por el fallback configurado. La evidencia corresponde al modelo de
fallback, no al primario.

## 3. Juez semántico real: El principito

Script: `scripts/p15_judge_existing.py --domain literature`.
Artefacto: `artifacts/certification/p15/real-matrix-judged.json`.

- 8/8 respuestas evaluadas semánticamente por LLM real.
- `intent_fulfilled`: 8/8.
- `persona_preserved`: 8/8.
- `style_applied`: 8/8.
- `evidence_integrity`: 8/8.
- `direct_answer_present`: 8/8.
- `unnecessary_refusal`: 8/8 en false.
- `irrelevant_internal_metadata`: 8/8 en false.
- `verbosity_appropriate`: 8/8.

Conclusión del caso: los ocho perfiles responden qué les parece la obra,
conservan la voz de narrador infantil dentro de su longitud/estructura, no
rechazan la valoración por falta de experiencia personal y no inventan citas.

## 4. Límites de la evidencia

- El juez es un LLM, no revisión humana con ≥5 personas.
- Los otros 40 resultados (5 dominios × 8 perfiles) tienen chequeos
  deterministas, no evaluación semántica con juez.
- La matriz usó evidencia congelada; no ejecutó retrieval real sobre el PDF
  cargado ni herramientas del agente.
- No se certifica el proveedor primario (403 por saldo); se usó el fallback.
- No se declara `PROVIDER_VERIFIED` ni se toca `ZENT_GOLD_RELEASE_ENABLED`.
- Las pruebas mock sólo cubren contratos, wiring y gate; no sustituyen la
  matriz real.
