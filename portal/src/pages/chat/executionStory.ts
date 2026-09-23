// =============================================================================
// Execution Story — de eventos canónicos a historia legible (§3, §36)
// =============================================================================
// Función pura y testeable: recibe el flow y devuelve la historia. Acá vive
// TODA la traducción semántica; los componentes sólo componen.
//
// Reglas:
// - El backend entrega semántica; acá se traduce a lenguaje humano.
// - Nunca se fabrican razones: si no hay señal, no se muestra "porque".
// - Los flows históricos (sin flow_version) se normalizan a los mismos eventos.
// - Nada de cadena de pensamiento: sólo hechos, veredictos y métricas.
// =============================================================================

export type Flow = Record<string, unknown>;

export type StoryStatus = "ok" | "warn" | "error" | "skipped" | "pending";

export type StoryPhaseId =
  | "understanding"
  | "context"
  | "planning"
  | "evidence"
  | "reasoning"
  | "decision"
  | "generation"
  | "verification"
  | "learning";

export type StoryEvidenceItem = {
  ref: string;
  title: string;
  authority?: string;
  relevance?: number;
  status: string;
};

export type StoryHypothesis = {
  id: string;
  statement: string;
  verdict: "SUPPORTED" | "REJECTED" | "UNRESOLVED";
  origin: string;
  supporting: number;
  contradicting: number;
  missing: string[];
  isUser: boolean;
};

export type StoryTransitionLink = {
  from: string;
  to: string;
  status: string;
  eventRef?: string;
};

export type StoryEvent = {
  id: string;
  phase: StoryPhaseId;
  kind: string;
  status: StoryStatus;
  durationMs?: number;
  title: string;
  detail?: string;
  statusLabel?: string;
  metrics: Record<string, unknown>;
  technical?: Record<string, unknown>;
  /** Clave semántica del backend cuando el evento es un incidente (fallback). */
  summaryKey?: string;
  evidence: StoryEvidenceItem[];
  hypotheses: StoryHypothesis[];
  transitions: StoryTransitionLink[];
  scenario?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  completion?: Record<string, unknown>;
  inference?: Record<string, unknown>;
  decisionReasonCodes: string[];
  /** Decisión compuesta del backend cuando el evento la trae (JEV, gates). */
  decisionAction?: string;
  decisionTier?: string;
  decisionAllowGeneration?: boolean;
  decisionApplied?: boolean;
};

export type StoryPhase = {
  id: StoryPhaseId;
  title: string;
  subtitle: string;
  status: StoryStatus;
  durationMs: number;
  events: StoryEvent[];
};

export type StoryIncident = {
  id: string;
  phase: StoryPhaseId;
  title: string;
  detail: string;
  status: StoryStatus;
};

export type StoryBreakdownRow = { label: string; ms: number; costUsd: number | null };

/** §36-§40: un juicio con su tipo, su decisión y su efecto. Sin CoT. */
export type StoryJudgment = {
  id: string;
  label: string;
  type: "choice" | "score" | "noul";
  typeLabel: string;
  version: number;
  decisionKey: string;
  decisionLabel: string;
  confidence?: number;
  value?: number;
  certainty?: number;
  scoreLabel?: string;
  ambiguous: boolean;
  effectKey?: string;
  effectLabel?: string;
  distribution?: Record<string, unknown>;
};

export type StoryReadinessRow = {
  key: string;
  label: string;
  state: string;
  stateLabel: string;
  confidence?: number;
  detail?: string;
  source: string;
};

export type StoryJudgmentPack = {
  id: string;
  phase: string;
  title: string;
  status: StoryStatus;
  judgmentCount: number;
  durationMs?: number;
  mode?: string;
  model?: string;
  cached: boolean;
  tokens?: { input: number; output: number };
  costUsd?: number;
  judgments: StoryJudgment[];
  effects: string[];
  effectLabels: string[];
  uncertain: string[];
  readiness: StoryReadinessRow[];
  actionLabel?: string;
  tierLabel?: string;
  allowGeneration?: boolean;
  applied?: boolean;
  reasonCodes: string[];
};

export type StoryJevImpact = {
  mode: string;
  headline: string;
  calls: number;
  judgments: number;
  decisionsInfluenced: number;
  uncertainCritical: number;
  escalationsAvoided: number;
  tierLabel?: string;
  expensiveModelAvoided: boolean;
  latencyMs?: number;
  costUsd?: number;
  facts: { label: string; value: string }[];
};


export type ExecutionStory = {
  version: number;
  legacy: boolean;
  status: string;
  headline: string;
  headlineStatus: StoryStatus;
  narrative: string;
  routeLabel: string;
  outcomeLabel: string;
  outcomeTone: "ok" | "warn" | "neutral";
  confidenceLabel: string;
  evidenceLabel: string;
  reasoningLabel: string;
  totalMs: number;
  costUsd: number | null;
  phases: StoryPhase[];
  incidents: StoryIncident[];
  breakdown: StoryBreakdownRow[];
  /** Juicios previos al generador, agrupados por pack (§35). */
  judgmentPacks: StoryJudgmentPack[];
  /** Efecto agregado del juicio previo (§42, §43). */
  jevImpact: StoryJevImpact | null;
  technical: {
    provider?: string;
    decider?: string;
    model?: string;
    jevUsed?: boolean;
    jevScore?: number | null;
    confidence?: number | null;
    tokens?: { prompt: number; completion: number; total: number };
    answerability?: Record<string, unknown>;
    pricing?: Record<string, unknown>;
    raw: Flow;
  };
};

// ---------------------------------------------------------------------------
// Traducciones (§5-§30, §38-§43)
// ---------------------------------------------------------------------------

export const PHASE_TITLES: Record<StoryPhaseId, string> = {
  understanding: "Entendió la pregunta",
  context: "Recuperó contexto empresarial",
  planning: "Diseñó el análisis",
  evidence: "Reunió evidencia",
  reasoning: "Reconstruyó el escenario",
  decision: "Decidió el camino",
  generation: "Redactó la respuesta",
  verification: "Verificó la respuesta",
  learning: "Qué aprendió Zent",
};

export const PHASE_ORDER: StoryPhaseId[] = [
  "understanding",
  "context",
  "planning",
  "evidence",
  "reasoning",
  "decision",
  "generation",
  "verification",
  "learning",
];

export const SHAPE_LABELS: Record<string, string> = {
  SIMPLE_LOOKUP: "Consulta directa",
  MULTI_EVIDENCE: "Combina varias evidencias",
  STATE_TRANSITION: "Análisis de secuencia",
  TEMPORAL_SEQUENCE: "Orden temporal",
  CONSISTENCY_CHECK: "Consistencia entre eventos",
  CAUSAL_ANALYSIS: "Análisis causal",
  DIAGNOSTIC: "Diagnóstico",
  HYPOTHESIS_TEST: "Contraste de hipótesis",
  COMPARATIVE_REASONING: "Comparación",
  GRAPH_REASONING: "Dependencias",
};

