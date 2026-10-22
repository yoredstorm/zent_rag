# Universal Studio — Remediación del planner real y certificación funcional

> **Fecha:** 2026-10-21.
> **HEAD de partida:** `c65dbdf729327eaf54fd74a9326cf5ae328dc0be`.
> **Alcance:** corregir la generación real con LLM, el descubrimiento de
> capacidades, el contrato del plan, el compile/validate y la evidencia.
> **Regla:** un test con provider fake no cuenta como calidad de modelo real.
> Un skip o un fallo de balance del proveedor no cuenta como PASS.

## 1. Resultado ejecutivo

El fallo `planner.invalid_llm_output` del informe anterior tenía dos causas
principales, no una:

1. **Thinking no se apagaba realmente.** `LLM_DISABLE_THINKING` enviaba
   `chat_template_kwargs.thinking=false`, que el gateway de certificación
   ignoraba. El modelo consumía `max_tokens` en `reasoning_content` y devolvía
   `content=""`. Se cambió a `thinking: {"type": "disabled"}`, verificado con
   una llamada real (`reasoning_tokens=0`).
2. **El contrato de salida era demasiado frágil.** El planner no toleraba
   alias, JSON envuelto en texto/DSML, tool calls nativos, `timeout_seconds`
   fuera de rango, `assumptions.impact=medium`, `bindings={}` ni
   `StopParams.status` inválido. Ahora normaliza explícitamente y repara con
   errores concretos.

Con el modelo **DeepSeek-V4.1-Pro** (Novita) el Gold real pasó:
`DRAFT_READY`, grafo válido, 4 llamadas LLM, 1 tool call, 1 reparación,
41 790 tokens, 88 s. Con el fallback **DeepSeek-V4.1-Flash** (DeepInfra), el
Gold de venta pasó con 4 llamadas, 1 tool, 1 reparación, 35 258 tokens.

**No se declara GO global.** El proveedor Novita agotó balance durante la
certificación (`NOT_ENOUGH_BALANCE`), por lo que no se completó la matriz de
100 casos ni las 5 experiencias Gold completas. Se documenta lo observado.

## 2. Causa raíz comprobada

### 2.1 Thinking oculto consumía la salida

Evidencia antes del cambio:

```text
finish_reason=length
content_chars=0
reasoning_chars>0
planner action output invalid
```

Prueba aislada con el gateway:

| Configuración | `reasoning_chars` | `reasoning_tokens` | `content` |
|---|---:|---:|---|
| `chat_template_kwargs.thinking=false` | 295 | 74 | `{"ok":true}` |
| `thinking: {"type": "disabled"}` | 0 | 0 | `{"ok":true}` |
| `reasoning_effort=low` | 335 | 84 | `{"ok":true}` |

El único parámetro que apagó el razonamiento en este gateway fue
`thinking: {"type": "disabled"}`.

**Archivo:** `src/infrastructure/llm/provider.py` (`_thinking_kwargs`).

### 2.2 Parser y contrato

Evidencia de los runs reales:

- `planner.invalid_llm_output` por `content=""`.
- `planner.invalid_plan_payload` por `timeout_seconds=86400` (máximo 3600).
- `planner.invalid_plan_payload` por `assumptions[].impact="medium"`.
- `planner.invalid_plan_payload` por `CapabilityMatch.bindings={}`.
- `contract.params_invalid` por `StopParams.status` distinto de
  `success|failed`.
- `plan.missing_match` por no incluir una fila por capacidad.
- `contract.output_unknown` por usar `order_id`/`status`/`port` sin contrato.

## 3. Cambios implementados

### 3.1 Provider y observabilidad

- `LLMResponse` ahora expone `reasoning_content` y `tool_calls`.
- `LiteLLMProvider` los rellena desde la respuesta del gateway.
- El planner registra por llamada: modelo, `finish_reason`, tokens,
  longitudes de content/reasoning, tool calls, latencia y propósito. No guarda
  prompts ni secretos.
- `PlannerUsage` y `trace.llm_responses` quedan en el resultado.

**Archivos:** `src/core/domain/entities.py`,
`src/infrastructure/llm/provider.py`,
`src/platform/workflows/planner_session.py`.

