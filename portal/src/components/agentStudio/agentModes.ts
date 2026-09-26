// =============================================================================
// agentModes — lógica de "Auto vs Personalizado" y recomendaciones del Studio.
// =============================================================================
// No es un modelo paralelo de configuración: lee y escribe EXACTAMENTE
// `AgentConfig`. "Auto" no se persiste: se deriva de comparar el valor guardado
// contra el valor recomendado. Un agente legacy con valores propios se clasifica
// como "Personalizado" y nunca se resetea.
// =============================================================================
import {
  DEFAULT_RESPONSE_PROFILE,
  RESPONSE_PROFILE_PRESETS,
  type AgentConfig,
  type AgentTone,
  type ResponseProfile,
} from "./types";

/** Ruta del gateway recomendada: Zent elige el motor real. */
export const DEFAULT_MODEL_ROUTE = "zent-default";

/** Defaults recomendados. Deben coincidir con `defaultConfig()` y el backend. */
export const RECOMMENDED_TEMPERATURE = 0.2;

export type RetrievalSettings = { strategy: string; top_k: number; score_threshold: number };

export const RECOMMENDED_RETRIEVAL: RetrievalSettings = {
  strategy: "hybrid",
  top_k: 10,
  score_threshold: 0,
};

export const RECOMMENDED_LIMITS = {
  max_steps: 8,
  max_tokens: 4000,
  max_cost_usd: 0.5,
};

export type Mode = "auto" | "custom";

/** Prioridades de modelo que ve el usuario, con la ruta técnica como pista. */
export const MODEL_PRIORITIES: { value: string; label: string; hint: string; tech: string }[] = [
  { value: "zent-default", label: "Automático", hint: "Zent elige el motor. Recomendado.", tech: "zent-default" },
  { value: "zent-fast", label: "Priorizar velocidad", hint: "Responde antes, cuesta parecido.", tech: "zent-fast" },
  { value: "zent-cheap", label: "Priorizar economía", hint: "Baja el costo por respuesta.", tech: "zent-cheap" },
  { value: "zent-quality", label: "Priorizar calidad", hint: "Más razonamiento, más latencia.", tech: "zent-quality" },
  { value: "zent-routed", label: "Según reglas de la organización", hint: "Usa el ruteo configurado en Control Center.", tech: "zent-routed" },
];

export const CUSTOM_MODEL_VALUE = "__custom__";

export function modelMode(model: string): Mode {
  return !model || model === DEFAULT_MODEL_ROUTE ? "auto" : "custom";
}

export function retrievalMode(retrieval: {
  strategy: string;
  top_k: number;
  score_threshold: number;
}): Mode {
  const same =
    retrieval.strategy === RECOMMENDED_RETRIEVAL.strategy &&
    Number(retrieval.top_k) === RECOMMENDED_RETRIEVAL.top_k &&
    Number(retrieval.score_threshold) === RECOMMENDED_RETRIEVAL.score_threshold;
  return same ? "auto" : "custom";
}

export function limitsMode(limits: AgentConfig["limits"]): Mode {
  if (!limits) return "auto";
  const same =
    (limits.max_steps ?? RECOMMENDED_LIMITS.max_steps) === RECOMMENDED_LIMITS.max_steps &&
    (limits.max_tokens ?? RECOMMENDED_LIMITS.max_tokens) === RECOMMENDED_LIMITS.max_tokens &&
    Number(limits.max_cost_usd ?? RECOMMENDED_LIMITS.max_cost_usd) === RECOMMENDED_LIMITS.max_cost_usd;
  return same ? "auto" : "custom";
}

/**
 * Overrides de JEV por agente. Cualquier valor definido —incluido `jev_loop`,
 * que el Studio no expone pero un agente legacy puede tener— cuenta como
 * personalización: nunca se pisa lo que el usuario ya decidió.
 */