export const VERDICT_LABELS: Record<string, string> = {
  SUPPORTED: "Respaldada",
  REJECTED: "Descartada",
  UNRESOLVED: "Sin resolver",
};

export const AUTHORITY_LABELS: Record<string, string> = {
  authoritative: "Autoritativa",
  primary: "Principal",
  secondary: "Secundaria",
  informational: "Informativa",
  untrusted: "No confiable",
};

export const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  USED: "Utilizada",
  KEEP: "Utilizada",
  DISCARDED: "Descartada",
  DROP_IRRELEVANT: "No relevante",
  DROP_WEAK: "Evidencia débil",
  WEAK: "Evidencia débil",
  FLAG_CONTRADICTION: "En conflicto",
  CONTRADICTED: "En conflicto",
  DROP_INJECTION: "Contenido inseguro bloqueado",
  INJECTION_BLOCKED: "Contenido inseguro bloqueado",
};

/** Motivos de fallback y bloqueos → explicación humana. Nunca inventada. */
export const REASON_LABELS: Record<string, string> = {
  RECORD_LAYOUT_REQUIRED: "el layout de los registros",
  SEQUENCE_FIELD_POSITION_REQUIRED: "la posición del campo de secuencia",
  ACTION_CODE_SEMANTICS_REQUIRED: "la semántica de los action codes",
  SCHEMA_REQUIRED: "el esquema de los campos",
  STATE_UNRESOLVED: "los cambios de estado no demostrados",
  HYPOTHESIS_UNRESOLVED: "la hipótesis sin resolver",
  INFERENCE_UNSUPPORTED: "la inferencia no demostrada",
  TIMELINE_INCOMPLETE: "el orden temporal",
  GRAPH_RELATION_UNCONFIRMED: "las relaciones por confirmar",
  ANALYSIS_INCOMPLETE: "el análisis completo",
  scenario_incomplete: "el escenario completo",
  timeline_incomplete: "el timeline",
  state_unresolved: "la reconstrucción de estados",
  hypothesis_unresolved: "la hipótesis del usuario",
  inference_unsupported: "el soporte de la inferencia",
  contradictions_open: "contradicciones abiertas",
  required_facts_unresolved: "hechos requeridos sin resolver",
  graph_evidence_missing: "evidencia de grafo",
  grounding_failed: "la respuesta no quedó respaldada por las fuentes",
  claims_abstained: "las afirmaciones no se pudieron respaldar",
  claims_conflict: "afirmaciones en conflicto con la evidencia",
  claims_revised: "la respuesta necesitó una revisión",
  plan_failed: "el plan de búsqueda no pudo aplicarse",
  SEARCH_ERROR: "la búsqueda devolvió un error",
  no_results: "la búsqueda no encontró resultados",
  // Juicio previo (JEV Preflight)
  gate_not_satisfied: "el control previo a la generación",
  jev_only_signal: "sólo el juicio lo indicaba",
  deterministic_signals_ok: "las señales determinísticas estaban bien",
  cheaper_tier_sufficient: "el modelo pequeño bastaba",
  more_analysis_requested: "hacía falta más análisis",
  observed_only: "sólo se observó (modo shadow)",
  budget_prefers_small: "el presupuesto pedía el modelo pequeño",
  judge_unavailable: "JEV no estaba disponible",
  jev_unavailable: "JEV no estaba disponible",
  mode_off: "el juicio previo estaba apagado",
  no_questions: "no había preguntas que hacer",
  questions_unavailable: "las preguntas no se pudieron preparar",
  judgment_blocked_generation: "el juicio previo impidió generar",
};

const DECISION_KIND_TITLES: Record<string, string> = {
  decision: "Decidió cómo resolver la consulta",
  tool_routing: "Eligió qué herramienta usar",
  tool_filter: "Filtró las herramientas disponibles",
  router_fallback: "Usó el camino de respaldo",
  termination_gate: "Evaluó si ya podía responder",
  answer_gate: "Revisó la respuesta antes de enviarla",
  answer_revision: "Revisó y ajustó la respuesta",
  reasoning_incomplete: "Retuvo la respuesta: análisis incompleto",
  guardrail: "Aplicó una regla de seguridad",
};

const EVIDENCE_KIND_TITLES: Record<string, string> = {
  retrieval: "Buscó en el conocimiento",
  tool_call: "Consultó una herramienta",
  sql: "Consultó la base de datos",
  sources: "Reunió las fuentes",
  evidence: "Evaluó si la evidencia alcanzaba",
  fallback: "Activó un respaldo",
  grounding: "Comprobó el respaldo de la respuesta",
};

const REASONING_KIND_TITLES: Record<string, string> = {
  scenario_parse: "Interpretó el escenario",
  state_reconstruction: "Reconstruyó los cambios",
  timeline: "Ordenó los eventos",
  hypothesis_test: "Contrastó explicaciones",
};

/** §39: la herramienta elegida se nombra en lenguaje humano. */
const TOOL_TITLES: Record<string, string> = {
  search_knowledge: "Consultó el conocimiento",
  query_database: "Consultó la base de datos",
  call_api: "Consultó una API",
  search_sources: "Consultó las fuentes",
  run_workflow: "Ejecutó un workflow",
};

export function toolTitle(tool: string): string {
  const key = tool.trim().toLowerCase();
  if (!key) return "Consultó una herramienta";
  return TOOL_TITLES[key] ?? `Consultó ${tool}`;
}

const UNDERSTANDING_KIND_TITLES: Record<string, string> = {
  reasoning_classification: "Entendió qué tipo de análisis necesitaba",
};

const VERIFICATION_KIND_TITLES: Record<string, string> = {
  inference_verification: "Verificó que la conclusión se desprenda de los hechos",
  analysis_completion: "Verificó que el análisis estuviera completo",
};

export function kindTitle(kind: string): string {
  return (
    REASONING_KIND_TITLES[kind] ??
    UNDERSTANDING_KIND_TITLES[kind] ??
    VERIFICATION_KIND_TITLES[kind] ??
    DECISION_KIND_TITLES[kind] ??
    EVIDENCE_KIND_TITLES[kind] ??
    (kind === "generation" ? "Redactó la respuesta" : kind.replace(/_/g, " "))
  );
}

function eventTitle(kind: string, technical: Record<string, unknown>): string {
  if (kind === "tool_call") {
    const tool = String(technical.tool ?? "");
    if (tool) return toolTitle(tool);
  }
  return kindTitle(kind);
}

export function reasonText(code: string): string {
  // §40: los motivos del juicio se enuncian por pregunta, no por id crudo.
  if (code.startsWith("unsatisfied_")) {
    return `faltaba: ${questionLabel(code.slice("unsatisfied_".length))}`;
  }
  if (code.startsWith("action_")) {
    return `decidió ${judgmentValueLabel(code.slice("action_".length)).toLowerCase()}`;
  }
  return REASON_LABELS[code] ?? code.replace(/_/g, " ").toLowerCase();
}