### 3.2 Extracción robusta de JSON

Nuevo `src/platform/workflows/json_output.py`:

- `iter_json_objects()` recorre objetos completos con `raw_decode`;
- `parse_json_object()` devuelve el primero;
- `parse_json_object_with_key()` busca una clave concreta.

Se usa en `architect.py`, `copilot_v2.py`, `architect_patch.py` y `patches.py`
para no romper una acción válida seguida de DSML, markdown o texto.

### 3.3 Acciones del planner

`_parse_action_text()` y `_action_from_response()` aceptan:

- JSON plano;
- JSON envuelto en markdown/texto;
- DSML (`<|DSML| invoke ...>`);
- tool calls nativos OpenAI;
- razonamiento con una acción JSON completa cuando `content` vino vacío.

`_normalize_action_mapping()` acepta alias (`final` → `plan`, `call_tool` →
`tool`, `name`/`args` → `tool`/`arguments`).

Si no hay acción, se hace **un reintento acotado** con un prompt mínimo y se
registra `planner.invalid_llm_output` con `finish_reason`, longitudes y tool
calls. No se inventa un plan.

### 3.4 Normalización de especificación y plan

- Alias de especificación: `trigger`, `actions`, `state`, `missing`,
  `confidence_score`, etc.
- Alias de pasos: `agent` → `agent_analysis`, `condition` → `decision`,
  `action` → `capability_call`, etc.
- Recorte de `goal` (600), `step.goal` (400), ids (80), listas.
- `timeout_seconds` acotado a 1..3600; `retries` a 0..5; `on_error` e
  `idempotency` válidos.
- `assumptions[].impact` normalizado a `low|high`.
- `CapabilityMatch.bindings/unresolved/alternatives` normalizados a listas.
- `StopParams.status` mapeado (`ok/done/completed` → `success`,
  `cancelled/error` → `failed`).
- `params.capability_ref`/`capability_id`/`tool` → `params.capability`.

### 3.5 Descubrimiento real y contratos

- Nuevo tool `capability.inspect_many` (hasta 12 contratos en una llamada).
- El planner recibe una digest de capacidades con contratos, estado,
  credenciales/permisos y eventos prioritarios (`payment.succeeded`,
  `conversation.message`, `document.uploaded`).
- `_descriptor_models` se incluye en la proyección del planner; antes faltaba y
  la digest decía “no hay contratos”.
- `capability.search` y `inspect` actualizan `_inspected_refs`; si el planner
  inspeccionó al menos una ref, el backend completa la inspección read-only de
  las demás refs usadas. Sin ninguna inspección, el plan se rechaza.
- Se añadieron contratos de salida reales para `sales.order.*`,
  `inventory.*`, `payments.checkout.create` y campos requeridos
  (`items`, `order_id`).
- Se añadieron `status`, `port`, `payment_reference` a las salidas de `wait`
  y `message/conversation_id` a `trigger_conversation`.

### 3.6 Seguridad determinística del plan

`_normalize_plan_semantics()`:

- inserta `human_approval` antes de una capacidad financiera/crítica sin
  aprobación ancestro;
- cierra `wait.on_timeout=branch` sin rama como `expire`;
- registra la normalización en `notes`.

No crea un motor ni ejecuta efectos. Es una proyección de seguridad antes de
validar/compilar.

### 3.7 Estado del draft y clarificaciones

- Un plan que compila ya no se bloquea por `spec.missing_information` o
  `planner.clarifications`; esas dudas quedan en la especificación y en
  `requirements`.
- Si no hay grafo, las clarificaciones siguen bloqueando.
- El endpoint de mensajes re-planifica cuando no hay grafo; solo aplica patch
  sobre un diseño compilado. Antes intentaba patch sobre un plan bloqueado y
  devolvía 422.

### 3.8 Fallback

- `fallback_payload` conserva la petición original hasta 4000 caracteres y su
  longitud (`preserved_chars`), no 600.
- `heuristic_semantic_plan` conserva las incertidumbres (`uncertainties`) del
  draft heurístico.
- El fallback sigue marcado `requires_review=true`, `publishable=false`.

### 3.9 Modelo del planner