export function intelligenceMode(runtime: AgentConfig["runtime"] | undefined | null): Mode {
  if (!runtime) return "auto";
  for (const value of Object.values(runtime)) {
    if (value === null || value === undefined) continue;
    if (typeof value === "boolean" || typeof value === "string") return "custom";
  }
  return "auto";
}

/** Texto de una línea para el resumen del bloque. */
export function intelligenceSummary(runtime: AgentConfig["runtime"] | undefined | null): string {
  const source = runtime ?? {};
  const parts: string[] = [];
  const label = (value: unknown) =>
    typeof value === "boolean" ? (value ? "activado" : "apagado") : "heredado";
  parts.push(`Ruteo de herramientas: ${label(source.tool_routing)}`);
  parts.push(`Corte por evidencia: ${label(source.termination_gate)}`);
  parts.push(`Verificación: ${label(source.answer_gate)}`);
  return parts.join(" · ");
}

export function retrievalSummary(retrieval: {
  strategy: string;
  top_k: number;
  score_threshold: number;
}): string {
  if (retrievalMode(retrieval) === "auto") return "Automática · búsqueda híbrida · 10 fragmentos";
  const strategy: Record<string, string> = {
    vector: "por significado",
    lexical: "por palabras exactas",
    hybrid: "híbrida",
  };
  const threshold = Number(retrieval.score_threshold)
    ? ` · similitud mínima ${retrieval.score_threshold}`
    : "";
  return `Personalizada · ${strategy[retrieval.strategy] ?? retrieval.strategy} · ${
    retrieval.top_k
  } fragmentos${threshold}`;
}

export function limitsSummary(limits: AgentConfig["limits"]): string {
  if (limitsMode(limits) === "auto") return "Protección automática · 8 pasos · 4.000 tokens · USD 0,50";
  const steps = limits?.max_steps ?? RECOMMENDED_LIMITS.max_steps;
  const tokens = limits?.max_tokens ?? RECOMMENDED_LIMITS.max_tokens;
  const cost = limits?.max_cost_usd ?? RECOMMENDED_LIMITS.max_cost_usd;
  return `Personalizado · ${steps} pasos · ${tokens} tokens · USD ${Number(cost).toFixed(2)}`;
}

export function modelSummary(model: string): string {
  if (modelMode(model) === "auto") return "Automático · Zent elige el motor";
  const known = MODEL_PRIORITIES.find((priority) => priority.value === model);
  return known ? `${known.label} · ${known.tech}` : `Modelo propio · ${model}`;
}

// ---------------------------------------------------------------------------
// Comportamiento: preset vs personalizado
// ---------------------------------------------------------------------------

const PROFILE_KEYS = [
  "language",
  "tone",
  "technical_level",
  "default_detail",
  "audience",
  "conclusion_first",
  "use_headings",
  "use_bold",
  "use_tables",
  "use_examples",
  "cite_sources",
  "show_uncertainty",
  "show_practical_implications",
  "preserve_domain_terms",
] as const;

export const CUSTOM_PROFILE = "custom";

/**
 * Compara el perfil guardado contra cada preset resuelto. Devuelve el id del
 * preset sólo si son indistinguibles; si no, `custom`. Un agente guardado con
 * `preset: "executive"` pero con el tono editado vuelve como `custom`, que es
 * justo lo que hay que mostrar sin tocarle los valores.
 */
export function matchResponsePreset(profile: ResponseProfile | null | undefined): string {
  const resolved: ResponseProfile = { ...DEFAULT_RESPONSE_PROFILE, ...(profile ?? {}) };
  if ((resolved.custom_instructions ?? "").trim()) return CUSTOM_PROFILE;
  const preferred = resolved.preferred_blueprints ?? [];
  if (preferred.length) return CUSTOM_PROFILE;
  for (const preset of RESPONSE_PROFILE_PRESETS) {
    const candidate: ResponseProfile = { ...DEFAULT_RESPONSE_PROFILE, ...preset.profile };
    const same = PROFILE_KEYS.every(
      (key) => String(resolved[key]) === String(candidate[key]),
    );
    if (same) return preset.id;
  }
  return CUSTOM_PROFILE;
}

