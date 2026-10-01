// =============================================================================
// Experiencia explicada — proyección tipada del contrato `flow.traceability`
// =============================================================================
// El backend entrega semántica (códigos + números + referencias). Acá vive la
// ÚNICA traducción a lenguaje humano para la vista "Cómo llegó Zent a esta
// respuesta". Reglas:
// - Ningún componente recalcula probabilidades ni conteos: todo sale de acá.
// - Un dato ausente no se muestra: jamás se fabrica una frase sin telemetría.
// - La vista técnica puede mostrar lo crudo; esta capa es la explicada.
// =============================================================================

import {
  authorityLabel,
  effectLabel,
  evidenceStatusLabel,
  jevPurposeLabel,
  judgmentValueLabel,
  questionLabel,
  reasonText,
  VERIFICATION_CHECK_LABELS,
  VERIFICATION_STATE_LABELS,
} from "./executionStory";

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------

export type ConfidenceBand = "high" | "medium" | "low";

export type Display = {
  outcomeKey?: string;
  probability?: number;
  confidenceBand?: ConfidenceBand;
  certain?: boolean;
  ambiguous?: boolean;
  certainty?: number;
  direction?: string;
  level?: string;
  runnerUpKey?: string;
  runnerUpProbability?: number;
};

export type TraceEvidenceItem = {
  evidenceId?: string;
  documentId?: string;
  sourceId?: string;
  chunkId?: string;
  documentName: string;
  page?: number;
  sectionPath: string[];
  excerpt?: string;
  score?: number;
  rerankScore?: number;
  retrieval?: string;
  match?: string;
  status?: string;
  usedInAnswer?: boolean;
  cited?: boolean;
  docIndex?: number;
  authority?: string;
  knowledgeType?: string;
};

export type TraceDocument = {
  key: string;
  documentId?: string;
  sourceId?: string;
  name: string;
  evidenceCount: number;
  usedCount: number;
  items: TraceEvidenceItem[];
};

export type TraceCounts = {
  documentsConsulted: number;
  documentsUsed: number;
  evidenceRetrieved: number;
  evidenceUsed: number;
  evidenceCited?: number;
};

export type TraceDecision = {
  id: string;
  phase: string;
  purpose: string;
  purposeLabel: string;
  questionId?: string;
  questionLabel?: string;
  verdict?: string;
  action?: string;
  actionLabel: string;
  applied: boolean;
  classification: "OBSERVATIONAL" | "ACTIONABLE" | "BLOCKING";
  effectCodes: string[];
  reasonCodes: string[];
  unsatisfied: string[];
  tier?: string;
  allowGeneration?: boolean;
  display: Display;
  beforeState?: { evidence?: number; sufficient?: boolean };
  afterState?: { evidence?: number; sufficient?: boolean };
  deltaEvidence?: number;
};

export type TraceAlternative = { key: string; probability?: number };

export type TraceJudgment = {
  id: string;
  phase: string;
  purpose: string;
  purposeLabel: string;
  questionCode: string;
  questionLabel: string;
  type: string;
  effectCode?: string;
  decisionId?: string;
  display: Display;
  alternatives: TraceAlternative[];
  sourceEventIds: string[];
};

export type TraceTimelineEvent = {
  id: string;
  type: string;
  stage?: string;
  sequence: number;
  summaryCode: string;
  summaryParams: Record<string, unknown>;
  userVisible: boolean;
  status: string;
  durationMs?: number;
  metrics: Record<string, unknown>;
  decisionId?: string;
  sourceEventIds: string[];
};

export type VerificationStatus =
  | "VERIFIED"
  | "PARTIALLY_VERIFIED"
  | "UNVERIFIED"
  | "CONFLICTING_EVIDENCE"
  | "INSUFFICIENT_EVIDENCE";

export type TraceVerification = {
  status: VerificationStatus;
  explanationCodes: Array<{ code: string; check?: string; count?: number }>;
  checks: Array<{ key: string; state: string; detail?: string; source?: string }>;
  signals: {
    grounded?: boolean;
    overall?: string;
    fallbackUsed: boolean;
    fallbackCode?: string;
    materialFallback: boolean;
    evidenceComplete?: string;
    answerability?: boolean;
  };
  technical: Record<string, unknown>;
};

