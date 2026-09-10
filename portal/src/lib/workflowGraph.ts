/** IR del Workflow Graph en el portal — espejo del backend
 *  (src/platform/workflows/ir.py). Los nodos se muestran en el canvas con
 *  metadatos locales (NODE_LIBRARY) y se persisten tal cual (v2+).
 */

export type PortDef = { name: string; type: string };

export type GraphNode = {
  id: string;
  type: string;
  version: number;
  label: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
  input_ports: PortDef[];
  output_ports: PortDef[];
  retry_policy: Record<string, unknown>;
  timeout_ms: number;
  error_policy: "fail" | "continue" | "stop";
  metadata: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  from_node: string;
  from_port: string;
  to_node: string;
  to_port: string;
  condition?: Record<string, unknown> | null;
};

export type WorkflowGraph = {
  workflow_version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  variables: Record<string, unknown>;
  entrypoints: string[];
  metadata: Record<string, unknown>;
};

let _seq = 0;
export function newGraphNodeId(): string {
  _seq += 1;
  return `n${Date.now().toString(36)}_${_seq}`;
}

export function newEdgeId(): string {
  return `e${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6)}`;
}

// ---------------------------------------------------------------------------
// Catálogo visual de nodos (portal-side registry; espejo del backend)
// ---------------------------------------------------------------------------
export type NodeCategory = "trigger" | "data" | "ai" | "integration" | "logic" | "business" | "control" | "output";

export type FieldDef = {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "textarea" | "json";
  placeholder?: string;
  options?: { value: string; label: string }[];
  default?: string | number;
  refs?: boolean; // permite data picker de referencias
  adv?: boolean; // advanced mode
};

export type NodeMeta = {
  type: string;
  category: NodeCategory;
  label: string;
  icon: string; // emoji simple, sustituible por iconos reales
  color: string; // clase tailwind del header
  ports?: { input?: (PortDef | string)[]; output?: (PortDef | string)[] };
  fields: FieldDef[];
  defaults?: Record<string, unknown>;
  summary?: (config: Record<string, unknown>) => string;
  risk?: "info" | "normal" | "elevated" | "critical";
};

export const CATEGORY_META: Record<NodeCategory, { label: string; color: string }> = {
  trigger: { label: "Triggers", color: "text-info" },
  data: { label: "My Data", color: "text-accent" },
  ai: { label: "AI & Agents", color: "text-purple-400" },
  integration: { label: "Integraciones", color: "text-fuchsia-400" },
  logic: { label: "Business Logic", color: "text-warn" },
  business: { label: "Business", color: "text-emerald-400" },
  control: { label: "Control", color: "text-danger" },
  output: { label: "Output", color: "text-ok" },
};

const COND_OPS = [
  { value: "<", label: "<" }, { value: "<=", label: "<=" }, { value: ">", label: ">" },
  { value: ">=", label: ">=" }, { value: "==", label: "==" }, { value: "!=", label: "!=" },
  { value: "contains", label: "contiene" },
];

const EVENTS_OPTIONS = [
  "source.connected", "source.synced", "document.uploaded", "document.processed",
  "entity.created", "entity.updated", "semantic.mapping.approved", "agent.run.completed",
  "invoice.detected", "customer.created", "sales.closed", "workflow.completed",
  "integration.connected",
].map((v) => ({ value: v, label: v }));

const P_IN = [{ name: "in", type: "json" }];
const P_OUT = [{ name: "out", type: "json" }];
const P_COND: PortDef[] = [
  { name: "out", type: "boolean" },
  { name: "then", type: "json" },
  { name: "else", type: "json" },
];
const P_LOOP: PortDef[] = [
  { name: "done", type: "json" },
  { name: "out", type: "json" },
];

