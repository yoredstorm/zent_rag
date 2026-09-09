/** Catálogo de bloques tipo Scratch/Blockly. Añadir un bloque = entrada aquí + IR + handler engine. */

export type BlockCategory = "cuando" | "datos" | "logica" | "avisar";

export type BlockKind =
  | "hat_schedule"
  | "hat_webhook"
  | "hat_event"
  | "api_call"
  | "kb_query"
  | "llm"
  | "condition"
  | "notify";

export type FieldType = "text" | "number" | "select";

export type BlockField = {
  key: string;
  label: string;
  type: FieldType;
  placeholder?: string;
  options?: { value: string; label: string }[];
  defaultValue?: string;
};

export type BlockDef = {
  kind: BlockKind;
  category: BlockCategory;
  label: string;
  color: string;
  hat?: boolean;
  hasThenElse?: boolean;
  stepType?: "llm" | "kb_query" | "api_call" | "condition" | "notify";
  fields: BlockField[];
};

export const BLOCK_REGISTRY: BlockDef[] = [
  {
    kind: "hat_schedule",
    category: "cuando",
    label: "Cada N minutos",
    color: "bg-ok",
    hat: true,
    fields: [{ key: "every_minutes", label: "minutos", type: "number", defaultValue: "5" }],
  },
  {
    kind: "hat_webhook",
    category: "cuando",
    label: "Cuando llega un webhook",
    color: "bg-info",
    hat: true,
    fields: [],
  },
  {
    kind: "hat_event",
    category: "cuando",
    label: "Cuando ocurre un evento",
    color: "bg-info",
    hat: true,
    fields: [],
  },
  {
    kind: "api_call",
    category: "datos",
    label: "Llamar API",
    color: "bg-accent",
    stepType: "api_call",
    fields: [
      { key: "url", label: "URL", type: "text", placeholder: "https://…" },
      {
        key: "method",
        label: "método",
        type: "select",
        options: [
          { value: "GET", label: "GET" },
          { value: "POST", label: "POST" },
        ],
        defaultValue: "GET",
      },
      { key: "json_path", label: "json_path", type: "text", placeholder: "quantity" },
    ],
  },
  {
    kind: "kb_query",
    category: "datos",
    label: "Consultar knowledge base",
    color: "bg-accent",
    stepType: "kb_query",
    fields: [
      { key: "knowledge_base_id", label: "KB", type: "select", options: [] },
      { key: "query", label: "pregunta", type: "text", placeholder: "política de stock" },
    ],
  },
  {
    kind: "llm",
    category: "datos",
    label: "Preguntar a un agente",
    color: "bg-accent",
    stepType: "llm",
    fields: [
      { key: "agent_id", label: "agente", type: "select", options: [] },
      { key: "prompt", label: "prompt", type: "text", placeholder: "Resume {{steps.0.output.extracted}}" },
    ],
  },
  {
    kind: "condition",
    category: "logica",
    label: "Si / si no",
    color: "bg-warn",
    stepType: "condition",
    hasThenElse: true,
    fields: [
      { key: "field", label: "campo", type: "text", placeholder: "steps.0.output.extracted" },
      {
        key: "operator",
        label: "op",
        type: "select",
        options: [
          { value: "<", label: "<" },
          { value: "<=", label: "<=" },
          { value: ">", label: ">" },
          { value: ">=", label: ">=" },
          { value: "==", label: "==" },
          { value: "!=", label: "!=" },
          { value: "contains", label: "contains" },
        ],
        defaultValue: "<",
      },
      { key: "value", label: "valor", type: "text", placeholder: "10" },
    ],
  },
  {
    kind: "notify",
    category: "avisar",
    label: "Avisar",
    color: "bg-ok",
    stepType: "notify",
    fields: [
      {
        key: "channel",
        label: "canal",
        type: "select",
        options: [
          { value: "in_app", label: "in-app" },
          { value: "email", label: "email" },
          { value: "webhook", label: "webhook" },
        ],
        defaultValue: "in_app",
      },
      { key: "title", label: "título", type: "text", placeholder: "Stock bajo" },
      { key: "message", label: "mensaje", type: "text", placeholder: "Quedan {{steps.0.output.extracted}}" },
    ],
  },
];

export const CATEGORY_LABEL: Record<BlockCategory, string> = {
  cuando: "Cuando",
  datos: "Datos",
  logica: "Lógica",
  avisar: "Avisar",
};

export function blockDef(kind: BlockKind): BlockDef {
  const found = BLOCK_REGISTRY.find((b) => b.kind === kind);
  if (!found) throw new Error(`bloque desconocido: ${kind}`);
  return found;
}

export function defaultFields(kind: BlockKind): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of blockDef(kind).fields) {
    out[f.key] = f.defaultValue ?? "";
  }
  return out;
}
