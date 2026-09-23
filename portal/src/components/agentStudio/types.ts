export type AgentTone = "professional" | "friendly" | "concise";

/** Cómo debe explicar el agente (§28). Estructura, no prompt libre. */
export type ResponseProfile = {
  preset?: string;
  language: string;
  tone: "professional" | "didactic" | "executive" | "neutral";
  technical_level: "basic" | "intermediate" | "advanced" | "expert";
  default_detail: "brief" | "normal" | "detailed" | "deep";
  audience: "beginner" | "business" | "technical" | "expert";
  conclusion_first: boolean;
  use_headings: boolean;
  use_bold: boolean;
  use_tables: boolean;
  use_examples: boolean;
  cite_sources: boolean;
  show_uncertainty: boolean;
  show_practical_implications: boolean;
  preserve_domain_terms: boolean;
  preferred_blueprints?: string[];
  custom_instructions: string;
};

export type ResponseProfilePreset = {
  id: string;
  label: string;
  hint: string;
  profile: Partial<ResponseProfile>;
};

/** Preguntas de arranque del panel Probar: genéricas, sin datos de dominio. */
export const SUGGESTED_QUESTIONS: string[] = [
  "¿Qué cubre la documentación que cargaste?",
  "Resumí lo más importante en 3 puntos.",
  "¿Qué límites o excepciones debería conocer?",
];

/** Presets de Agent Studio (§29): el backend sólo guarda el resultado. */
export const RESPONSE_PROFILE_PRESETS: ResponseProfilePreset[] = [
  {
    id: "clear_didactic",
    label: "Claro y didáctico",
    hint: "Explica el porqué y usa ejemplos.",
    profile: {
      tone: "didactic",
      technical_level: "intermediate",
      default_detail: "detailed",
      use_examples: true,
      show_practical_implications: true,
    },
  },
  {
    id: "technical_detailed",
    label: "Técnico detallado",
    hint: "Precisión técnica, sin explicar lo básico.",
    profile: {
      tone: "professional",
      technical_level: "advanced",
      default_detail: "detailed",
      use_tables: true,
      use_examples: true,
      preserve_domain_terms: true,
    },
  },
  {
    id: "executive",
    label: "Ejecutivo",
    hint: "Conclusión e impacto, sin detalle técnico.",
    profile: {
      tone: "executive",
      technical_level: "basic",
      default_detail: "normal",
      audience: "business",
      use_examples: false,
      cite_sources: false,
    },
  },
  {
    id: "concise",
    label: "Conciso",
    hint: "Lo mínimo necesario para responder.",
    profile: {
      tone: "neutral",
      default_detail: "brief",
      use_examples: false,
      show_practical_implications: false,
      cite_sources: false,
    },
  },
  {
    id: "analytical",
    label: "Analítico",
    hint: "Profundidad y contraste de opciones.",
    profile: {
      tone: "professional",
      technical_level: "advanced",
      default_detail: "deep",
      audience: "expert",
      use_tables: true,
      show_uncertainty: true,
    },
  },
  {
    id: "evidence_first",
    label: "Con evidencia",
    hint: "Cada afirmación con su fuente.",
    profile: {
      tone: "professional",
      default_detail: "detailed",
      cite_sources: true,
      show_uncertainty: true,
      show_practical_implications: true,
    },
  },
];

export const DEFAULT_RESPONSE_PROFILE: ResponseProfile = {
  language: "es",
  tone: "professional",
  technical_level: "intermediate",
  default_detail: "normal",
  audience: "technical",
  conclusion_first: true,
  use_headings: true,
  use_bold: true,
  use_tables: false,
  use_examples: true,
  cite_sources: true,
  show_uncertainty: true,
  show_practical_implications: true,
  preserve_domain_terms: true,
  custom_instructions: "",
};

/** Campos que el usuario puede activar o desactivar (§28). */
export const RESPONSE_PROFILE_TOGGLES: Array<{
  key: keyof ResponseProfile;
  label: string;
  hint: string;
}> = [
  { key: "conclusion_first", label: "Conclusión primero", hint: "Responde antes de explicar." },
  { key: "show_practical_implications", label: "Implicación práctica", hint: "Qué cambia en el caso." },
  { key: "use_examples", label: "Ejemplos", hint: "Cuando aclaran la explicación." },
  { key: "use_tables", label: "Tablas", hint: "Para atributos comparables." },
  { key: "cite_sources", label: "Citas", hint: "Fuente junto a la afirmación." },
  { key: "show_uncertainty", label: "Declarar lo que falta", hint: "Sin especular." },
  {
    key: "preserve_domain_terms",
    label: "Conservar términos del dominio",
    hint: "Sin traducir lo que pierde sentido.",
  },
  { key: "use_headings", label: "Encabezados", hint: "Estructura visible." },
  { key: "use_bold", label: "Negritas", hint: "Sólo valores y conceptos clave." },
];

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
  /** Override de JEV por agente (si falta, hereda los flags del sistema). */
  runtime?: {
    tool_routing?: boolean | null;
    termination_gate?: boolean | null;
    answer_gate?: boolean | null;
  } | null;
  /** Cómo debe responder: tono, nivel, detalle, formato, citas (§28). */
  response_profile?: ResponseProfile | null;
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

export type IngestionJob = {
  id: string;
  job_type: string;
  status: string;
  progress: number;
  source_id: string | null;
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

export const ADVANCED_TABS = ["behavior", "capabilities", "publish"] as const;

export type AdvancedTab = (typeof ADVANCED_TABS)[number];

export const ADVANCED_TAB_LABELS: Record<AdvancedTab, string> = {
  behavior: "Cómo responde",
  capabilities: "Qué puede hacer",
  publish: "Publicar",
};

/** Las 11 pestañas antiguas siguen llegando por URL (enlaces guardados, redirects). */
const LEGACY_TAB_GROUPS: Record<string, AdvancedTab> = {
  model: "behavior",
  output: "behavior",
  tools: "capabilities",
  security: "capabilities",
  retrieval: "capabilities",
  limits: "capabilities",
  readiness: "publish",
  evaluation: "publish",
  versions: "publish",
  deployments: "publish",
  embed: "publish",
};

export function isAdvancedTab(value: string | null): value is AdvancedTab {
  return ADVANCED_TABS.includes(value as AdvancedTab);
}

/** Resuelve el grupo visible a partir de `?tab=`, o null si no es una pestaña conocida. */
export function legacyTabToGroup(value: string | null): AdvancedTab | null {
  if (!value) return null;
  if (isAdvancedTab(value)) return value;
  return LEGACY_TAB_GROUPS[value] ?? null;
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
  if (semantic) tools.push("search_knowledge", "query_tabular_data");
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
      runtime: input.config.runtime ?? undefined,
      response_profile: input.config.response_profile ?? undefined,
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
