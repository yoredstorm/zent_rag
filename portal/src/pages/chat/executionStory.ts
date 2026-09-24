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

export type StoryStatus = "ok" | "warn" | "uncertain" | "error" | "skipped" | "pending";

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

/** §19-§21: la verificación no es un booleano, es un conjunto de comprobaciones. */
export type StoryVerificationCheck = {
  key: string;
  label: string;
  state: string;
  stateLabel: string;
  detail?: string;
};

export type StoryVerification = {
  overall: string;
  label: string;
  tone: "ok" | "warn" | "neutral";
  checks: StoryVerificationCheck[];
};

/** §24, §25: qué señales de observabilidad llegaron realmente. */
export type StoryTelemetryDimension = {
  key: string;
  label: string;
  state: string;
  stateLabel: string;
};

export type StoryTelemetry = {
  dimensions: StoryTelemetryDimension[];
  quality: "full" | "partial" | "legacy";
  qualityLabel: string;
  qualityTone: "ok" | "warn" | "neutral";
  /** Dimensiones no observadas (no son ceros ni fallos). */
  missing: string[];
};

/** §36: cuántos steps crudos llegaron y cuántos se mapearon a eventos. */
export type StoryCounts = {
  canonicalEvents: number;
  rawSteps: number;
  mapped: number;
  unmapped: number;
};

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

/**
 * §51-§54 (Response Intelligence): la forma de explicar que eligió Zent.
 * No es contenido: es la decisión de composición, en lenguaje humano.
 */
export type StoryResponseShape = {
  blueprint: string;
  label: string;
  detail: string;
  detailLabel: string;
  decidedBy: string;
  decidedByLabel: string;
  conclusionFirst: boolean;
  needsExample: boolean;
  needsTable: boolean;
  needsStepByStep: boolean;
  citationsRequired: boolean;
  hedgingRequired: boolean;
  sections: string[];
  uncertain: string[];
  /** §54: cómo se anuncia el paso de generación según la forma elegida. */
  generationTitle: string;
  generationSubtitle: string;
};

/** §43-§47: rendimiento real del run. Wall-clock manda; los spans se declaran. */
export type StoryPerformanceSegment = { key: string; label: string; ms: number };

export type StoryLlmCall = {
  index: number;
  label: string;
  ms?: number;
  tokens?: number;
  model?: string;
};

export type StorySearch = {
  index: number;
  label: string;
  ms?: number;
  chunks?: number;
  evidences?: number;
};

export type StoryJevDecision = {
  label: string;
  phaseLabel: string;
  purpose: string;
  judgmentCount: number;
  confidence?: number;
  uncertain: number;
  cached: boolean;
};

