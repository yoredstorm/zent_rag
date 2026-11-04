import { CaretDown, CaretRight, CheckCircle, Code, LockSimple, PushPin, Trash, Warning, X, XCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { GraphEdge, GraphNode, NodeMeta, WorkflowGraph } from "../lib/workflowGraph";
import { describeEdge, EVENTS_OPTIONS, graphIssues, nodeMeta, nodePorts, referenceOptions } from "../lib/workflowGraph";
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
import { DataQueryForm } from "./workflowStudio/DataQueryForm";
import { IntentRouteForm } from "./workflowStudio/IntentRouteForm";
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
  /** Catálogo backend de eventos (GET /workflows/event-catalog). */
  eventOptions?: SelectOption[] | null;
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
  /** Contrae el panel sin perder la selección. */
  onCollapse?: () => void;
  /** Abre una pestaña concreta (p. ej. "Probar este nodo" desde el lienzo); `key` fuerza el cambio. */
  tabRequest?: { tab: NodeTab; key: number } | null;
  /** Readiness del backend para este nodo. */
  nodeIssue?: { status: string; message: string } | null;
  /** Lleva el lienzo a otro nodo (conexiones de Entradas/Salidas). */
  onFocusNode?: (id: string) => void;
};

const LEVELS: ParameterLevel[] = ["simple", "guided", "advanced"];

export type NodeTab = "config" | "input" | "output" | "run" | "validation";