export function shapeLabel(shape: unknown): string {
  const key = String(shape ?? "").toUpperCase();
  return SHAPE_LABELS[key] ?? "";
}

export function statusLabel(status: StoryStatus): string {
  switch (status) {
    case "ok":
      return "Completado";
    case "warn":
      return "Requiere atención";
    case "error":
      return "No se pudo completar";
    case "skipped":
      return "No aplicó";
    default:
      return "Pendiente";
  }
}

export function authorityLabel(authority: unknown): string {
  return AUTHORITY_LABELS[String(authority ?? "").toLowerCase()] ?? "";
}

export function evidenceStatusLabel(status: unknown): string {
  const key = String(status ?? "").toUpperCase();
  return EVIDENCE_STATUS_LABELS[key] ?? "Utilizada";
}

export function verdictLabel(verdict: unknown): string {
  return VERDICT_LABELS[String(verdict ?? "").toUpperCase()] ?? "Sin resolver";
}

// ---------------------------------------------------------------------------
// JEV — traducción del juicio previo (§35-§52)
// ---------------------------------------------------------------------------

/** §35: cada pack se nombra por su momento, no por su id técnico. */
export const JUDGMENT_PACK_TITLES: Record<string, string> = {
  pre_reasoning: "Preparación",
  post_retrieval: "Evidencia",
  post_reconstruction: "Reconstrucción",
  pre_generation: "Antes de generar",
  post_generation: "Verificación",
  agent_step: "Paso del agente",
};

/** §52: la pregunta en lenguaje humano. Sin traducción, se muestra el id. */
export const QUESTION_LABELS: Record<string, string> = {
  reasoning_shape: "¿Qué tipo de análisis necesita?",
  preferred_capability: "¿De dónde deben venir los hechos?",
  analysis_complexity: "¿Qué complejidad tiene el análisis?",
  needs_private_knowledge: "¿Necesita conocimiento privado?",
  needs_multiple_evidence: "¿Necesita múltiples evidencias?",
  needs_structured_data: "¿Necesita datos estructurados?",
  needs_graph: "¿Necesita relaciones del grafo?",
  needs_timeline: "¿Necesita línea de tiempo?",
  needs_state_reconstruction: "¿Necesita reconstruir el estado?",
  needs_hypothesis_testing: "¿Necesita contrastar hipótesis?",
  simple_lookup_sufficient: "¿Basta una consulta simple?",
  scenario_completeness: "¿Qué tan completo quedó el escenario?",
  state_reconstruction_quality: "¿Qué tan sólida es la reconstrucción?",
  rule_coverage: "¿Las reglas cubren el caso?",
  timeline_coherent: "¿La secuencia temporal es coherente?",
  critical_transition_missing: "¿Falta una transición crítica?",
  hypothesis_user_supported: "¿La explicación del usuario está respaldada?",
  hypothesis_user_contradicted: "¿La explicación del usuario está contradicha?",
  alternative_hypothesis_supported: "¿Hay una explicación alternativa respaldada?",
  inference_possible: "¿La conclusión se desprende de los hechos?",
  critical_unknown_remaining: "¿Queda algún desconocido crítico?",
  analysis_complete: "¿El análisis está completo?",
  answerable_from_current_evidence: "¿Se puede responder con la evidencia actual?",
  critical_fact_missing: "¿Falta información crítica?",
  critical_conflict_unresolved: "¿Hay un conflicto sin resolver?",
  inference_supported: "¿La conclusión se desprende de los hechos?",
  expensive_llm_needed: "¿Hace falta razonamiento generativo avanzado?",
  simple_deterministic_answer_possible: "¿Basta una respuesta determinística?",
  needs_complex_reasoning_model: "¿Necesita un modelo de razonamiento?",
  answer_readiness: "¿Qué tan lista está la respuesta?",
  evidence_strength: "¿Qué fuerza tiene la evidencia?",
  risk_of_wrong_answer: "¿Qué riesgo hay de responder mal?",
  generation_complexity: "¿Qué complejidad tiene la redacción?",
  next_action: "¿Qué corresponde hacer ahora?",
  generation_tier: "¿Qué nivel de generación necesita?",
  evidence_sufficient: "¿Ya tiene evidencia suficiente?",
  evidence_on_topic: "¿La evidencia es del tema?",
  evidence_direct: "¿Hay evidencia directa?",
  evidence_quality: "¿Qué calidad tiene la evidencia?",
  answer_grounded: "¿La respuesta está respaldada?",
  answer_complete: "¿La respuesta está completa?",
  answer_addresses_question: "¿Responde la pregunta formulada?",
  answer_contains_unsupported_conclusion: "¿Incluye una conclusión sin respaldo?",
  answer_overstates_uncertainty: "¿Exagera la certeza?",
  answer_ignores_material_conflict: "¿Ignora un conflicto material?",
  answer_quality: "¿Qué calidad tiene la respuesta?",
  clarity: "¿Qué tan clara es la respuesta?",
  evidence_alignment: "¿Qué tan alineada está con la evidencia?",
  final_action: "¿Qué hacemos con esta respuesta?",
};

/** §40: el efecto dice si el juicio CAMBIÓ algo. */
export const EFFECT_LABELS: Record<string, string> = {
  fast_path_selected: "eligió el camino rápido",
  multi_evidence_required: "exigió varias fuentes",
  timeline_required: "activó la línea de tiempo",
  state_reconstruction_activated: "activó la reconstrucción de estados",
  graph_traversal_activated: "activó el grafo",
  hypothesis_testing_activated: "activó el contraste de hipótesis",
  structured_lookup_required: "pidió datos estructurados",
  retrieval_required: "pidió búsqueda de evidencia",
  reasoning_shape_selected: "fijó el tipo de análisis",
  source_family_selected: "fijó la familia de fuentes",
  state_chain_incomplete: "marcó la cadena de estados incompleta",
  timeline_conflict: "detectó un conflicto temporal",
  user_hypothesis_rejected: "descartó la explicación del usuario",
  user_hypothesis_supported: "respaldó la explicación del usuario",
  alternative_explanation_active: "dejó activa una explicación alternativa",
  inference_blocked: "bloqueó la inferencia",
  unknown_blocks_conclusion: "un desconocido impide concluir",
  hypothesis_supported: "respaldó una explicación",
  hypothesis_rejected: "descartó una explicación",
  generation_allowed: "habilitó la generación",
  generation_blocked: "bloqueó la generación",
  retrieval_round_requested: "pidió otra ronda de búsqueda",
  reconstruction_requested: "pidió reconstruir más",
  user_input_requested: "pidió intervención del usuario",
  generation_skipped: "omitió el generador",
  generation_tier_deterministic: "respondió sin generador",
  generation_tier_small: "usó el modelo pequeño",
  generation_tier_standard: "usó el modelo estándar",
  generation_tier_reasoning: "usó el modelo de razonamiento",
  expensive_model_avoided: "evitó el modelo caro",
  deterministic_answer_possible: "la conclusión ya estaba establecida",
  critical_fact_missing: "faltaba un dato crítico",
  critical_conflict: "quedó un conflicto abierto",
  analysis_incomplete: "el análisis estaba incompleto",
  inference_unsupported: "la inferencia no se sostenía",
  low_risk_of_wrong_answer: "riesgo bajo de responder mal",
  answer_ready: "la respuesta estaba lista",
  scenario_incomplete: "el escenario quedó incompleto",
  ungrounded_answer: "la respuesta no quedó respaldada",
  unsupported_conclusion: "había una conclusión sin respaldo",
  overstated_certainty: "exageraba la certeza",
  conflict_not_disclosed: "no declaró un conflicto",
  answer_incomplete: "la respuesta quedó incompleta",
  answer_approved: "aprobó la respuesta",
  revision_requested: "pidió una revisión",
  answer_abstained: "retuvo la respuesta",
};

