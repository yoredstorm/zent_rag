import { CaretDown, Code, LockSimple, PushPin, Trash, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { GraphEdge, GraphNode, NodeMeta, WorkflowGraph } from "../lib/workflowGraph";
import { describeEdge, nodeMeta, nodePorts, referenceOptions } from "../lib/workflowGraph";
import type {
  BusinessParameter,
  NodeBusinessSchema,
  ParameterLevel,
  SelectOption,
} from "../lib/businessSchema";
import { LEVEL_LABELS, setByPath } from "../lib/businessSchema";
import {
  buildDataSources,
  dataSourcesFromCatalog,
  type DataCatalogPayload,
  type NodeSamples,
} from "../lib/dataPicker";
import type { ConditionGroupNode } from "../lib/conditionTree";
import { BusinessParameterForm } from "./workflowStudio/BusinessParameterForm";
import { ConditionBuilder } from "./workflowStudio/ConditionBuilder";
import { AiDecisionForm } from "./workflowStudio/AiDecisionForm";
import { DataView } from "./workflowStudio/DataView";
import { NodeHelpCard } from "./workflowStudio/NodeHelpCard";
import { NotificationBuilder } from "./workflowStudio/NotificationBuilder";
import { ScheduleBuilder } from "./workflowStudio/ScheduleBuilder";
import type { RunDetail, RunStep } from "./WorkflowRunInspector";
import {
  Button,
  ButtonLink,
  CodeBlock,
  Field,
  IconButton,
  Input,
  Popover,
  Select,
  StatusBadge,
  Textarea,
  cn,
} from "./ui";

type Props = {
  graph: WorkflowGraph;
  node: GraphNode | null;
  edge: GraphEdge | null;
  onChange: (graph: WorkflowGraph) => void;
  onDeleteNode: (id: string) => void;
  onDeleteEdge: (id: string) => void;
  kbs: { id: string; name: string }[];
  agents: { id: string; name: string }[];
  mxInstalls?: { id: string; integration: { slug: string; name: string } }[];
  mxActions?: Record<string, { action_id: string; display_name: string }[]>;
  /** Schemas de negocio por node_type (GET /workflows/node-schemas). */
  nodeSchemas?: Record<string, NodeBusinessSchema> | null;
  /** Catálogo backend (GET /workflows/node-catalog) con disponibilidad. */
  catalogNodes?: Record<string, NodeMeta> | null;
  /** Catálogo de datos backend (GET /workflows/{id}/data-catalog). */
  dataCatalog?: DataCatalogPayload | null;
  /** Últimos outputs reales por nodo (Live Preview / Data Picker). */
  samples?: NodeSamples | null;
  /** Último run inspeccionado: alimenta INPUT/OUTPUT/RUN. */
  run?: RunDetail | null;
  /** Dato fijado para pruebas en este nodo. */
  pinned?: boolean;
  onPinData?: (nodeId: string, output: Record<string, unknown>) => void;
  onUnpinData?: (nodeId: string) => void;
  /** Ejecución parcial (Fase 3). */
  onRunPartial?: (nodeId: string, mode: "node" | "until_node" | "from_node") => void;
  partialBusy?: string;
  /** Nivel de configuración controlado por el estudio. */
  configLevel?: ParameterLevel;
  onConfigLevelChange?: (level: ParameterLevel) => void;
  /** El estudio lo monta como sheet flotante sobre el lienzo. */
  className?: string;
  onClose?: () => void;
  /** Agregar un nodo sugerido después de este (brief §19). */
  onAddSuggested?: (nodeType: string) => void;
};

const LEVELS: ParameterLevel[] = ["simple", "guided", "advanced"];

const NODE_TABS = [
  { key: "config", label: "Configurar" },
  { key: "input", label: "Input" },
  { key: "output", label: "Output" },
  { key: "run", label: "Run" },
] as const;

/** Claves que el NotificationBuilder edita; el resto las cubre el schema. */
const NOTIFY_BUILDER_KEYS = new Set(["channel", "title", "message"]);

/** Controles segmentados del panel (tabs de nodo y nivel de configuración). */
const SEGMENT_BASE = "min-h-7 flex-1 cursor-pointer rounded-sm px-2 text-[12px] font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-45";

export function NodeConfigPanel({
  graph,
  node,
  edge,
  onChange,
  onDeleteNode,
  onDeleteEdge,
  kbs,
  agents,
  mxInstalls,
  mxActions,
  nodeSchemas,
  catalogNodes,
  dataCatalog,
  samples,
  run,
  pinned = false,
  onPinData,
  onUnpinData,
  onRunPartial,
  partialBusy,
  configLevel,
  onConfigLevelChange,
  className = "w-72 shrink-0",
  onClose,
  onAddSuggested,
}: Props) {
  const { session } = useAuth();
  const [localLevel, setLocalLevel] = useState<ParameterLevel>("simple");
  const [actionPorts, setActionPorts] = useState<BusinessParameter[] | null>(null);
  const [portsError, setPortsError] = useState("");

  const level = configLevel ?? localLevel;
  const n = node;
  const actionId = n?.type === "marketplace_action" ? String(n.config.action_id ?? "") : "";
  const dataSources = useMemo(() => {
    const fromCatalog = dataSourcesFromCatalog(dataCatalog, n?.id ?? null);
    if (fromCatalog.length > 0) return fromCatalog;
    return buildDataSources(graph, nodeSchemas ?? null, samples ?? null, n?.id ?? null);
  }, [dataCatalog, graph, nodeSchemas, samples, n?.id]);
  const [tab, setTab] = useState<"config" | "input" | "output" | "run">("config");
  const runStep = useMemo<RunStep | null>(
    () => (node ? (run?.steps ?? []).find((s) => s.node_id === node.id) ?? null : null),
    [run, node],
  );

  // Formulario de la acción del marketplace según su input_schema (misión §17).
  useEffect(() => {
    if (!session || !actionId || !n || n.type !== "marketplace_action") {
      setActionPorts(null);
      setPortsError("");
      return;
    }
    let alive = true;
    api<{ input_parameters?: BusinessParameter[] }>(
      `/api/v1/workflows/marketplace/ports/${encodeURIComponent(actionId)}`,
      { token: session.token, organizationId: session.organizationId },
    )
      .then((d) => {
        if (alive) setActionPorts(d.input_parameters ?? []);
      })
      .catch((e) => {
        if (alive) {
          setActionPorts([]);
          setPortsError(e instanceof Error ? e.message : "No pude cargar los parámetros de la acción");
        }
      });
    return () => {
      alive = false;
    };
  }, [session, actionId, n]);

  const business = n && nodeSchemas ? nodeSchemas[n.type] ?? null : null;
  const refs = useMemo(() => (n && graph ? referenceOptions(graph, n.id) : []), [graph, n]);
  const referenceSelectOptions: SelectOption[] = refs.map((r) => ({ value: r.ref, label: r.label }));

  if (!node && !edge) return null;

  if (edge && !node) {
    return (
      <aside className={cn("panel p-3", className)} data-testid="wf-edge-config">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-h3">Conexión</h3>
            <p className="mt-1 font-mono text-[11px] break-all text-muted">
              {edge.from_node}.{edge.from_port} → {edge.to_node}.{edge.to_port}
            </p>
          </div>
          {onClose && <IconButton label="Cerrar configuración" icon={X} className="-mt-1 -mr-1 h-8 w-8" onClick={onClose} />}
        </div>
        <p className="mt-2 rounded-sm bg-soft px-2 py-1.5 text-[12px] text-muted" data-testid="wf-edge-meaning">
          {describeEdge(graph, edge)}
        </p>
        <Button
          variant="ghost"
          size="sm"
          leadingIcon={Trash}
          className="mt-3 w-full text-danger"
          onClick={() => onDeleteEdge(edge.id)}
        >
          Eliminar conexión
        </Button>
      </aside>
    );
  }

  const current = node!;
  const meta = catalogNodes?.[current.type] ?? nodeMeta(current.type);
  const ports = nodePorts(current.type);

  function patchConfig(patch: Record<string, unknown>) {
    onChange({
      ...graph,
      nodes: graph.nodes.map((x) => (x.id === current.id ? { ...x, config: { ...x.config, ...patch } } : x)),
    });
  }
  function setField(key: string, value: unknown) {
    if (key === "agent_id") {
      const picked = agents.find((a) => a.id === String(value));
      patchConfig({ agent_id: value, agent_name: picked?.name ?? "" });
      return;
    }
    patchConfig({ [key]: value });
  }
  function setConfigPath(path: string, value: unknown) {
    onChange({
      ...graph,
      nodes: graph.nodes.map((x) => (x.id === current.id ? { ...x, config: setByPath(x.config, path, value) } : x)),
    });
  }
  function replaceConfig(next: Record<string, unknown>) {
    onChange({
      ...graph,
      nodes: graph.nodes.map((x) => (x.id === current.id ? { ...x, config: next } : x)),
    });
  }
  function setPolicy(key: "retry_policy" | "timeout_ms" | "error_policy", value: unknown) {
    onChange({
      ...graph,
      nodes: graph.nodes.map((x) =>
        x.id === current.id
          ? key === "retry_policy"
            ? { ...x, retry_policy: { ...x.retry_policy, ...(value as Record<string, unknown>) } }
            : { ...x, [key]: value }
          : x,
      ),
    });
  }

  function insertRef(field: string, ref: string) {
    const cur = String(current.config[field] ?? "");
    setField(field, cur ? `${cur} ${ref}` : ref);
  }

  const dynamicOptions = (param: BusinessParameter): SelectOption[] | undefined => {
    switch (param.dynamic_options) {
      case "agents":
        return agents.map((a) => ({ value: a.id, label: a.name }));
      case "knowledge_bases":
        return kbs.map((k) => ({ value: k.id, label: k.name }));
      case "installed_integrations":
        return (mxInstalls ?? []).map((i) => ({ value: i.id, label: i.integration?.name ?? i.id }));
      case "actions": {
        const installId = String(current.config.install_id ?? "");
        return (mxActions?.[installId] ?? []).map((a) => ({ value: a.action_id, label: a.display_name }));
      }
      case "event_types":
        return EVENT_TYPE_OPTIONS;
      default:
        return undefined;
    }
  };

  const needsAgent = current.type === "llm" && !current.config.agent_id;
  const showPolicies = level === "advanced";
  const legacyFields = meta.fields.filter((f) => (f.adv ? showPolicies : true));
  const hasAdvancedOptions = meta.fields.some((f) => f.adv);

  function chooseLevel(next: ParameterLevel) {
    setLocalLevel(next);
    onConfigLevelChange?.(next);
  }

  return (
    <aside className={cn("panel flex flex-col overflow-hidden", className)} data-testid="wf-node-config">
      <header className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2.5">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-border-soft bg-soft text-[13px] text-muted"
          aria-hidden
        >
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[13px] font-semibold text-text">{business?.label || meta.label}</h3>
          <p className="truncate font-mono text-[10px] text-faint">{current.type} · v{current.version}</p>
        </div>
        {current.type !== "end" && !current.type.startsWith("trigger_") && (
          <IconButton
            label="Eliminar nodo"
            icon={Trash}
            className="h-8 w-8 shrink-0 text-danger"
            onClick={() => onDeleteNode(current.id)}
          />
        )}
        {onClose && (
          <IconButton
            label="Cerrar configuración"
            icon={X}
            className="-mr-1 h-8 w-8 shrink-0"
            onClick={onClose}
          />
        )}
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {/* Pestañas del nodo: configurar / input / output / run (Fase 1). */}
        <div
          className="flex items-center gap-0.5 rounded-md border border-border bg-soft p-0.5"
          role="tablist"
          aria-label="Vista del nodo"
          data-testid="wf-node-tabs"
        >
          {NODE_TABS.map((nodeTab) => (
            <button
              key={nodeTab.key}
              type="button"
              role="tab"
              aria-selected={tab === nodeTab.key}
              className={cn(
                SEGMENT_BASE,
                tab === nodeTab.key ? "bg-surface text-text shadow-panel" : "text-muted hover:text-text",
              )}
              data-testid={`wf-tab-${nodeTab.key}`}
              onClick={() => setTab(nodeTab.key)}
            >
              {nodeTab.label}
            </button>
          ))}
        </div>

        {tab === "config" && (
          <>
            <NodeHelpCard meta={meta} onAddSuggested={onAddSuggested} />

            {/* Nivel de configuración: mismo grafo, distinta vista. */}
            <div
              className="flex items-center gap-0.5 rounded-md border border-border p-0.5"
              role="tablist"
              aria-label="Nivel de configuración"
              data-testid="wf-level-toggle"
            >
              {LEVELS.map((l) => (
                <button
                  key={l}
                  type="button"
                  role="tab"
                  aria-selected={level === l}
                  className={cn(
                    SEGMENT_BASE,
                    level === l ? "bg-accent-soft text-accent" : "text-faint hover:text-text",
                  )}
                  data-testid={`wf-level-${l}`}
                  onClick={() => chooseLevel(l)}
                >
                  {LEVEL_LABELS[l]}
                </button>
              ))}
            </div>

            {business?.description && level !== "advanced" && (
              <p className="text-[12px] leading-relaxed text-muted">{business.description}</p>
            )}

            {needsAgent && (
              <div
                className="rounded-md border border-warn/40 bg-warn-soft px-2.5 py-2 text-[12px] leading-relaxed text-text"
                data-testid="wf-agent-required"
              >
                {agents.length === 0 ? (
                  <>
                    No tienes agentes todavía. Crea uno y vuelve: sin agente este nodo solo devuelve
                    un eco del prompt.
                    <ButtonLink
                      to="/agents/new"
                      variant="secondary"
                      size="sm"
                      className="mt-2 w-full"
                      data-testid="wf-agent-cta"
                    >
                      Crear un agente
                    </ButtonLink>
                  </>
                ) : (
                  "Elige el agente que va a responder. Sin agente el nodo devuelve un eco, no una respuesta."
                )}
              </div>
            )}

            {business ? (
              current.type === "condition" ? (
                <ConditionBuilder
                  config={current.config}
                  sources={dataSources}
                  onChange={(tree: ConditionGroupNode) => {
                    const next = { ...current.config };
                    delete next.field;
                    delete next.operator;
                    delete next.value;
                    next.rules = tree;
                    replaceConfig(next);
                  }}
                />
              ) : current.type === "ai_decision" ? (
                <AiDecisionForm config={current.config} onChange={patchConfig} />
              ) : current.type === "notify" ? (
                <>
                  <NotificationBuilder
                    config={current.config}
                    dataSources={dataSources}
                    onChange={patchConfig}
                  />
                  {business.parameters.some((p) => !NOTIFY_BUILDER_KEYS.has(p.key)) && (
                    <div className="border-t border-border pt-3">
                      <BusinessParameterForm
                        parameters={business.parameters.filter((p) => !NOTIFY_BUILDER_KEYS.has(p.key))}
                        level={level}
                        values={current.config}
                        onChange={(key, value) => setField(key, value)}
                        optionsFor={dynamicOptions}
                        referenceOptions={referenceSelectOptions}
                        dataSources={dataSources}
                      />
                    </div>
                  )}
                </>
              ) : current.type === "trigger_schedule" ? (
                <ScheduleBuilder config={current.config} onChange={patchConfig} />
              ) : (
                <>
                  <BusinessParameterForm
                    parameters={business.parameters}
                    level={level}
                    values={current.config}
                    onChange={(key, value) => setField(key, value)}
                    optionsFor={dynamicOptions}
                    referenceOptions={referenceSelectOptions}
                    dataSources={dataSources}
                  />
                  {current.type === "marketplace_action" && actionId && (
                    <div className="space-y-2.5 rounded-md border border-border bg-soft/50 p-3" data-testid="wf-action-params">
                      <p className="eyebrow">Parámetros de la acción</p>
                      {portsError ? (
                        <p className="field-error">{portsError}</p>
                      ) : actionPorts === null ? (
                        <p className="text-[12px] text-faint">Cargando parámetros…</p>
                      ) : (
                        <BusinessParameterForm
                          parameters={actionPorts}
                          level={level}
                          values={(current.config.inputs as Record<string, unknown>) ?? {}}
                          onChange={(key, value) => setConfigPath(`inputs.${key}`, value)}
                          optionsFor={dynamicOptions}
                          referenceOptions={referenceSelectOptions}
                          dataSources={dataSources}
                          emptyHint="Esta acción no declara parámetros."
                        />
                      )}
                    </div>
                  )}
                </>
              )
            ) : (
              legacyFields.map((f) => {
                const id = `${current.id}-${f.key}`;
                const value = current.config[f.key];
                const invalid = f.key === "agent_id" && !value;
                return (
                  <div key={f.key} className="space-y-1.5">
                    <div className="flex items-center gap-1.5">
                      <label htmlFor={id} className="text-[13px] font-medium text-text">
                        {f.label}
                      </label>
                      {invalid && (
                        <span className="text-danger" aria-hidden>
                          *
                        </span>
                      )}
                      {f.refs && refs.length > 0 && (
                        <span className="ml-auto">
                          <Popover
                            width={264}
                            trigger={
                              <Button
                                variant="ghost"
                                size="sm"
                                leadingIcon={Code}
                                className="px-1.5 text-[11px]"
                                aria-label={`Insertar dato en ${f.label}`}
                              >
                                Dato
                              </Button>
                            }
                          >
                            <div className="max-h-56 space-y-0.5 overflow-y-auto">
                              {refs.map((r) => (
                                <button
                                  key={r.ref}
                                  type="button"
                                  className="block w-full truncate rounded-sm px-2 py-1.5 text-left text-[12px] text-text transition-colors duration-150 hover:bg-soft"
                                  onClick={() => insertRef(f.key, r.ref)}
                                >
                                  <span className="block truncate font-medium">{r.label}</span>
                                  <span className="block truncate font-mono text-[10px] text-faint">{r.ref}</span>
                                </button>
                              ))}
                            </div>
                          </Popover>
                        </span>
                      )}
                    </div>
                    {f.type === "textarea" ? (
                      <Textarea
                        id={id}
                        rows={3}
                        placeholder={f.placeholder}
                        value={String(value ?? "")}
                        onChange={(e) => setField(f.key, e.target.value)}
                      />
                    ) : f.type === "json" ? (
                      <Textarea
                        id={id}
                        rows={2}
                        className="font-mono text-[12px]"
                        placeholder={f.placeholder ?? "{}"}
                        value={typeof value === "object" ? JSON.stringify(value ?? {}, null, 0) : String(value ?? "")}
                        onChange={(e) => {
                          try {
                            setField(f.key, JSON.parse(e.target.value || "{}"));
                          } catch {
                            setField(f.key, e.target.value);
                          }
                        }}
                      />
                    ) : f.type === "select" ? (
                      <Select
                        id={id}
                        value={String(value ?? "")}
                        aria-invalid={invalid || undefined}
                        data-testid={f.key === "agent_id" ? "wf-agent-select" : undefined}
                        onChange={(e) => setField(f.key, e.target.value)}
                      >
                        <option value="">{f.key === "agent_id" ? "Elige un agente…" : "—"}</option>
                        {selectOptions(f.key, current, kbs, agents, mxInstalls, mxActions).map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Input
                        id={id}
                        type={f.type === "number" ? "number" : "text"}
                        placeholder={f.placeholder}
                        value={String(value ?? "")}
                        onChange={(e) =>
                          setField(
                            f.key,
                            f.type === "number"
                              ? e.target.value === ""
                                ? ""
                                : Number(e.target.value)
                              : e.target.value,
                          )
                        }
                      />
                    )}
                    {invalid && (
                      <p className="field-hint text-warn">
                        Elige un agente activo o crea uno: sin agente la respuesta es un eco.
                      </p>
                    )}
                  </div>
                );
              })
            )}

            {!business && hasAdvancedOptions && !showPolicies && (
              <p className="text-[12px] text-faint">Cambia a Avanzado para ver más opciones.</p>
            )}

            {/* Avanzado (Fase 6): potencia disponible, complejidad progresiva. */}
            <details className="group rounded-md border border-border" data-testid="wf-advanced">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 px-2.5 py-2 text-[12px] font-medium text-muted transition-colors duration-150 hover:text-text">
                <CaretDown
                  size={11}
                  className="transition-transform duration-150 group-open:rotate-180"
                  aria-hidden
                />
                Avanzado · ejecución, errores y developer
              </summary>
              <div className="space-y-3 border-t border-border p-2.5">
                <div>
                  <p className="eyebrow">Contrato</p>
                  <div className="mt-1.5 rounded-sm border border-border px-2 py-1.5 font-mono text-[11px] text-muted">
                    {ports.input.length > 0 && <p>in: {ports.input.map((p) => `${p.name}:${p.type}`).join(", ")}</p>}
                    {ports.output.length > 0 && <p>out: {ports.output.map((p) => `${p.name}:${p.type}`).join(", ")}</p>}
                    <p>riesgo: {meta.risk ?? "normal"}</p>
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="eyebrow">Ejecución y errores</p>
                  <Field label="Reintentos">
                    <Input
                      type="number"
                      min={1}
                      max={10}
                      className="max-w-24"
                      value={String((current.retry_policy.max_attempts as number) ?? 1)}
                      onChange={(e) =>
                        setPolicy("retry_policy", { max_attempts: Math.max(1, Number(e.target.value || 1)) })
                      }
                    />
                  </Field>
                  <Field label="Timeout (ms)">
                    <Input
                      type="number"
                      min={100}
                      className="max-w-32"
                      value={String(current.timeout_ms ?? 60_000)}
                      onChange={(e) => setPolicy("timeout_ms", Math.max(100, Number(e.target.value || 60_000)))}
                    />
                  </Field>
                  <Field label="Si falla">
                    <Select
                      value={current.error_policy}
                      onChange={(e) => setPolicy("error_policy", e.target.value)}
                    >
                      <option value="fail">detener flujo</option>
                      <option value="continue">continuar</option>
                      <option value="stop">detener (stop)</option>
                    </Select>
                  </Field>
                </div>

                <div className="space-y-1.5">
                  <p className="eyebrow">Developer</p>
                  <CodeBlock code={JSON.stringify(current.config, null, 2)} language="json" maxHeight={220} />
                </div>
                {business && (
                  <p className="flex items-center gap-1.5 text-[11px] text-faint">
                    <LockSimple size={11} aria-hidden /> Los secretos se guardan en SecretStore, nunca en el grafo.
                  </p>
                )}
              </div>
            </details>
          </>
        )}

        {tab === "input" && (
          <div className="space-y-2" data-testid="wf-node-input">
            <p className="text-[12px] text-muted">Datos con los que corrió este paso en el run seleccionado.</p>
            <DataView
              data={runStep?.input ?? null}
              testId="wf-input-view"
              emptyHint="Sin run reciente para este nodo: ejecuta una prueba."
            />
          </div>
        )}

        {tab === "output" && (
          <div className="space-y-3" data-testid="wf-node-output">
            {pinned && (
              <p
                className="flex items-center gap-1.5 rounded-md border border-warn/40 bg-warn-soft px-2.5 py-2 text-[11px] text-text"
                data-testid="wf-pinned-badge"
              >
                <PushPin size={12} aria-hidden /> Datos fijados para pruebas (no aplican en producción)
              </p>
            )}
            <DataView
              data={runStep?.output ?? null}
              testId="wf-output-view"
              emptyHint="Sin salida registrada todavía."
            />
            {(() => {
              const planned = (run?.planned_effects ?? []).filter((effect) => effect.node_id === current.id);
              if (planned.length === 0) return null;
              return (
                <div className="rounded-md border border-border bg-soft/50 px-2.5 py-2">
                  <p className="text-[11px] font-semibold text-muted">Efectos planeados (simulación)</p>
                  <DataView data={planned.map((effect) => effect.planned)} testId="wf-output-planned" />
                </div>
              );
            })()}
            <div className="flex flex-wrap gap-1.5">
              {onPinData && runStep?.output && !pinned && (
                <Button
                  variant="secondary"
                  size="sm"
                  leadingIcon={PushPin}
                  className="text-[11px]"
                  data-testid="wf-pin-data"
                  onClick={() => onPinData(current.id, runStep.output ?? {})}
                >
                  Fijar datos para pruebas
                </Button>
              )}
              {pinned && onUnpinData && (
                <Button
                  variant="ghost"
                  size="sm"
                  leadingIcon={Trash}
                  className="text-[11px] text-danger"
                  data-testid="wf-unpin-data"
                  onClick={() => onUnpinData(current.id)}
                >
                  Quitar datos fijados
                </Button>
              )}
            </div>
          </div>
        )}

        {tab === "run" && (
          <div className="space-y-3" data-testid="wf-node-run">
            {runStep ? (
              <>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[12px]">
                  <div>
                    <dt className="eyebrow">Estado</dt>
                    <dd className="mt-0.5 text-text">{runStep.status}</dd>
                  </div>
                  <div>
                    <dt className="eyebrow">Duración</dt>
                    <dd className="mt-0.5 text-text tabular-nums">
                      {runStep.duration_ms != null ? `${runStep.duration_ms} ms` : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="eyebrow">Intentos</dt>
                    <dd className="mt-0.5 text-text tabular-nums">{runStep.attempt ?? 1}</dd>
                  </div>
                  <div>
                    <dt className="eyebrow">Reintentos</dt>
                    <dd className="mt-0.5 text-text tabular-nums">{runStep.retries ?? 0}</dd>
                  </div>
                  {typeof runStep.output?.cost === "number" && runStep.output.cost > 0 && (
                    <div>
                      <dt className="eyebrow">Costo</dt>
                      <dd className="mt-0.5 text-text tabular-nums">S/ {Number(runStep.output.cost).toFixed(4)}</dd>
                    </div>
                  )}
                  {typeof runStep.output?.model === "string" && (
                    <div className="col-span-2">
                      <dt className="eyebrow">Modelo</dt>
                      <dd className="mt-0.5 truncate text-text">{String(runStep.output.model)}</dd>
                    </div>
                  )}
                </dl>
                {runStep.error && (
                  <p className="rounded-md border border-danger/40 bg-danger-soft px-2.5 py-2 text-[12px] leading-relaxed text-danger">
                    {runStep.error}
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-faint">
                  <span className="font-mono">Run {run?.id}</span>
                  {run?.status && <StatusBadge status={run.status} />}
                  {run?.duration_ms != null && <span className="tabular-nums">{run.duration_ms} ms</span>}
                </div>
              </>
            ) : (
              <p className="text-[12px] text-faint" data-testid="wf-node-run-empty">
                Este nodo no participó en el último run (o fue saltado).
              </p>
            )}
            {onRunPartial && !current.type.startsWith("trigger_") && current.type !== "end" && (
              <div className="space-y-2 border-t border-border pt-3">
                <p className="eyebrow">Ejecución parcial (pruebas)</p>
                <div className="flex flex-wrap gap-1.5">
                  <Button
                    variant="secondary"
                    size="sm"
                    className="text-[11px]"
                    disabled={!!partialBusy}
                    data-testid="wf-run-node"
                    onClick={() => onRunPartial(current.id, "node")}
                  >
                    Ejecutar este nodo
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="text-[11px]"
                    disabled={!!partialBusy}
                    data-testid="wf-run-until"
                    onClick={() => onRunPartial(current.id, "until_node")}
                  >
                    Ejecutar hasta aquí
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="text-[11px]"
                    disabled={!!partialBusy}
                    data-testid="wf-run-from"
                    onClick={() => onRunPartial(current.id, "from_node")}
                  >
                    Ejecutar desde aquí
                  </Button>
                </div>
                <p className="text-[11px] leading-relaxed text-faint">
                  Usa datos del último run o de los datos fijados. Nada se publica ni se activa.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

/** Catálogo de eventos para pickers (espejo de events.STANDARD_EVENTS). */
const EVENT_TYPE_OPTIONS: SelectOption[] = [
  "source.connected", "source.synced", "document.uploaded", "document.processed",
  "entity.created", "entity.updated", "semantic.mapping.approved", "agent.run.completed",
  "invoice.detected", "customer.created", "sales.closed", "workflow.completed",
  "integration.connected",
].map((v) => ({ value: v, label: v }));

function selectOptions(
  key: string,
  current: GraphNode,
  kbs: { id: string; name: string }[],
  agents: { id: string; name: string }[],
  mxInstalls?: { id: string; integration: { slug: string; name: string } }[],
  mxActions?: Record<string, { action_id: string; display_name: string }[]>,
): SelectOption[] {
  if (key === "knowledge_base_id") return kbs.map((k) => ({ value: k.id, label: k.name }));
  if (key === "agent_id") return agents.map((a) => ({ value: a.id, label: a.name }));
  if (key === "install_id") return (mxInstalls ?? []).map((i) => ({ value: i.id, label: i.integration?.name ?? i.id }));
  if (key === "action_id") {
    const installId = String(current.config.install_id ?? "");
    return (mxActions?.[installId] ?? []).map((a) => ({ value: a.action_id, label: a.display_name }));
  }
  return [];
}