export const NODE_LIBRARY: Record<string, NodeMeta> = {
  trigger_schedule: {
    type: "trigger_schedule",
    category: "trigger",
    label: "Schedule",
    icon: "⏰",
    color: "bg-info",
    ports: { output: P_OUT },
    fields: [
      { key: "every_minutes", label: "Cada (minutos)", type: "number", default: 5, adv: true },
      {
        key: "daily",
        label: "Diario (hh:mm)", type: "text", placeholder: "18:00", refs: false,
      },
      {
        key: "weekly", label: "Semanal (días 0-6, hh:mm)", type: "text", placeholder: "0,2 09:00", adv: true,
      },
      { key: "timezone", label: "Zona horaria", type: "text", placeholder: "America/Lima", default: "UTC", adv: true },
    ],
    defaults: { daily: "18:00", timezone: "UTC" },
    summary: (c) =>
      c.daily ? `Todos los días a las ${c.daily}` : `Cada ${c.every_minutes ?? 5} min`,
  },
  trigger_webhook: {
    type: "trigger_webhook",
    category: "trigger",
    label: "Webhook",
    icon: "🔗",
    color: "bg-info",
    ports: { output: P_OUT },
    fields: [{ key: "note", label: "URL pública", type: "text", placeholder: "se genera al guardar", adv: true }],
    summary: () => "Inbound HTTP",
  },
  trigger_event: {
    type: "trigger_event",
    category: "trigger",
    label: "Zent Event",
    icon: "🔔",
    color: "bg-info",
    ports: { output: P_OUT },
    fields: [
      { key: "event_type", label: "Evento", type: "select", options: EVENTS_OPTIONS },
      { key: "filters", label: "Filtros (JSON)", type: "json", adv: true },
    ],
    defaults: { event_type: "source.synced", filters: {} },
    summary: (c) => `Evento: ${String(c.event_type || "source.synced")}`,
  },
  api_call: {
    type: "api_call",
    category: "integration",
    label: "Llamar API",
    icon: "🌐",
    color: "bg-accent",
    fields: [
      { key: "url", label: "URL", type: "text", placeholder: "https://…", refs: true },
      { key: "method", label: "Método", type: "select", options: [{ value: "GET", label: "GET" }, { value: "POST", label: "POST" }], default: "GET" },
      { key: "json_path", label: "Campo de salida", type: "text", placeholder: "quantity", adv: true },
      { key: "json_body", label: "Body (JSON)", type: "json", adv: true, refs: true },
    ],
    defaults: { method: "GET" },
    summary: (c) => `${String(c.method || "GET")} ${String(c.url || "—").slice(0, 40)}`,
    risk: "elevated",
  },
  marketplace_action: {
    type: "marketplace_action",
    category: "integration",
    label: "Acción de integración",
    icon: "🧩",
    color: "bg-fuchsia-500",
    fields: [
      { key: "install_id", label: "Integración instalada", type: "select", options: [] },
      { key: "action_id", label: "Acción", type: "select", options: [] },
      { key: "inputs", label: "Inputs (JSON)", type: "json", refs: true },
      { key: "purpose", label: "Propósito (datos personales)", type: "text", adv: true },
    ],
    defaults: { inputs: {} },
    summary: (c) => `${String(c.action_id || "acción de integración").slice(0, 44)}`,
    risk: "normal",
  },
  business_node: {
    type: "business_node",
    category: "business",
    label: "Operación de negocio",
    icon: "🎯",
    color: "bg-emerald-500",
    fields: [
      { key: "title", label: "Título (outcome)", type: "text", placeholder: "Verify Business" },
      { key: "actions", label: "Acciones (JSON)", type: "json", adv: true },
      { key: "business_result", label: "Resultado de negocio (JSON)", type: "json", adv: true },
    ],
    defaults: { title: "Operación de negocio", actions: [], business_result: {} },
    summary: (c) => `${String(c.title || "operación de negocio").slice(0, 44)}`,
    risk: "normal",
  },
  kb_query: {
    type: "kb_query",
    category: "data",
    label: "Consultar knowledge base",
    icon: "📚",
    color: "bg-accent",
    fields: [
      { key: "knowledge_base_id", label: "Base", type: "select", options: [], refs: false },
      { key: "query", label: "Pregunta", type: "text", placeholder: "política de stock", refs: true },
      { key: "limit", label: "Límite", type: "number", default: 5, adv: true },
    ],
    defaults: { limit: 5 },
    summary: (c) => String(c.query || "búsqueda en KB").slice(0, 44),
  },
  query_business_data: {
    type: "query_business_data",
    category: "data",
    label: "Consultar datos de negocio",
    icon: "📊",
    color: "bg-accent",
    fields: [
      { key: "ask", label: "Pregunta", type: "textarea", placeholder: "Ventas de hoy por vendedor", refs: true },
    ],
    defaults: { ask: "" },
    summary: (c) => String(c.ask || "pregunta en lenguaje natural").slice(0, 44),
  },
  llm: {
    type: "llm",
    category: "ai",
    label: "Preguntar a un agente",
    icon: "🧠",
    color: "bg-purple-500",
    fields: [
      { key: "agent_id", label: "Agente", type: "select", options: [] },
      { key: "prompt", label: "Prompt", type: "textarea", placeholder: "Resume {{nodes…}}", refs: true },
      { key: "model", label: "Modelo (fallback)", type: "text", default: "gpt-4o-mini", adv: true },
    ],
    defaults: { model: "gpt-4o-mini" },
    summary: (c) => String(c.prompt || "consulta a agente").slice(0, 44),
  },
  condition: {
    type: "condition",
    category: "logic",
    label: "Si / si no",
    icon: "🔀",
    color: "bg-warn",
    ports: { input: P_IN, output: P_COND },
    fields: [
      { key: "field", label: "Campo / referencia", type: "text", placeholder: "{{nodes.n1.output.extracted}}", refs: true },
      {
        key: "operator", label: "Operador", type: "select",
        options: [
          { value: "<", label: "<" }, { value: "<=", label: "<=" }, { value: ">", label: ">" },
          { value: ">=", label: ">=" }, { value: "==", label: "==" }, { value: "!=", label: "!=" },
          { value: "contains", label: "contiene" },
        ],
        default: ">",
      },
      { key: "value", label: "Valor", type: "text", placeholder: "10", refs: true },
    ],
    defaults: { operator: ">" },
    summary: (c) => `${String(c.field || "campo")} ${String(c.operator || ">")} ${String(c.value ?? "")}`,
  },
  for_each: {
    type: "for_each",
    category: "logic",
    label: "Para cada",
    icon: "🔁",
    color: "bg-warn",
    ports: { input: P_IN, output: P_LOOP },
    fields: [
      { key: "collection", label: "Lista", type: "text", placeholder: "{{nodes.n1.output.rows}}", refs: true },
      { key: "max_iterations", label: "Máx. iteraciones", type: "number", default: 100 },
      { key: "concurrency", label: "Concurrencia", type: "number", default: 1, adv: true },
      { key: "fail_policy", label: "Si falla", type: "select", options: [{ value: "fail", label: "Falla el flujo" }, { value: "continue", label: "Continúa" }], default: "fail" },
    ],
    defaults: { max_iterations: 100, concurrency: 1, fail_policy: "fail" },
    summary: (c) => `Sobre ${String(c.collection || "lista")}`,
  },
  join: {
    type: "join",
    category: "logic",
    label: "Unir resultados",
    icon: "🧩",
    color: "bg-warn",
    fields: [],
    summary: () => "espera todos los predecesores",
  },
  merge: {
    type: "merge",
    category: "logic",
    label: "Primer resultado",
    icon: "⚡",
    color: "bg-warn",
    fields: [],
    summary: () => "corre con el primer predecesor",
  },
  filter: {
    type: "filter",
    category: "logic",
    label: "Filtrar",
    icon: "🪝",
    color: "bg-warn",
    fields: [
      { key: "items", label: "Lista", type: "text", refs: true },
      { key: "field", label: "Campo", type: "text" },
      { key: "operator", label: "Operador", type: "select", options: COND_OPS, default: "==" },
      { key: "value", label: "Valor", type: "text", refs: true },
    ],
    defaults: { operator: "==" },
    summary: (c) => `filtra por ${String(c.field || "?").slice(0, 30)}`,
  },
  set_variable: {
    type: "set_variable",
    category: "logic",
    label: "Guardar variable",
    icon: "📌",
    color: "bg-warn",
    fields: [
      { key: "name", label: "Nombre", type: "text" },
      { key: "value", label: "Valor", type: "text", refs: true },
    ],
    summary: (c) => `${String(c.name || "var")} = ${String(c.value ?? "").slice(0, 24)}`,
  },
  stop: {
    type: "stop",
    category: "control",
    label: "Detener",
    icon: "🛑",
    color: "bg-danger",
    fields: [
      { key: "status", label: "Al detener", type: "select", options: [{ value: "success", label: "Éxito" }, { value: "fail", label: "Fallo" }], default: "success" },
      { key: "message", label: "Mensaje", type: "text", refs: true },
    ],
    defaults: { status: "success" },
    summary: (c) => `termina con ${String(c.status || "success")}`,
  },
  human_approval: {
    type: "human_approval",
    category: "control",
    label: "Esperar aprobación",
    icon: "👤",
    color: "bg-danger",
    fields: [
      { key: "action", label: "Acción sensible", type: "text", placeholder: "Aprobar pago…" },
      { key: "summary", label: "Resumen", type: "textarea", refs: true },
      { key: "expires_minutes", label: "Expira (minutos)", type: "number", default: 1440, adv: true },
    ],
    defaults: { expires_minutes: 1440 },
    summary: (c) => String(c.action || "aprobación").slice(0, 44),
    risk: "critical",
  },
  notify: {
    type: "notify",
    category: "output",
    label: "Avisar",
    icon: "📣",
    color: "bg-ok",
    fields: [
      {
        key: "channel", label: "Canal", type: "select",
        options: [{ value: "in_app", label: "in-app" }, { value: "email", label: "email" }, { value: "webhook", label: "webhook" }],
        default: "in_app",
      },
      { key: "title", label: "Título", type: "text", refs: true },
      { key: "message", label: "Mensaje", type: "textarea", refs: true },
      { key: "data", label: "Data (JSON)", type: "json", adv: true, refs: true },
    ],
    defaults: { channel: "in_app" },
    summary: (c) => `${String(c.channel || "in_app")} · ${String(c.title || "aviso").slice(0, 30)}`,
  },
  end: {
    type: "end",
    category: "control",
    label: "Fin",
    icon: "🏁",
    color: "bg-faint",
    ports: { input: P_IN },
    fields: [],
    summary: () => "termina el flujo",
  },
};

