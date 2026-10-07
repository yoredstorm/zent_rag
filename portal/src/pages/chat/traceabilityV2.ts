// =============================================================================
// traceabilityV2 — parser y derivaciones del Traceability Schema v2 (§2, §29)
// =============================================================================
// El backend entrega la única verdad; este módulo sólo la valida, tipa y
// expone derivaciones de presentación. No recalcula conteos ni reinterpreta
// distribuciones: si un dato no viene, queda `null` (UNKNOWN != 0).

import { diagnosticCopy, headlineMeta } from "./traceabilityCatalog";

type Json = Record<string, unknown>;

function record(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Json)
    : {};
}

function records(value: unknown): Json[] {
  return Array.isArray(value)
    ? value.filter((item): item is Json => Boolean(item) && typeof item === "object")
    : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function bool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function str(value: unknown): string | null {
  const value_ = text(value).trim();
  return value_ ? value_ : null;
}

/* --- Tipos ---------------------------------------------------------------- */

export interface TraceV2Counts {
  documentsRetrieved: number | null;
  documentsUsed: number | null;
  documentsSelected: number | null;
  documentsUsedForDecision: number | null;
  documentsCited: number | null;
  evidenceRetrieved: number | null;
  evidenceDeduplicated: number | null;
  evidenceUnique: number | null;
  evidenceSelected: number | null;
  evidenceUsed: number | null;
  evidenceUsedForReasoning: number | null;
  evidenceUsedForRuleCompilation: number | null;
  evidenceUsedForPremiseClosure: number | null;
  evidenceUsedForDecision: number | null;
  evidenceDecision: number | null;
  mainRetrievalHits: number | null;
  evidenceCited: number | null;
}

export interface TraceV2RawHit {
  hitId: string | null;
  evidenceId: string | null;
  chunkId: string | null;
  page: number | null;
  score: number | null;
  retrieval: string | null;
  origin: string | null;
  status: string | null;
  used: boolean;
  cited: boolean;
}

export interface TraceV2EvidenceItem {
  evidenceId: string | null;
  canonicalSourceId: string | null;
  documentId: string | null;
  documentName: string | null;
  displayName: string | null;
  nameMissing: boolean;
  page: number | null;
  sectionPath: string[];
  excerpt: string | null;
  score: number | null;
  rerankScore: number | null;
  retrieval: string | null;
  authority: string | null;
  knowledgeType: string | null;
  used: boolean;
  usedForReasoning: boolean;
  usedForRuleCompilation: boolean;
  usedForPremiseClosure: boolean;
  usedForDecision: boolean;
  citationOnlyContext: boolean;
  decisionEvidence: boolean;
  cited: boolean;
  selected: boolean;
  mergedCount: number;
  dedupKind: string | null;
  hitCount: number;
  rawHits: TraceV2RawHit[];
}

export interface TraceV2Document {
  key: string;
  canonicalSourceId: string | null;
  documentId: string | null;
  name: string | null;
  displayName: string | null;
  nameMissing: boolean;
  identityWeak: boolean;
  evidenceCount: number;
  usedCount: number;
  decisionCount: number;
  citedCount: number;
  items: TraceV2EvidenceItem[];
}

export interface TraceV2Option {
  key: string;
  probability: number | null;
  selected: boolean;
}

export interface TraceV2Judgment {
  id: string;
  phase: string | null;
  purpose: string | null;
  questionCode: string;
  type: string;
  answer: string | null;
  selectedProbability: number | null;
  confidence: number | null;
  certainty: number | null;
  margin: number | null;
  entropy: number | null;
  band: string | null;
  verdict: string | null;
  options: TraceV2Option[];
  raw: Json;
  appliedDecisionId: string | null;
  effectCode: string | null;
  status: string;
  supersededBy: string | null;
  sequence: number | null;
  timestamp: string | null;
  finalEffect: string | null;
}

export interface TraceV2Decision {
  id: string;
  phase: string | null;
  action: string;
  provider: string;
  questionId: string | null;
  applied: boolean;
  material: boolean;
  changedRoute: boolean;
  isDefault: boolean;
  classification: string;
  reasonCodes: string[];
  effectCodes: string[];
  allowGeneration: boolean | null;
  tier: string | null;
  status: string;
  supersededBy: string | null;
  sequence: number | null;
}

export interface TraceV2Control {
  controlCode: string;
  severity: string;
  trigger: string | null;
  actionTaken: string | null;
  recovered: boolean;
  materialEffect: boolean;
  params: Json;
  sourceEventIds: string[];
}

export interface TraceV2FallbackEvent {
  code: string;
  fallbackClass: string;
  materialEffect: boolean;
  recovered: boolean;
}

export interface TraceV2GenerationCall {
  id: string;
  sequence: number | null;
  purpose: string;
  model: string | null;
  provider: string | null;
  durationMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  costUsd: number | null;
}

export interface TraceV2VerificationCheck {
  key: string;
  state: string;
  detail: string | null;
  quality: number | null;
}

export interface TraceV2DecisionVerification {
  status: string;
  authoritative: boolean;
  deterministic: boolean;
  operation: string | null;
  result: string | null;
  canonicalRuleIds: string[];
  premiseStatus: string | null;
  evidenceRefs: string[];
  ruleVerification: string | null;
  conflicts: string[];
}

export interface TraceV2NarrativeVerification {
  status: string;
  citationsValid: boolean | null;
  explanationComplete: boolean | null;
  groundingComplete: boolean | null;
  truncated: boolean;
  warnings: string[];
}

export interface TraceV2Degradation {
  code: string;
  impact: string;
  checks: Json;
}

export interface TraceV2DiagnosticItem {
  code: string;
  severity: string;
  dimension: string;
  materialEffect: boolean;
  meaningCode: string;
  impactCode: string;
  fixCode: string | null;
  params: Json;
  sourceEventIds: string[];
}

export interface TraceV2Dimension {
  status: string;
  severity: string | null;
  findings: number;
}

export interface TraceV2JourneyNode {
  id: string;
  kind: string;
  sequence: number;
  params: Json;
  sourceEventIds: string[];
}

export interface TraceV2Explanation {
  code: string;
  params: Json;
}

export interface TraceV2FastPathDecisionEvidence {
  resolved: number | null;
  unresolved: string[];
  outOfScope: string[];
  mainRetrievalHits: number | null;
  decisionEvidenceCount: number | null;
  documentsUsedForDecision: number | null;
}

export interface TraceV2WinningRule {
  ruleId: string | null;
  documentIds: string[];
  sourceIds: string[];
  pages: number[];
  documentTitle: string | null;
  parserEngine: string | null;
  parserVersion: string | null;
}

export interface TraceV2FastPath {
  eligible: boolean;
  reason: string | null;
  operation: string | null;
  result: string | null;
  executionMode: string | null;
  llmCalls: number | null;
  llmCallsAvoided: number | null;
  tokensAvoided: number | null;
  costAvoidedUsd: number | null;
  latencyMs: number | null;
  verificationStatus: string | null;
  decisionEvidence: TraceV2FastPathDecisionEvidence | null;
  winningRule: TraceV2WinningRule | null;
}

export interface TraceV2 {
  schemaVersion: 2;
  upgradedFromSchema: number | null;
  execution: {
    kind: string | null;
    id: string | null;
    question: string | null;
    status: string | null;
    delivered: boolean | null;
    method: string | null;
    mode: string | null;
    fastPath: TraceV2FastPath | null;
  };
  routing: {
    route: string | null;
    decider: string | null;
    confidence: number | null;
    intent: string | null;
  };
  knowledge: {
    strategy: string | null;
    engineStrategy: string | null;
    chunks: number | null;
    topScore: number | null;
    representation: Json;
  };
  retrieval: {
    rounds: Array<{
      attempt: number;
      strategy: string | null;
      evidence: number | null;
      sufficient: boolean | null;
      qualityScore: number | null;
    }>;
    expanded: boolean;
    skipRetrieval: boolean | null;
    attempts: number | null;
  };
  counts: TraceV2Counts;
  legacyCounts: TraceV2Counts;
  collection: string;
  dedup: { merged: number | null; exact: number | null; overlap: number | null; semantic: number | null };
  canonicalEvidence: TraceV2EvidenceItem[];
  rawHits: TraceV2RawHit[];
  documents: TraceV2Document[];
  citationsSummary: {
    references: number | null;
    citedReferences: number | null;
    uniqueCited: number | null;
    collapsed: number | null;
    dangling: string[];
  };
  jev: {
    executed: boolean;
    mode: string | null;
    calls: number | null;
    checks: number | null;
    judgmentsCount: number;
    materialIntervention: boolean;
    changedRoute: boolean;
    requestedMoreEvidence: boolean;
    blockedGeneration: boolean;
    latencyMs: number | null;
    costUsd: number | null;
    judgments: TraceV2Judgment[];
    decisions: TraceV2Decision[];
    supersededCount: number;
    resolution: { label: string | null; authority: boolean; premiseClosed: boolean } | null;
  };
  generation: {
    observed: boolean;
    skipped: boolean | null;
    model: string | null;
    provider: string | null;
    calls: number | null;
    answerCalls: number | null;
    reasoningCalls: number | null;
    revisionCalls: number | null;
    callsDetail: TraceV2GenerationCall[];
    tokens: { input: number | null; output: number | null; total: number | null };
    durationMs: number | null;
    costUsd: number | null;
    finishReason: string | null;
  };
  controls: TraceV2Control[];
  fallbacks: {
    events: TraceV2FallbackEvent[];
    material: boolean;
    classes: Record<string, number>;
  };
  verification: {
    status: string;
    explanationCodes: Array<{ code: string; check?: string; count?: number; impact?: string }>;
    checks: TraceV2VerificationCheck[];
    degradations: TraceV2Degradation[];
    grounded: boolean | null;
    fallbackUsed: boolean;
    fallbackCode: string | null;
    materialFallback: boolean;
    quality: number | null;
    decisionVerification: TraceV2DecisionVerification | null;
    narrativeVerification: TraceV2NarrativeVerification | null;
    decisionGrounding: string | null;
    narrativeGrounding: string | null;
  };
  memory: {
    observed: boolean;
    available: boolean | null;
    used: number | null;
    created: number | null;
    reinforced: number | null;
    contradicted: number | null;
  };
  timing: {
    wallClockMs: number | null;
    accumulatedMs: number | null;
    parallel: boolean | null;
    breakdown: Array<{ code: string; ms: number }>;
  };
  cost: {
    totalUsd: number | null;
    breakdown: Array<{ code: string; usd: number }>;
  };
  diagnostics: {
    items: TraceV2DiagnosticItem[];
    dimensions: Record<string, TraceV2Dimension>;
    consistency: { status: string; findings: number; responseQuality: string | null };
    overall: { status: string; severity: string | null; findings: number };
  };
  presentation: {
    headlineCode: string;
    support: {
      documentsUsed: number | null;
      evidenceUnique: number | null;
      evidenceUsed: number | null;
      evidenceCited: number | null;
      collection: string;
    };
    journey: TraceV2JourneyNode[];
    explanations: TraceV2Explanation[];
    metricRefs: string[];
    glossaryRefs: string[];
  };
  timeline: Array<{
    id: string;
    type: string;
    purpose: string | null;
    userVisible: boolean;
    status: string;
    decisionId: string | null;
  }>;
  runtimeSteps: Array<{
    type: string;
    name: string | null;
    status: string;
    detail: string | null;
    ms: number | null;
    unmapped: boolean;
    superseded: boolean;
    supersededBy: string | null;
  }>;
}

/* --- Parser --------------------------------------------------------------- */

function parseCounts(raw: unknown): TraceV2Counts {
  const block = record(raw);
  return {
    documentsRetrieved: num(block.documents_retrieved) ?? num(block.documents_consulted),
    documentsUsed: num(block.documents_used),
    documentsSelected: num(block.documents_selected),
    documentsUsedForDecision: num(block.documents_used_for_decision),
    documentsCited: num(block.documents_cited),
    evidenceRetrieved: num(block.evidence_retrieved),
    evidenceDeduplicated: num(block.evidence_deduplicated),
    evidenceUnique: num(block.evidence_unique),
    evidenceSelected: num(block.evidence_selected),
    evidenceUsed: num(block.evidence_used),
    evidenceUsedForReasoning: num(block.evidence_used_for_reasoning),
    evidenceUsedForRuleCompilation: num(block.evidence_used_for_rule_compilation),
    evidenceUsedForPremiseClosure: num(block.evidence_used_for_premise_closure),
    evidenceUsedForDecision: num(block.evidence_used_for_decision),
    evidenceDecision: num(block.evidence_decision),
    mainRetrievalHits: num(block.main_retrieval_hits),
    evidenceCited: num(block.evidence_cited),
  };
}

function parseRawHit(raw: Json): TraceV2RawHit {
  return {
    hitId: str(raw.hit_id),
    evidenceId: str(raw.evidence_id),
    chunkId: str(raw.chunk_id),
    page: num(raw.page),
    score: num(raw.score),
    retrieval: str(raw.retrieval),
    origin: str(raw.origin),
    status: str(raw.status),
    used: raw.used === true,
    cited: raw.cited === true,
  };
}

function parseEvidenceItem(raw: Json): TraceV2EvidenceItem {
  const section = raw.section_path;
  return {
    evidenceId: str(raw.evidence_id),
    canonicalSourceId: str(raw.canonical_source_id),
    documentId: str(raw.document_id),
    documentName: str(raw.document_name),
    displayName: str(raw.display_name),
    nameMissing: raw.name_missing === true,
    page: num(raw.page),
    sectionPath: Array.isArray(section)
      ? section.filter((part): part is string => typeof part === "string")
      : [],
    excerpt: str(raw.excerpt),
    score: num(raw.score),
    rerankScore: num(raw.rerank_score),
    retrieval: str(raw.retrieval),
    authority: str(raw.authority),
    knowledgeType: str(raw.knowledge_type),
    used: raw.used === true,
    usedForReasoning: raw.used_for_reasoning === true,
    usedForRuleCompilation: raw.used_for_rule_compilation === true,
    usedForPremiseClosure: raw.used_for_premise_closure === true,
    usedForDecision: raw.used_for_decision === true,
    citationOnlyContext: raw.citation_only_context === true,
    decisionEvidence: raw.decision_evidence === true,
    cited: raw.cited === true,
    selected: raw.selected === true,
    mergedCount: num(raw.merged_count) ?? 0,
    dedupKind: str(raw.dedup_kind),
    hitCount: num(raw.hit_count) ?? 1,
    rawHits: records(raw.raw_hits).map(parseRawHit),
  };
}

function parseDocument(raw: Json): TraceV2Document {
  return {
    key: text(raw.document_key),
    canonicalSourceId: str(raw.canonical_source_id),
    documentId: str(raw.document_id),
    name: str(raw.document_name),
    displayName: str(raw.display_name),
    nameMissing: raw.name_missing === true,
    identityWeak: raw.identity_weak === true,
    evidenceCount: num(raw.evidence_count) ?? 0,
    usedCount: num(raw.used_count) ?? 0,
    decisionCount: num(raw.decision_count) ?? 0,
    citedCount: num(raw.cited_count) ?? 0,
    items: records(raw.items).map(parseEvidenceItem),
  };
}

function parseJudgment(raw: Json): TraceV2Judgment {
  const interpretation = record(raw.interpretation);
  const options = records(interpretation.options).map((option) => ({
    key: text(option.key),
    probability: num(option.probability),
    selected: option.selected === true,
  }));
  return {
    id: str(raw.judgment_id) ?? str(raw.id) ?? "judgment",
    phase: str(raw.phase),
    purpose: str(raw.purpose),
    questionCode: text(raw.question_code) || text(raw.id),
    type: text(raw.type) || "noul",
    answer: raw.answer === null || raw.answer === undefined ? null : String(raw.answer),
    selectedProbability: num(interpretation.selected_probability),
    confidence: num(interpretation.confidence),
    certainty: num(interpretation.certainty),
    margin: num(interpretation.margin),
    entropy: num(interpretation.entropy),
    band: str(interpretation.band),
    verdict: str(interpretation.verdict),
    options,
    raw: record(raw.raw),
    appliedDecisionId: str(raw.applied_decision_id),
    effectCode: str(raw.effect_code),
    status: text(raw.status) || "ACTIVE",
    supersededBy: str(raw.superseded_by),
    sequence: num(raw.sequence),
    timestamp: str(raw.timestamp),
    finalEffect:
      raw.final_effect === null || raw.final_effect === undefined
        ? null
        : String(raw.final_effect),
  };
}

function parseDecision(raw: Json): TraceV2Decision {
  return {
    id: str(raw.decision_id) ?? str(raw.id) ?? "decision",
    phase: str(raw.phase),
    action: text(raw.action),
    provider: text(raw.provider) || "JEV",
    questionId: str(raw.question_id),
    applied: raw.action_applied === true,
    material: raw.material === true,
    changedRoute: raw.changed_route === true,
    isDefault: raw.is_default === true,
    classification: text(raw.classification) || "OBSERVATIONAL",
    reasonCodes: Array.isArray(raw.reason_codes)
      ? raw.reason_codes.filter((code): code is string => typeof code === "string")
      : [],
    effectCodes: Array.isArray(raw.effect_codes)
      ? raw.effect_codes.filter((code): code is string => typeof code === "string")
      : [],
    allowGeneration: bool(raw.allow_generation),
    tier: str(raw.tier),
    status: text(raw.status) || "ACTIVE",
    supersededBy: str(raw.superseded_by),
    sequence: num(raw.sequence),
  };
}

function parseControl(raw: Json): TraceV2Control {
  return {
    controlCode: text(raw.control_code),
    severity: text(raw.severity) || "NOTICE",
    trigger: str(raw.trigger),
    actionTaken: str(raw.action_taken),
    recovered: raw.recovered === true,
    materialEffect: raw.material_effect === true,
    params: record(raw.params),
    sourceEventIds: Array.isArray(raw.source_event_ids)
      ? raw.source_event_ids.filter((id): id is string => typeof id === "string")
      : [],
  };
}

function parseDiagnosticItem(raw: Json): TraceV2DiagnosticItem {
  return {
    code: text(raw.code),
    severity: text(raw.severity) || "NOTICE",
    dimension: text(raw.dimension) || "execution",
    materialEffect: raw.material_effect === true,
    meaningCode: text(raw.meaning_code),
    impactCode: text(raw.impact_code),
    fixCode: str(raw.fix_code),
    params: record(raw.params),
    sourceEventIds: Array.isArray(raw.source_event_ids)
      ? raw.source_event_ids.filter((id): id is string => typeof id === "string")
      : [],
  };
}

function parseDecisionVerification(raw: unknown): TraceV2DecisionVerification | null {
  const block = record(raw);
  const status = str(block.status);
  if (!status) return null;
  const result = block.result;
  return {
    status,
    authoritative: block.authoritative === true,
    deterministic: block.deterministic === true,
    operation: str(block.operation),
    result:
      result === null || result === undefined
        ? null
        : typeof result === "boolean" || typeof result === "number" || typeof result === "string"
          ? String(result)
          : JSON.stringify(result),
    canonicalRuleIds: strings(block.canonical_rule_ids),
    premiseStatus: str(block.premise_status),
    evidenceRefs: strings(block.evidence_refs),
    ruleVerification: str(block.rule_verification),
    conflicts: strings(block.conflicts),
  };
}

function parseNarrativeVerification(raw: unknown): TraceV2NarrativeVerification | null {
  const block = record(raw);
  const status = str(block.status);
  if (!status) return null;
  return {
    status,
    citationsValid: bool(block.citations_valid),
    explanationComplete: bool(block.explanation_complete),
    groundingComplete: bool(block.grounding_complete),
    truncated: block.truncated === true,
    warnings: strings(block.warnings),
  };
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function parseJevResolution(
  raw: unknown,
): { label: string | null; authority: boolean; premiseClosed: boolean } | null {
  const block = record(raw);
  if (!Object.keys(block).length) return null;
  return {
    label: str(block.label),
    authority: block.authority === true,
    premiseClosed: block.premise_closed === true,
  };
}

function parseFastPath(raw: unknown): TraceV2FastPath | null {
  const block = record(raw);
  if (!Object.keys(block).length) return null;
  const result = block.result;
  return {
    eligible: block.eligible === true,
    reason: str(block.reason),
    operation: str(block.operation),
    result:
      result === null || result === undefined
        ? null
        : typeof result === "boolean" || typeof result === "number" || typeof result === "string"
          ? String(result)
          : JSON.stringify(result),
    executionMode: str(block.execution_mode),
    llmCalls: num(block.llm_calls),
    llmCallsAvoided: num(block.llm_calls_avoided),
    tokensAvoided: num(block.tokens_avoided),
    costAvoidedUsd: num(block.cost_avoided_usd),
    latencyMs: num(block.latency_ms),
    verificationStatus: str(record(block.verification).status),
    decisionEvidence: parseFastPathDecisionEvidence(block.decision_evidence),
    winningRule: parseWinningRule(block.winning_rule),
  };
}

function parseFastPathDecisionEvidence(
  raw: unknown,
): TraceV2FastPathDecisionEvidence | null {
  const block = record(raw);
  if (!Object.keys(block).length) return null;
  return {
    resolved: num(block.resolved),
    unresolved: strings(block.unresolved),
    outOfScope: strings(block.out_of_scope),
    mainRetrievalHits: num(block.main_retrieval_hits),
    decisionEvidenceCount: num(block.decision_evidence_count),
    documentsUsedForDecision: num(block.documents_used_for_decision),
  };
}

function parseWinningRule(raw: unknown): TraceV2WinningRule | null {
  const block = record(raw);
  if (!Object.keys(block).length) return null;
  const pages = Array.isArray(block.pages)
    ? block.pages.filter((item): item is number => typeof item === "number")
    : [];
  return {
    ruleId: str(block.rule_id),
    documentIds: strings(block.document_ids),
    sourceIds: strings(block.source_ids),
    pages,
    documentTitle: str(block.document_title),
    parserEngine: str(block.parser_engine),
    parserVersion: str(block.parser_version),
  };
}

export function normalizeRuleId(value: string): string {
  return value.replace(/^rule:rule:/, "rule:");
}

export function parseTraceabilityV2(value: unknown): TraceV2 | null {
  const raw = record(value);
  if (raw.schema_version !== 2) return null;

  const evidence = record(raw.evidence);
  const jev = record(raw.jev);
  const generation = record(raw.generation);
  const controls = record(raw.controls);
  const verification = record(raw.verification);
  const diagnostics = record(raw.diagnostics);
  const presentation = record(raw.presentation);
  const timing = record(raw.timing);
  const cost = record(raw.cost);
  const memory = record(raw.memory);

  const dimensions: Record<string, TraceV2Dimension> = {};
  for (const [key, value] of Object.entries(record(diagnostics.dimensions))) {
    const dimension = record(value);
    dimensions[key] = {
      status: text(dimension.status) || "unknown",
      severity: str(dimension.severity),
      findings: num(dimension.findings) ?? 0,
    };
  }

  return {
    schemaVersion: 2,
    upgradedFromSchema: num(raw.upgraded_from_schema),
    execution: {
      kind: str(record(raw.execution).kind),
      id: str(record(raw.execution).id),
      question: str(record(raw.execution).question),
      status: str(record(raw.execution).status),
      delivered: bool(record(raw.execution).delivered),
      method: str(record(raw.execution).method),
      mode: str(record(raw.execution).mode),
      fastPath: parseFastPath(record(raw.execution).fast_path),
    },
    routing: {
      route: str(record(raw.routing).route),
      decider: str(record(raw.routing).decider),
      confidence: num(record(raw.routing).confidence),
      intent: str(record(raw.routing).intent),
    },
    knowledge: {
      strategy: str(record(raw.knowledge).strategy),
      engineStrategy: str(record(raw.knowledge).engine_strategy),
      chunks: num(record(raw.knowledge).chunks),
      topScore: num(record(raw.knowledge).top_score),
      representation: record(record(raw.knowledge).representation),
    },
    retrieval: {
      rounds: records(record(raw.retrieval).rounds).map((round) => ({
        attempt: num(round.attempt) ?? 0,
        strategy: str(round.strategy),
        evidence: num(round.evidence),
        sufficient: bool(round.sufficient),
        qualityScore: num(round.quality_score),
      })),
      expanded: record(raw.retrieval).expanded === true,
      skipRetrieval: bool(record(raw.retrieval).skip_retrieval),
      attempts: num(record(raw.retrieval).attempts),
    },
    counts: parseCounts(evidence.counts),
    legacyCounts: parseCounts(raw.counts),
    collection: text(evidence.collection) || "unknown",
    dedup: {
      merged: num(record(evidence.dedup).merged),
      exact: num(record(evidence.dedup).exact),
      overlap: num(record(evidence.dedup).overlap),
      semantic: num(record(evidence.dedup).semantic),
    },
    canonicalEvidence: records(evidence.canonical_evidence).map(parseEvidenceItem),
    rawHits: records(evidence.raw_hits).map(parseRawHit),
    documents: records(evidence.documents).map(parseDocument),
    citationsSummary: {
      references: num(record(evidence.citations_summary).references),
      citedReferences: num(record(evidence.citations_summary).cited_references),
      uniqueCited: num(record(evidence.citations_summary).unique_cited),
      collapsed: num(record(evidence.citations_summary).collapsed),
      dangling: Array.isArray(record(evidence.citations_summary).dangling)
        ? (record(evidence.citations_summary).dangling as unknown[]).filter(
            (item): item is string => typeof item === "string",
          )
        : [],
    },
    jev: {
      executed: jev.executed === true,
      mode: str(jev.mode),
      calls: num(jev.calls),
      checks: num(jev.checks),
      judgmentsCount: num(jev.judgments_count) ?? 0,
      materialIntervention: jev.material_intervention === true,
      changedRoute: jev.changed_route === true,
      requestedMoreEvidence: jev.requested_more_evidence === true,
      blockedGeneration: jev.blocked_generation === true,
      latencyMs: num(jev.latency_ms),
      costUsd: num(jev.cost_usd),
      judgments: records(jev.judgments).map(parseJudgment),
      decisions: records(jev.decisions).map(parseDecision),
      supersededCount: num(jev.superseded_count) ?? 0,
      resolution: parseJevResolution(jev.resolution),
    },
    generation: {
      observed: generation.observed === true,
      skipped: bool(generation.skipped),
      model: str(generation.model),
      provider: str(generation.provider),
      calls: num(generation.calls),
      answerCalls: num(generation.answer_calls),
      reasoningCalls: num(generation.reasoning_calls),
      revisionCalls: num(generation.revision_calls),
      callsDetail: records(generation.call_details).map((call) => ({
        id: text(call.id) || "model-call",
        sequence: num(call.sequence),
        purpose: text(call.purpose) || "unknown",
        model: str(call.model),
        provider: str(call.provider),
        durationMs: num(call.duration_ms),
        inputTokens: num(call.input_tokens),
        outputTokens: num(call.output_tokens),
        totalTokens: num(call.total_tokens),
        costUsd: num(call.cost_usd),
      })),
      tokens: {
        input: num(record(generation.tokens).input),
        output: num(record(generation.tokens).output),
        total: num(record(generation.tokens).total),
      },
      durationMs: num(generation.duration_ms),
      costUsd: num(generation.cost_usd),
      finishReason: str(generation.finish_reason),
    },
    controls: records(controls.controls).map(parseControl),
    fallbacks: {
      events: records(record(controls.fallbacks).events).map((event) => ({
        code: text(event.code),
        fallbackClass: text(event.class) || "warning",
        materialEffect: event.material_effect === true,
        recovered: event.recovered === true,
      })),
      material: record(controls.fallbacks).material === true,
      classes: Object.fromEntries(
        Object.entries(record(record(controls.fallbacks).classes)).map(
          ([key, value]) => [key, num(value) ?? 0],
        ),
      ),
    },
    verification: {
      status: text(verification.status) || "UNVERIFIED",
      explanationCodes: records(verification.explanation_codes).map((item) => ({
        code: text(item.code),
        check: str(item.check) ?? undefined,
        count: num(item.count) ?? undefined,
        impact: str(item.impact) ?? undefined,
      })),
      checks: records(verification.checks).map((check) => ({
        key: text(check.key),
        state: text(check.state) || "not_observed",
        detail: str(check.detail),
        quality: num(check.quality),
      })),
      degradations: records(verification.degradations).map((item) => ({
        code: text(item.code),
        impact: text(item.impact),
        checks: record(item.checks),
      })),
      grounded: bool(record(verification.signals).grounded),
      fallbackUsed: record(verification.signals).fallback_used === true,
      fallbackCode: str(record(verification.signals).fallback_code),
      materialFallback: record(verification.signals).material_fallback === true,
      quality: num(record(record(verification.metrics).quality).value),
      decisionVerification: parseDecisionVerification(verification.decision_verification),
      narrativeVerification: parseNarrativeVerification(verification.narrative_verification),
      decisionGrounding: str(verification.decision_grounding) ?? str(record(verification.signals).decision_grounding),
      narrativeGrounding: str(verification.narrative_grounding) ?? str(record(verification.signals).narrative_grounding),
    },
    memory: {
      observed: memory.observed === true,
      available: bool(memory.available),
      used: num(memory.used),
      created: num(memory.created),
      reinforced: num(memory.reinforced),
      contradicted: num(memory.contradicted),
    },
    timing: {
      wallClockMs: num(timing.wall_clock_ms),
      accumulatedMs: num(timing.accumulated_ms),
      parallel: bool(timing.parallel),
      breakdown: records(timing.breakdown).map((part) => ({
        code: text(part.code),
        ms: num(part.ms) ?? 0,
      })),
    },
    cost: {
      totalUsd: num(cost.total_usd),
      breakdown: records(cost.breakdown).map((part) => ({
        code: text(part.code),
        usd: num(part.usd) ?? 0,
      })),
    },
    diagnostics: {
      items: records(diagnostics.items).map(parseDiagnosticItem),
      dimensions,
      consistency: {
        status: text(record(diagnostics.consistency).status) || "consistent",
        findings: num(record(diagnostics.consistency).findings) ?? 0,
        responseQuality: str(record(diagnostics.consistency).response_quality),
      },
      overall: {
        status: text(record(diagnostics.overall).status) || "unknown",
        severity: str(record(diagnostics.overall).severity),
        findings: num(record(diagnostics.overall).findings) ?? 0,
      },
    },
    presentation: {
      headlineCode: text(record(presentation.headline).code),
      support: {
        documentsUsed: num(record(presentation.support).documents_used),
        evidenceUnique: num(record(presentation.support).evidence_unique),
        evidenceUsed: num(record(presentation.support).evidence_used),
        evidenceCited: num(record(presentation.support).evidence_cited),
        collection: text(record(presentation.support).collection) || "unknown",
      },
      journey: records(presentation.journey).map((node) => ({
        id: text(node.id) || `journey:${text(node.kind)}`,
        kind: text(node.kind),
        sequence: num(node.sequence) ?? 0,
        params: record(node.params),
        sourceEventIds: Array.isArray(node.source_event_ids)
          ? node.source_event_ids.filter((id): id is string => typeof id === "string")
          : [],
      })),
      explanations: records(presentation.explanations).map((item) => ({
        code: text(item.code),
        params: record(item.params),
      })),
      metricRefs: Array.isArray(presentation.metric_refs)
        ? presentation.metric_refs.filter((item): item is string => typeof item === "string")
        : [],
      glossaryRefs: Array.isArray(presentation.glossary_refs)
        ? presentation.glossary_refs.filter((item): item is string => typeof item === "string")
        : [],
    },
    timeline: records(raw.timeline).map((entry) => ({
      id: text(entry.id) || "trace",
      type: text(entry.type),
      purpose: str(entry.purpose),
      userVisible: entry.user_visible === true,
      status: text(entry.status) || "ok",
      decisionId: str(entry.decision_id),
    })),
    runtimeSteps: records(raw.runtime_steps).map((step) => ({
      type: text(step.type) || "step",
      name: str(step.name),
      status: text(step.status) || "ok",
      detail: str(step.detail),
      ms: num(step.ms),
      unmapped: step.unmapped === true,
      superseded: step.superseded === true,
      supersededBy: str(step.superseded_by),
    })),
  };
}

/* --- Derivaciones de presentación ----------------------------------------- */

export function supportSummary(trace: TraceV2): string {
  const { documentsUsed, evidenceUnique, evidenceCited } = trace.presentation.support;
  const parts: string[] = [];
  if (documentsUsed !== null) {
    parts.push(`${documentsUsed} ${documentsUsed === 1 ? "documento" : "documentos"}`);
  }
  if (evidenceUnique !== null) {
    parts.push(`${evidenceUnique} ${evidenceUnique === 1 ? "evidencia única" : "evidencias únicas"}`);
  } else if (evidenceCited !== null) {
    parts.push(`${evidenceCited} ${evidenceCited === 1 ? "evidencia citada" : "evidencias citadas"}`);
  }
  return parts.length ? parts.join(" · ") : "Sin evidencia documental";
}

export function jevSummary(trace: TraceV2): string {
  const jev = trace.jev;
  if (!jev.executed) return "No fue necesario";
  const checks = jev.checks;
  const checksText =
    checks !== null
      ? `Revisó ${checks} ${checks === 1 ? "decisión" : "decisiones"}`
      : "Revisó las decisiones";
  if (jev.requestedMoreEvidence) {
    const resolution = jev.resolution?.label;
    if (resolution) {
      return `${checksText}, pidió más evidencia y ese juicio quedó superado por ${resolution}`;
    }
    return `${checksText} y pidió más evidencia`;
  }
  if (jev.changedRoute) return `${checksText} y cambió el camino`;
  return `${checksText} y mantuvo el camino original`;
}

export function evidenceUsageSummary(trace: TraceV2): string {
  const counts = trace.counts;
  const parts: string[] = [];
  if (counts.evidenceRetrieved !== null) {
    parts.push(
      `${counts.evidenceRetrieved} ${counts.evidenceRetrieved === 1 ? "fragmento recuperado" : "fragmentos recuperados"}`,
    );
  }
  if (counts.evidenceUnique !== null) {
    parts.push(
      `${counts.evidenceUnique} ${counts.evidenceUnique === 1 ? "evidencia única" : "evidencias únicas"}`,
    );
  }
  if (counts.evidenceUsedForDecision !== null) {
    parts.push(`${counts.evidenceUsedForDecision} usadas para la decisión`);
  }
  if (counts.evidenceUsedForReasoning !== null) {
    parts.push(`${counts.evidenceUsedForReasoning} usadas para razonar`);
  }
  if (counts.evidenceCited !== null) {
    parts.push(
      `${counts.evidenceCited} ${counts.evidenceCited === 1 ? "citada" : "citadas"}`,
    );
  }
  return parts.join(" · ");
}

export function verificationSummary(trace: TraceV2): string {
  const decision = trace.verification.decisionVerification;
  const narrative = trace.verification.narrativeVerification;
  if (decision && decision.status === "VERIFIED") {
    if (narrative && narrative.status === "VERIFIED") return "Respuesta verificada";
    if (narrative && narrative.status === "UNVERIFIED") {
      return "Decisión verificada · explicación sin verificar";
    }
    return "Decisión verificada · explicación parcialmente verificada";
  }
  if (decision && decision.status === "NOT_VERIFIED") return "Decisión no verificada";
  const status = trace.verification.status;
  if (status === "VERIFIED") return "Respaldo confirmado";
  if (status === "PARTIALLY_VERIFIED") return "Respaldo confirmado parcialmente";
  if (status === "CONFLICTING_EVIDENCE") return "Evidencia en conflicto";
  if (status === "INSUFFICIENT_EVIDENCE") return "Evidencia insuficiente";
  return "Sin respaldo confirmado";
}

export function decisionStatusLabel(status: string): string {
  if (status === "VERIFIED") return "Verificada determinísticamente";
  if (status === "NOT_VERIFIED") return "No verificada";
  if (status === "UNDETERMINED") return "Sin decisión determinista";
  return status;
}

export function narrativeStatusLabel(status: string): string {
  if (status === "VERIFIED") return "Verificada";
  if (status === "PARTIAL") return "Parcialmente verificada";
  if (status === "TRUNCATED") return "Truncada por límite de generación";
  if (status === "UNVERIFIED") return "Sin verificar";
  return status;
}

export function groundingLabel(status: string | null): string {
  if (status === "CONFIRMED") return "Confirmado";
  if (status === "COMPLETE") return "Completo";
  if (status === "PARTIAL") return "Parcial";
  if (status === "BLOCKED") return "Bloqueado";
  if (status === "UNKNOWN") return "Sin datos";
  return "—";
}

export function findingGroups(trace: TraceV2): Array<{
  code: string;
  count: number;
  title: string;
}> {
  const byCode = new Map<string, number>();
  for (const item of trace.diagnostics.items) {
    byCode.set(item.code, (byCode.get(item.code) ?? 0) + 1);
  }
  return Array.from(byCode.entries()).map(([code, count]) => ({
    code,
    count,
    title: diagnosticCopy(code).title,
  }));
}

export function metricHelpFor(trace: TraceV2): string[] {
  return trace.presentation.metricRefs;
}

export function headlineFor(trace: TraceV2) {
  return headlineMeta(trace.presentation.headlineCode);
}

export function fmtMs(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.round(value)} ms`;
}

export function fmtUsd(value: number | null): string {
  if (value === null) return "—";
  return `USD ${value.toFixed(6)}`;
}

export function fmtPercent(value: number | null): string {
  if (value === null) return "—";
  const percent = value * 100;
  return `${percent >= 10 ? Math.round(percent) : percent.toFixed(1)}%`;
}
