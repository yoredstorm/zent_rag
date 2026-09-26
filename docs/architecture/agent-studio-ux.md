# Agent Studio — arquitectura de la experiencia

Cómo el módulo Agents pasó de "panel de configuración de infraestructura" a
"constructor de agentes", sin perder ni una capacidad del motor.

## Principio

La complejidad no se eliminó: se jerarquizó. Todo lo que el runtime lee sigue
siendo configurable y sigue persistiéndose con la misma forma. Lo que cambió es
cuándo aparece.

Tres niveles de visibilidad sobre **el mismo** `AgentConfig`:

| Nivel | Qué es | Dónde vive |
|---|---|---|
| 1 — Esencial | Identidad, conocimiento, comportamiento, inteligencia | Etapa **Desarrollar**, columna de diseño |
| 2 — Contextual | Herramientas según fuentes, indexado, checklist de estado, versión | Aparece cuando el estado lo justifica |
| 3 — Avanzado | Modelo, retrieval, límites, JEV, salida estructurada, publicación | **Configuración avanzada** y etapa **Publicar** |

## Etapas

```
DESARROLLAR  →  PROBAR  →  PUBLICAR
```

Configurar el agente y **operarlo** son cosas distintas. Versiones, entornos,
deployments, rollback, embed, evaluación y quality gates no son parámetros del
agente: son operación posterior. Ahora viven en Publicar.

URL: `?panel=develop|test|publish`. Alias legacy: `configure` (→ develop),
`advanced` (→ develop con avanzado abierto), `publish`.

## Auto vs Personalizado

No hay campo nuevo persistido. `Auto` se **deriva** de comparar el valor
guardado contra el valor recomendado (`agentModes.ts`):

| Grupo | Automático cuando | Personalizado cuando |
|---|---|---|
| Modelo | `model` vacío o `zent-default` | cualquier otra ruta o modelo concreto |
| Respuesta | perfil indistinguible de un preset | cualquier desvío, `custom_instructions` o `preferred_blueprints` |
| Búsqueda | `hybrid` / `top_k=10` / `score_threshold=0` | cualquier otro valor |
| JEV | `runtime` sin ningún valor definido | cualquier override (`tool_routing`, `termination_gate`, `answer_gate`, `jev_loop`) |
| Límites | `8` / `4000` / `0.5` | cualquier otro tope |
| Salida | sin `output_schema` | con `output_schema` |

Consecuencia de diseño: un agente legacy con `vector` / `top_k=8` aparece como
**Personalizado** y **no se resetea**. Sólo se pisa un valor cuando el usuario
pide explícitamente "Automático" o "Restaurar valores recomendados".

## Defaults

Sin cambios respecto del comportamiento previo:

```
temperature = 0.2   max_steps = 8   max_tokens = 4000   max_cost_usd = 0.5
retrieval   = hybrid / top_k 10 / score_threshold 0     model = zent-default
```

El payload de guardado (`buildAgentPayload`) conserva su forma exacta: sigue
enviando `tone` (aunque la UI ya no lo exponga), `knowledge_base_ids` (el backend
lo deriva de `source_ids`), `retrieval` siempre presente y `runtime` sólo si hay
overrides.

## Deduplicación de `tone`

`AgentConfig.tone` se validaba en el schema pero **ningún consumidor de runtime
lo leía**: el tono efectivo sale de `response_profile.tone` vía
`profile_from_config`. La UI tenía dos selectores de tono que no significaban lo
mismo.

Decisión: una sola experiencia de "cómo responde" (`response_profile`). El campo
legacy se sigue persistiendo con su valor actual para no romper contratos, pero
deja de ser una decisión visible.

## Corrección: perfil por defecto desalineado

`DEFAULT_RESPONSE_PROFILE` del portal declaraba `use_tables: false` mientras el
dominio (`src/core/domain/response.py`) usa `use_tables: true`. En agentes sin
`response_profile` guardado el portal mostraba un perfil que no era el aplicado.
Ahora el espejo del portal coincide con el dominio.

## Capacidades y fuentes

`toolApplicability.ts` sigue siendo el espejo de `_filter_tools_by_sources`. La
UI presenta capacidades semánticas y mantiene el identificador técnico como pista
secundaria:

| Capacidad | Tools reales | Disponible cuando |
|---|---|---|
| Consultar conocimiento | `search_knowledge`, `query_tabular_data` | siempre |
| Consultar datos | `query_database` | hay fuentes de base de datos |
| Usar integraciones externas | `call_api` | siempre |

Una capacidad incompatible nunca se activa: el checkbox queda deshabilitado y el
runtime ya omite esa herramienta. SQL y APIs siguen siendo permisos sensibles de
activación explícita.

## Recomendación automática

`recommendAgentConfiguration` es determinista: reglas sobre el propósito
(normativa → con evidencia; dirección → ejecutivo; técnico → experto técnico;
capacitación → didáctico; brevedad → conciso) y sobre los tipos de fuente. Nunca
enciende una capacidad que el agente no pueda usar y muestra **qué decidió y por
qué**. Nada se aplica sin confirmación.

El borrador de estilo con IA reutiliza el endpoint existente
(`POST /agents/{id}/config/response-profile`), que sólo lee datos reales del
agente y rechaza mencionar capacidades no configuradas.

## Componentes

```
agentStudio/
  useAgentStudio.ts          estado y acciones (una sola fuente de verdad)
  agentModes.ts              Auto/Personalizado, presets, recomendación (puro)
  types.ts                   AgentConfig, etapas, grupos, payload
  AgentStageNav.tsx          DESARROLLAR / PROBAR / PUBLICAR
  AgentPurposeForm.tsx       Identidad + instrucciones adicionales
  AgentKnowledgeSection.tsx  Conocimiento (resumen) + administrar fuentes
  AgentBehaviorPresetSection.tsx  Comportamiento (presets)
  AgentIntelligenceSection.tsx    Inteligencia (Nivel 1)
  AgentReadinessChecklist.tsx     Estado del agente en el header
  AgentAiConfigSuggestion.tsx     "Crear configuración con IA"
  AgentAdvancedPanel.tsx     7 grupos con progressive disclosure interno
  AgentSettingGroup.tsx      patrón Auto/Personalizado reutilizable
  AgentSettingGroups.tsx     modelo, herramientas, búsqueda, JEV, límites, salida
  AgentResponseProfileSection.tsx  perfil detallado (un solo lugar por vez)
  AgentSourcePicker.tsx      selección de fuentes
  AgentTestChat.tsx          playground
  AgentPublishSection.tsx    versiones, entornos, embed, evaluación, gates
```

`AgentStudio.tsx` sólo ensambla: no guarda estado propio.

## Readiness

Los ítems del checklist son **los que devuelve el backend**
(`/agents/{id}/readiness`). No se inventan señales que el sistema no mida: por eso
el checklist habla de "Modelo elegido", "Conocimiento disponible" o "Publicado y
atendiendo", y no de "Probado" o "Inteligencia configurada". Los ítems con peso 0
(límites de uso, observabilidad) quedan en el detalle de Publicar.

## Límites de la etapa test

Con `use_tables` corregido y los presets alineados, el resultado de la etapa
Probar depende del runtime real: el portal únicamente renderiza el `flow`
canónico que manda el backend (`run/stream`), sin reconstruirlo.