export function nodeMeta(type: string): NodeMeta {
  return NODE_LIBRARY[type] ?? {
    type, category: "data", label: type, icon: "◆", color: "bg-faint",
    fields: [], summary: () => type,
  };
}

export function nodePorts(type: string): { input: PortDef[]; output: PortDef[] } {
  const m = nodeMeta(type);
  const ports = m.ports ?? {};
  const input = (ports.input ?? P_IN).map((p) => (typeof p === "string" ? { name: p, type: "json" } : p));
  const output = (ports.output ?? P_OUT).map((p) => (typeof p === "string" ? { name: p, type: "json" } : p));
  return { input, output };
}

// ---------------------------------------------------------------------------
// Helpers de grafo
// ---------------------------------------------------------------------------
export function emptyGraph(triggerType: "webhook" | "schedule" | "event" = "webhook"): WorkflowGraph {
  const trigger = triggerType === "schedule" ? "trigger_schedule" : triggerType === "event" ? "trigger_event" : "trigger_webhook";
  const t = makeNode(trigger);
  return {
    workflow_version: 2,
    nodes: [t],
    edges: [],
    variables: {},
    entrypoints: [t.id],
    metadata: { canvas: true },
  };
}

export function makeNode(type: string, position?: { x: number; y: number }): GraphNode {
  const meta = nodeMeta(type);
  const { input, output } = nodePorts(type);
  return {
    id: newGraphNodeId(),
    type,
    version: 1,
    label: meta.label,
    position: position ?? { x: 0, y: 0 },
    config: { ...(meta.defaults ?? {}) },
    input_ports: input,
    output_ports: output,
    retry_policy: { max_attempts: 1 },
    timeout_ms: 60_000,
    error_policy: "fail",
    metadata: {},
  };
}