export function responseProfileSummary(profile: ResponseProfile | null | undefined): string {
  const presetId = matchResponsePreset(profile);
  if (presetId !== CUSTOM_PROFILE) {
    return RESPONSE_PROFILE_PRESETS.find((preset) => preset.id === presetId)?.label ?? "Preset";
  }
  const resolved: ResponseProfile = { ...DEFAULT_RESPONSE_PROFILE, ...(profile ?? {}) };
  const tone: Record<string, string> = {
    professional: "profesional",
    didactic: "didáctico",
    executive: "ejecutivo",
    neutral: "neutro",
  };
  const detail: Record<string, string> = {
    brief: "breve",
    normal: "normal",
    detailed: "detallado",
    deep: "profundo",
  };
  const traits = [
    tone[resolved.tone] ?? resolved.tone,
    detail[resolved.default_detail] ?? resolved.default_detail,
    resolved.cite_sources ? "con citas" : "sin citas",
  ];
  return `Personalizado · ${traits.join(" · ")}`;
}

// ---------------------------------------------------------------------------
// Herramientas: capacidades semánticas
// ---------------------------------------------------------------------------

export type CapabilityId = "knowledge" | "data" | "integrations";

export type CapabilityState = {
  id: CapabilityId;
  label: string;
  hint: string;
  /** Identificadores técnicos que activa. Sólo se muestran en avanzado. */
  tech: string[];
  checked: boolean;
  available: boolean;
  unavailableHint: string;
};

export type CapabilityFlags = { knowledge: boolean; data: boolean; integrations: boolean };

const CAPABILITY_COPY: Record<
  CapabilityId,
  { label: string; hint: string; tech: string[]; unavailableHint: string }
> = {
  knowledge: {
    label: "Consultar conocimiento",
    hint: "Lee tus documentos y tablas antes de responder.",
    tech: ["search_knowledge", "query_tabular_data"],
    unavailableHint: "",
  },
  data: {
    label: "Consultar datos",
    hint: "Ejecuta consultas de solo lectura sobre tus bases de datos conectadas.",
    tech: ["query_database"],
    unavailableHint: "Tus fuentes no incluyen base de datos: esta capacidad se omite en este agente.",
  },
  integrations: {
    label: "Usar integraciones externas",
    hint: "Trae o envía datos con los servicios que conectaste en Integraciones.",
    tech: ["call_api"],
    unavailableHint: "",
  },
};

/** Estado de cada capacidad: disponibilidad por fuentes + activación por tools. */
export function capabilityStates(
  flags: CapabilityFlags,
  options: { dbAvailable: boolean },
): CapabilityState[] {
  const ids: CapabilityId[] = ["knowledge", "data", "integrations"];
  return ids.map((id) => ({
    id,
    ...CAPABILITY_COPY[id],
    checked: flags[id],
    available: id === "data" ? options.dbAvailable : true,
  }));
}

/**
 * Qué capacidades puede usar el agente según sus fuentes. `dbAvailable` es
 * `true` con lista vacía (igual criterio permisivo que el backend).
 */
export function flagsFromTools(tools: string[], opts?: { semanticFallback?: boolean }): CapabilityFlags {
  const has = (name: string) => tools.includes(name);
  return {
    knowledge: has("search_knowledge") || has("query_tabular_data") || Boolean(opts?.semanticFallback),
    data: has("query_database"),
    integrations: has("call_api"),
  };
}

export function capabilityLabels(flags: CapabilityFlags): string[] {
  return capabilityStates(flags, { dbAvailable: true })
    .filter((capability) => capability.checked)
    .map((capability) => capability.label);
}

// ---------------------------------------------------------------------------
// Recomendación automática ("Crear configuración con IA")
// ---------------------------------------------------------------------------

