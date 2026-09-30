// Presentational contract emitted by src/rag/execution_narrative.py.
// It is a projection of canonical runtime facts, never a second authority.

export type NarrativeOutcomeCode =
  | "ANSWERED"
  | "ANSWERED_WITH_LIMITS"
  | "RETRIED_AND_ANSWERED"
  | "ABSTAINED"
  | "FAILED"
  | "BLOCKED";

export type NarrativeRequirement = {
  id: string;
  label: string;
  kind: "DOCUMENTABLE" | "USER_INPUT";
  status: string;
  sourceRequired: boolean;
  evidenceRefs: string[];
};

export type NarrativePassage = {
  evidenceId?: string;
  page?: string | number;
  section?: string;
  excerpt: string;
  status: string;
  relevance?: number;
};

export type NarrativeDocument = {
  key: string;
  documentId?: string;
  sourceId?: string;
  displayName: string;
  passageCount: number;
  passages: NarrativePassage[];
};

export type NarrativeJudgment = {
  id: string;
  phase: string;
  questionCode: string;
  type: string;
  answer: unknown;
  probability?: number;
  certainty?: number;
  confidenceBand?: string;
  ambiguous: boolean;
  alternatives: Array<{ key: string; probability?: number }>;
  appliedDecisionId?: string;
  effectCode?: string;
};

export type NarrativeDecision = {
  id: string;
  phase: string;
  questionId?: string;
  action: string;
  decider: string;
  reasonCodes: string[];
  impactCode: string;
  affectedEventIds: string[];
};

export type NarrativeModelCall = {
  id: string;
  sequence: number;
  purpose: "ANALYSIS" | "ANSWER" | "REVISION" | "UNKNOWN";
  durationMs?: number;
  model?: string;
  provider?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  costUsd?: number;
};

export type NarrativeJourneyNode = {
  id: string;
  kind: string;
  sequence: number;
  decisionId?: string;
  callId?: string;
  iteration?: number;
};

export type ExecutionNarrative = {
  schemaVersion: 1;
  outcome: {
    code: NarrativeOutcomeCode;
    reasonCode: string;
    evidenceState: "complete" | "incomplete" | "unknown";
    verificationState: string;
    finalStatus: string;
    materialFallback: boolean;
    answerDelivered: boolean;
  };
  summary: {
    decisionsInfluenced: number;
    judgmentCount: number;
    jevCalls: number;
    totalMs?: number;
    costUsd?: number;
  };
  understanding: {
    intentCode: string;
    taskCode: string;
    observedSummary: string;
    application: string;
    question: string;
    fields: string[];
    rules: string[];
    references: string[];
    examples: string[];
    entities: string[];
  };
  requirements: NarrativeRequirement[];
  journey: NarrativeJourneyNode[];
  judgments: NarrativeJudgment[];
  appliedDecisions: NarrativeDecision[];
  evidence: {
    complete: boolean | null;
    generationMode: string;
    coverageRatio?: number;
    missingDocumentableEvidence: string[];
    conflicts: unknown[];
    requirements: unknown[];
    documents: NarrativeDocument[];
    documentCount: number;
    passageCount: number;
    searches: Array<{ index: number; kind: string; durationMs?: number }>;
  };
  modelCalls: NarrativeModelCall[];
  verification: {
    overall: string;
    checks: Array<Record<string, unknown>>;
    primaryAvailable?: boolean;
    fallbackUsed: boolean;
    fallbackCode?: string;
    affectedOutcome: boolean;
    corrections: Array<Record<string, unknown>>;
  };
  responseShape: Record<string, unknown>;
  learning: Record<string, unknown>;
  diagnostics: Array<Record<string, unknown>>;
};

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record).filter((item) => Object.keys(item).length) : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function number(value: unknown): number | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function probability(value: unknown): number | undefined {
  const parsed = number(value);
  return parsed !== undefined && parsed >= 0 && parsed <= 1 ? parsed : undefined;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : [];
}

function optionalText(value: unknown): string | undefined {
  return text(value) || undefined;
}