export const PORT_TYPE_COMPAT: Record<string, string[]> = {
  number: ["string", "money", "json"],
  money: ["string", "number", "json"],
  boolean: ["string"],
  date: ["string", "datetime"],
  datetime: ["string", "date"],
  record: ["json", "string"],
  record_list: ["json", "string"],
  document: ["json"],
  evidence: ["json"],
  entity: ["json", "record"],
  json: ["string"],
};

export function portCompatible(src: string, dst: string): boolean {
  return src === dst || (PORT_TYPE_COMPAT[src] ?? []).includes(dst);
}

/** Layout por niveles topológicos (solo nodos sin posición). */
export function layoutGraph(graph: WorkflowGraph): WorkflowGraph {
  const entry = graph.entrypoints[0];
  const levelOf: Record<string, number> = {};
  const queue: string[] = [entry];
  levelOf[entry] = 0;
  while (queue.length) {
    const cur = queue.shift()!;
    const level = levelOf[cur] ?? 0;
    for (const e of graph.edges) {
      if (e.from_node !== cur) continue;
      const targetLevel = Math.max(level + 1, levelOf[e.to_node] ?? 0);
      levelOf[e.to_node] = targetLevel;
      queue.push(e.to_node);
    }
  }
  const byLevel: Record<number, string[]> = {};
  for (const n of graph.nodes) byLevel[levelOf[n.id] ?? 0] = [...(byLevel[levelOf[n.id] ?? 0] ?? []), n.id];
  const placed = new Set(graph.nodes.filter((n) => n.position.x !== 0 || n.position.y !== 0).map((n) => n.id));
  graph.nodes.forEach((n) => {
    if (placed.has(n.id)) return;
    const level = levelOf[n.id] ?? 0;
    const siblings = byLevel[level] ?? [n.id];
    const idx = Math.max(0, siblings.indexOf(n.id));
    n.position = { x: level * 300, y: Math.max(idx * 150 - ((siblings.length - 1) * 150) / 2, 0) };
  });
  return graph;
}

