import { AgentField } from "./AgentField";
import {
  COPY,
  CUSTOM_MODEL_VALUE,
  GATEWAY_ROUTES,
  TONE_CHOICES,
  choiceOptionLabel,
} from "./advancedCopy";
import { Input, Select, Textarea } from "../ui";
import { type AgentConfig, parseSchema } from "./types";

const KNOWN_ROUTES = GATEWAY_ROUTES.map((route) => route.value);

/** Pestaña "Cómo responde": motor, creatividad, tono y formato de salida. */
export function AgentBehaviorSection({
  model,
  setModel,
  routes,
  canCustomModel,
  config,
  setConfig,
  outputSchema,
  setOutputSchema,
}: {
  model: string;
  setModel: (value: string) => void;
  routes: { name: string; description: string }[];
  canCustomModel: boolean;
  config: AgentConfig;
  setConfig: (config: AgentConfig) => void;
  outputSchema: string;
  setOutputSchema: (value: string) => void;
}) {
  const isKnownRoute = routes.some((r) => r.name === model) || KNOWN_ROUTES.includes(model);
  const gatewayValue = isKnownRoute ? model : model && canCustomModel ? CUSTOM_MODEL_VALUE : "zent-default";
  const showCustomModel = canCustomModel && (!isKnownRoute || model === "");
  const schemaInvalid = outputSchema.trim() !== "" && !parseSchema(outputSchema);

  return (
    <section className="grid gap-5">
      <AgentField id="agent-model-route" label={COPY.model.label} hint={COPY.model.hint}>
        <Select
          id="agent-model-route"
          value={gatewayValue}
          onChange={(e) => {
            const next = e.target.value;
            if (next === CUSTOM_MODEL_VALUE) {
              setModel("");
              return;
            }
            setModel(next);
          }}
        >
          {GATEWAY_ROUTES.map((route) => (
            <option key={route.value} value={route.value}>
              {choiceOptionLabel(route)}
            </option>
          ))}
          {routes
            .filter((r) => !KNOWN_ROUTES.includes(r.name))
            .map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          {canCustomModel && <option value={CUSTOM_MODEL_VALUE}>Modelo propio…</option>}
        </Select>
      </AgentField>

      {showCustomModel && (
        <AgentField id="agent-model-custom" label={COPY.model.customLabel} hint={COPY.model.customHint}>
          <Input
            id="agent-model-custom"
            placeholder="openai/gpt-4o-mini"
            value={isKnownRoute ? "" : model}
            onChange={(e) => setModel(e.target.value)}
          />
        </AgentField>
      )}

      <AgentField
        id="agent-temperature"
        label={`${COPY.temperature.label} (${config.temperature.toFixed(2)})`}
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
          className="h-9 w-full cursor-pointer accent-accent"
        />
        <div className="flex justify-between text-xs text-faint">
          <span>{COPY.temperature.min}</span>
          <span>{COPY.temperature.max}</span>
        </div>
      </AgentField>

      <AgentField id="agent-tone" label={COPY.tone.label} hint={COPY.tone.hint}>
        <Select
          id="agent-tone"
          value={config.tone}
          onChange={(e) => setConfig({ ...config, tone: e.target.value as AgentConfig["tone"] })}
        >
          {TONE_CHOICES.map((tone) => (
            <option key={tone.value} value={tone.value}>
              {tone.label} · {tone.hint}
            </option>
          ))}
        </Select>
      </AgentField>

      <AgentField
        id="agent-output-schema"
        label={COPY.output.label}
        hint={COPY.output.hint}
        error={schemaInvalid ? COPY.output.invalid : undefined}
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
    </section>
  );
}