export type TraceRetrievalRound = {
  attempt: number;
  strategy?: string;
  evidence?: number;
  sufficient?: boolean;
  qualityScore?: number;
};

export type Traceability = {
  schemaVersion: number;
  counts: TraceCounts;
  documents: TraceDocument[];
  items: TraceEvidenceItem[];
  decisions: TraceDecision[];
  judgments: TraceJudgment[];
  timeline: TraceTimelineEvent[];
  verification: TraceVerification;
  retrieval: { rounds: TraceRetrievalRound[]; expanded: boolean; strategy?: string };
  diagnostics: {
    invariants: Array<Record<string, unknown>>;
    gaps: Array<Record<string, unknown>>;
  };
};

// ---------------------------------------------------------------------------
// Parseo (defensivo: nunca lanza, nunca inventa)
// ---------------------------------------------------------------------------

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    : [];
}

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function num(value: unknown): number | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : [];
}

function band(value: unknown): ConfidenceBand | undefined {
  return value === "high" || value === "medium" || value === "low" ? value : undefined;
}

function parseDisplay(raw: unknown): Display {
  const item = record(raw);
  const display: Display = {};
  const outcomeKey = text(item.outcome_key);
  if (outcomeKey) display.outcomeKey = outcomeKey;
  const probability = num(item.probability) ?? num(item.confidence);
  if (probability !== undefined) display.probability = probability;
  const confidenceBand = band(item.confidence_band);
  if (confidenceBand) display.confidenceBand = confidenceBand;
  if (typeof item.certain === "boolean") display.certain = item.certain;
  if (typeof item.ambiguous === "boolean") display.ambiguous = item.ambiguous;
  const certainty = num(item.certainty);
  if (certainty !== undefined) display.certainty = certainty;
  if (text(item.direction)) display.direction = text(item.direction);
  if (text(item.level)) display.level = text(item.level);
  if (text(item.runner_up_key)) display.runnerUpKey = text(item.runner_up_key);
  const runnerUp = num(item.runner_up_probability);
  if (runnerUp !== undefined) display.runnerUpProbability = runnerUp;
  return display;
}

function parseEvidenceItem(raw: Record<string, unknown>): TraceEvidenceItem {
  const sectionPath = strings(raw.section_path);
  return {
    evidenceId: text(raw.evidence_id) || undefined,
    documentId: text(raw.document_id) || undefined,
    sourceId: text(raw.source_id) || undefined,
    chunkId: text(raw.chunk_id) || undefined,
    documentName: text(raw.document_name),
    page: num(raw.page),
    sectionPath,
    excerpt: text(raw.excerpt) || undefined,
    score: num(raw.score),
    rerankScore: num(raw.rerank_score),
    retrieval: text(raw.retrieval) || undefined,
    match: text(raw.match) || undefined,
    status: text(raw.status) || undefined,
    usedInAnswer: typeof raw.used_in_answer === "boolean" ? raw.used_in_answer : undefined,
    cited: typeof raw.cited === "boolean" ? raw.cited : undefined,
    docIndex: num(raw.doc_index),
    authority: text(raw.authority) || undefined,
    knowledgeType: text(raw.knowledge_type) || undefined,
  };
}