function walkBranch(graph: WorkflowGraph, start: string): string[] {
  const visited: string[] = [];
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length) {
    const cur = stack.pop()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    visited.push(cur);
    const outgoing = graph.edges.filter((e) => e.from_node === cur && e.from_port === "out");
    for (const e of outgoing) {
      const target = graph.nodes.find((n) => n.id === e.to_node);
      const indegree = graph.edges.filter((ed) => ed.to_node === e.to_node).length;
      if (target && indegree <= 1) stack.push(e.to_node);
    }
  }
  return visited;
}

/** Prepara el grafo para persistencia: branch de for_each, entrypoints, version. */
export function prepareGraphForSave(graph: WorkflowGraph): WorkflowGraph {
  const g: WorkflowGraph = JSON.parse(JSON.stringify(graph));
  g.workflow_version = 2;
  g.metadata = { ...(g.metadata ?? {}), canvas: true };
  for (const n of g.nodes) {
    if (n.type === "for_each") {
      const branches = g.edges
        .filter((e) => e.from_node === n.id && e.from_port === "out")
        .map((e) => e.to_node);
      const branchNodes: string[] = [];
      const seen = new Set<string>();
      for (const b of branches) {
        for (const id of walkBranch(g, b)) {
          if (!seen.has(id)) {
            seen.add(id);
            branchNodes.push(id);
          }
        }
      }
      n.config = { ...n.config, _branch: branchNodes };
    }
  }
  return g;
}

