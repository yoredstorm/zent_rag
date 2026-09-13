export type AgentTone = "professional" | "friendly" | "concise";

export type AgentConfig = {
  purpose: string | null;
  temperature: number;
  tone: AgentTone;
  knowledge_base_ids: string[];
  source_ids: string[];
  limits: {
    max_steps: number | null;
    max_tokens: number | null;
    max_cost_usd: number | null;
  } | null;
  security: { sql_enabled: boolean; api_calls_enabled: boolean } | null;
  retrieval?: { strategy: string; top_k: number; score_threshold: number };
  output_schema?: Record<string, unknown>;
};

export type Agent = {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string | null;
  tools: string[];
  model: string | null;
  is_active: boolean;
  created_at: string;
  config: AgentConfig;
  workspace_id?: string | null;
};

export type KnowledgeSource = {
  id: string;
  name: string;
  type: string;
  status: string;
  document_count: number;
  last_sync: string | null;
  knowledge_base_id?: string | null;
};

export type AgentVersion = {
  id: string;
  version_number: number;
  status: string;
  notes: string | null;
  created_at: string;
};

export type Environment = { id: string; name: string; slug: string; is_default: boolean };

export type Deployment = {
  id: string;
  agent_id: string;
  environment_id: string;
  agent_version_id: string;
  slug: string;
  status: string;
  endpoint: string | null;
  deployed_at: string | null;
  rollback_from_id: string | null;
};

export const ADVANCED_TABS = [
  "model",
  "output",
  "retrieval",
  "tools",
  "security",
  "limits",
  "readiness",
  "evaluation",
  "versions",
  "deployments",
  "embed",
] as const;

export type AdvancedTab = (typeof ADVANCED_TABS)[number];

export const ADVANCED_TAB_LABELS: Record<AdvancedTab, string> = {
  model: "Modelo",
  output: "Salida",
  retrieval: "Retrieval",
  tools: "Tools",
  security: "Seguridad",
  limits: "Límites",
  readiness: "Readiness",
  evaluation: "Evaluación",
  versions: "Versiones",
  deployments: "Despliegues",
  embed: "Embed",
};

export function isAdvancedTab(value: string | null): value is AdvancedTab {
  return ADVANCED_TABS.includes(value as AdvancedTab);
}

export function defaultConfig(): AgentConfig {
  return {
    purpose: "",
    temperature: 0.2,
    tone: "professional",
    knowledge_base_ids: [],
    source_ids: [],
    limits: { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 },
    security: { sql_enabled: false, api_calls_enabled: false },
  };
}

export function toolsFromCapabilities(semantic: boolean, sql: boolean, apiCalls: boolean): string[] {
  const tools: string[] = [];
  if (semantic) tools.push("search_knowledge");
  if (sql) tools.push("query_database");
  if (apiCalls) tools.push("call_api");
  return tools;
}

export function parseSchema(raw: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    return null;
  } catch {
    return null;
  }
}

export function buildAgentPayload(input: {
  name: string;
  systemPrompt: string;
  model: string;
  semantic: boolean;
  sql: boolean;
  apiCalls: boolean;
  isActive: boolean;
  config: AgentConfig;
  retrieval: { strategy: string; top_k: number; score_threshold: number };
  outputSchema: string;
  workspaceId: string;
}) {
  const purpose = input.config.purpose?.trim() || null;
  return {
    name: input.name.trim(),
    description: purpose,
    system_prompt: input.systemPrompt.trim() || null,
    model: input.model.trim() || null,
    tools: toolsFromCapabilities(input.semantic, input.sql, input.apiCalls),
    is_active: input.isActive,
    config: {
      purpose,
      temperature: input.config.temperature,
      tone: input.config.tone,
      knowledge_base_ids: input.config.knowledge_base_ids,
      source_ids: input.config.source_ids,
      limits: input.config.limits,
      security: {
        sql_enabled: input.sql,
        api_calls_enabled: input.apiCalls,
      },
      retrieval: input.retrieval.strategy ? input.retrieval : undefined,
      output_schema: input.outputSchema.trim() ? parseSchema(input.outputSchema) : undefined,
    },
    workspace_id: input.workspaceId || undefined,
  };
}

export function sourceIdsFromSteps(steps: unknown): string[] {
  if (!Array.isArray(steps)) return [];
  const ids: string[] = [];
  for (const step of steps) {
    if (!step || typeof step !== "object") continue;
    const record = step as { type?: string; meta?: { source_ids?: unknown } };
    if (record.type !== "tool_call") continue;
    const raw = record.meta?.source_ids;
    if (!Array.isArray(raw)) continue;
    for (const item of raw) {
      const id = String(item);
      if (id && !ids.includes(id)) ids.push(id);
    }
  }
  return ids;
}

export function toolErrorsFromSteps(steps: unknown): string[] {
  if (!Array.isArray(steps)) return [];
  const errors: string[] = [];
  for (const step of steps) {
    if (!step || typeof step !== "object") continue;
    const record = step as { type?: string; error?: unknown };
    if (record.type !== "tool_call") continue;
    const message = typeof record.error === "string" ? record.error.trim() : "";
    if (message && !errors.includes(message)) errors.push(message);
  }
  return errors;
}