/** Valores de Choice / Noul / tier / acción en lenguaje humano. */
export const JUDGMENT_VALUE_LABELS: Record<string, string> = {
  simple_lookup: "Consulta directa",
  multi_evidence: "Múltiples evidencias",
  state_transition: "Transición de estado",
  temporal_sequence: "Secuencia temporal",
  consistency_check: "Consistencia",
  causal_analysis: "Análisis causal",
  diagnostic: "Diagnóstico",
  hypothesis_test: "Contraste de hipótesis",
  graph_reasoning: "Relaciones del grafo",
  documents: "Documentos",
  structured: "Datos estructurados",
  graph: "Grafo",
  tool: "Herramienta",
  workflow: "Workflow",
  direct: "Sin fuentes",
  generate_answer: "Generar la respuesta",
  retrieve_more: "Buscar más evidencia",
  reconstruct_more: "Reconstruir más",
  ask_user: "Preguntar al usuario",
  abstain: "Abstenerse",
  deterministic_answer: "Responder con hechos establecidos",
  deterministic: "Sin generador",
  small: "Modelo pequeño",
  standard: "Modelo estándar",
  reasoning: "Modelo de razonamiento",
  approve: "Aprobar",
  revise: "Revisar",
  yes: "Sí",
  no: "No",
  uncertain: "Incierto",
};

/** Niveles de Score: se traducen los adjetivos declarados en los criterios. */
export const SCORE_LEVEL_LABELS: Record<string, string> = {
  empty: "Sin evidencia",
  weak: "Débil",
  partial: "Parcial",
  adequate: "Adecuada",
  usable: "Utilizable",
  good: "Buena",
  strong: "Fuerte",
  excellent: "Excelente",
  complete: "Completa",
  conclusive: "Concluyente",
  unreliable: "No confiable",
  sound: "Sólida",
  negligible: "Despreciable",
  low: "Bajo",
  material: "Material",
  high: "Alto",
  "not ready": "No lista",
  "partially ready": "Parcialmente lista",
  ready: "Lista",
  "fully ready": "Totalmente lista",
};

export const READINESS_ROW_LABELS: Record<string, string> = {
  evidence: "Evidencia",
  scenario: "Escenario",
  state: "Estado",
  hypothesis: "Hipótesis",
  inference: "Inferencia",
  conflicts: "Conflictos",
  answerability: "Answerability",
  llm: "LLM",
};

export const READINESS_STATE_LABELS: Record<string, string> = {
  ok: "Listo",
  warn: "Con reservas",
  blocked: "Bloqueado",
  unknown: "Sin dato",
};

export const JUDGMENT_TYPE_LABELS: Record<string, string> = {
  choice: "Elección",
  score: "Nivel",
  noul: "Sí/No",
};

export function questionLabel(id: string): string {
  return QUESTION_LABELS[id] ?? id.replace(/_/g, " ");
}

export function effectLabel(key: string): string {
  return EFFECT_LABELS[key] ?? key.replace(/_/g, " ");
}

export function judgmentValueLabel(key: string): string {
  return JUDGMENT_VALUE_LABELS[key] ?? key.replace(/_/g, " ");
}

export function scoreLevelLabel(key: string): string {
  return SCORE_LEVEL_LABELS[key.toLowerCase()] ?? key;
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function record(value: unknown): Flow {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Flow)
    : {};
}

function list(value: unknown): Flow[] {
  return Array.isArray(value)
    ? value.filter((item): item is Flow => !!item && typeof item === "object")
    : [];
}

