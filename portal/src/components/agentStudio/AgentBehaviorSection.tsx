import { AgentField, FIELD_INPUT_CLASS } from "./AgentField";
import {
  COPY,
  CUSTOM_MODEL_VALUE,
  GATEWAY_ROUTES,
  TONE_CHOICES,
  choiceOptionLabel,
} from "./advancedCopy";
import { type AgentConfig, parseSchema } from "./types";

const INPUT_CLASS = FIELD_INPUT_CLASS;

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
    <section className="mt-4 grid gap-5">
      <AgentField id="agent-model-route" label={COPY.model.label} hint={COPY.model.hint}>
        <select
          id="agent-model-route"
          aria-describedby="agent-model-route-hint"
          className={INPUT_CLASS}
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
        </select>
      </AgentField>

      {showCustomModel && (
        <AgentField id="agent-model-custom" label={COPY.model.customLabel} hint={COPY.model.customHint}>
          <input
            id="agent-model-custom"
            aria-describedby="agent-model-custom-hint"
            className={INPUT_CLASS}
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
          className="w-full"
        />
        <div className="mt-1 flex justify-between text-xs text-faint">
          <span>{COPY.temperature.min}</span>
          <span>{COPY.temperature.max}</span>
        </div>
      </AgentField>

      <AgentField id="agent-tone" label={COPY.tone.label} hint={COPY.tone.hint}>
        <select
          id="agent-tone"
          aria-describedby="agent-tone-hint"
          className={INPUT_CLASS}
          value={config.tone}
          onChange={(e) => setConfig({ ...config, tone: e.target.value as AgentConfig["tone"] })}
        >
          {TONE_CHOICES.map((tone) => (
            <option key={tone.value} value={tone.value}>
              {tone.label} · {tone.hint}
            </option>
          ))}
        </select>
      </AgentField>

      <AgentField id="agent-output-schema" label={COPY.output.label} hint={COPY.output.hint}>
        <textarea
          id="agent-output-schema"
          aria-describedby="agent-output-schema-hint"
          aria-invalid={schemaInvalid}
          className={`${INPUT_CLASS} min-h-52 font-mono text-xs`}
          value={outputSchema}
          onChange={(e) => setOutputSchema(e.target.value)}
          placeholder={'{"product": "string", "warehouse": "string", "stock": "integer"}'}
          spellCheck={false}
        />
        {schemaInvalid && (
          <p className="mt-2 text-xs text-danger" role="alert">
            {COPY.output.invalid}
          </p>
        )}
      </AgentField>
    </section>
  );
}