export type AgentRecommendation = {
  presetId: string;
  presetLabel: string;
  capabilities: CapabilityFlags;
  model: string;
  /** Frases listas para el panel de revisión. */
  decisions: string[];
  /** Por qué se decidió, para que el usuario pueda discutirlo. */
  reasons: string[];
};

type Rule = { presetId: string; reason: string; match: RegExp };

/**
 * Reglas deterministas sobre el propósito y las fuentes. Nunca inventa
 * capacidades: `data` sólo se enciende si hay fuentes de base de datos.
 */
const PRESET_RULES: Rule[] = [
  {
    presetId: "evidence_first",
    reason: "El propósito menciona normativa, políticas o auditoría: conviene citar la fuente.",
    match: /norma|pol[ií]tica|legal|regul|compliance|audit|evidencia|contrato|jur[ií]dic|atpco|regla/i,
  },
  {
    presetId: "executive",
    reason: "El propósito apunta a decisiones de negocio o dirección.",
    match: /ejecutiv|directiv|gerent|resumen|negocio|comercial|ventas|inversi|riesgo/i,
  },
  {
    presetId: "technical_detailed",
    reason: "El propósito apunta a trabajo técnico o de ingeniería.",
    match: /t[eé]cnic|api|sql|c[oó]digo|ingenier|infraestructura|log|servidor|esquema|integraci/i,
  },
  {
    presetId: "clear_didactic",
    reason: "El propósito menciona explicar, capacitar o dar soporte.",
    match: /explic|capacit|entren|ayuda|soporte|onboard|gu[ií]a|document|enseñ|formaci/i,
  },
  {
    presetId: "concise",
    reason: "El propósito pide respuestas breves.",
    match: /conciso|breve|r[aá]pido|resumido|una l[ií]nea/i,
  },
];

export const BALANCED_PRESET_ID = "balanced";

export function recommendAgentConfiguration(input: {
  purpose: string;
  sourceTypes: string[] | null;
  sourceKindLabels?: string[];
}): AgentRecommendation {
  const purpose = String(input.purpose || "");
  const reasons: string[] = [];
  let presetId = BALANCED_PRESET_ID;
  for (const rule of PRESET_RULES) {
    if (rule.match.test(purpose)) {
      presetId = rule.presetId;
      reasons.push(rule.reason);
      break;
    }
  }
  if (presetId === BALANCED_PRESET_ID) {
    reasons.push("Sin señales de estilo en el propósito: se usa el equilibrio recomendado.");
  }

  const sourceTypes = input.sourceTypes ?? [];
  const dbAvailable =
    sourceTypes.length === 0 || sourceTypes.some((type) => type === "sql" || type === "postgres" || type === "mysql" || type === "mssql" || type === "oracle" || type === "snowflake");
  const hasSources = sourceTypes.length > 0;
  const capabilities: CapabilityFlags = {
    knowledge: hasSources,
    data: hasSources && dbAvailable,
    integrations: false,
  };
  if (hasSources) reasons.push(`Hay ${input.sourceKindLabels?.length ?? sourceTypes.length} fuente(s) conectada(s): el agente puede consultarlas.`);
  if (capabilities.data) reasons.push("Hay fuentes de base de datos: la consulta de datos queda disponible.");

  const presetLabel =
    RESPONSE_PROFILE_PRESETS.find((preset) => preset.id === presetId)?.label ?? "Equilibrado";

  const decisions = [
    presetLabel,
    capabilities.knowledge ? "Consulta conocimiento" : "",
    capabilities.data ? "Consulta datos" : "",
    "JEV automático",
    "Modelo equilibrado",
  ].filter(Boolean);

  return {
    presetId,
    presetLabel,
    capabilities,
    model: DEFAULT_MODEL_ROUTE,
    decisions,
    reasons,
  };
}

/** Tono legacy (`config.tone`) que se conserva al guardar sin exponerlo en la UI. */
export function legacyTone(config: AgentConfig): AgentTone {
  return config.tone ?? "professional";
}
