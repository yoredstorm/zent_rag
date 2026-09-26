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
  /** Delta sobre `DEFAULT_RESPONSE_PROFILE`. */
  profile: Partial<ResponseProfile>;
};

/** Preguntas de arranque del panel Probar: genéricas, sin datos de dominio. */
export const SUGGESTED_QUESTIONS: string[] = [
  "¿Qué cubre la documentación que cargaste?",
  "Resumí lo más importante en 3 puntos.",
  "¿Qué límites o excepciones debería conocer?",
];

/**
 * Presets de Agent Studio (§29). El backend guarda el resultado, no el preset:
 * cada delta se aplana sobre el perfil antes de persistir (§32).
 * `balanced` equivale a los defaults recomendados: es el estado "Auto".
 */
export const BALANCED_PRESET = "balanced";

export const RESPONSE_PROFILE_PRESETS: ResponseProfilePreset[] = [
  {
    id: BALANCED_PRESET,
    label: "Equilibrado",
    hint: "Recomendado. Conciso, con evidencia y sin relleno.",
    profile: { use_tables: true },
  },
  {
    id: "precise",
    label: "Preciso",
    hint: "Terminología exacta y cero explicaciones de base.",
    profile: {
      tone: "professional",
      technical_level: "advanced",
      default_detail: "normal",
      audience: "technical",
      use_examples: false,
      use_tables: true,
      preserve_domain_terms: true,
    },
  },
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
      show_practical_implications: true,
    },
  },
  {
    id: "technical_detailed",
    label: "Experto técnico",
    hint: "Precisión técnica, sin explicar lo básico.",
    profile: {
      tone: "professional",
      technical_level: "advanced",
      default_detail: "detailed",
      audience: "expert",
      use_tables: true,
      use_examples: true,
      preserve_domain_terms: true,
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
      technical_level: "intermediate",
      default_detail: "detailed",
      cite_sources: true,
      show_uncertainty: true,
      show_practical_implications: true,
    },
  },
];

/**
 * Espejo de `ResponseProfile` del dominio (`src/core/domain/response.py:127`).
 * Si estos valores se desalinean, la UI muestra un perfil distinto del que
 * aplica el runtime en agentes sin `response_profile` guardado.
 */
export const DEFAULT_RESPONSE_PROFILE: ResponseProfile = {
  language: "es",
  tone: "professional",
  technical_level: "intermediate",
  default_detail: "normal",
  audience: "technical",
  conclusion_first: true,
  use_headings: true,
  use_bold: true,
  use_tables: true,
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
    /** Modo del loop JEV (off|shadow|on|canary). No se edita desde el Studio. */
    jev_loop?: string | null;
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

// ---------------------------------------------------------------------------
// Etapas del Studio: DESARROLLAR → PROBAR → PUBLICAR
// ---------------------------------------------------------------------------

export const AGENT_STAGES = ["develop", "test", "publish"] as const;
export type AgentStage = (typeof AGENT_STAGES)[number];

export const AGENT_STAGE_LABELS: Record<AgentStage, string> = {
  develop: "Desarrollar",
  test: "Probar",
  publish: "Publicar",
};

// ---------------------------------------------------------------------------
// Configuración avanzada: grupos con estado resumido + Personalizar
// ---------------------------------------------------------------------------

export const ADVANCED_GROUPS = [
  "model",
  "response",
  "tools",
  "retrieval",
  "intelligence",
  "limits",
  "integration",
] as const;

export type AdvancedGroup = (typeof ADVANCED_GROUPS)[number];

/** Volver a la raíz del grupo (no abre su detalle) falta a propósito: el
 *  resumen se lee primero y el detalle aparece al pulsar Personalizar. */
export const ADVANCED_GROUP_LABELS: Record<AdvancedGroup, string> = {
  model: "Modelo",
  response: "Respuesta",
  tools: "Herramientas",
  retrieval: "Conocimiento y búsqueda",
  intelligence: "Orquestación JEV",
  limits: "Seguridad y límites",
  integration: "Integración y salida",
};

export const DEFAULT_ADVANCED_GROUP: AdvancedGroup = "model";

export function isAdvancedGroup(value: string | null): value is AdvancedGroup {
  return ADVANCED_GROUPS.includes(value as AdvancedGroup);
}

/**
 * Pestañas que existieron en URLs guardadas. Las de publicación ya no son
 * grupos avanzados: ahora viven en la etapa Publicar.
 */
const LEGACY_ADVANCED_TABS: Record<string, AdvancedGroup> = {
  behavior: "model",
  model: "model",
  output: "integration",
  capabilities: "tools",
  tools: "tools",
  security: "tools",
  retrieval: "retrieval",
  jev: "intelligence",
  limits: "limits",
};

const LEGACY_PUBLISH_TABS = new Set([
  "publish",
  "readiness",
  "evaluation",
  "versions",
  "deployments",
  "embed",
]);

/** Resuelve un `?tab=` legacy al grupo avanzado, o `null` si no es un grupo. */
export function legacyTabToGroup(value: string | null): AdvancedGroup | null {
  if (!value) return null;
  if (isAdvancedGroup(value)) return value;
  return LEGACY_ADVANCED_TABS[value] ?? null;
}

export type StudioView = {
  stage: AgentStage;
  /** Sub-sección de Publicar que la URL pidió enfocar. */
  publishFocus: string | null;
  advancedOpen: boolean;
  /** Grupo avanzado expandido; `null` = todos plegados mostrando su resumen. */
  advancedGroup: AdvancedGroup | null;
};

/**
 * Traduce `?panel=` / `?tab=` (incluidos los valores viejos) a la vista.
 * Compatibilidad: `configure`, `advanced`, `publish` y las 11 pestañas
 * antiguas siguen resolviendo a una pantalla con sentido.
 */
export function resolveStudioView(panel: string | null, tab: string | null): StudioView {
  const base: StudioView = {
    stage: "develop",
    publishFocus: null,
    advancedOpen: false,
    advancedGroup: null,
  };
  if (tab && LEGACY_PUBLISH_TABS.has(tab)) {
    return { ...base, stage: "publish", publishFocus: tab === "publish" ? null : tab };
  }
  if (panel === "publish") {
    return { ...base, stage: "publish" };
  }
  const group = legacyTabToGroup(tab);
  if (panel === "advanced" || group !== null) {
    return { ...base, advancedOpen: true, advancedGroup: group };
  }
  if (panel === "test") {
    return { ...base, stage: "test" };
  }
  return base;
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