function parseDecision(raw: Record<string, unknown>, index: number): TraceDecision {
  const phase = text(raw.phase);
  const classification =
    raw.classification === "ACTIONABLE" || raw.classification === "BLOCKING"
      ? raw.classification
      : "OBSERVATIONAL";
  const before = record(raw.before_state);
  const after = record(raw.after_state);
  return {
    id: text(raw.decision_id) || `decision-${index}`,
    phase,
    purpose: text(raw.purpose) || phase,
    purposeLabel: jevPurposeLabel(phase),
    questionId: text(raw.question_id) || undefined,
    questionLabel: text(raw.question_id) ? questionLabel(text(raw.question_id)) : undefined,
    verdict: text(raw.verdict) || undefined,
    action: text(raw.action) || undefined,
    actionLabel: text(raw.action) ? judgmentValueLabel(text(raw.action)) : "Decisión registrada",
    applied: raw.action_applied === true,
    classification,
    effectCodes: strings(raw.effect_codes),
    reasonCodes: strings(raw.reason_codes),
    unsatisfied: strings(raw.unsatisfied),
    tier: text(raw.tier) || undefined,
    allowGeneration:
      typeof raw.allow_generation === "boolean" ? raw.allow_generation : undefined,
    display: parseDisplay(raw.display),
    beforeState: Object.keys(before).length
      ? { evidence: num(before.evidence), sufficient: boolOrUndefined(before.sufficient) }
      : undefined,
    afterState: Object.keys(after).length
      ? { evidence: num(after.evidence), sufficient: boolOrUndefined(after.sufficient) }
      : undefined,
    deltaEvidence: num(raw.delta_evidence),
  };
}

