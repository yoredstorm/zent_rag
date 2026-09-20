import { AgentField, AgentFieldGroup, AgentToggleCard } from "./AgentField";
import { COPY, RETRIEVAL_STRATEGIES, TOOL_CHOICES, choiceOptionLabel } from "./advancedCopy";
import { hasDbSources } from "./toolApplicability";
import { Button, Input, Select } from "../ui";
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
  jevMode,
  setJevMode,
  answerGate,
  setAnswerGate,
  sourceTypes = null,
  onEnableAll,
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
  jevMode: "inherit" | "on" | "off";
  setJevMode: (value: "inherit" | "on" | "off") => void;
  answerGate: "inherit" | "on" | "off";
  setAnswerGate: (value: "inherit" | "on" | "off") => void;
  /** Tipos de fuente del agente; `null` = desconocido (no se restringe). */
  sourceTypes?: string[] | null;
  onEnableAll: () => void;
}) {
  const dbAvailable = hasDbSources(sourceTypes);
  const toolState: Record<
    string,
    {
      checked: boolean;
      onChange: (value: boolean) => void;
      disabled?: boolean;
      disabledHint?: string;
    }
  > = {
    search_knowledge: { checked: semantic, onChange: setSemantic },
    query_database: {
      checked: sql && dbAvailable,
      onChange: setSql,
      disabled: !dbAvailable,
      disabledHint: "Tus fuentes no incluyen base de datos: SQL se omite en este agente.",
    },
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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="prose-measure text-xs leading-relaxed text-muted">
            Con 3 o más herramientas activas, JEV elige cuál usar en cada paso. Las claves sensibles
            (base de datos, APIs) se pueden apagar por agente.
          </p>
          <Button variant="secondary" size="sm" onClick={onEnableAll}>
            Activar todas
          </Button>
        </div>
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
              disabled={toolState[tool.tool].disabled}
              disabledHint={toolState[tool.tool].disabledHint}
            />
          ))}
        </div>
        <p className="text-xs leading-relaxed text-faint">
          Consultar la base de datos y Llamar APIs externas son permisos sensibles: al activarlos
          también quedan habilitados en la seguridad del agente. SQL solo se ofrece si el agente
          tiene fuentes de datos conectadas.
        </p>
      </AgentFieldGroup>

      <AgentFieldGroup
        title="Motor de decisión (JEV)"
        hint="JEV decide la ruta y la herramienta; si lo apagás, decide el LLM del agente."
      >
        <AgentField
          id="agent-jev-mode"
          label="JEV en este agente"
          hint="Heredar usa la configuración del sistema (Control Center)."
        >
          <Select
            id="agent-jev-mode"
            value={jevMode}
            onChange={(e) => setJevMode(e.target.value as "inherit" | "on" | "off")}
          >
            <option value="inherit">Heredar del sistema</option>
            <option value="on">Activado en este agente</option>
            <option value="off">Apagado en este agente</option>
          </Select>
        </AgentField>

        <AgentField
          id="agent-jev-answer-gate"
          label="JEV verifica la respuesta"
          hint="Antes de responder, JEV puntúa el borrador contra la evidencia. Si está flojo, pide una corrección."
        >
          <Select
            id="agent-jev-answer-gate"
            value={answerGate}
            onChange={(e) => setAnswerGate(e.target.value as "inherit" | "on" | "off")}
          >
            <option value="inherit">Heredar del sistema</option>
            <option value="on">Activado en este agente</option>
            <option value="off">Apagado en este agente</option>
          </Select>
        </AgentField>
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