export type StoryPerformance = {
  /** Tiempo real de pared. Es la base de la vista de rendimiento (§44). */
  totalMs: number;
  segments: StoryPerformanceSegment[];
  attributedMs: number;
  /** Tiempo real que ningún segmento explica. Nunca negativo. */
  unattributedMs: number;
  /** §44: suma de spans. Puede superar el wall-clock y se declara. */
  cumulativeSpanMs: number | null;
  overlaps: boolean;
  note: string;
  llmCalls: StoryLlmCall[];
  llmCallCount: number | null;
  searches: StorySearch[];
  uniqueEvidence: number | null;
  jevDecisions: StoryJevDecision[];
  reusedJudgments: number;
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
  /** Verificación real del run (§19-§21). */
  verification: StoryVerification;
  /** Observabilidad realmente recibida (§24, §25). */
  telemetry: StoryTelemetry;
  /** Steps crudos vs eventos canónicos (§36). */
  counts: StoryCounts;
  /** Run de la ejecución cuando existe (agent/workflow). */
  runId?: string;
  /** Llamadas al modelo realmente observadas (§42). */
  llmCalls?: number;
  /** §51-§54: forma de explicar elegida (Response Intelligence). */
  response: StoryResponseShape | null;
  /** §43-§47: rendimiento real del run. */
  performance: StoryPerformance;
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
  // Agent JEV Loop: por qué el paso decidió lo que decidió.
  evidence_gap: "faltaba evidencia para lo que se preguntó",
  termination_satisfied: "la evidencia alcanzaba para responder",
  no_usable_evidence: "no había evidencia utilizable",
  tool_choice_pending: "faltaba elegir herramienta",
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
  response_planning: "Preparó cómo explicar la respuesta",
  // Agent JEV Loop: el juicio del paso, con su veredicto compuesto.
  agent_step: "JEV juzgó el paso",
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
  // Búsqueda extra pedida por JEV porque faltaba evidencia para lo preguntado.
  jev_retrieval: "Volvió a buscar: faltaba evidencia",
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
    case "uncertain":
      // §42: un juicio incierto no es un error: es confianza moderada.
      return "Confianza moderada";
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
  response_composition: "Cómo explicar",
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
  // Response Intelligence: forma de explicar y gate de presentación (§5, §24).
  response_blueprint: "¿Cómo conviene explicar la respuesta?",
  required_detail: "¿Qué nivel de detalle necesita?",
  needs_example: "¿Conviene un ejemplo?",
  needs_table: "¿Conviene una tabla?",
  needs_step_by_step: "¿Conviene paso a paso?",
  needs_warning: "¿Hay que advertir algo?",
  needs_definition: "¿Hay que definir algún término?",
  needs_practical_implication: "¿Hay que explicar la consecuencia práctica?",
  needs_source_explanation: "¿Hay que explicar de dónde sale?",
  needs_citations: "¿Hay que citar fuentes?",
  answer_explains_key_reason: "¿Explica el motivo clave?",
  answer_is_needlessly_verbose: "¿Es innecesariamente largo?",
  important_context_missing: "¿Falta contexto importante?",
  structure: "¿Qué tan clara es la estructura?",
  usefulness: "¿Qué tan útil es?",
  revision_reason: "¿Por qué revisarla?",
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
  // Formas de explicación (§5): el valor del Choice, en lenguaje humano.
  direct_fact: "Respuesta directa",
  definition_explanation: "Definición explicada",
  technical_explanation: "Explicación técnica",
  scenario_analysis: "Análisis de escenario",
  comparison: "Comparación",
  procedure: "Procedimiento",
  data_interpretation: "Lectura de datos",
  executive_summary: "Resumen ejecutivo",
  tutorial: "Tutorial",
  brief: "Breve",
  normal: "Normal",
  detailed: "Detallado",
  deep: "Profundo",
  // Motivos de revisión (§25).
  unclear: "Poco clara",
  too_verbose: "Demasiado extensa",
  too_short: "Demasiado breve",
  missing_explanation: "Le falta explicación",
  missing_example: "Le falta un ejemplo",
  missing_evidence: "Le falta evidencia",
  unsupported_claim: "Afirmación sin respaldo",
  poor_structure: "Estructura confusa",
  does_not_answer_question: "No responde la pregunta",
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
// Verificación y telemetría (§19-§25, §47)
// ---------------------------------------------------------------------------

/** §21: resultados posibles del run, en lenguaje honesto. */
export const VERIFICATION_OVERALL_LABELS: Record<string, string> = {
  verified: "Verificada",
  partial: "Verificada parcialmente",
  not_verified: "Sin verificación",
  blocked: "Retenida por seguridad",
};

export const VERIFICATION_CHECK_LABELS: Record<string, string> = {
  analysis_complete: "Análisis",
  inference_supported: "Inferencia",
  answer_gate: "Gate de respuesta",
  grounding: "Respaldo en fuentes",
  claims: "Afirmaciones",
};

export const VERIFICATION_STATE_LABELS: Record<string, string> = {
  ok: "Comprobado",
  warn: "Con reservas",
  blocked: "Bloqueado",
  not_observed: "No se ejecutó",
  not_applicable: "No aplica",
};

/** §24: dimensiones de observabilidad y sus estados. */
export const TELEMETRY_LABELS: Record<string, string> = {
  routing: "Decisión",
  reasoning: "Razonamiento",
  company_context: "Contexto empresarial",
  jev: "JEV",
  tools: "Herramientas",
  evidence: "Evidencia",
  generation: "Generación",
  verification: "Verificación",
  memory: "Memoria",
  cost: "Costo",
  timings: "Tiempos",
};

export const TELEMETRY_STATE_LABELS: Record<string, string> = {
  observed: "Observado",
  not_applicable: "No aplica",
  not_available: "No disponible",
  not_observed: "No observado",
};

export const DATA_QUALITY_LABELS: Record<string, string> = {
  full: "Telemetría completa",
  partial: "Telemetría parcial",
  legacy: "Flujo histórico",
};

/** §51: formas de explicación en lenguaje humano. */
export const BLUEPRINT_LABELS: Record<string, string> = {
  direct_fact: "Respuesta directa",
  definition_explanation: "Definición explicada",
  technical_explanation: "Explicación técnica",
  scenario_analysis: "Análisis de escenario",
  diagnostic: "Diagnóstico",
  comparison: "Comparación",
  procedure: "Procedimiento",
  data_interpretation: "Lectura de datos",
  executive_summary: "Resumen ejecutivo",
  tutorial: "Tutorial",
};

/** §54: cómo se anuncia la generación según la forma elegida. */
export const BLUEPRINT_GENERATION_TITLES: Record<string, string> = {
  direct_fact: "Respondió el dato",
  definition_explanation: "Definió el concepto",
  technical_explanation: "Explicó la conclusión",
  scenario_analysis: "Explicó el escenario",
  diagnostic: "Explicó la causa",
  comparison: "Comparó las opciones",
  procedure: "Indicó los pasos",
  data_interpretation: "Leyó los datos",
  executive_summary: "Resumió lo esencial",
  tutorial: "Enseñó el tema",
};

export const DETAIL_LABELS: Record<string, string> = {
  brief: "Breve",
  normal: "Normal",
  detailed: "Detallado",
  deep: "Profundo",
};

export const SECTION_LABELS: Record<string, string> = {
  direct_answer: "Respuesta directa",
  meaning: "Qué significa",
  practical_effect: "Qué implica en la práctica",
  example: "Ejemplo",
  sequence: "Qué ocurre en la secuencia",
  why: "Por qué",
  discarded_alternative: "Qué alternativa se descartó",
  what_to_check: "Qué verificaría adicionalmente",
  cause: "Causa principal",
  evidence: "Evidencia",
  comparison: "Comparación",
  steps: "Pasos",
  definition: "Definición",
  uses: "Para qué sirve",
  where_it_applies: "Dónde interviene",
  data_reading: "Lectura de los datos",
  summary: "Resumen",
  limitations: "Importante / límites",
  sources: "Fuentes",
};

export const DECIDED_BY_LABELS: Record<string, string> = {
  deterministic: "Elegida por reglas",
  rules: "Elegida por reglas",
  jev: "Elegida por juicio previo",
  profile: "Elegida por el perfil del agente",
};

export function blueprintLabel(blueprint: unknown): string {
  const key = str(blueprint);
  return BLUEPRINT_LABELS[key] ?? (key ? key.replace(/_/g, " ") : "");
}

export function detailLabel(detail: unknown): string {
  const key = str(detail);
  return DETAIL_LABELS[key] ?? key;
}

export function sectionLabel(section: unknown): string {
  const key = str(section);
  return SECTION_LABELS[key] ?? key.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Rendimiento (§43-§47)
// ---------------------------------------------------------------------------

/** §45: la llamada al modelo se nombra por lo que hizo, si el backend lo dice. */
const LLM_ACTION_LABELS: Record<string, string> = {
  plan_search: "Preparó la búsqueda",
  rewrite_query: "Refinó la búsqueda",
  reason: "Analizó el caso",
  analyze: "Analizó el caso",
  answer: "Redactó la respuesta",
  final: "Redactó la respuesta",
  generation: "Redactó la respuesta",
};

export function llmActionLabel(action: unknown, fallback = "Llamada al modelo"): string {
  const key = str(action).trim().toLowerCase();
  if (!key) return fallback;
  if (LLM_ACTION_LABELS[key]) return LLM_ACTION_LABELS[key];
  if (key.includes("search") || key.includes("retriev")) return "Preparó la búsqueda";
  if (key.includes("refine") || key.includes("rewrite")) return "Refinó la búsqueda";
  if (key.includes("reason") || key.includes("analy")) return "Analizó el caso";
  if (key.includes("answer") || key.includes("generat")) return "Redactó la respuesta";
  return fallback;
}

/** §47: el propósito de cada decisión JEV, por su momento — nunca inventado. */
export const JEV_PURPOSE_LABELS: Record<string, string> = {
  pre_reasoning: "Preparó el análisis",
  post_retrieval: "Evaluó la evidencia",
  post_reconstruction: "Comprobó la reconstrucción",
  pre_generation: "Decidió cómo responder",
  response_composition: "Eligió cómo explicarlo",
  post_generation: "Verificó la respuesta",
  agent_step: "Eligió el siguiente paso",
};

export function jevPurposeLabel(phase: unknown): string {
  const key = str(phase);
  return JEV_PURPOSE_LABELS[key] ?? (key ? "Juicio previo" : "Juicio previo");
}

export const PERFORMANCE_SEGMENT_LABELS: Record<string, string> = {
  llm: "Llamadas al modelo",
  retrieval: "Búsqueda de conocimiento",
  sql: "Datos estructurados",
  jev: "Juicio previo y gates",
  analysis: "Análisis y verificación",
};

export function responseShapeFor(
  flow: Flow,
  events: StoryEvent[],
): StoryResponseShape | null {
  const contract = record(record(flow.response_contract ?? record(flow.response).contract));
  const planning = events.find((event) => event.kind === "response_planning");
  const blueprint = str(contract.blueprint) || str(planning?.metrics.blueprint);
  if (!blueprint) return null;
  const detail = str(contract.detail) || str(planning?.metrics.detail_level) || "normal";
  const sections = Array.isArray(contract.sections)
    ? (contract.sections as unknown[]).map((item) => str(item))
    : [];
  const formatting = record(contract.formatting);
  const evidence = record(contract.evidence);
  const uncertain =
    strings(contract.uncertainty_notes).length
      ? strings(contract.uncertainty_notes)
      : strings(record(planning?.metrics).uncertain);
  const decidedBy = str(contract.decided_by) || str(planning?.metrics.decided_by) || "deterministic";
  const pack = events.find((event) => event.kind === "jev_pack" && event.phase === "planning");
  const packMetrics = record(pack?.metrics);
  const packDetail = record(packMetrics.composition);
  const needsExample =
    sections.includes("example") ||
    planning?.metrics.needs_example === true ||
    packDetail.needs_example === true;
  const needsTable = formatting.table === true || planning?.metrics.needs_table === true;
  const needsStepByStep =
    formatting.numbered_steps === true || planning?.metrics.needs_step_by_step === true;
  const citationsRequired =
    evidence.citations_required === true || planning?.metrics.citations_required === true;
  const hedgingRequired =
    contract.hedging_required === true || planning?.metrics.hedging_required === true;
  const generation = record(flow.generation);
  const tokens = num(generation.total_tokens);
  const ms = num(generation.ms);
  const subtitleParts = [
    blueprintLabel(blueprint),
    detailLabel(detail).toLowerCase(),
    tokens ? `${tokens} tokens` : "",
    ms ? `${(ms / 1000).toFixed(1)} s` : "",
  ].filter(Boolean);
  return {
    blueprint,
    label: blueprintLabel(blueprint),
    detail,
    detailLabel: detailLabel(detail),
    decidedBy,
    decidedByLabel: DECIDED_BY_LABELS[decidedBy] ?? decidedBy,
    conclusionFirst: contract.conclusion_first !== false,
    needsExample,
    needsTable,
    needsStepByStep,
    citationsRequired,
    hedgingRequired,
    sections,
    uncertain,
    generationTitle: BLUEPRINT_GENERATION_TITLES[blueprint] ?? "Redactó la respuesta",
    generationSubtitle: subtitleParts.join(" · "),
  };
}

function performanceFor(flow: Flow, events: StoryEvent[]): StoryPerformance {
  const timings = record(flow.timings);
  const generation = record(flow.generation);
  const retrieval = record(flow.retrieval);
  const totalMs = num(timings.total_ms) ?? num(flow.total_ms) ?? 0;
  const segments: StoryPerformanceSegment[] = [];
  const add = (key: string, ms: number | undefined) => {
    const value = num(ms) ?? 0;
    if (value <= 0) return;
    const existing = segments.find((segment) => segment.key === key);
    if (existing) existing.ms = Math.round(existing.ms + value);
    else segments.push({ key, label: PERFORMANCE_SEGMENT_LABELS[key] ?? key, ms: Math.round(value) });
  };

  // §43: atribución por lo que realmente declaró el backend.
  const llmMs =
    num(timings.llm_ms) ??
    (num(timings.generation_ms) || num(generation.ms)
      ? (num(timings.generation_ms) ?? num(generation.ms) ?? 0) +
        events
          .filter((event) => event.kind === "llm")
          .reduce((sum, event) => sum + (event.durationMs ?? 0), 0) -
        Math.min(
          num(timings.generation_ms) ?? num(generation.ms) ?? 0,
          events
            .filter((event) => event.kind === "llm")
            .reduce((sum, event) => sum + (event.durationMs ?? 0), 0),
        )
      : undefined);
  add("llm", llmMs);
  add(
    "retrieval",
    num(timings.retrieval_ms) ??
      (retrieval.used === true || num(retrieval.chunks)
        ? num(retrieval.ms) ?? sumDurations(events, ["retrieval", "tool_call"])
        : undefined),
  );
  add("sql", num(timings.sql_ms) || num(record(flow.sql).ms));
  const jevMs = sumDurations(events, ["jev_pack", "decision", "tool_routing", "answer_gate", "termination_gate"]);
  add("jev", num(timings.gates_ms) ?? (jevMs || undefined));
  const analysisMs =
    (num(timings.plan_ms) ?? 0) +
    (num(timings.evidence_ms) ?? 0) +
    (num(timings.grounding_ms) ?? 0) +
    sumDurations(events, [
      "evidence",
      "grounding",
      "reasoning_plan",
      "scenario_parse",
      "state_reconstruction",
      "timeline",
      "hypothesis_test",
      "inference_verification",
      "analysis_completion",
    ]);
  add("analysis", analysisMs || undefined);

  const attributedMs = segments.reduce((sum, segment) => sum + segment.ms, 0);
  const spanStages = record(timings.span_stages);
  const cumulativeSpanMs = Object.keys(spanStages).length
    ? Math.round(
        Object.values(spanStages).reduce<number>(
          (sum, value) => sum + (num(value) ?? 0),
          0,
        ),
      )
    : null;
  const overlaps =
    cumulativeSpanMs !== null && totalMs > 0 && cumulativeSpanMs > totalMs + 1;
  const unattributedMs = Math.max(0, Math.round(totalMs - attributedMs));
  const note = overlaps
    ? "El trabajo acumulado de los spans se solapa entre sí (una fase contiene a otra); la barra usa sólo el tiempo real de pared."
    : attributedMs > totalMs && totalMs > 0
      ? "Algunos tramos se solapan; el total mostrado es el tiempo real de pared."
      : "";

  // §45: desglose por llamada, sólo si el backend dejó el detalle.
  const llmCalls: StoryLlmCall[] = events
    .filter((event) => event.kind === "llm")
    .map((event, index) => {
      const technical = record(event.technical);
      const metrics = record(event.metrics);
      return {
        index: num(technical.step) ?? index + 1,
        label: llmActionLabel(technical.action ?? technical.step_kind ?? metrics.action),
        ms: event.durationMs,
        tokens: num(metrics.tokens) ?? num(technical.tokens),
        model: technical.model ? str(technical.model) : undefined,
      };
    });
  const declaredCalls = num(generation.calls);
  const llmCallCount = declaredCalls ?? (llmCalls.length || null);

  // §46: cada búsqueda con sus fragmentos; la evidencia única sale del backend.
  const searches: StorySearch[] = events
    .filter(
      (event) =>
        event.kind === "retrieval" ||
        (event.kind === "tool_call" &&
          /search|know|source|retriev/i.test(str(record(event.technical).tool))),
    )
    .map((event, index) => {
      const metrics = record(event.metrics);
      return {
        index: index + 1,
        label: event.kind === "retrieval" ? "Búsqueda en el conocimiento" : event.title,
        ms: event.durationMs,
        chunks: num(metrics.chunks) ?? num(metrics.results),
        evidences: num(metrics.sources_used) ?? num(metrics.sources_total),
      };
    });
  const uniqueEvidence =
    num(record(events.find((event) => event.kind === "sources")?.metrics).sources) ??
    (list(flow.sources).length || null);

  // §47: decisiones JEV con propósito traducido; nunca repetir el mismo texto.
  const jevDecisions: StoryJevDecision[] = [];
  for (const pack of toJudgmentPacks(events)) {
    if (pack.phase === "response_composition") {
      jevDecisions.push({
        label: jevPurposeLabel(pack.phase),
        phaseLabel: pack.title,
        purpose: pack.judgments.map((judgment) => judgment.decisionLabel).join(" · "),
        judgmentCount: pack.judgmentCount,
        confidence: minConfidence(pack.judgments),
        uncertain: pack.uncertain.length,
        cached: pack.cached,
      });
      continue;
    }
    const confidences = pack.judgments
      .filter((judgment) => judgment.id === "preferred_capability" || judgment.id === "next_action")
      .map((judgment) => judgment.confidence)
      .filter((value): value is number => value !== undefined);
    jevDecisions.push({
      label: jevPurposeLabel(pack.phase),
      phaseLabel: pack.title,
      purpose: pack.judgments.length
        ? pack.judgments.map((judgment) => judgment.decisionLabel).slice(0, 3).join(" · ")
        : "",
      judgmentCount: pack.judgmentCount,
      confidence: confidences.length ? Math.min(...confidences) : minConfidence(pack.judgments),
      uncertain: pack.uncertain.length,
      cached: pack.cached,
    });
  }

  return {
    totalMs,
    segments,
    attributedMs,
    unattributedMs,
    cumulativeSpanMs,
    overlaps,
    note,
    llmCalls,
    llmCallCount,
    searches,
    uniqueEvidence,
    jevDecisions,
    reusedJudgments: toJudgmentPacks(events).filter((pack) => pack.cached).length,
  };
}

function sumDurations(events: StoryEvent[], kinds: string[]): number {
  return events
    .filter((event) => kinds.includes(event.kind))
    .reduce((sum, event) => sum + (event.durationMs ?? 0), 0);
}

function minConfidence(judgments: StoryJudgment[]): number | undefined {
  const values = judgments
    .map((judgment) => judgment.confidence)
    .filter((value): value is number => value !== undefined);
  return values.length ? Math.min(...values) : undefined;
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

/** Lista de strings sin inventar: lo que no es string se descarta. */
function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item) => typeof item === "string" || typeof item === "number").map((item) => String(item))
    : [];
}