function boolOrUndefined(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function parseJudgment(raw: Record<string, unknown>, index: number): TraceJudgment {
  const phase = text(raw.phase);
  const questionCode = text(raw.question_code);
  return {
    id: text(raw.judgment_id) || `judgment-${index}`,
    phase,
    purpose: text(raw.purpose) || phase,
    purposeLabel: jevPurposeLabel(phase),
    questionCode,
    questionLabel: questionLabel(questionCode),
    type: text(raw.type) || "noul",
    effectCode: text(raw.effect_code) || undefined,
    decisionId: text(raw.decision_id) || undefined,
    display: parseDisplay(raw.display),
    alternatives: records(raw.alternatives).map((alt) => ({
      key: text(alt.key),
      probability: num(alt.probability),
    })),
    sourceEventIds: strings(raw.source_event_ids),
  };
}

function parseTimelineEvent(raw: Record<string, unknown>, index: number): TraceTimelineEvent {
  return {
    id: text(raw.id) || `trace-${index}`,
    type: text(raw.type),
    stage: text(raw.stage) || undefined,
    sequence: num(raw.sequence) ?? index + 1,
    summaryCode: text(raw.summary_code),
    summaryParams: record(raw.summary_params),
    userVisible: raw.user_visible === true,
    status: text(raw.status) || "ok",
    durationMs: num(raw.duration_ms),
    metrics: record(raw.metrics),
    decisionId: text(raw.decision_id) || undefined,
    sourceEventIds: strings(raw.source_event_ids),
  };
}

/** Parsea el bloque canónico. Devuelve null si no existe (flows históricos). */
export function parseTraceability(raw: unknown): Traceability | null {
  const block = record(raw);
  if (!Object.keys(block).length || block.schema_version === undefined) return null;
  const evidence = record(block.evidence);
  const counts = record(block.counts);
  const verification = record(block.verification);
  const diagnostics = record(block.diagnostics);
  const status = text(verification.status);
  return {
    schemaVersion: num(block.schema_version) ?? 0,
    counts: {
      documentsConsulted: num(counts.documents_consulted) ?? 0,
      documentsUsed: num(counts.documents_used) ?? 0,
      evidenceRetrieved: num(counts.evidence_retrieved) ?? 0,
      evidenceUsed: num(counts.evidence_used) ?? 0,
      evidenceCited: num(counts.evidence_cited),
    },
    documents: records(evidence.documents).map((doc, index) => ({
      key: text(doc.document_key) || `document-${index}`,
      documentId: text(doc.document_id) || undefined,
      sourceId: text(doc.source_id) || undefined,
      name: text(doc.document_name),
      evidenceCount: num(doc.evidence_count) ?? 0,
      usedCount: num(doc.used_count) ?? 0,
      items: records(doc.items).map(parseEvidenceItem),
    })),
    items: records(evidence.items).map(parseEvidenceItem),
    decisions: records(block.decisions).map(parseDecision),
    judgments: records(block.judgments).map(parseJudgment),
    timeline: records(block.timeline).map(parseTimelineEvent),
    verification: {
      status: (status || "UNVERIFIED") as VerificationStatus,
      explanationCodes: records(verification.explanation_codes).map((item) => ({
        code: text(item.code),
        check: text(item.check) || undefined,
        count: num(item.count),
      })),
      checks: records(verification.checks).map((check) => ({
        key: text(check.key),
        state: text(check.state) || "not_observed",
        detail: text(check.detail) || undefined,
        source: text(check.source) || undefined,
      })),
      signals: {
        grounded: boolOrUndefined(record(verification.signals).grounded),
        overall: text(record(verification.signals).overall) || undefined,
        fallbackUsed: record(verification.signals).fallback_used === true,
        fallbackCode: text(record(verification.signals).fallback_code) || undefined,
        materialFallback: record(verification.signals).material_fallback === true,
        evidenceComplete: text(record(verification.signals).evidence_complete) || undefined,
        answerability: boolOrUndefined(record(verification.signals).answerability),
      },
      technical: record(verification.technical),
    },
    retrieval: {
      rounds: records(record(block.retrieval).rounds).map((round, index) => ({
        attempt: num(round.attempt) ?? index + 1,
        strategy: text(round.strategy) || undefined,
        evidence: num(round.evidence),
        sufficient: boolOrUndefined(round.sufficient),
        qualityScore: num(round.quality_score),
      })),
      expanded: record(block.retrieval).expanded === true,
      strategy: text(record(block.retrieval).strategy) || undefined,
    },
    diagnostics: {
      invariants: records(diagnostics.invariants),
      gaps: records(diagnostics.gaps),
    },
  };
}

// ---------------------------------------------------------------------------
// Traducciones — una sola fuente para toda la vista explicada
// ---------------------------------------------------------------------------

export const CONFIDENCE_BAND_LABELS: Record<ConfidenceBand, string> = {
  high: "Alta",
  medium: "Media",
  low: "Baja",
};

export const DECISION_CLASS_LABELS: Record<TraceDecision["classification"], string> = {
  OBSERVATIONAL: "Sólo observó",
  ACTIONABLE: "Cambió la ejecución",
  BLOCKING: "Bloqueó o retuvo",
};

export const VERIFICATION_STATUS_TEXT: Record<
  VerificationStatus,
  { label: string; sentence: string; tone: "ok" | "warn" | "neutral" }
> = {
  VERIFIED: {
    label: "Respaldo suficiente",
    sentence:
      "La respuesta está respaldada por las fuentes recuperadas y las comprobaciones principales pasaron.",
    tone: "ok",
  },
  PARTIALLY_VERIFIED: {
    label: "Verificada parcialmente",
    sentence:
      "La respuesta está respaldada por las fuentes recuperadas, pero una comprobación secundaria no pudo ejecutarse.",
    tone: "warn",
  },
  UNVERIFIED: {
    label: "Sin verificación",
    sentence:
      "No se pudo confirmar el respaldo de la respuesta con la evidencia recuperada.",
    tone: "warn",
  },
  CONFLICTING_EVIDENCE: {
    label: "Evidencia en conflicto",
    sentence: "Las fuentes recuperadas contienen información que se contradice.",
    tone: "warn",
  },
  INSUFFICIENT_EVIDENCE: {
    label: "Evidencia insuficiente",
    sentence:
      "Zent no generó la conclusión final o la retuvo porque la evidencia no alcanzaba.",
    tone: "warn",
  },
};

/** §9: ÚNICA transformación de probabilidad → texto mostrado. */
export function formatDisplayProbability(display: Display): string {
  if (display.probability === undefined) return "";
  const percent = Math.round(display.probability * 100);
  return `${percent}%`;
}

/** §9: ÚNICA transformación de confianza → etiqueta mostrada. */
export function displayConfidenceLabel(display: Display): string {
  if (!display.confidenceBand) return "";
  return CONFIDENCE_BAND_LABELS[display.confidenceBand];
}

/** Resultado de un juicio en lenguaje humano. Sin dato => "". Jamás inventa. */
export function judgmentOutcomeLabel(
  type: string,
  display: Display,
  effectCode?: string,
): string {
  const key = display.outcomeKey ?? effectCode ?? "";
  if (!key) return "";
  if (type === "noul") {
    if (key === "yes") return "Sí";
    if (key === "no") return "No";
    if (key === "uncertain") return "Incierto";
  }
  if (type === "choice" || type === "score") return judgmentValueLabel(key);
  return key;
}

// ---------------------------------------------------------------------------
// Presentación de la ejecución (timeline)
// ---------------------------------------------------------------------------

export type TraceStepPresentation = {
  title: string;
  detail?: string;
  tone: "ok" | "warn" | "neutral";
};

function evidenceCountText(params: Record<string, unknown>): string {
  const evidence = num(params.evidence) ?? num(params.evidence_retrieved);
  const used = num(params.evidence_used);
  const documents = num(params.documents) ?? num(params.documents_used);
  const parts: string[] = [];
  if (evidence !== undefined) {
    parts.push(`${evidence} evidencia${evidence === 1 ? "" : "s"} encontrada${evidence === 1 ? "" : "s"}`);
  }
  if (used !== undefined && used !== evidence) parts.push(`${used} utilizada${used === 1 ? "" : "s"}`);
  if (documents !== undefined) {
    parts.push(`${documents} documento${documents === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
}

/** Traduce un evento de timeline. Sólo usa datos del propio evento. */
export function traceStepPresentation(
  event: TraceTimelineEvent,
  decisions: TraceDecision[],
): TraceStepPresentation {
  const params = event.summaryParams;
  const tone: TraceStepPresentation["tone"] =
    event.status === "warn" || event.status === "error"
      ? "warn"
      : event.status === "skipped"
        ? "neutral"
        : "ok";
  switch (event.type) {
    case "QUERY_CLASSIFIED":
      return { title: "Entendió la consulta", tone };
    case "CONTEXT_LOADED":
      return { title: "Recuperó contexto de la empresa", tone };
    case "PLAN_CREATED":
      return { title: "Diseñó el análisis", tone };
    case "ROUTE_SELECTED":
      return { title: "Definió la ruta", tone };
    case "RETRIEVAL_COMPLETED": {
      const chunks = num(params.chunks);
      const detailParts: string[] = [];
      if (chunks !== undefined) {
        detailParts.push(`${chunks} fragmento${chunks === 1 ? "" : "s"} recuperado${chunks === 1 ? "" : "s"}`);
      }
      const evidenceText = evidenceCountText(params);
      if (evidenceText) detailParts.push(evidenceText);
      return { title: "Buscó evidencia", detail: detailParts.join(" · "), tone };
    }
    case "EVIDENCE_FOUND": {
      const detail = evidenceCountText(params);
      return { title: "Encontró evidencia", detail: detail || undefined, tone };
    }
    case "EVIDENCE_ASSESSED": {
      const sufficient = boolOrUndefined(params.sufficient);
      const action = text(params.action);
      const detail =
        sufficient === true
          ? "La evidencia alcanzaba para responder."
          : sufficient === false
            ? "La evidencia no era suficiente todavía."
            : action
              ? effectLabel(action)
              : undefined;
      return { title: "Evaluó la evidencia", detail, tone };
    }
    case "SQL_EXECUTED": {
      const rows = num(params.rows);
      return {
        title: "Consultó datos estructurados",
        detail: rows !== undefined ? `${rows} fila${rows === 1 ? "" : "s"}` : undefined,
        tone,
      };
    }
    case "JEV_DECISION": {
      const decision = decisions.find((item) => item.id === event.decisionId);
      if (decision) {
        return {
          title: `JEV intervino: ${decision.actionLabel}`,
          detail: decision.effectCodes.map(effectLabel).join(" · ") || undefined,
          tone,
        };
      }
      return { title: "JEV evaluó el camino", tone };
    }
    case "RETRIEVAL_EXPANDED": {
      const before = num(params.before);
      const after = num(params.after);
      const detail =
        before !== undefined && after !== undefined
          ? `La búsqueda pasó de ${before} a ${after} evidencias.`
          : undefined;
      return { title: "JEV pidió ampliar la búsqueda", detail, tone };
    }
    case "GENERATION_STARTED":
      return { title: "Comenzó a redactar", tone };
    case "GENERATION_COMPLETED": {
      const tokens = num(params.tokens);
      return {
        title: "Generó la respuesta",
        detail: tokens !== undefined ? `${tokens} tokens` : undefined,
        tone,
      };
    }
    case "ANSWER_REVISED":
      return {
        title: "Corrigió la respuesta",
        detail: text(params.reason) || undefined,
        tone,
      };
    case "VERIFICATION_COMPLETED": {
      const grounded = boolOrUndefined(params.grounded);
      const overall = text(params.overall);
      const detail =
        overall === "verified" || grounded === true
          ? "Respaldo confirmado."
          : overall === "partial"
            ? "Verificación parcial."
            : grounded === false
              ? "No se confirmó el respaldo."
              : undefined;
      return { title: "Verificó la respuesta", detail, tone };
    }
    case "GUARDRAIL": {
      const reason = text(params.reason);
      return {
        title: reason ? `Se aplicó un control: ${reasonText(reason)}` : "Se aplicó un control",
        tone: "warn",
      };
    }
    case "RESPONSE_DELIVERED":
      return { title: "Entregó la respuesta", tone };
    default:
      return { title: event.type.replace(/_/g, " ").toLowerCase(), tone };
  }
}

/** Pasos visibles de la ejecución, ya traducidos y en orden real. */
export function visibleExecutionSteps(
  traceability: Traceability,
): Array<{ event: TraceTimelineEvent; presentation: TraceStepPresentation }> {
  return traceability.timeline
    .filter((event) => event.userVisible)
    .map((event) => ({
      event,
      presentation: traceStepPresentation(event, traceability.decisions),
    }));
}

// ---------------------------------------------------------------------------
// Decisiones (§22)
// ---------------------------------------------------------------------------

export function decisionAppliedCount(traceability: Traceability): number {
  return traceability.decisions.filter(
    (decision) => decision.applied && decision.classification !== "OBSERVATIONAL",
  ).length;
}

export function decisionEffectText(decision: TraceDecision): string {
  if (decision.deltaEvidence !== undefined && decision.deltaEvidence > 0) {
    return `+${decision.deltaEvidence} evidencia${decision.deltaEvidence === 1 ? "" : "s"}`;
  }
  const effects = decision.effectCodes.map(effectLabel);
  return effects.join(" · ");
}

export function decisionResultText(decision: TraceDecision): string {
  const parts: string[] = [];
  if (decision.beforeState?.evidence !== undefined && decision.afterState?.evidence !== undefined) {
    parts.push(
      `Evidencia: ${decision.beforeState.evidence} a ${decision.afterState.evidence}`,
    );
  }
  if (decision.effectCodes.length) {
    parts.push(decision.effectCodes.map(effectLabel).join(" · "));
  }
  return parts.join(". ");
}

// ---------------------------------------------------------------------------
// Verificación (§12)
// ---------------------------------------------------------------------------

export function verificationCheckLabel(key: string): string {
  return (
    EXPLAINED_CHECK_LABELS[key] ??
    VERIFICATION_CHECK_LABELS[key] ??
    key.replace(/_/g, " ")
  );
}

/** Nombres humanos de las comprobaciones en la vista explicada. */
const EXPLAINED_CHECK_LABELS: Record<string, string> = {
  answer_gate: "La verificación de respuesta",
  grounding: "El respaldo en fuentes",
  evidence_sufficiency: "La suficiencia de evidencia",
  answerability: "La comprobabilidad de la pregunta",
  analysis_complete: "El análisis",
  inference_supported: "La inferencia",
  claims: "La comprobación de afirmaciones",
};

export function verificationCheckState(state: string): string {
  return VERIFICATION_STATE_LABELS[state] ?? state;
}

export function verificationExplanationLines(
  verification: TraceVerification,
): Array<{ code: string; text: string; tone: "ok" | "warn" | "neutral" }> {
  return verification.explanationCodes.map((item) => {
    switch (item.code) {
      case "DOCUMENTARY_SUPPORT_CONFIRMED":
        return {
          code: item.code,
          text: "Respaldo documental confirmado",
          tone: "ok" as const,
        };
      case "SECONDARY_CHECK_UNAVAILABLE": {
        const label = item.check ? verificationCheckLabel(item.check) : "Una comprobación secundaria";
        return {
          code: item.code,
          text: `${label} no estuvo disponible`,
          tone: "warn" as const,
        };
      }
      case "ANSWER_WITH_LIMITS":
        return {
          code: item.code,
          text: "La respuesta se entregó con límites declarados.",
          tone: "warn" as const,
        };
      case "FALLBACK_VERIFIER_USED":
        return {
          code: item.code,
          text: "La respuesta pudo verificarse mediante un mecanismo alternativo.",
          tone: "ok" as const,
        };
      case "EVIDENCE_CONFLICT":
        return {
          code: item.code,
          text: item.count
            ? `Se detectaron ${item.count} fragmentos en conflicto.`
            : "Se detectó evidencia en conflicto.",
          tone: "warn" as const,
        };
      case "GENERATION_RETAINED":
        return {
          code: item.code,
          text: "La generación se retuvo para no inventar una conclusión.",
          tone: "warn" as const,
        };
      case "EVIDENCE_INSUFFICIENT":
        return {
          code: item.code,
          text: "No había evidencia suficiente.",
          tone: "warn" as const,
        };
      case "SUPPORT_NOT_CONFIRMED":
        return {
          code: item.code,
          text: "El respaldo documental no quedó confirmado.",
          tone: "warn" as const,
        };
      case "NO_VERIFICATION_RECORDED":
        return {
          code: item.code,
          text: "No se registró una comprobación final.",
          tone: "neutral" as const,
        };
      default:
        return {
          code: item.code,
          text: reasonText(item.code),
          tone: "neutral" as const,
        };
    }
  });
}

// ---------------------------------------------------------------------------
// Evidencia (§3, §4, §5, §16)
// ---------------------------------------------------------------------------

export const EVIDENCE_NAME_FALLBACK = "Fuente sin nombre";

export function documentDisplayName(document: TraceDocument): string {
  return document.name || EVIDENCE_NAME_FALLBACK;
}

export function evidenceLocation(item: TraceEvidenceItem): string {
  const parts: string[] = [];
  if (item.page !== undefined) parts.push(`Página ${item.page}`);
  if (item.sectionPath.length) parts.push(item.sectionPath.join(" · "));
  return parts.join(" · ");
}

export function evidenceUsageLabel(item: TraceEvidenceItem): string {
  if (item.cited === true) return "Citada en la respuesta";
  if (item.usedInAnswer === true) return "Usada para responder";
  if (item.usedInAnswer === false) return "Recuperada, no utilizada";
  return "";
}

export function evidenceMatchLabel(item: TraceEvidenceItem): string {
  if (!item.match) return "";
  return EFFECT_LABELS_FALLBACK[item.match] ?? item.match.replace(/_/g, " ");
}

const EFFECT_LABELS_FALLBACK: Record<string, string> = {
  exact_anchor_match: "Coincidencia exacta con lo preguntado",
  exact_entity_match: "Cubre todas las entidades de la pregunta",
  source_name_match: "El nombre de la fuente coincide",
  entity_pin: "Fue fijada por entidad",
  section_match: "Coincide la sección",
  lexical_match: "Coincidencia de términos",
  semantic_match: "Similitud semántica",
};

export function evidenceAuthorityLabel(item: TraceEvidenceItem): string {
  return item.authority ? authorityLabel(item.authority) : "";
}

export function evidenceStatusText(item: TraceEvidenceItem): string {
  return item.status ? evidenceStatusLabel(item.status) : "";
}