Nuevo setting `WORKFLOW_PLANNER_MODEL` (vacío = modelo por defecto). Permite
usar un modelo más fuerte solo para el planner sin cambiar el modelo de los
agentes. Ejemplo de certificación:

```powershell
$env:RAG_WORKFLOW_PLANNER_MODEL="openai/deepseek/deepseek-v4-pro"
```

## 4. Evidencia real

### 4.1 Gold de venta con planner Pro (Novita)

```powershell
$env:RAG_CERT_REAL_LLM="1"
$env:RAG_WORKFLOW_PLANNER_MODEL="openai/deepseek/deepseek-v4-pro"
pytest tests/certification/ai/test_real_llm_gold.py
```

Resultado: **1 passed** en 88.32 s.

| Dato | Valor |
|---|---|
| Estado | `DRAFT_READY` |
| LLM calls | 4 |
| Tool calls | 1 (`capability.inspect_many`) |
| Reparaciones | 1 |
| Tokens | 41 790 |
| Grafo | válido |
| `issue_codes` | `cost.many_agents`, `runtime.requires_instance`, `compile.implicit_then` |

Artefacto del run: `artifacts/certification/ai/gold-real-llm.pro-pass.json`.
El artefacto histórico `gold-real-llm.json` no se sobrescribió.

### 4.2 Gold de venta con planner Flash (DeepInfra)

En la matriz de 5 experiencias, `sales` pasó:

- `DRAFT_READY`, 4 LLM calls, 1 tool, 1 reparación, 35 258 tokens.
- `test_real_llm_universal_gold[sales]` PASSED.

El Gold largo de `test_real_llm_gold.py` también pasó con el fallback Flash
(DeepInfra):

- `DRAFT_READY`, 5 LLM calls, 1 tool, 2 reparaciones, 56 837 tokens, 236 s.
- `PASSED` con `RAG_WORKFLOW_PLANNER_MODEL=openai/deepseek-ai/DeepSeek-V4.1-Flash`.
- Log: `artifacts/universal-studio-real-llm-gold-deepinfra-final.log`.
- Artefacto: `artifacts/certification/ai/gold-real-llm.deepinfra-pass.json`.

### 4.3 Mentoría

`test_real_llm_universal_gold[mentoring]` pasó con dos turnos:

- el planner pidió decisiones de negocio;
- el usuario respondió con supuestos;
- el backend re-planificó y produjo `DRAFT_READY` con grafo válido;
- 4 LLM calls, 1 tool, 1 reparación, 34 257 tokens.

### 4.4 Auditoría, soporte y bienestar

En la corrida de 5 experiencias con DeepInfra Flash:

| Experiencia | Resultado | Lectura |
|---|---|---|
| sales | **PASSED** | borrador ejecutable, grafo válido |
| mentoring | **PASSED** | borrador tras una aclaración |
| support | **PASSED** (corrida separada) | borrador tras una aclaración |
| audit | **NEEDS_CLARIFICATION** | pidió fuente/criterio y `missing.input`; no produjo draft |
| wellness | **NEEDS_CLARIFICATION** | pidió protocolo/consentimiento; no produjo draft |

No se declaran PASS para audit/wellness. El planner preguntó en lugar de
inventar; es un comportamiento seguro, pero no cumple todavía la definición de
“borrador ejecutable” para esas dos experiencias.

### 4.5 Bloqueo de proveedor

Durante la certificación, Novita devolvió:

```text
403 NOT_ENOUGH_BALANCE
```

Por eso:

- no se completó la matriz de 100 casos con Pro;
- no se completaron las 5 experiencias con Pro;
- se usó el fallback autorizado DeepInfra (`DeepSeek-V4.1-Flash`) para las
  corridas que sí se ejecutaron;
- no se declara GO de calidad del modelo.

### 4.6 Matriz de 100 casos

El dataset está en `tests/certification/ai/universal_cases.json` (100 casos,
10 dominios, sin copiar los templates Gold). El harness está en
`scripts/certification/eval_universal_cases.py`.

Estado: **EJECUTADO CON PRESUPUESTO RESTRINGIDO**. La corrida de 100 casos con
DeepInfra Flash, 4 llamadas LLM, 2 tools y 90 s por caso terminó:

| Métrica | Observado |
|---|---:|
| Casos | 100 |
| Errores de harness | 84 |
| Intención válida | 16% |
| Grafo válido | 0% |
| Contrato limpio | 99% |
| Simulación ejecutada | 0% |
| Durable observado | 61% |
| Aprobación observada | 20% |
| Cobertura de excepciones | 1% |
| Latencia media | 19 323 ms |
| P95 | 30 081 ms |
| Tokens totales | 244 595 |
| Costo reportado | 0.0 USD (el provider no devolvió costo) |

**Lectura correcta:** este resultado mide un presupuesto de 4 llamadas, no la
calidad máxima del modelo. La mayoría de los casos no llegó a `action=plan`
porque el planner usó las llamadas en descubrimiento o clarificación. No se
presenta como calidad del modelo ni como GO. El artefacto está en
`artifacts/certification/ai/universal-eval-100.json`.

Distribución observada:

- 82 casos `budget_exceeded:tool_calls`;
- 2 casos `budget_exceeded:tokens`;
- 16 casos `NEEDS_CLARIFICATION`;
- 0 casos con grafo válido bajo ese presupuesto.

Esto no demuestra que el modelo no pueda planificar: demuestra que 4 llamadas
y 2 tools no alcanzan para descubrir contratos y planificar. Se requiere una
corrida con presupuesto suficiente y repetibilidad antes de cualquier GO.

### 4.7 Muestra de 20 casos con más presupuesto

Corrida: 20 casos, 8 llamadas LLM, 4 tools, 40k tokens, 120 s, 1 reparación.

| Métrica | Observado |
|---|---:|
| Casos | 20 |
| Errores de harness | 13 |
| Intención válida | 35% |
| Grafo válido | 20% |
| Contrato limpio | 100% |
| Simulación ejecutada | 20% |
| Durable observado | 15% |
| Aprobación observada | 55% |
| Cobertura de excepciones | 20% |
| Latencia media | 27 248 ms |
| P95 | 51 696 ms |
| Tokens totales | 211 014 |

Errores: 9 `budget_exceeded:tool_calls`, 4 `budget_exceeded:tokens`, 4
`NEEDS_CONFIGURATION`, 3 `NEEDS_CLARIFICATION`.

**Lectura:** incluso con más presupuesto, el 20% de grafo válido no alcanza
para un GO. El planner sigue gastando llamadas en descubrimiento y el modelo
no cubre bien los dominios fuera de venta. El artefacto está en
`artifacts/certification/ai/universal-eval-20-highbudget.json`.

Se ejecutaron 3 casos de humo antes; el proveedor Pro agotó balance antes de
una matriz completa con Pro. Los resultados de humo no se presentan como
calidad del modelo. Ver
`artifacts/certification/ai/universal-eval-smoke3.json`.

## 4.8 Comandos reproducibles

```powershell
# Gold real con Pro (Novita)
$env:RAG_CERT_REAL_LLM="1"
$env:RAG_WORKFLOW_PLANNER_MODEL="openai/deepseek/deepseek-v4-pro"
.venv/Scripts/python.exe -m pytest tests/certification/ai/test_real_llm_gold.py -q

# Gold real con fallback Flash (DeepInfra)
$env:RAG_LITELLM_DEFAULT_MODEL="openai/deepseek-ai/DeepSeek-V4.1-Flash"
$env:RAG_WORKFLOW_PLANNER_MODEL="openai/deepseek-ai/DeepSeek-V4.1-Flash"
.venv/Scripts/python.exe -m pytest tests/certification/ai/test_real_llm_gold.py -q

# 5 experiencias
.venv/Scripts/python.exe -m pytest tests/certification/ai/test_real_llm_universal_gold.py -q

# Matriz restringida de 100
.venv/Scripts/python.exe scripts/certification/eval_universal_cases.py `
  --limit 100 --concurrency 3 --max-llm-calls 4 --max-tool-calls 2 `
  --max-tokens 20000 --max-seconds 90 --repairs 0 `
  --out artifacts/certification/ai/universal-eval-100.json