const _TRIGGER_TYPES = ["trigger_schedule", "trigger_webhook", "trigger_event"] as const;
export function triggerTypeOf(graph: WorkflowGraph): "webhook" | "schedule" | "event" {
  const t = graph.nodes.find((n) => _TRIGGER_TYPES.includes(n.type as (typeof _TRIGGER_TYPES)[number]));
  const type = t?.type;
  if (type === "trigger_schedule") return "schedule";
  if (type === "trigger_event") return "event";
  return "webhook";
}

/** Extrae trigger_config del nodo trigger (para persistir schedules v2). */
export function triggerConfigOf(graph: WorkflowGraph): Record<string, unknown> {
  const t = graph.nodes.find((n) => _TRIGGER_TYPES.includes(n.type as (typeof _TRIGGER_TYPES)[number]));
  if (!t) return {};
  const c = { ...t.config };
  if (t.type === "trigger_event") {
    return { event_type: c.event_type, filters: c.filters ?? {}, subscription: true };
  }
  if (t.type === "trigger_schedule") {
    const daily = String(c.daily ?? "");
    const weekly = String(c.weekly ?? "");
    const out: Record<string, unknown> = {};
    if (daily.includes(":")) {
      out.daily = { time: daily.trim() };
    } else if (weekly.includes(":")) {
      const parts = weekly.trim().split(/\s+/, 2);
      out.weekly = {
        days: (parts[0] ?? "")
          .split(",")
          .map((d) => parseInt(d, 10))
          .filter((v) => !Number.isNaN(v)),
        time: parts[1] ?? "09:00",
      };
    } else {
      const every = parseInt(String(c.every_minutes ?? ""), 10);
      out.every_minutes = Number.isFinite(every) && every > 0 ? every : 5;
    }
    if (c.timezone) out.timezone = c.timezone;
    return out;
  }
  return {};
}

// ---------------------------------------------------------------------------
// Data picker de referencias
// ---------------------------------------------------------------------------
export type RefOption = { label: string; ref: string };

const OUTPUT_FIELDS: Record<string, string[]> = {
  api_call: ["extracted", "status_code", "json", "body"],
  kb_query: ["count", "documents", "chunks"],
  query_business_data: ["rows", "columns", "answer", "evidence", "query_id"],
  llm: ["text", "agent_id", "model"],
  notify: ["sent", "channel"],
  for_each: ["items_processed", "results", "errors"],
  join: ["values"],
  merge: ["values", "first"],
  filter: ["filtered", "count"],
  set_variable: ["variable", "value"],
  condition: ["result"],
  human_approval: ["approval_id", "status"],
  marketplace_action: ["evidence_id", "cached", "cost", "latency_ms"],
  business_node: ["result_id", "evidence_ids", "total_cost", "action_0"],
  trigger_schedule: [],
  trigger_webhook: [],
  trigger_event: [],
};

export function referenceOptions(graph: WorkflowGraph, excludeNodeId?: string): RefOption[] {
  const out: RefOption[] = [];
  for (const n of graph.nodes) {
    if (n.id === excludeNodeId) continue;
    const fields = OUTPUT_FIELDS[n.type] ?? [];
    if (fields.length === 0) {
      out.push({ label: `${n.label} (salida)`, ref: `{{nodes.${n.id}.output}}` });
      continue;
    }
    for (const f of fields) {
      out.push({ label: `${n.label} → ${f}`, ref: `{{nodes.${n.id}.output.${f}}}` });
    }
  }
  return out;
}

export function findNodeByRef(ref: string, graph: WorkflowGraph): string | undefined {
  const m = /nodes\.([A-Za-z0-9_-]+)/.exec(ref);
  if (!m) return undefined;
  return graph.nodes.find((n) => n.id === m[1])?.id;
}