// =============================================================================
// AgentSettingGroups — grupos de configuración con estado resumido.
// =============================================================================
// Cada grupo muestra primero su resumen y su estado (Automático vs
// Personalizado); los campos técnicos aparecen al personalizar. Ninguno
// introduce estado propio: todos leen y escriben `AgentConfig`.
// =============================================================================
import type { CSSProperties } from "react";
import { AgentField } from "./AgentField";
import { AgentSettingGroup, type SettingMode } from "./AgentSettingGroup";
import {
  DEFAULT_MODEL_ROUTE,
  MODEL_PRIORITIES,
  RECOMMENDED_LIMITS,
  RECOMMENDED_RETRIEVAL,
  capabilityStates,
  intelligenceMode,
  intelligenceSummary,
  limitsMode,
  limitsSummary,
  modelMode,
  modelSummary,
  retrievalMode,
  retrievalSummary,
  type CapabilityFlags,
} from "./agentModes";
import { COPY, CUSTOM_MODEL_VALUE, RETRIEVAL_STRATEGIES, choiceOptionLabel } from "./advancedCopy";
import { hasDbSources } from "./toolApplicability";
import { Button, Input, Select, Textarea } from "../ui";
import { parseSchema, type AgentConfig } from "./types";

// ---------------------------------------------------------------------------
// MODELO
// ---------------------------------------------------------------------------