# Muestra de 20 con más presupuesto
.venv/Scripts/python.exe scripts/certification/eval_universal_cases.py `
  --limit 20 --concurrency 2 --max-llm-calls 8 --max-tool-calls 4 `
  --max-tokens 40000 --max-seconds 120 --repairs 1 `
  --out artifacts/certification/ai/universal-eval-20-highbudget.json
```

## 5. Pruebas de regresión ejecutadas

| Suite | Resultado |
|---|---|
| `tests/test_workflow_planner_agentic.py` + `test_workflow_planner_output.py` | **34 passed** |
| `tests/test_workflow_architect.py` + `test_workflow_semantic_v2.py` + `test_workflow_design_sessions.py` | **38 passed** |
| `tests/test_llm_streaming.py` + `test_llm_router.py` | **21 passed** |
| `tests/test_workflow_planner_agentic.py` (tras cambios de contrato) | **34 passed** |
| `tests/test_workflow_simulation.py` + `test_capability_registry.py` + `test_workflow_architect_capability_call.py` + `test_workflow_readiness.py` | **37 passed** |
| `ruff` sobre archivos tocados | **OK** |
| `test_real_llm_gold.py` con Pro | **1 passed** (88.32 s) |
| `test_real_llm_gold.py` con Flash/DeepInfra | **1 passed** (236.16 s) |
| `test_real_llm_gold.py` con Flash/Novita antes del fix final | FAILED / luego balance agotado |
| 5 experiencias Gold con DeepInfra | **3 passed (sales, mentoring, support), 2 NEEDS_CLARIFICATION (audit, wellness)** |

No se ejecutaron: suite completa, carga, caos, sandbox de pagos, worker
restart ni una matriz de 100 casos con presupuesto suficiente para planificar
(la corrida de 100 usó 4 llamadas y se reporta como restringida).

## 6. GO / NO-GO

| Dominio | Decisión |
|---|---|
| Generación Gold de venta con Pro | **GO técnico condicionado** a presupuesto/modelo |
| Generación Gold de venta con Flash (DeepInfra) | **GO observado** en dos corridas; falta repetibilidad formal |
| Mentoría | **GO observado** con dos turnos |
| Auditoría / bienestar | **NO-GO**: quedan en clarificación |
| Soporte | **GO observado** con una aclaración |
| Matriz 100 casos | **EJECUTADA CON PRESUPUESTO RESTRINGIDO**; 0% grafo válido |
| Muestra 20 casos con más presupuesto | **NO-GO**: 20% grafo válido |
| Repetibilidad del Gold | **NO VERIFICADA** (falta presupuesto) |
| Producción general | **NO-GO** |

Para pasar a GO se requiere:

1. repetir el Gold 3 veces con el mismo modelo y presupuesto;
2. completar las 5 experiencias con draft ejecutable o aceptar formalmente
   clarificación como resultado de producto;
3. ejecutar los 100 casos con métricas y costo;
4. sandbox real de proveedores;
5. carga/chaos y worker restart;
6. integrar la certificación al gate de publicación.

## 7. Riesgos abiertos

| Riesgo | Propietario | Estado |
|---|---|---|
| Balance/limite del proveedor Pro | AI/Workflow Lead | Abierto |
| Repetibilidad del modelo Flash | AI/Workflow Lead | Abierto |
| 2 experiencias sin draft (audit, wellness) | Product/Workflow Lead | Abierto |
| 100 casos sin ejecutar | QA Lead | Abierto |
| Sandbox de pagos | QA/Partners | Abierto |
| Carga/chaos | SRE Lead | Abierto |
| Gate de publicación con certificación | Workflow Lead | Abierto (fase 06) |

## 8. Conclusión

La causa del `planner.invalid_llm_output` está corregida y el Gold real de
venta genera un grafo válido con Pro y con el fallback Flash. El sistema ya no
convierte una salida vacía o truncada en un plan falso: la explica, la repara
de forma acotada y conserva la petición original en el fallback.

No se declara GO porque la cobertura real no alcanza: 2 de 5 experiencias
quedan en clarificación y la matriz de 20/100 casos muestra 20%/0% de grafo
válido bajo los presupuestos usados. La evidencia está separada por proveedor,
modelo y tipo de prueba.