const NODE_TABS: { key: NodeTab; label: string }[] = [
  { key: "config", label: "Parámetros" },
  { key: "input", label: "Entradas" },
  { key: "output", label: "Salidas" },
  { key: "run", label: "Ejecución" },
  { key: "validation", label: "Validación" },
];

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
  eventOptions,
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
  onCollapse,
  tabRequest,
  nodeIssue,
  onFocusNode,
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
  const [tab, setTab] = useState<NodeTab>("config");
  const runStep = useMemo<RunStep | null>(
    () => (node ? (run?.steps ?? []).find((s) => s.node_id === node.id) ?? null : null),
    [run, node],
  );
  const validation = useMemo(() => {
    if (!node) return [];
    const out: { tone: "error" | "warning"; message: string }[] = [];
    for (const issue of graphIssues(graph)) if (issue.node_id === node.id) out.push({ tone: "warning", message: issue.message });
    if (nodeIssue && nodeIssue.status !== "ok") out.push({ tone: nodeIssue.status === "error" ? "error" : "warning", message: nodeIssue.message });
    if (runStep?.error) out.push({ tone: "error", message: `Último run: ${runStep.error}` });
    // graphIssues ya marca los nodos inalcanzables salvo `end`.
    if (node.type === "end" && !graph.edges.some((e) => e.to_node === node.id)) {
      out.push({ tone: "warning", message: "Nada llega a este nodo: conecta una salida a su entrada." });
    }
    return out;
  }, [graph, node, nodeIssue, runStep]);

  useEffect(() => {
    if (tabRequest) setTab(tabRequest.tab);
  }, [tabRequest]);

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
  const note = typeof current.metadata?.note === "string" ? current.metadata.note : "";

  function patchConfig(patch: Record<string, unknown>) {
    onChange({
      ...graph,
      nodes: graph.nodes.map((x) => (x.id === current.id ? { ...x, config: { ...x.config, ...patch } } : x)),
    });
  }
  function setLabel(label: string) {
    onChange({
      ...graph,
      nodes: graph.nodes.map((x) => (x.id === current.id ? { ...x, label } : x)),
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
        return eventOptions?.length ? eventOptions : EVENTS_OPTIONS;
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
          <h3 className="truncate text-[14px] font-semibold text-text">{current.label || business?.label || meta.label}</h3>
          <p className="truncate text-[11px] text-faint">
            {business?.label || meta.label} · <span className="font-mono">{current.type}</span> ·{" "}
            <span className="font-mono">{current.id}</span>
          </p>
        </div>
        {current.type !== "end" && !current.type.startsWith("trigger_") && (
          <IconButton
            label="Eliminar nodo"
            icon={Trash}
            className="h-8 w-8 shrink-0 text-danger"
            onClick={() => onDeleteNode(current.id)}
          />
        )}
        {onCollapse && (
          <IconButton
            label="Contraer panel"
            icon={CaretRight}
            className="h-8 w-8 shrink-0"
            onClick={onCollapse}
            data-testid="wf-inspector-collapse"
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

      {/* Pestañas fijas: parámetros / entradas / salidas / ejecución / validación. */}
      <div
        className="flex shrink-0 items-center gap-0.5 overflow-x-auto border-b border-border px-2 py-1.5"
        role="tablist"
        aria-label="Vista del nodo"
        data-testid="wf-node-tabs"
        onKeyDown={(ev) => {
          if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
          const index = NODE_TABS.findIndex((t) => t.key === tab);
          const next = NODE_TABS[(index + (ev.key === "ArrowRight" ? 1 : NODE_TABS.length - 1)) % NODE_TABS.length];
          setTab(next.key);
          (ev.currentTarget.querySelector(`[data-testid="wf-tab-${next.key}"]`) as HTMLElement | null)?.focus();
        }}
      >
        {NODE_TABS.map((nodeTab) => (
          <button
            key={nodeTab.key}
            type="button"
            role="tab"
            aria-selected={tab === nodeTab.key}
            tabIndex={tab === nodeTab.key ? 0 : -1}
            className={cn(
              SEGMENT_BASE,
              "flex-none whitespace-nowrap",
              tab === nodeTab.key ? "bg-soft text-text" : "text-muted hover:text-text",
            )}
            data-testid={`wf-tab-${nodeTab.key}`}
            onClick={() => setTab(nodeTab.key)}
          >
            {nodeTab.label}
            {nodeTab.key === "validation" && validation.length > 0 && (
              <span
                className={cn(
                  "ml-1 inline-flex min-w-4 justify-center rounded-full px-1 text-[10px] tabular-nums",
                  validation.some((v) => v.tone === "error") ? "bg-danger-soft text-danger" : "bg-warn-soft text-warn",
                )}
              >
                {validation.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">

        {tab === "config" && (
          <>
            {note && (
              <p
                className="rounded-md border border-border-soft bg-soft/50 px-2.5 py-2 text-[12px] leading-relaxed text-muted"
                data-testid="wf-node-note"
              >
                {note}
              </p>
            )}
            <NodeHelpCard meta={meta} onAddSuggested={onAddSuggested} />

            <Field
              label="Nombre del paso"
              hint="Solo cambia la etiqueta visible. El tipo técnico no cambia."
            >
              <Input
                value={current.label}
                placeholder={meta.label}
                onChange={(event) => setLabel(event.target.value)}
              />
            </Field>

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
              ) : current.type === "data_query" ? (
                <DataQueryForm
                  config={current.config}
                  onChange={patchConfig}
                  level={level}
                  dataSources={dataSources}
                />
              ) : current.type === "intent_route" ? (
                <IntentRouteForm config={current.config} onChange={patchConfig} level={level} />
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
                        {selectOptions(f.key, current, kbs, agents, mxInstalls, mxActions, eventOptions).map((o) => (
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
            <PortConnections graph={graph} node={current} side="in" onFocusNode={onFocusNode} />
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
            <PortConnections graph={graph} node={current} side="out" onFocusNode={onFocusNode} />
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

        {tab === "validation" && (
          <div className="space-y-2" data-testid="wf-node-validation">
            {validation.length === 0 ? (
              <p className="flex items-center gap-1.5 text-[12px] text-ok" data-testid="wf-node-valid">
                <CheckCircle size={14} weight="fill" aria-hidden /> Sin problemas detectados en este nodo.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {validation.map((item, i) => (
                  <li
                    key={i}
                    className={cn(
                      "flex items-start gap-2 rounded-md border px-2.5 py-2 text-[12px] leading-relaxed",
                      item.tone === "error" ? "border-danger/40 bg-danger-soft text-danger" : "border-warn/40 bg-warn-soft text-text",
                    )}
                  >
                    {item.tone === "error" ? (
                      <XCircle size={14} weight="fill" className="mt-0.5 shrink-0" aria-hidden />
                    ) : (
                      <Warning size={14} weight="fill" className="mt-0.5 shrink-0 text-warn" aria-hidden />
                    )}
                    <span>{item.message}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[11px] leading-relaxed text-faint">
              La validación definitiva la hace el servidor al publicar; aquí ves lo que ya se sabe del borrador.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}

/** Puertos del nodo y a qué nodos están conectados (navegable). */
function PortConnections({
  graph,
  node,
  side,
  onFocusNode,
}: {
  graph: WorkflowGraph;
  node: GraphNode;
  side: "in" | "out";
  onFocusNode?: (id: string) => void;
}) {
  const ports = side === "in" ? node.input_ports : node.output_ports;
  if (ports.length === 0) {
    return <p className="text-[12px] text-faint">{side === "in" ? "Este nodo inicia el flujo: no tiene entradas." : "Este nodo termina el flujo: no tiene salidas."}</p>;
  }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  return (
    <div className="rounded-md border border-border" data-testid={`wf-ports-${side}`}>
      <p className="border-b border-border px-2.5 py-1.5 text-[11px] font-semibold text-muted">
        {side === "in" ? "Puertos de entrada" : "Puertos de salida"}
      </p>
      <ul className="divide-y divide-border-soft">
        {ports.map((port) => {
          const links = graph.edges.filter((e) =>
            side === "in" ? e.to_node === node.id && e.to_port === port.name : e.from_node === node.id && e.from_port === port.name,
          );
          return (
            <li key={port.name} className="px-2.5 py-1.5">
              <p className="flex items-center gap-1.5 text-[12px] text-text">
                <span className="font-mono">{port.name}</span>
                <span className="text-[11px] text-faint">{port.type}</span>
              </p>
              {links.length === 0 ? (
                <p className="text-[11px] text-faint">Sin conexión</p>
              ) : (
                <ul className="mt-0.5 flex flex-wrap gap-1">
                  {links.map((e) => {
                    const otherId = side === "in" ? e.from_node : e.to_node;
                    const other = byId.get(otherId);
                    const label = other ? other.label || nodeMeta(other.type).label : otherId;
                    return (
                      <li key={e.id}>
                        <button
                          type="button"
                          disabled={!onFocusNode}
                          className="min-h-6 cursor-pointer rounded-sm border border-border px-1.5 text-[11px] text-muted hover:border-accent/50 hover:text-text disabled:cursor-default"
                          onClick={() => onFocusNode?.(otherId)}
                        >
                          {side === "in" ? "desde " : "hacia "}
                          {label}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function selectOptions(
  key: string,
  current: GraphNode,
  kbs: { id: string; name: string }[],
  agents: { id: string; name: string }[],
  mxInstalls?: { id: string; integration: { slug: string; name: string } }[],
  mxActions?: Record<string, { action_id: string; display_name: string }[]>,
  eventOptions?: SelectOption[] | null,
): SelectOption[] {
  if (key === "knowledge_base_id") return kbs.map((k) => ({ value: k.id, label: k.name }));
  if (key === "agent_id") return agents.map((a) => ({ value: a.id, label: a.name }));
  if (key === "install_id") return (mxInstalls ?? []).map((i) => ({ value: i.id, label: i.integration?.name ?? i.id }));
  if (key === "action_id") {
    const installId = String(current.config.install_id ?? "");
    return (mxActions?.[installId] ?? []).map((a) => ({ value: a.action_id, label: a.display_name }));
  }
  if (key === "event_type") return eventOptions?.length ? eventOptions : EVENTS_OPTIONS;
  return [];
}