function status(value: unknown): StoryStatus {
  const key = str(value).toLowerCase();
  if (key === "warn" || key === "warning") return "warn";
  if (key === "uncertain") return "uncertain";
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
  response_planning: "planning",
  agent_step: "decision",
  jev_retrieval: "evidence",
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
  const kind = str(raw.kind) || "step";
  const uncertainJudgments = strings(metrics.uncertain).length;
  const blocksGeneration =
    decision.allow_generation === false || str(decision.action) === "abstain";
  const resolved = status(raw.status);
  return {
    id: str(raw.id) || `event-${index}`,
    phase,
    kind,
    // §42: un juicio incierto que NO bloqueó nada se marca como incertidumbre,
    // no como "Requiere atención".
    status:
      resolved === "warn" && kind === "jev_pack" && uncertainJudgments > 0 && !blocksGeneration
        ? "uncertain"
        : resolved,
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
  const response = responseShapeFor(safe, events);
  const performance = performanceFor(safe, events);

  const phases: StoryPhase[] = [];
  for (const id of PHASE_ORDER) {
    const phaseEvents = events.filter((event) => event.phase === id);
    if (!phaseEvents.length) continue;
    const worst = worstStatus(phaseEvents.map((event) => event.status));
    phases.push({
      id,
      // §54: el paso de generación se nombra por la forma de explicar elegida.
      title: id === "generation" && response ? response.generationTitle : PHASE_TITLES[id],
      subtitle: phaseSubtitle(id, phaseEvents, response),
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
  const jev = record(safe.jev);
  const totalMs = num(record(safe.timings).total_ms) ?? num(safe.total_ms) ?? 0;
  const reasoningShape = events
    .flatMap((event) => [str(record(event.metrics.reasoning).shape)])
    .find(Boolean);
  const completion = events.find((event) => event.completion)?.completion;
  const analysisComplete = completion ? completion.complete !== false : undefined;
  const sourcesEvent = events.find((event) => event.kind === "sources");
  const sourcesCount =
    num(record(sourcesEvent?.metrics).sources) ??
    list(safe.sources).length;
  const costUsd = num(record(generation).cost) ?? num(safe.cost);
  const hasReasoning = phases.some((phase) => phase.id === "reasoning");
  const judgmentPacks = toJudgmentPacks(events);
  const jevImpact = buildJevImpact(safe, judgmentPacks);
  const verification = verificationFor(safe, events);
  const execution = record(safe.execution);
  const counts: StoryCounts = {
    canonicalEvents: events.length,
    rawSteps: list(safe.steps).length,
    unmapped: events.filter((event) => event.technical?.unmapped === true).length,
    mapped: 0,
  };
  counts.mapped = Math.max(0, counts.canonicalEvents - counts.unmapped);
  const telemetry = telemetryFor(safe, {
    legacy,
    verification,
    sourcesCount,
  });
  const llmCalls = num(generation.calls);
  const confidence = num(decision.confidence);

  return {
    version: num(safe.flow_version) ?? (legacy ? 1 : 2),
    legacy,
    status: str(safe.status) || "completed",
    headline: headlineFor(str(safe.status), analysisComplete),
    // §47: la telemetría faltante NO convierte el run en warning. Sólo lo hacen
    // un error real, una verificación bloqueada, un fallback material o una
    // retención por seguridad.
    headlineStatus: headlineStatusFor({
      status: str(safe.status),
      events,
      verification,
      fallbacks: list(safe.fallbacks),
      analysisComplete,
    }),
    narrative: narrativeFor({ events, sourcesCount, analysisComplete }),
    routeLabel: routeLabelFor(safe, events),
    outcomeLabel: verification.label,
    outcomeTone: verification.tone,
    confidenceLabel: confidenceLabelFor(confidence),
    evidenceLabel: sourcesCount ? `${sourcesCount} fuente${sourcesCount === 1 ? "" : "s"}` : "",
    // El razonamiento sólo se anuncia cuando la historia lo demuestra.
    reasoningLabel: hasReasoning
      ? shapeLabel(reasoningShape) || "Análisis secuencial"
      : "",
    totalMs,
    costUsd: costUsd ?? null,
    phases,
    incidents,
    breakdown: breakdownFor(phases),
    judgmentPacks,
    jevImpact,
    verification,
    telemetry,
    counts,
    runId: str(execution.id) || undefined,
    response,
    performance,
    technical: {
      provider: str(decision.provider) || undefined,
      decider: str(verdict.decider) || undefined,
      model: str(generation.model) || undefined,
      jevUsed: typeof jev.used === "boolean" ? jev.used : undefined,
      // §10: no existe un "Score JEV" universal. Sólo se expone si el juicio
      // realmente produjo un score (p.ej. el gate de respuesta).
      jevScore: num(jev.score) ?? null,
      confidence: confidence ?? null,
      tokens:
        num(generation.prompt_tokens) ||
        num(generation.completion_tokens) ||
        num(generation.total_tokens)
          ? {
              prompt: num(generation.prompt_tokens) ?? 0,
              completion: num(generation.completion_tokens) ?? 0,
              total: num(generation.total_tokens) ?? 0,
            }
          : undefined,
      answerability: Object.keys(record(safe.answerability)).length
        ? record(safe.answerability)
        : undefined,
      pricing: Object.keys(record(safe.pricing)).length ? record(safe.pricing) : undefined,
      raw: safe,
    },
    llmCalls,
  };
}

/** §47: sólo señales reales convierten el run en "Revisar". */
function headlineStatusFor(input: {
  status: string;
  events: StoryEvent[];
  verification: StoryVerification;
  fallbacks: Flow[];
  analysisComplete: boolean | undefined;
}): StoryStatus {
  if (input.status && input.status !== "completed") return "warn";
  if (input.events.some((event) => event.status === "error")) return "warn";
  if (input.verification.overall === "blocked") return "warn";
  if (input.analysisComplete === false) return "warn";
  if (input.fallbacks.length) return "warn";
  if (input.events.some((event) => event.kind === "guardrail")) return "warn";
  // La telemetría faltante es información, no una incidencia (§46, §47).
  return "ok";
}

function worstStatus(statuses: StoryStatus[]): StoryStatus {
  // §42: la incertidumbre no es un warning. Va después de warn y antes de ok.
  const rank: StoryStatus[] = ["error", "warn", "uncertain", "pending", "ok", "skipped"];
  return rank.find((candidate) => statuses.includes(candidate)) ?? "ok";
}

function phaseSubtitle(
  id: StoryPhaseId,
  events: StoryEvent[],
  response: StoryResponseShape | null = null,
): string {
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
    // §52: la planificación de la respuesta se declara junto al plan de análisis.
    const planning = events.find((event) => event.kind === "response_planning");
    const blueprint = str(record(planning?.metrics).blueprint);
    if (blueprint) parts.push(blueprintLabel(blueprint));
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
    const metrics = record(events[0]?.metrics);
    const tokens = num(metrics.total_tokens);
    if (response) parts.push(response.generationSubtitle);
    else if (tokens) parts.push(`${tokens} tokens`);
    // §42, §43: si hubo varias llamadas al modelo, no se atribuye todo a
    // "redactar": se declara cuántas fueron de razonamiento y cuántas respuesta.
    const llmEvents = events.filter((event) => event.kind === "llm");
    const calls = num(record(events.find((event) => event.kind === "generation")?.technical).calls);
    const total = calls ?? llmEvents.length;
    if (total > 1) {
      const answerCalls = events
        .map((event) => num(record(event.technical).answer_calls))
        .find((value) => value !== undefined);
      const reasoningCalls = events
        .map((event) => num(record(event.technical).reasoning_calls))
        .find((value) => value !== undefined);
      const detail = [
        `${total} llamadas al modelo`,
        reasoningCalls ? `${reasoningCalls} de razonamiento` : "",
        answerCalls ? `${answerCalls} de respuesta` : "",
      ]
        .filter(Boolean)
        .join(" · ");
      parts.push(detail);
    }
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

/**
 * §19, §20: la verificación se compone de las comprobaciones REALES del run.
 * Nunca se dice "Verificada" si sólo corrió el gate de respuesta.
 */
function verificationFor(flow: Flow, events: StoryEvent[]): StoryVerification {
  const block = record(flow.verification);
  const rawChecks = Array.isArray(block.checks) ? list(block.checks) : [];
  const checks: StoryVerificationCheck[] = rawChecks.map((check) => {
    const key = str(check.key);
    const state = str(check.state) || "not_observed";
    return {
      key,
      label: VERIFICATION_CHECK_LABELS[key] ?? key.replace(/_/g, " "),
      state,
      stateLabel: VERIFICATION_STATE_LABELS[state] ?? state,
      detail: check.detail ? str(check.detail) : undefined,
    };
  });

  // Fallback para flows sin bloque de verificación: se leen los eventos reales.
  if (!checks.length) {
    const gate = events.find((event) => event.kind === "answer_gate");
    if (gate) {
      const verdict = str(gate.metrics.verdict);
      const provider = str(gate.metrics.provider || "jev");
      const state =
        provider === "skip"
          ? "not_observed"
          : verdict === "abstain"
            ? "blocked"
            : verdict === "revise"
              ? "warn"
              : "ok";
      checks.push({
        key: "answer_gate",
        label: VERIFICATION_CHECK_LABELS.answer_gate,
        state,
        stateLabel: VERIFICATION_STATE_LABELS[state] ?? state,
        detail: verdict || undefined,
      });
      if (typeof gate.metrics.grounded === "boolean") {
        const grounded = gate.metrics.grounded === true;
        checks.push({
          key: "grounding",
          label: VERIFICATION_CHECK_LABELS.grounding,
          state: grounded ? "ok" : "blocked",
          stateLabel: grounded ? VERIFICATION_STATE_LABELS.ok : VERIFICATION_STATE_LABELS.blocked,
        });
      }
    }
    const grounding = events.find((event) => event.kind === "grounding");
    if (grounding && typeof grounding.metrics.grounded === "boolean") {
      const grounded = grounding.metrics.grounded === true;
      checks.push({
        key: "grounding",
        label: VERIFICATION_CHECK_LABELS.grounding,
        state: grounded ? "ok" : "blocked",
        stateLabel: grounded ? VERIFICATION_STATE_LABELS.ok : VERIFICATION_STATE_LABELS.blocked,
      });
    }
    const completion = events.find((event) => event.completion)?.completion;
    if (completion && typeof completion.complete === "boolean") {
      const complete = completion.complete === true;
      checks.push({
        key: "analysis_complete",
        label: VERIFICATION_CHECK_LABELS.analysis_complete,
        state: complete ? "ok" : "blocked",
        stateLabel: complete
          ? VERIFICATION_STATE_LABELS.ok
          : VERIFICATION_STATE_LABELS.blocked,
      });
    }
  }

  const declared = str(block.overall);
  const overall =
    declared ||
    (checks.some((check) => check.state === "blocked")
      ? "blocked"
      : checks.length === 0
        ? "not_verified"
        : checks.some((check) => check.key === "grounding" && check.state === "ok")
          ? "verified"
          : "partial");
  const tone: StoryVerification["tone"] =
    overall === "verified" ? "ok" : overall === "blocked" ? "warn" : "neutral";
  return {
    overall,
    label: verificationLabel(overall, checks),
    tone,
    checks,
  };
}

/** §21: el resultado se nombra por lo que realmente pasó, no por un default. */
function verificationLabel(overall: string, checks: StoryVerificationCheck[]): string {
  if (overall === "verified") return "Verificada";
  if (overall === "partial") return "Verificada parcialmente";
  if (overall === "not_verified") return "Sin verificación";
  const gate = checks.find((check) => check.key === "answer_gate");
  if (gate?.detail === "abstain") return "Retenida por seguridad";
  const analysis = checks.find((check) => check.key === "analysis_complete");
  if (analysis?.state === "blocked") return "Análisis incompleto";
  return "Evidencia insuficiente";
}

const TELEMETRY_ORDER = [
  "routing",
  "reasoning",
  "company_context",
  "jev",
  "tools",
  "evidence",
  "generation",
  "verification",
  "memory",
  "cost",
  "timings",
];

/**
 * §24, §25: qué señales llegaron. No es una confidence ni un score agregado:
 * cada dimensión declara si se observó, no aplica o no está disponible.
 */
function telemetryFor(
  flow: Flow,
  options: {
    legacy: boolean;
    verification: StoryVerification;
    sourcesCount: number;
  },
): StoryTelemetry {
  const { legacy, verification, sourcesCount } = options;
  const declared = record(flow.telemetry);
  const rawSteps = list(flow.steps);
  const generation = record(flow.generation);
  const jev = record(flow.jev);

  const state = (key: string): string => {
    const value = str(declared[key]);
    if (value) return value;
    if (legacy) return "not_available";
    switch (key) {
      case "routing":
        return Object.keys(record(flow.decision)).length ? "observed" : "not_available";
      case "jev":
        return jev.used === true ? "observed" : "not_applicable";
      case "tools":
        return rawSteps.some((step) => str(step.type) === "tool_call")
          ? "observed"
          : "not_applicable";
      case "evidence":
        return sourcesCount ? "observed" : "not_applicable";
      case "generation":
        return Object.keys(generation).length ? "observed" : "not_available";
      case "verification":
        return verification.checks.length ? "observed" : "not_available";
      case "cost":
        return num(generation.cost) ? "observed" : "not_available";
      case "timings":
        return num(record(flow.timings).total_ms) ? "observed" : "not_available";
      default:
        return "not_observed";
    }
  };

  const dimensions: StoryTelemetryDimension[] = TELEMETRY_ORDER.map((key) => {
    const value = state(key);
    return {
      key,
      label: TELEMETRY_LABELS[key] ?? key,
      state: value,
      stateLabel: TELEMETRY_STATE_LABELS[value] ?? value,
    };
  });
  const missing = dimensions
    .filter((dimension) => dimension.state === "not_available" || dimension.state === "not_observed")
    .map((dimension) => dimension.key);

  const quality: StoryTelemetry["quality"] = legacy
    ? "legacy"
    : missing.length === 0
      ? "full"
      : "partial";
  return {
    dimensions,
    quality,
    qualityLabel: DATA_QUALITY_LABELS[quality],
    qualityTone: quality === "full" ? "ok" : quality === "legacy" ? "neutral" : "warn",
    missing,
  };
}

function confidenceLabelFor(confidence: number | undefined): string {
  // §7: un 0 real se muestra; "sin dato" no inventa una etiqueta.
  if (confidence === undefined) return "";
  if (confidence >= 0.8) return "Alta";
  if (confidence >= 0.6) return "Media";
  return "Baja";
}

function breakdownFor(phases: StoryPhase[]): StoryBreakdownRow[] {
  // §44: el costo del run es costo de LLM y no se atribuye a una fase que no lo
  // produjo. Si sólo existe el total, cada fase queda sin costo.
  return phases.map((phase) => ({
    label: phase.title,
    ms: phase.durationMs,
    costUsd: null,
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
