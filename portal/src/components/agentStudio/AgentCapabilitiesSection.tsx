import { AgentField, AgentFieldGroup, AgentToggleCard } from "./AgentField";
import { COPY, RETRIEVAL_STRATEGIES, TOOL_CHOICES, choiceOptionLabel } from "./advancedCopy";
import { Input, Select } from "../ui";
import type { AgentConfig } from "./types";

const DEFAULT_LIMITS = { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 };

/** Pestaña "Qué puede hacer": permisos, búsqueda en fuentes y topes de gasto. */
export function AgentCapabilitiesSection({
  config,
  setConfig,
  semantic,
  setSemantic,
  sql,
  setSql,
  apiCalls,
  setApiCalls,
  retrieval,
  setRetrieval,
}: {
  config: AgentConfig;
  setConfig: (config: AgentConfig) => void;
  semantic: boolean;
  setSemantic: (value: boolean) => void;
  sql: boolean;
  setSql: (value: boolean) => void;
  apiCalls: boolean;
  setApiCalls: (value: boolean) => void;
  retrieval: { strategy: string; top_k: number; score_threshold: number };
  setRetrieval: (value: { strategy: string; top_k: number; score_threshold: number }) => void;
}) {
  const toolState: Record<string, { checked: boolean; onChange: (value: boolean) => void }> = {
    search_knowledge: { checked: semantic, onChange: setSemantic },
    query_database: { checked: sql, onChange: setSql },
    call_api: { checked: apiCalls, onChange: setApiCalls },
  };

  function setLimit(key: keyof typeof DEFAULT_LIMITS, value: number) {
    setConfig({
      ...config,
      limits: { ...(config.limits || DEFAULT_LIMITS), [key]: value },
    });
  }

  return (
    <div className="grid gap-6">
      <AgentFieldGroup title={COPY.tools.title} hint={COPY.tools.hint}>
        <div className="grid gap-2 sm:grid-cols-2">
          {TOOL_CHOICES.map((tool) => (
            <AgentToggleCard
              key={tool.tool}
              id={`agent-tool-${tool.tool}`}
              label={tool.label}
              hint={tool.hint}
              tech={tool.tool}
              checked={toolState[tool.tool].checked}
              onChange={toolState[tool.tool].onChange}
            />
          ))}
        </div>
        <p className="text-xs leading-relaxed text-faint">
          Consultar la base de datos y Llamar APIs externas son permisos sensibles: al activarlos
          también quedan habilitados en la seguridad del agente.
        </p>
      </AgentFieldGroup>

      <AgentFieldGroup title={COPY.retrieval.title} hint={COPY.retrieval.hint}>
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
      </AgentFieldGroup>

      <AgentFieldGroup title={COPY.limits.title} hint={COPY.limits.hint}>
        <div className="grid gap-4 sm:grid-cols-3">
          <AgentField id="agent-limit-steps" label={COPY.limits.stepsLabel} hint={COPY.limits.stepsHint}>
            <Input
              id="agent-limit-steps"
              type="number"
              className="tabular-nums"
              min={1}
              max={100}
              value={config.limits?.max_steps ?? DEFAULT_LIMITS.max_steps}
              onChange={(e) => setLimit("max_steps", Number(e.target.value))}
            />
          </AgentField>

          <AgentField id="agent-limit-tokens" label={COPY.limits.tokensLabel} hint={COPY.limits.tokensHint}>
            <Input
              id="agent-limit-tokens"
              type="number"
              className="tabular-nums"
              min={1}
              value={config.limits?.max_tokens ?? DEFAULT_LIMITS.max_tokens}
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
              value={config.limits?.max_cost_usd ?? DEFAULT_LIMITS.max_cost_usd}
              onChange={(e) => setLimit("max_cost_usd", Number(e.target.value))}
            />
          </AgentField>
        </div>
      </AgentFieldGroup>
    </div>
  );
}
