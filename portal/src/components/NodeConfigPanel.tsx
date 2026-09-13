import { CaretDown, Code, LockSimple, Trash, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { GraphEdge, GraphNode, WorkflowGraph } from "../lib/workflowGraph";
import { nodeMeta, nodePorts, referenceOptions } from "../lib/workflowGraph";
import type {
  BusinessParameter,
  NodeBusinessSchema,
  ParameterLevel,
  SelectOption,
} from "../lib/businessSchema";
import { LEVEL_LABELS, setByPath } from "../lib/businessSchema";
import { BusinessParameterForm } from "./workflowStudio/BusinessParameterForm";

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
  /** Nivel de configuración controlado por el estudio. */
  configLevel?: ParameterLevel;
  onConfigLevelChange?: (level: ParameterLevel) => void;
  /** El estudio lo monta como sheet flotante sobre el lienzo. */
  className?: string;
  onClose?: () => void;
};

const LEVELS: ParameterLevel[] = ["simple", "guided", "advanced"];

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
  configLevel,
  onConfigLevelChange,
  className = "w-72 shrink-0",
  onClose,
}: Props) {
  const { session } = useAuth();
  const [localLevel, setLocalLevel] = useState<ParameterLevel>("simple");
  const [refOpen, setRefOpen] = useState<string | null>(null);
  const [actionPorts, setActionPorts] = useState<BusinessParameter[] | null>(null);
  const [portsError, setPortsError] = useState("");

  const level = configLevel ?? localLevel;
  const n = node;
  const actionId = n?.type === "marketplace_action" ? String(n.config.action_id ?? "") : "";

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
      <aside className={`rounded-lg border border-border bg-surface p-3 shadow-panel ${className}`} data-testid="wf-edge-config">
        <div className="flex items-start gap-2">
          <h3 className="flex-1 text-sm font-semibold text-text">Conexión</h3>
          {onClose && (
            <button type="button" className="btn btn-ghost min-h-7 px-1.5" aria-label="Cerrar" onClick={onClose}>
              <X size={14} aria-hidden />
            </button>
          )}
        </div>
        <p className="mt-1 font-mono text-[10px] text-muted">
          {edge.from_node}.{edge.from_port} → {edge.to_node}.{edge.to_port}
        </p>
        <button type="button" className="btn btn-ghost mt-3 min-h-8 w-full text-[11px] text-danger" onClick={() => onDeleteEdge(edge.id)}>
          <Trash size={13} /> Eliminar conexión
        </button>
      </aside>
    );
  }

  const current = node!;
  const meta = nodeMeta(current.type);
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
    setRefOpen(null);
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

  function chooseLevel(next: ParameterLevel) {
    setLocalLevel(next);
    onConfigLevelChange?.(next);
  }

  return (
    <aside className={`flex flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-panel ${className}`} data-testid="wf-node-config">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <span className={`flex h-7 w-7 items-center justify-center rounded-md text-[13px] ${meta.color} bg-opacity-20`} aria-hidden>
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[13px] font-semibold text-text">{business?.label || meta.label}</h3>
          <p className="truncate font-mono text-[9px] text-faint">{current.type} · v{current.version}</p>
        </div>
        {current.type !== "end" && !current.type.startsWith("trigger_") && (
          <button type="button" className="btn btn-ghost min-h-7 px-1.5 text-danger" aria-label="Eliminar nodo" onClick={() => onDeleteNode(current.id)}>
            <Trash size={14} />
          </button>
        )}
        {onClose && (
          <button type="button" className="btn btn-ghost min-h-7 px-1.5" aria-label="Cerrar configuración" onClick={onClose}>
            <X size={14} aria-hidden />
          </button>
        )}
      </div>

      <div className="flex-1 space-y-2.5 overflow-y-auto p-3">
        {/* Nivel de configuración: mismo grafo, distinta vista. */}
        <div className="flex rounded-md border border-border p-0.5" data-testid="wf-level-toggle" role="tablist" aria-label="Nivel de configuración">
          {LEVELS.map((l) => (
            <button
              key={l}
              type="button"
              role="tab"
              aria-selected={level === l}
              className={`flex-1 rounded px-1.5 py-1 text-[10px] ${
                level === l ? "bg-accent/15 font-medium text-text" : "text-faint hover:text-muted"
              }`}
              data-testid={`wf-level-${l}`}
              onClick={() => chooseLevel(l)}
            >
              {LEVEL_LABELS[l]}
            </button>
          ))}
        </div>

        {business?.description && level !== "advanced" && (
          <p className="text-[10px] text-muted">{business.description}</p>
        )}

        {needsAgent && (
          <div className="rounded-md border border-warn/40 bg-warn-soft px-2.5 py-2 text-[10px] text-text" data-testid="wf-agent-required">
            {agents.length === 0 ? (
              <>
                No tienes agentes todavía. Crea uno y vuelve: sin agente este nodo solo devuelve un
                eco del prompt.
                <Link to="/agents/new" className="btn btn-secondary mt-2 min-h-8 w-full text-[10px]" data-testid="wf-agent-cta">
                  Crear un agente
                </Link>
              </>
            ) : (
              "Elige el agente que va a responder. Sin agente el nodo devuelve un eco, no una respuesta."
            )}
          </div>
        )}

        {business ? (
          <>
            <BusinessParameterForm
              parameters={business.parameters}
              level={level}
              values={current.config}
              onChange={(key, value) => setField(key, value)}
              optionsFor={dynamicOptions}
              referenceOptions={referenceSelectOptions}
            />
            {current.type === "marketplace_action" && actionId && (
              <div className="space-y-2 rounded-md border border-border bg-soft/40 p-2" data-testid="wf-action-params">
                <p className="text-[10px] font-medium text-text">Parámetros de la acción</p>
                {portsError ? (
                  <p className="text-[10px] text-danger">{portsError}</p>
                ) : actionPorts === null ? (
                  <p className="text-[10px] text-faint">Cargando parámetros…</p>
                ) : (
                  <BusinessParameterForm
                    parameters={actionPorts}
                    level={level}
                    values={(current.config.inputs as Record<string, unknown>) ?? {}}
                    onChange={(key, value) => setConfigPath(`inputs.${key}`, value)}
                    optionsFor={dynamicOptions}
                    referenceOptions={referenceSelectOptions}
                    emptyHint="Esta acción no declara parámetros."
                  />
                )}
              </div>
            )}
          </>
        ) : (
          legacyFields.map((f) => {
            const value = current.config[f.key];
            return (
              <label key={f.key} className="block">
                <span className="mb-0.5 flex items-center justify-between gap-1 text-[10px] font-medium text-muted">
                  <span>
                    {f.label}
                    {f.key === "agent_id" && <span className="ml-1 text-danger">*</span>}
                  </span>
                  {f.refs && refs.length > 0 && (
                    <span className="relative">
                      <button type="button" className="btn btn-ghost min-h-5 px-1 text-[9px]" onClick={() => setRefOpen(refOpen === f.key ? null : f.key)} aria-label={`Insertar referencia en ${f.label}`}>
                        <Code size={10} /> datos
                      </button>
                      {refOpen === f.key && (
                        <span className="absolute top-5 right-0 z-30 max-h-48 w-52 overflow-y-auto rounded-md border border-border bg-raised p-1 shadow-pop">
                          {refs.map((r) => (
                            <button
                              key={r.ref}
                              type="button"
                              className="block w-full truncate rounded px-2 py-1 text-left text-[10px] text-text hover:bg-soft"
                              onClick={() => insertRef(f.key, r.ref)}
                            >
                              <span className="block font-medium">{r.label}</span>
                              <span className="block font-mono text-[8px] text-faint">{r.ref}</span>
                            </button>
                          ))}
                        </span>
                      )}
                    </span>
                  )}
                </span>
                {f.type === "textarea" ? (
                  <textarea
                    className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
                    rows={3}
                    placeholder={f.placeholder}
                    value={String(value ?? "")}
                    onChange={(e) => setField(f.key, e.target.value)}
                  />
                ) : f.type === "json" ? (
                  <textarea
                    className="w-full rounded-md border border-border bg-soft px-2 py-1.5 font-mono text-[10px]"
                    rows={2}
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
                  <select
                    className={`w-full rounded-md border bg-soft px-2 py-2 text-[11px] ${
                      f.key === "agent_id" && !value ? "border-warn/60" : "border-border"
                    }`}
                    value={String(value ?? "")}
                    data-testid={f.key === "agent_id" ? "wf-agent-select" : undefined}
                    onChange={(e) => setField(f.key, e.target.value)}
                  >
                    <option value="">{f.key === "agent_id" ? "Elige un agente…" : "—"}</option>
                    {selectOptions(f.key, current, kbs, agents, mxInstalls, mxActions).map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="w-full rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
                    type={f.type === "number" ? "number" : "text"}
                    placeholder={f.placeholder}
                    value={String(value ?? "")}
                    onChange={(e) => setField(f.key, f.type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
                  />
                )}
              </label>
            );
          })
        )}

        {!business && meta.fields.some((f) => f.adv) && (
          <p className="text-[10px] text-faint">Cambia a Avanzado para ver más opciones.</p>
        )}

        {/* Puertos y políticas: solo Advanced (misión §25). */}
        {showPolicies && (
          <>
            <div className="rounded-md border border-border p-2 text-[9px] text-faint">
              {ports.input.length > 0 && <p>in: {ports.input.map((p) => `${p.name}:${p.type}`).join(", ")}</p>}
              {ports.output.length > 0 && <p>out: {ports.output.map((p) => `${p.name}:${p.type}`).join(", ")}</p>}
              <p>riesgo: {meta.risk ?? "normal"}</p>
            </div>

            <div className="space-y-1.5">
              <label className="flex items-center justify-between gap-2 text-[10px] text-muted">
                Reintentos (max_attempts)
                <input
                  className="w-16 rounded border border-border bg-soft px-1 py-0.5 text-[10px]"
                  type="number" min={1} max={10}
                  value={String((current.retry_policy.max_attempts as number) ?? 1)}
                  onChange={(e) => setPolicy("retry_policy", { max_attempts: Math.max(1, Number(e.target.value || 1)) })}
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-[10px] text-muted">
                Timeout (ms)
                <input
                  className="w-16 rounded border border-border bg-soft px-1 py-0.5 text-[10px]"
                  type="number" min={100}
                  value={String(current.timeout_ms ?? 60_000)}
                  onChange={(e) => setPolicy("timeout_ms", Math.max(100, Number(e.target.value || 60_000)))}
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-[10px] text-muted">
                Si falla
                <select
                  className="rounded border border-border bg-soft px-1 py-0.5 text-[10px]"
                  value={current.error_policy}
                  onChange={(e) => setPolicy("error_policy", e.target.value)}
                >
                  <option value="fail">detener flujo</option>
                  <option value="continue">continuar</option>
                  <option value="stop">detener (stop)</option>
                </select>
              </label>
            </div>

            <details className="rounded-md border border-border p-2">
              <summary className="flex cursor-pointer list-none items-center gap-1 text-[10px] text-faint">
                <CaretDown size={10} aria-hidden /> Configuración técnica (JSON)
              </summary>
              <pre className="mt-1.5 max-h-40 overflow-auto rounded bg-soft p-1.5 font-mono text-[9px] text-muted">
                {JSON.stringify(current.config, null, 2)}
              </pre>
            </details>
            {business && (
              <p className="flex items-center gap-1 text-[9px] text-faint">
                <LockSimple size={10} aria-hidden /> Los secretos se guardan en SecretStore, nunca en el grafo.
              </p>
            )}
          </>
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