export function parseExecutionNarrative(value: unknown): ExecutionNarrative | null {
  const source = record(value);
  if (number(source.schema_version) !== 1) return null;

  const outcome = record(source.outcome);
  const summary = record(source.summary);
  const understanding = record(source.understanding);
  const evidence = record(source.evidence);
  const verification = record(source.verification);
  const outcomeCode = text(outcome.code) as NarrativeOutcomeCode;
  const allowedOutcomes: NarrativeOutcomeCode[] = [
    "ANSWERED",
    "ANSWERED_WITH_LIMITS",
    "RETRIED_AND_ANSWERED",
    "ABSTAINED",
    "FAILED",
    "BLOCKED",
  ];
  if (!allowedOutcomes.includes(outcomeCode)) return null;

  return {
    schemaVersion: 1,
    outcome: {
      code: outcomeCode,
      reasonCode: text(outcome.reason_code),
      evidenceState: (["complete", "incomplete", "unknown"].includes(text(outcome.evidence_state))
        ? text(outcome.evidence_state)
        : "unknown") as "complete" | "incomplete" | "unknown",
      verificationState: text(outcome.verification_state),
      finalStatus: text(outcome.final_status),
      materialFallback: outcome.material_fallback === true,
      answerDelivered: outcome.answer_delivered === true,
    },
    summary: {
      decisionsInfluenced: number(summary.decisions_influenced) ?? 0,
      judgmentCount: number(summary.judgment_count) ?? 0,
      jevCalls: number(summary.jev_calls) ?? 0,
      totalMs: number(summary.total_ms),
      costUsd: number(summary.cost_usd),
    },
    understanding: {
      intentCode: text(understanding.intent_code),
      taskCode: text(understanding.task_code),
      observedSummary: text(understanding.observed_summary),
      application: text(understanding.application),
      question: text(understanding.question),
      fields: strings(understanding.fields),
      rules: strings(understanding.rules),
      references: strings(understanding.references),
      examples: strings(understanding.examples),
      entities: strings(understanding.entities),
    },
    requirements: records(source.requirements).map((item) => ({
      id: text(item.id),
      label: text(item.label),
      kind: item.kind === "USER_INPUT" ? "USER_INPUT" : "DOCUMENTABLE",
      status: text(item.status),
      sourceRequired: item.source_required === true,
      evidenceRefs: strings(item.evidence_refs),
    })),
    journey: records(source.journey).map((item) => ({
      id: text(item.id),
      kind: text(item.kind),
      sequence: number(item.sequence) ?? 0,
      decisionId: optionalText(item.decision_id),
      callId: optionalText(item.call_id),
      iteration: number(item.iteration),
    })),
    judgments: records(source.judgments).map((item) => ({
      id: text(item.id),
      phase: text(item.phase),
      questionCode: text(item.question_code),
      type: text(item.type),
      answer: item.answer,
      probability: probability(item.probability),
      certainty: probability(item.certainty),
      confidenceBand: optionalText(item.confidence_band),
      ambiguous: item.ambiguous === true,
      alternatives: records(item.alternatives).map((alternative) => ({
        key: text(alternative.key),
        probability: probability(alternative.probability),
      })),
      appliedDecisionId: optionalText(item.applied_decision_id),
      effectCode: optionalText(item.effect_code),
    })),
    appliedDecisions: records(source.applied_decisions).map((item) => ({
      id: text(item.id),
      phase: text(item.phase),
      questionId: optionalText(item.question_id),
      action: text(item.action),
      decider: text(item.decider),
      reasonCodes: strings(item.reason_codes),
      impactCode: text(item.impact_code),
      affectedEventIds: strings(item.affected_event_ids),
    })),
    evidence: {
      complete: typeof evidence.complete === "boolean" ? evidence.complete : null,
      generationMode: text(evidence.generation_mode),
      coverageRatio: probability(evidence.coverage_ratio),
      missingDocumentableEvidence: strings(evidence.missing_documentable_evidence),
      conflicts: Array.isArray(evidence.conflicts) ? evidence.conflicts : [],
      requirements: Array.isArray(evidence.requirements) ? evidence.requirements : [],
      documents: records(evidence.documents).map((document) => ({
        key: text(document.document_key),
        documentId: optionalText(document.document_id),
        sourceId: optionalText(document.source_id),
        displayName: text(document.display_name) || "Documento sin título",
        passageCount: number(document.passage_count) ?? 0,
        passages: records(document.passages).map((passage) => ({
          evidenceId: optionalText(passage.evidence_id),
          page:
            typeof passage.page === "string" || typeof passage.page === "number"
              ? passage.page
              : undefined,
          section: optionalText(passage.section),
          excerpt: text(passage.excerpt),
          status: text(passage.status),
          relevance: probability(passage.relevance),
        })),
      })),
      documentCount: number(evidence.document_count) ?? 0,
      passageCount: number(evidence.passage_count) ?? 0,
      searches: records(evidence.searches).map((search) => ({
        index: number(search.index) ?? 0,
        kind: text(search.kind),
        durationMs: number(search.duration_ms),
      })),
    },
    modelCalls: records(source.model_calls).map((call) => ({
      id: text(call.id),
      sequence: number(call.sequence) ?? 0,
      purpose: (["ANALYSIS", "ANSWER", "REVISION"].includes(text(call.purpose))
        ? text(call.purpose)
        : "UNKNOWN") as NarrativeModelCall["purpose"],
      durationMs: number(call.duration_ms),
      model: optionalText(call.model),
      provider: optionalText(call.provider),
      inputTokens: number(call.input_tokens),
      outputTokens: number(call.output_tokens),
      totalTokens: number(call.total_tokens),
      costUsd: number(call.cost_usd),
    })),
    verification: {
      overall: text(verification.overall),
      checks: records(verification.checks),
      primaryAvailable:
        typeof verification.primary_available === "boolean"
          ? verification.primary_available
          : undefined,
      fallbackUsed: verification.fallback_used === true,
      fallbackCode: optionalText(verification.fallback_code),
      affectedOutcome: verification.affected_outcome === true,
      corrections: records(verification.corrections),
    },
    responseShape: record(source.response_shape),
    learning: record(source.learning),
    diagnostics: records(source.diagnostics),
  };
}