function num(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function str(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function status(value: unknown): StoryStatus {
  const key = str(value).toLowerCase();
  if (key === "warn" || key === "warning") return "warn";
  if (key === "error" || key === "failed") return "error";
  if (key === "skipped") return "skipped";
  if (key === "pending") return "pending";
  return "ok";
}

const PHASE_BY_KIND: Record<string, StoryPhaseId> = {
  reasoning_classification: "understanding",
  context: "context",
  company_context: "context",
  reasoning_plan: "planning",
  decision: "decision",
  tool_routing: "decision",
  tool_filter: "decision",
  router_fallback: "decision",
  termination_gate: "decision",
  answer_gate: "verification",
  reasoning_incomplete: "verification",
  answer_revision: "verification",
  scenario_parse: "reasoning",
  state_reconstruction: "reasoning",
  timeline: "reasoning",
  hypothesis_test: "reasoning",
  inference_verification: "verification",
  analysis_completion: "verification",
  tool_call: "evidence",
  guardrail: "verification",
  retrieval: "evidence",
  sql: "evidence",
  sources: "evidence",
  evidence: "evidence",
  fallback: "verification",
  grounding: "verification",
  generation: "generation",
  final: "generation",
  llm: "generation",
  memory: "learning",
};

function toHypotheses(value: unknown): StoryHypothesis[] {
  const payload = record(value);
  return list(payload.items).map((item, index) => ({
    id: str(item.id) || `hyp-${index}`,
    statement: str(item.statement),
    verdict: (str(item.verdict).toUpperCase() as StoryHypothesis["verdict"]) || "UNRESOLVED",
    origin: str(item.origin) || "USER",
    supporting: num(item.supporting) ?? 0,
    contradicting: num(item.contradicting) ?? 0,
    missing: Array.isArray(item.missing_requirements)
      ? (item.missing_requirements as unknown[]).map((entry) => str(entry))
      : [],
    isUser: item.is_user_hypothesis === true,
  }));
}

function toEvidence(value: unknown): StoryEvidenceItem[] {
  return list(value).map((item, index) => ({
    ref: str(item.ref) || `source-${index}`,
    title: str(item.title),
    authority: item.authority ? str(item.authority) : undefined,
    relevance: num(item.relevance),
    status: str(item.status) || "USED",
  }));
}

function toTransitions(value: unknown): StoryTransitionLink[] {
  return list(value).map((item) => ({
    from: str(item.from),
    to: str(item.to),
    status: str(item.status) || "UNRESOLVED",
    eventRef: item.event_ref ? str(item.event_ref) : undefined,
  }));
}

// ---------------------------------------------------------------------------
// Juicios JEV (§36-§44): lectura de lo que el backend ya decidió
// ---------------------------------------------------------------------------

function judgmentType(value: unknown): StoryJudgment["type"] {
  const key = str(value).toLowerCase();
  if (key === "choice" || key === "score" || key === "noul") return key;
  return "noul";
}

function judgmentDecision(
  type: StoryJudgment["type"],
  decisionKey: string,
  value: unknown,
): string {
  if (!decisionKey) return "Sin dato";
  if (type === "noul") {
    if (decisionKey === "yes") return "Sí";
    if (decisionKey === "no") return "No";
    if (decisionKey === "uncertain") return "Incierto";
  }
  if (type === "choice") return judgmentValueLabel(decisionKey);
  if (type === "score") {
    const numeric = num(value);
    const level = scoreLevelLabel(decisionKey);
    return numeric !== undefined ? `${level} · ${numeric.toFixed(2)} / 3` : level;
  }
  return decisionKey;
}

function toJudgments(value: unknown): StoryJudgment[] {
  return list(value).map((item) => {
    const type = judgmentType(item.type);
    const decisionKey = str(item.decision);
    const distribution = Object.keys(record(item.distribution)).length
      ? record(item.distribution)
      : undefined;
    return {
      id: str(item.id),
      label: questionLabel(str(item.id)),
      type,
      typeLabel: JUDGMENT_TYPE_LABELS[type] ?? type,
      version: num(item.version) ?? 0,
      decisionKey,
      decisionLabel: judgmentDecision(type, decisionKey, item.value),
      confidence: num(item.confidence),
      value: num(item.value),
      certainty: num(item.certainty),
      scoreLabel: type === "score" ? scoreLevelLabel(str(item.decision)) : undefined,
      ambiguous: item.ambiguous === true,
      effectKey: item.effect ? str(item.effect) : undefined,
      effectLabel: item.effect ? effectLabel(str(item.effect)) : undefined,
      distribution,
    };
  });
}

function toReadiness(value: unknown): StoryReadinessRow[] {
  return list(record(value).rows).map((row) => {
    const key = str(row.key);
    const state = str(row.state) || "unknown";
    return {
      key,
      label: READINESS_ROW_LABELS[key] ?? key,
      state,
      stateLabel: READINESS_STATE_LABELS[state] ?? state,
      confidence: num(row.confidence),
      detail: row.detail ? str(row.detail) : undefined,
      source: str(row.source) || "deterministic",
    };
  });
}

/** Un pack JEV por evento `jev_pack`: un llamado, N juicios, un efecto (§35). */
export function toJudgmentPacks(events: StoryEvent[]): StoryJudgmentPack[] {
  return events
    .filter((event) => event.kind === "jev_pack")
    .map((event) => {
      const metrics = record(event.metrics);
      const technical = record(event.technical);
      const phase = str(metrics.phase);
      const judgments = toJudgments(metrics.questions);
      const effects = Array.isArray(metrics.effects)
        ? (metrics.effects as unknown[]).map((item) => str(item))
        : [];
      const uncertain = Array.isArray(metrics.uncertain)
        ? (metrics.uncertain as unknown[]).map((item) => str(item))
        : judgments.filter((item) => item.decisionKey === "uncertain").map((item) => item.id);
      const tokens = record(technical.tokens);
      const tier = str(event.decisionTier ?? "");
      return {
        id: event.id,
        phase,
        title: JUDGMENT_PACK_TITLES[phase] ?? phase.replace(/_/g, " "),
        status: event.status,
        judgmentCount: num(metrics.judgment_count) ?? judgments.length,
        durationMs: event.durationMs,
        mode: technical.mode ? str(technical.mode) : undefined,
        model: technical.model ? str(technical.model) : undefined,
        cached: technical.cached === true,
        tokens:
          num(tokens.input) || num(tokens.output)
            ? { input: num(tokens.input) ?? 0, output: num(tokens.output) ?? 0 }
            : undefined,
        costUsd: num(technical.cost_usd),
        judgments,
        effects,
        effectLabels: effects.map(effectLabel),
        uncertain,
        readiness: toReadiness(metrics.readiness),
        actionLabel: event.decisionAction ? judgmentValueLabel(event.decisionAction) : undefined,
        tierLabel: tier ? judgmentValueLabel(tier) : undefined,
        allowGeneration: event.decisionAllowGeneration,
        applied: event.decisionApplied,
        reasonCodes: event.decisionReasonCodes,
      };
    });
}

function buildJevImpact(
  flow: Flow,
  packs: StoryJudgmentPack[],
): StoryJevImpact | null {
  const block = record(flow.jev_preflight);
  if (!packs.length && !Object.keys(block).length) return null;
  const summary = record(block.summary);
  const decisions = list(block.decisions);
  const preGeneration = decisions.find((entry) => str(entry.phase) === "pre_generation");
  const tier = str(preGeneration?.tier);
  const calls = num(summary.calls) ?? packs.length;
  const judgments =
    num(summary.judgments) ?? packs.reduce((total, pack) => total + pack.judgmentCount, 0);
  const uncertain = num(summary.uncertain_critical_judgments) ?? 0;
  const influenced = num(summary.decisions_influenced) ?? 0;
  const avoided = num(summary.llm_escalations_avoided) ?? 0;
  const facts: { label: string; value: string }[] = [];
  facts.push({
    label: "Llamadas",
    value: `${calls} ${calls === 1 ? "llamada" : "llamadas"} agrupadas`,
  });
  facts.push({ label: "Juicios", value: `${judgments}` });
  facts.push({ label: "Decisiones influidas", value: `${influenced}` });
  if (uncertain) facts.push({ label: "Juicios críticos inciertos", value: `${uncertain}` });
  if (avoided) facts.push({ label: "Generación cara evitada", value: `${avoided}` });
  const latency = num(summary.latency_ms);
  if (latency) facts.push({ label: "Tiempo de juicio", value: `${Math.round(latency)} ms` });
  const cost = num(summary.cost_usd);
  if (cost) facts.push({ label: "Costo del juicio", value: `$${cost.toFixed(5)}` });
  return {
    mode: str(block.mode) || "off",
    headline:
      judgments > 0
        ? `Zent hizo ${judgments} comprobaciones antes de generar`
        : "Juicio previo registrado",
    calls,
    judgments,
    decisionsInfluenced: influenced,
    uncertainCritical: uncertain,
    escalationsAvoided: avoided,
    tierLabel: tier ? judgmentValueLabel(tier) : undefined,
    expensiveModelAvoided: tier === "small" || tier === "deterministic",
    latencyMs: latency,
    costUsd: cost,
    facts,
  };
}

// ---------------------------------------------------------------------------
// Normalización: eventos canónicos (v2) y flows históricos
// ---------------------------------------------------------------------------

function canonicalEvent(raw: Flow, index: number): StoryEvent {
  const phase = (str(raw.phase) as StoryPhaseId) || PHASE_BY_KIND[str(raw.kind)] || "generation";
  const technical = record(raw.technical);
  const metrics = record(raw.metrics);
  const decision = record(raw.decision);
  const evidence = toEvidence(record(technical).items ?? metrics.items);
  const reasonCodes = Array.isArray(decision.reason_codes)
    ? (decision.reason_codes as unknown[]).map((code) => str(code))
    : [];
  return {
    id: str(raw.id) || `event-${index}`,
    phase,
    kind: str(raw.kind) || "step",
    status: status(raw.status),
    durationMs: num(raw.duration_ms),
    title: eventTitle(str(raw.kind), technical),
    statusLabel: raw.status_label ? str(raw.status_label) : undefined,
    metrics,
    technical,
    summaryKey: raw.summary ? str(raw.summary) : undefined,
    evidence,
    hypotheses: toHypotheses(metrics.hypotheses),
    transitions: toTransitions(record(metrics.transitions).chain),
    scenario: Object.keys(record(metrics.scenario)).length ? record(metrics.scenario) : undefined,
    plan: Object.keys(record(metrics.plan)).length ? record(metrics.plan) : undefined,
    completion: Object.keys(record(metrics.completion)).length
      ? record(metrics.completion)
      : undefined,
    inference: Object.keys(record(metrics.inference)).length
      ? record(metrics.inference)
      : undefined,
    decisionReasonCodes: reasonCodes,
    decisionAction: decision.action ? str(decision.action) : undefined,
    decisionTier: decision.tier ? str(decision.tier) : undefined,
    decisionAllowGeneration:
      typeof decision.allow_generation === "boolean" ? decision.allow_generation : undefined,
    decisionApplied: typeof decision.applied === "boolean" ? decision.applied : undefined,
  };
}

/** §64: flows sin `flow_version` se adaptan a la misma forma canónica. */
export function normalizeLegacyFlow(flow: Flow): StoryEvent[] {
  const events: Flow[] = [];
  const steps = list(flow.steps);
  for (const [index, step] of steps.entries()) {
    const kind = str(step.type || step.kind);
    if (!kind) continue;
    const phase = PHASE_BY_KIND[kind];
    if (!phase) continue;
    const payload: Flow = { ...record(step[keyForKind(kind)]) };
    events.push({
      id: str(step.id) || `step-${index}`,
      phase,
      kind,
      status: step.status ?? "ok",
      duration_ms: step.duration_ms ?? step.latency_ms ?? step.ms,
      metrics: payload,
      // Los steps históricos guardan la herramienta y el detalle en el propio
      // step: se preservan para poder nombrarlos en la historia.
      technical: {
        tool: step.tool,
        detail: step.detail,
        model: step.model,
      },
    });
  }
  const sources = list(flow.sources).map((source) => ({
    ref: str(source.document_id),
    title: str(source.title),
    relevance: source.score,
    authority: source.authority,
    status: source.status ?? "USED",
  }));
  const retrieval = record(flow.retrieval);
  if (retrieval.used === true || num(retrieval.chunks)) {
    events.push({
      id: "legacy-retrieval",
      phase: "evidence",
      kind: "retrieval",
      status: "ok",
      duration_ms: retrieval.ms,
      metrics: {
        chunks: retrieval.chunks,
        sources_total: sources.length,
        sources_used: sources.length,
        top_score: retrieval.top_score,
      },
    });
  }
  if (sources.length) {
    events.push({
      id: "legacy-sources",
      phase: "evidence",
      kind: "sources",
      status: "ok",
      metrics: { sources: sources.length },
      technical: { items: sources },
    });
  }
  const sql = record(flow.sql);
  if (Object.keys(sql).length) {
    events.push({
      id: "legacy-sql",
      phase: "evidence",
      kind: "sql",
      status: "ok",
      duration_ms: sql.ms,
      metrics: { rows: sql.rows },
    });
  }
  const decision = record(flow.decision);
  if (Object.keys(decision).length) {
    events.push({
      id: "legacy-decision",
      phase: "decision",
      kind: "decision",
      status: decision.evaluated === false ? "skipped" : decision.fallback_used ? "warn" : "ok",
      duration_ms: decision.ms,
      technical: {
        provider: decision.provider,
        capability: decision.capability,
        confidence: decision.confidence,
        jev_used: decision.jev_used,
      },
    });
  }
  const generation = record(flow.generation);
  if (Object.keys(generation).length) {
    events.push({
      id: "legacy-generation",
      phase: "generation",
      kind: "generation",
      status: generation.skipped ? "skipped" : "ok",
      duration_ms: generation.ms,
      metrics: {
        prompt_tokens: generation.prompt_tokens,
        completion_tokens: generation.completion_tokens,
        total_tokens: generation.total_tokens,
        cost_usd: generation.cost,
      },
      technical: { model: generation.model },
    });
  }
  const grounding = record(flow.grounding);
  if (Object.keys(grounding).length) {
    events.push({
      id: "legacy-grounding",
      phase: "verification",
      kind: "grounding",
      status: grounding.grounded ? "ok" : "warn",
      duration_ms: grounding.ms,
      metrics: { score: grounding.score, grounded: grounding.grounded },
    });
  }
  const evidence = record(flow.evidence);
  if (Object.keys(evidence).length) {
    events.push({
      id: "legacy-evidence",
      phase: "evidence",
      kind: "evidence",
      status: evidence.sufficient ? "ok" : "warn",
      duration_ms: evidence.ms,
      metrics: {
        score: evidence.score,
        sufficient: evidence.sufficient,
        items: evidence.items,
      },
    });
  }
  for (const [index, fallback] of (Array.isArray(flow.fallbacks) ? flow.fallbacks : []).entries()) {
    events.push({
      id: `legacy-fallback-${index}`,
      phase: "verification",
      kind: "fallback",
      status: "warn",
      technical: { raw: str(fallback) },
    });
  }
  const order = new Map(PHASE_ORDER.map((phase, position) => [phase, position]));
  return events
    .map((event, index) => canonicalEvent(event, index))
    .sort((left, right) => (order.get(left.phase) ?? 99) - (order.get(right.phase) ?? 99));
}

function keyForKind(kind: string): string {
  switch (kind) {
    case "reasoning_classification":
      return "reasoning";
    case "company_context":
      return "company_context";
    case "reasoning_plan":
      return "plan";
    case "scenario_parse":
      return "scenario";
    case "state_reconstruction":
      return "transitions";
    case "timeline":
      return "timeline";
    case "hypothesis_test":
      return "hypotheses";
    case "inference_verification":
      return "inference";
    case "analysis_completion":
      return "completion";
    default:
      return kind;
  }
}

export function storyEvents(flow: Flow): { events: StoryEvent[]; legacy: boolean } {
  const canonical = list(flow.events);
  if (canonical.length) {
    return { events: canonical.map((event, index) => canonicalEvent(event, index)), legacy: false };
  }
  return { events: normalizeLegacyFlow(flow), legacy: true };
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

export function buildExecutionStory(flow: Flow | null | undefined): ExecutionStory {
  const safe = record(flow);
  const { events: rawEvents, legacy } = storyEvents(safe);
  const events = enrichCompletionEvents(rawEvents);

  const phases: StoryPhase[] = [];
  for (const id of PHASE_ORDER) {
    const phaseEvents = events.filter((event) => event.phase === id);
    if (!phaseEvents.length) continue;
    const worst = worstStatus(phaseEvents.map((event) => event.status));
    phases.push({
      id,
      title: PHASE_TITLES[id],
      subtitle: phaseSubtitle(id, phaseEvents),
      status: worst,
      durationMs: phaseEvents.reduce((total, event) => total + (event.durationMs ?? 0), 0),
      events: phaseEvents,
    });
  }

  const incidents = events
    .filter((event) => event.status === "warn" || event.status === "error")
    .map((event) => ({
      id: `${event.id}-incident`,
      phase: event.phase,
      title: event.title,
      detail: incidentDetail(event),
      status: event.status,
    }));

  const decision = record(safe.decision);
  const verdict = record(safe.verdict);
  const generation = record(safe.generation);
  const grounding = groundingFor(safe, events);
  const jev = record(safe.jev);
  const totalMs = num(record(safe.timings).total_ms) ?? num(safe.total_ms) ?? 0;
  const reasoningShape = events
    .flatMap((event) => [str(record(event.metrics.reasoning).shape)])
    .find(Boolean);
  const completion = events.find((event) => event.completion)?.completion;
  const analysisComplete = completion ? completion.complete !== false : undefined;
  const sourcesEvent = events.find((event) => event.kind === "sources");
  const sourcesCount =
    num(record(sourcesEvent?.metrics).sources) ?? list(safe.sources).length;
  const costUsd = num(record(generation).cost);
  const hasReasoning = phases.some((phase) => phase.id === "reasoning");
  const judgmentPacks = toJudgmentPacks(events);
  const jevImpact = buildJevImpact(safe, judgmentPacks);

  return {
    version: num(safe.flow_version) ?? (legacy ? 1 : 2),
    legacy,
    status: str(safe.status) || "completed",
    headline: headlineFor(str(safe.status), analysisComplete),
    headlineStatus: str(safe.status) === "completed" ? "ok" : "warn",
    narrative: narrativeFor({ events, sourcesCount, analysisComplete }),
    routeLabel: routeLabelFor(safe, events),
    outcomeLabel: outcomeLabelFor(grounding),
    outcomeTone: grounding.grounded === false ? "warn" : grounding.grounded ? "ok" : "neutral",
    confidenceLabel: confidenceLabelFor(num(decision.confidence)),
    evidenceLabel: sourcesCount ? `${sourcesCount} fuente${sourcesCount === 1 ? "" : "s"}` : "",
    // El razonamiento sólo se anuncia cuando la historia lo demuestra.
    reasoningLabel: hasReasoning
      ? shapeLabel(reasoningShape) || "Análisis secuencial"
      : "",
    totalMs,
    costUsd: costUsd ?? null,
    phases,
    incidents,
    breakdown: breakdownFor(phases, generation),
    judgmentPacks,
    jevImpact,
    technical: {
      provider: str(decision.provider) || undefined,
      decider: str(verdict.decider) || undefined,
      model: str(generation.model) || undefined,
      jevUsed: typeof jev.used === "boolean" ? jev.used : undefined,
      jevScore: num(jev.score) ?? null,
      confidence: num(decision.confidence) ?? null,
      tokens: {
        prompt: num(generation.prompt_tokens) ?? 0,
        completion: num(generation.completion_tokens) ?? 0,
        total: num(generation.total_tokens) ?? 0,
      },
      answerability: Object.keys(record(safe.answerability)).length
        ? record(safe.answerability)
        : undefined,
      pricing: Object.keys(record(safe.pricing)).length ? record(safe.pricing) : undefined,
      raw: safe,
    },
  };
}

function worstStatus(statuses: StoryStatus[]): StoryStatus {
  const rank: StoryStatus[] = ["error", "warn", "pending", "ok", "skipped"];
  return rank.find((candidate) => statuses.includes(candidate)) ?? "ok";
}

function phaseSubtitle(id: StoryPhaseId, events: StoryEvent[]): string {
  const parts: string[] = [];
  if (id === "understanding") {
    const shape = events.map((event) => str(record(event.metrics.reasoning).shape)).find(Boolean);
    if (shape) parts.push(shapeLabel(shape) || shape);
  }
  if (id === "context") {
    const counts = record(events.find((event) => event.kind === "company_context")?.metrics
      ?.company_context);
    for (const [key, label] of [
      ["concepts", "conceptos"],
      ["rules", "reglas"],
      ["systems", "sistemas"],
      ["processes", "procesos"],
      ["memories", "memorias"],
    ] as const) {
      const value = num(counts[key]);
      if (value) parts.push(`${value} ${label}`);
    }
  }
  if (id === "planning") {
    const operations = list(record(events[0]?.plan).operations);
    if (operations.length) parts.push(`${operations.length} pasos requeridos`);
  }
  if (id === "evidence") {
    const retrieval = events.find((event) => event.kind === "retrieval");
    const used = num(record(retrieval?.metrics).sources_used);
    const found = num(record(retrieval?.metrics).sources_total);
    if (found) parts.push(`${found} fuentes`);
    if (used && found && used !== found) parts.push(`${used} utilizadas`);
  }
  if (id === "reasoning") {
    const scenario = events.find((event) => event.scenario)?.scenario;
    const transitions = events.find((event) => event.transitions.length)?.transitions;
    const hypotheses = events.flatMap((event) => event.hypotheses);
    const scenarioEvents = num(record(scenario).events);
    if (scenarioEvents) parts.push(`${scenarioEvents} eventos`);
    if (transitions?.length) parts.push(`${transitions.length} transiciones`);
    if (hypotheses.length) {
      const supported = hypotheses.filter((item) => item.verdict === "SUPPORTED").length;
      const rejected = hypotheses.filter((item) => item.verdict === "REJECTED").length;
      if (supported) parts.push(`${supported} respaldada${supported === 1 ? "" : "s"}`);
      if (rejected) parts.push(`${rejected} descartada${rejected === 1 ? "" : "s"}`);
    }
  }
  if (id === "generation") {
    const tokens = num(record(events[0]?.metrics).total_tokens);
    if (tokens) parts.push(`${tokens} tokens`);
  }
  if (id === "verification") {
    const completion = events.find((event) => event.completion)?.completion;
    if (completion) {
      parts.push(completion.complete === false ? "análisis incompleto" : "análisis completo");
    }
    const inference = events.find((event) => event.inference)?.inference;
    const verdicts = list(record(inference).verdicts);
    const unsupported = verdicts.filter((item) => str(item.verdict) !== "SUPPORTED").length;
    if (unsupported) parts.push(`${unsupported} inferencia sin respaldo`);
  }
  // §35: el juicio previo se anuncia en la fase donde ocurrió.
  const judgmentEvents = events.filter((event) => event.kind === "jev_pack");
  if (judgmentEvents.length) {
    const total = judgmentEvents.reduce(
      (sum, event) => sum + (num(record(event.metrics).judgment_count) ?? 0),
      0,
    );
    if (total) {
      parts.push(
        `${total} juicio${total === 1 ? "" : "s"} previo${total === 1 ? "" : "s"}`,
      );
    }
  }
  return parts.join(" · ");
}

function incidentDetail(event: StoryEvent): string {
  const codes = eventReasonCodes(event);
  if (codes.length) return codes.map(reasonText).join(", ");
  const summary = event.summaryKey ? reasonText(event.summaryKey) : "";
  if (summary) return summary;
  const raw = str(event.technical?.raw);
  if (raw) return reasonText(raw);
  return statusLabel(event.status);
}

function headlineFor(status: string, analysisComplete: boolean | undefined): string {
  if (status && status !== "completed") return "Respuesta con incidencias";
  if (analysisComplete === false) return "Respuesta con análisis incompleto";
  return "Respuesta completada";
}

function narrativeFor(input: {
  events: StoryEvent[];
  sourcesCount: number;
  analysisComplete: boolean | undefined;
}): string {
  const has = (phase: StoryPhaseId) => input.events.some((event) => event.phase === phase);
  const hasSql = input.events.some((event) => event.kind === "sql");
  const hasTransitions = input.events.some((event) => event.transitions.length > 0);
  if (hasTransitions) {
    return input.analysisComplete === false
      ? "Zent reconstruyó el escenario y declaró qué evidencia le falta para concluir."
      : "Zent reconstruyó el escenario antes de responder.";
  }
  if (has("reasoning")) return "Zent analizó el caso antes de responder.";
  if (hasSql) return "Zent consultó la base de datos y respondió con esos datos.";
  if (input.sourcesCount)
    return "Zent buscó en el conocimiento y respondió con las fuentes citadas.";
  if (has("generation")) return "Zent respondió de forma directa, sin consultar fuentes.";
  return "Sin pasos registrados para esta respuesta.";
}

function routeLabelFor(flow: Flow, events: StoryEvent[]): string {
  const route = str(record(flow.verdict).route);
  const hasReasoning = events.some((event) => event.phase === "reasoning");
  const hasSql = events.some((event) => event.kind === "sql");
  const hasSources = events.some(
    (event) => event.kind === "sources" || event.kind === "retrieval",
  );
  if (hasSql && hasReasoning) return "Datos estructurados + análisis";
  if (hasSql) return "Base de datos";
  if (hasReasoning && hasSources) return "Documentos + análisis secuencial";
  if (hasReasoning) return `${route || "Análisis"} + análisis`;
  if (route === "Documentos") return "Documentos";
  if (route === "Herramientas") return "Herramientas del agente";
  if (route === "Nodos") return "Workflow";
  if (route === "Directa") return "Respuesta directa";
  return route || "Respuesta";
}

/** El grounding puede venir del bloque histórico o de su evento canónico. */
function groundingFor(flow: Flow, events: StoryEvent[]): Flow {
  const block = record(flow.grounding);
  if (Object.keys(block).length) return block;
  const event = events.find((item) => item.kind === "grounding");
  if (!event) return {};
  return {
    grounded: event.metrics.grounded,
    score: event.metrics.score,
    ms: event.durationMs,
  };
}

/** §22: la tarjeta de completitud muestra también lo que faltó en el escenario. */
function enrichCompletionEvents(events: StoryEvent[]): StoryEvent[] {
  const missing: string[] = [];
  for (const event of events) {
    const requirements = (event.scenario?.missing_requirements ?? []) as Array<
      Record<string, unknown>
    >;
    for (const requirement of requirements) {
      const kind = str(requirement.kind);
      if (kind && !missing.includes(kind)) missing.push(kind);
    }
  }
  if (!missing.length) return events;
  return events.map((event) => {
    if (!event.completion) return event;
    return {
      ...event,
      decisionReasonCodes: [...event.decisionReasonCodes, ...missing].filter(
        (code, index, all) => all.indexOf(code) === index,
      ),
    };
  });
}

function outcomeLabelFor(grounding: Flow): string {
  if (grounding.grounded === true) return "Respaldada";
  if (grounding.grounded === false) return "Sin respaldo";
  return "Sin verificación";
}

function confidenceLabelFor(confidence: number | undefined): string {
  if (!confidence) return "";
  if (confidence >= 0.8) return "Alta";
  if (confidence >= 0.6) return "Media";
  return "Baja";
}

function breakdownFor(phases: StoryPhase[], generation: Flow): StoryBreakdownRow[] {
  const cost = num(generation.cost) ?? null;
  return phases.map((phase) => ({
    label: phase.title,
    ms: phase.durationMs,
    costUsd: phase.id === "generation" ? cost : null,
  }));
}

// Los componentes consultan motivos sin volver a calcularlos: el evento ya los
// trae normalizados desde el backend o desde el adaptador legacy.
export function eventReasonCodes(event: StoryEvent): string[] {
  const codes = [...(event.decisionReasonCodes ?? [])];
  const completion = event.completion;
  if (completion) {
    for (const key of ["blockers", "reason_codes"] as const) {
      for (const code of (completion[key] as unknown[]) ?? []) {
        const value = str(code);
        if (value && !codes.includes(value)) codes.push(value);
      }
    }
  }
  for (const requirement of (event.scenario?.missing_requirements ?? []) as Array<
    Record<string, unknown>
  >) {
    const kind = str(requirement.kind);
    if (kind && !codes.includes(kind)) codes.push(kind);
  }
  const reason = str(event.technical?.reason_code);
  if (reason && !codes.includes(reason)) codes.push(reason);
  return codes;
}

/** Motivos de un evento ya en lenguaje humano (§22). Nunca inventados. */
export function eventReasonsText(event: StoryEvent): string {
  const codes = eventReasonCodes(event);
  if (!codes.length) return "";
  return codes.map(reasonText).join(", ");
}