export function AgentModelGroup({
  model,
  setModel,
  routes,
  canCustomModel,
  config,
  setConfig,
  open,
  onOpenChange,
}: {
  model: string;
  setModel: (value: string) => void;
  routes: { name: string; description: string }[];
  canCustomModel: boolean;
  config: AgentConfig;
  setConfig: (config: AgentConfig) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const knownRoutes = MODEL_PRIORITIES.map((priority) => priority.value);
  const isKnownRoute = routes.some((route) => route.name === model) || knownRoutes.includes(model);
  const priorityValue = isKnownRoute ? model : canCustomModel ? CUSTOM_MODEL_VALUE : DEFAULT_MODEL_ROUTE;
  const showCustomModel = canCustomModel && !isKnownRoute;

  return (
    <AgentSettingGroup
      id="model"
      title="Modelo"
      mode={modelMode(model)}
      summary={modelSummary(model)}
      onMode={(next: SettingMode) => {
        onOpenChange(true);
        if (next === "auto") setModel(DEFAULT_MODEL_ROUTE);
      }}
      open={open}
      onOpenChange={onOpenChange}
      autoLabel="Automático (recomendado)"
      customLabel="Personalizado"
      autoHint="Zent elige el motor según la tarea y el presupuesto."
      customHint="Fijá la prioridad o un modelo concreto."
    >
      <AgentField id="agent-model-route" label={COPY.model.label} hint={COPY.model.hint}>
        <Select
          id="agent-model-route"
          value={priorityValue}
          onChange={(e) => {
            const next = e.target.value;
            if (next === CUSTOM_MODEL_VALUE) {
              setModel("");
              return;
            }
            setModel(next);
          }}
        >
          {MODEL_PRIORITIES.filter((priority) => priority.value !== DEFAULT_MODEL_ROUTE).map(
            (priority) => (
              <option key={priority.value} value={priority.value}>
                {choiceOptionLabel(priority)}
              </option>
            ),
          )}
          {routes
            .filter((route) => !knownRoutes.includes(route.name))
            .map((route) => (
              <option key={route.name} value={route.name}>
                {route.name}
              </option>
            ))}
          {canCustomModel && <option value={CUSTOM_MODEL_VALUE}>Modelo específico…</option>}
        </Select>
      </AgentField>

      {showCustomModel && (
        <AgentField id="agent-model-custom" label={COPY.model.customLabel} hint={COPY.model.customHint}>
          <Input
            id="agent-model-custom"
            placeholder="openai/gpt-4o-mini"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </AgentField>
      )}

      <AgentField
        id="agent-temperature"
        label={`${COPY.temperature.label} · ${config.temperature.toFixed(2)}`}
        hint={COPY.temperature.hint}
      >
        <input
          id="agent-temperature"
          aria-describedby="agent-temperature-hint"
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={config.temperature}
          onChange={(e) => setConfig({ ...config, temperature: Number(e.target.value) })}
          className="range mt-1 w-full cursor-pointer"
          style={{ "--range-progress": `${Math.round(config.temperature * 100)}%` } as CSSProperties}
        />
        <div className="flex justify-between text-xs text-faint">
          <span>{COPY.temperature.min}</span>
          <span>{COPY.temperature.max}</span>
        </div>
      </AgentField>
    </AgentSettingGroup>
  );
}

// ---------------------------------------------------------------------------
// HERRAMIENTAS
// ---------------------------------------------------------------------------

export function AgentToolsGroup({
  flags,
  onToggle,
  sourceTypes,
  onEnableAvailable,
  open,
  onOpenChange,
}: {
  flags: CapabilityFlags;
  onToggle: (id: keyof CapabilityFlags, value: boolean) => void;
  /** `null` = no se pudo determinar: no se restringe. */
  sourceTypes?: string[] | null;
  /** Activa de una vez las capacidades compatibles con las fuentes. */
  onEnableAvailable?: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const dbAvailable = hasDbSources(sourceTypes);
  const capabilities = capabilityStates(flags, { dbAvailable });
  const active = capabilities.filter((capability) => capability.checked).length;

  return (
    <AgentSettingGroup
      id="tools"
      title={COPY.tools.title}
      mode={active > 0 ? "custom" : "auto"}
      summary={
        active === 0
          ? "Sin herramientas activas: sólo responde con su propósito."
          : `${active} de ${capabilities.length} activas · ${capabilities
              .filter((capability) => capability.checked)
              .map((capability) => capability.label)
              .join(" · ")}`
      }
      open={open}
      onOpenChange={onOpenChange}
      autoLabel="Recomendadas"
      customLabel="Elegidas por mí"
    >
      <p className="text-xs leading-relaxed text-muted">{COPY.tools.hint}</p>
      <div className="grid gap-2">
        {capabilities.map((capability) => (
          <label
            key={capability.id}
            htmlFor={`agent-capability-${capability.id}`}
            className={`flex cursor-pointer items-start gap-2.5 rounded-md border bg-raised p-3 transition-colors duration-150 ${
              capability.checked ? "border-accent-line bg-accent-soft/40" : "border-border hover:border-border-strong"
            } ${capability.available ? "" : "cursor-not-allowed opacity-70"}`}
          >
            <input
              id={`agent-capability-${capability.id}`}
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
              checked={capability.checked && capability.available}
              disabled={!capability.available}
              onChange={(event) => onToggle(capability.id, event.target.checked)}
            />
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-text">{capability.label}</span>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{capability.hint}</span>
              {capability.tech.length > 0 && (
                <span className="mt-1 block font-mono text-[11px] text-faint">
                  {capability.tech.join(" · ")}
                </span>
              )}
              {!capability.available && (
                <span className="mt-1 block text-[11px] leading-relaxed text-faint">
                  {capability.unavailableHint}
                </span>
              )}
            </span>
          </label>
        ))}
      </div>
      <p className="text-xs leading-relaxed text-faint">
        SQL y APIs externas son permisos sensibles: al activarlos quedan habilitados también en la
        seguridad del agente, y SQL sólo se ofrece si el agente tiene fuentes de datos conectadas.
      </p>
      {onEnableAvailable && (
        <div>
          <Button variant="secondary" size="sm" onClick={onEnableAvailable}>
            Activar las compatibles con mis fuentes
          </Button>
        </div>
      )}
    </AgentSettingGroup>
  );
}

// ---------------------------------------------------------------------------
// BÚSQUEDA
// ---------------------------------------------------------------------------

export function AgentRetrievalGroup({
  retrieval,
  setRetrieval,
  open,
  onOpenChange,
}: {
  retrieval: { strategy: string; top_k: number; score_threshold: number };
  setRetrieval: (value: { strategy: string; top_k: number; score_threshold: number }) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <AgentSettingGroup
      id="retrieval"
      title={COPY.retrieval.title}
      mode={retrievalMode(retrieval)}
      summary={retrievalSummary(retrieval)}
      onMode={(next) => {
        onOpenChange(true);
        if (next === "auto") setRetrieval({ ...RECOMMENDED_RETRIEVAL });
      }}
      open={open}
      onOpenChange={onOpenChange}
      onRestore={() => setRetrieval({ ...RECOMMENDED_RETRIEVAL })}
      autoLabel="Búsqueda inteligente — Automática"
      customLabel="Personalizada"
      autoHint="Zent decide cómo buscar y cuántos fragmentos usar."
      customHint="Elegí la forma de buscar y los topes."
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <AgentField
          id="agent-retrieval-strategy"
          label={COPY.retrieval.strategyLabel}
          hint={COPY.retrieval.strategyHint}
        >
          <Select
            id="agent-retrieval-strategy"
            value={retrieval.strategy}
            onChange={(e) => setRetrieval({ ...retrieval, strategy: e.target.value })}
          >
            {RETRIEVAL_STRATEGIES.map((strategy) => (
              <option key={strategy.value} value={strategy.value}>
                {choiceOptionLabel(strategy)}
              </option>
            ))}
          </Select>
        </AgentField>

        <AgentField id="agent-retrieval-topk" label={COPY.retrieval.topKLabel} hint={COPY.retrieval.topKHint}>
          <Input
            id="agent-retrieval-topk"
            type="number"
            className="tabular-nums"
            min={1}
            max={50}
            value={retrieval.top_k}
            onChange={(e) => setRetrieval({ ...retrieval, top_k: Number(e.target.value) || 8 })}
          />
        </AgentField>

        <AgentField
          id="agent-retrieval-threshold"
          label={COPY.retrieval.thresholdLabel}
          hint={COPY.retrieval.thresholdHint}
        >
          <Input
            id="agent-retrieval-threshold"
            type="number"
            className="tabular-nums"
            step={0.05}
            min={0}
            max={1}
            value={retrieval.score_threshold}
            onChange={(e) => setRetrieval({ ...retrieval, score_threshold: Number(e.target.value) || 0 })}
          />
        </AgentField>
      </div>
    </AgentSettingGroup>
  );
}

// ---------------------------------------------------------------------------
// ORQUESTACIÓN JEV
// ---------------------------------------------------------------------------

const JEV_FIELDS = [
  {
    key: "tool_routing" as const,
    id: "agent-jev-tool-routing",
    label: "Ruteo de herramientas",
    hint: "JEV elige qué herramienta usar en cada paso (tool_routing).",
  },
  {
    key: "termination_gate" as const,
    id: "agent-jev-termination-gate",
    label: "Corte por evidencia suficiente",
    hint: "JEV decide cuándo ya hay evidencia para responder y corta la búsqueda (termination_gate).",
  },
  {
    key: "answer_gate" as const,
    id: "agent-jev-answer-gate",
    label: "Verificación de la respuesta",
    hint: "Antes de responder, JEV puntúa el borrador contra la evidencia y pide correcciones (answer_gate).",
  },
];

export function AgentIntelligenceGroup({
  runtime,
  onOverride,
  open,
  onOpenChange,
}: {
  runtime: AgentConfig["runtime"] | null | undefined;
  onOverride: (patch: { tool_routing?: boolean | null; termination_gate?: boolean | null; answer_gate?: boolean | null }) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const source = runtime ?? {};
  const value = (key: (typeof JEV_FIELDS)[number]["key"]) =>
    typeof source[key] === "boolean" ? (source[key] ? "on" : "off") : "inherit";

  return (
    <AgentSettingGroup
      id="intelligence"
      title="Optimización inteligente"
      hint="Zent decide cómo buscar, qué herramienta usar y cuándo hay evidencia suficiente para responder."
      mode={intelligenceMode(runtime)}
      summary={intelligenceSummary(runtime)}
      onMode={(next) => {
        onOpenChange(true);
        if (next === "auto") {
          onOverride({ tool_routing: null, termination_gate: null, answer_gate: null });
        }
      }}
      open={open}
      onOpenChange={onOpenChange}
      onRestore={() => onOverride({ tool_routing: null, termination_gate: null, answer_gate: null })}
      restoreLabel="Volver a heredar de Zent"
      autoLabel="Heredar inteligencia de Zent"
      customLabel="Personalizar"
      autoHint="Usa la configuración de Control Center."
      customHint="Activá o apagá cada parte sólo en este agente."
    >
      <div className="grid gap-4">
        {JEV_FIELDS.map((field) => (
          <AgentField key={field.key} id={field.id} label={field.label} hint={field.hint}>
            <Select
              id={field.id}
              value={value(field.key)}
              onChange={(e) => {
                const next = e.target.value;
                onOverride({ [field.key]: next === "inherit" ? null : next === "on" });
              }}
            >
              <option value="inherit">Heredar del sistema</option>
              <option value="on">Activado en este agente</option>
              <option value="off">Apagado en este agente</option>
            </Select>
          </AgentField>
        ))}
      </div>
    </AgentSettingGroup>
  );
}

// ---------------------------------------------------------------------------
// SEGURIDAD Y LÍMITES
// ---------------------------------------------------------------------------

export function AgentLimitsGroup({
  config,
  setConfig,
  open,
  onOpenChange,
}: {
  config: AgentConfig;
  setConfig: (config: AgentConfig) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  function setLimit(key: keyof typeof RECOMMENDED_LIMITS, value: number) {
    setConfig({ ...config, limits: { ...(config.limits || RECOMMENDED_LIMITS), [key]: value } });
  }

  return (
    <AgentSettingGroup
      id="limits"
      title="Límites y costos"
      mode={limitsMode(config.limits)}
      summary={limitsSummary(config.limits)}
      onMode={(next) => {
        onOpenChange(true);
        if (next === "auto") setConfig({ ...config, limits: { ...RECOMMENDED_LIMITS } });
      }}
      open={open}
      onOpenChange={onOpenChange}
      onRestore={() => setConfig({ ...config, limits: { ...RECOMMENDED_LIMITS } })}
      autoLabel="Protección recomendada"
      customLabel="Personalizar"
      autoHint="Topes que evitan bucles y gasto inesperado."
      customHint="Subí o bajá cada tope según el caso."
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <AgentField id="agent-limit-steps" label={COPY.limits.stepsLabel} hint={COPY.limits.stepsHint}>
          <Input
            id="agent-limit-steps"
            type="number"
            className="tabular-nums"
            min={1}
            max={100}
            value={config.limits?.max_steps ?? RECOMMENDED_LIMITS.max_steps}
            onChange={(e) => setLimit("max_steps", Number(e.target.value))}
          />
        </AgentField>

        <AgentField id="agent-limit-tokens" label={COPY.limits.tokensLabel} hint={COPY.limits.tokensHint}>
          <Input
            id="agent-limit-tokens"
            type="number"
            className="tabular-nums"
            min={1}
            value={config.limits?.max_tokens ?? RECOMMENDED_LIMITS.max_tokens}
            onChange={(e) => setLimit("max_tokens", Number(e.target.value))}
          />
        </AgentField>

        <AgentField id="agent-limit-cost" label={COPY.limits.costLabel} hint={COPY.limits.costHint}>
          <Input
            id="agent-limit-cost"
            type="number"
            className="tabular-nums"
            min={0}
            step={0.01}
            value={config.limits?.max_cost_usd ?? RECOMMENDED_LIMITS.max_cost_usd}
            onChange={(e) => setLimit("max_cost_usd", Number(e.target.value))}
          />
        </AgentField>
      </div>
      <p className="text-xs leading-relaxed text-faint">
        Si el agente llega a un tope, Zent corta el turno y responde con lo que tenga. El detalle de
        cada corte queda en «Ver cómo llegó a esta respuesta».
      </p>
    </AgentSettingGroup>
  );
}

// ---------------------------------------------------------------------------
// INTEGRACIÓN / SALIDA ESTRUCTURADA
// ---------------------------------------------------------------------------

export function AgentIntegrationGroup({
  outputSchema,
  setOutputSchema,
  open,
  onOpenChange,
}: {
  outputSchema: string;
  setOutputSchema: (value: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const declared = outputSchema.trim() !== "";
  const invalid = declared && !parseSchema(outputSchema);

  return (
    <AgentSettingGroup
      id="integration"
      title="Salida estructurada"
      mode={declared ? "custom" : "auto"}
      summary={declared ? "Responde siempre con el JSON declarado" : "Texto libre"}
      open={open}
      onOpenChange={onOpenChange}
      autoLabel="Texto libre"
      customLabel="JSON declarado"
    >
      <p className="text-xs leading-relaxed text-muted">
        Actívalo si otro sistema necesita recibir siempre una estructura JSON determinada.
      </p>
      <AgentField
        id="agent-output-schema"
        label={COPY.output.label}
        hint={COPY.output.hint}
        error={invalid ? COPY.output.invalid : undefined}
      >
        <Textarea
          id="agent-output-schema"
          className="min-h-52 font-mono text-xs"
          value={outputSchema}
          onChange={(e) => setOutputSchema(e.target.value)}
          placeholder={'{"product": "string", "warehouse": "string", "stock": "integer"}'}
          spellCheck={false}
        />
      </AgentField>
    </AgentSettingGroup>
  );
}
