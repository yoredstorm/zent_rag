// =============================================================================
// traceabilityV2 — parser y derivaciones del contrato canónico v2
// =============================================================================
import { describe, expect, it } from "vitest";
import { diagnosticCopy, headlineMeta } from "./traceabilityCatalog";
import {
  evidenceUsageSummary,
  fmtMs,
  fmtPercent,
  fmtUsd,
  jevSummary,
  parseTraceabilityV2,
  supportSummary,
  verificationSummary,
} from "./traceabilityV2";

const TRACE = {
  schema_version: 2,
  execution: {
    kind: "query",
    id: "q-1",
    question: "¿Qué código aplica?",
    status: "completed",
    delivered: true,
    method: "rag",
  },
  routing: { route: "Documentos", decider: "JEV", confidence: 0.93 },
  knowledge: { strategy: "hybrid", chunks: 5 },
  retrieval: { rounds: [], expanded: false },
  counts: {
    documents_consulted: 5,
    documents_used: 5,
    evidence_retrieved: 5,
    evidence_used: 4,
    evidence_cited: 3,
  },
  evidence: {
    collection: "complete",
    counts: {
      documents_retrieved: 5,
      documents_used: 5,
      evidence_retrieved: 8,
      evidence_deduplicated: 3,
      evidence_unique: 5,
      evidence_selected: 5,
      evidence_used: 4,
      evidence_cited: 4,
    },
    dedup: { merged: 3, exact: 2, overlap: 1, semantic: 0 },
    documents: [
      {
        document_key: "src_a",
        canonical_source_id: "src_a",
        document_name: "rules.pdf",
        display_name: "rules.pdf",
        name_missing: false,
        evidence_count: 2,
        used_count: 2,
        cited_count: 1,
        items: [],
      },
    ],
    items: [],
    canonical_evidence: [
      {
        evidence_id: "E1",
        canonical_source_id: "src_a",
        document_name: "rules.pdf",
        display_name: "rules.pdf",
        page: 18,
        excerpt: "Carrier Code",
        used: true,
        cited: true,
        merged_count: 1,
        hit_count: 2,
        dedup_kind: "overlap",
        raw_hits: [{ hit_id: "hit:1", evidence_id: "E1", used: true }],
      },
    ],
    citations_summary: {
      references: 5,
      cited_references: 5,
      unique_cited: 4,
      collapsed: 1,
      dangling: [],
    },
  },
  jev: {
    executed: true,
    mode: "on",
    calls: 1,
    checks: 4,
    judgments_count: 1,
    material_intervention: false,
    changed_route: false,
    requested_more_evidence: false,
    blocked_generation: false,
    decisions: [
      {
        decision_id: "decision:1",
        action: "generate",
        action_applied: true,
        classification: "OBSERVATIONAL",
        material: false,
        is_default: true,
        changed_route: false,
        reason_codes: ["default"],
      },
    ],
    judgments: [
      {
        id: "tool",
        judgment_id: "pre_generation:tool",
        phase: "pre_generation",
        question_code: "tool",
        type: "choice",
        answer: "none",
        effect_code: null,
        applied_decision_id: null,
        interpretation: {
          outcome_key: "none",
          selected_probability: 0.75,
          confidence: 0.49,
          certainty: null,
          margin: 0.5,
          entropy: 0.81,
          band: "low",
          verdict: "UNCERTAIN",
          options: [
            { key: "none", probability: 0.75, selected: true },
            { key: "search_knowledge", probability: 0.25, selected: false },
          ],
        },
        raw: { type: "choice", distribution: { probabilities: { none: 0.75 } } },
      },
    ],
  },
  generation: {
    observed: true,
    skipped: false,
    model: "zent-default",
    calls: 2,
    answer_calls: 1,
    reasoning_calls: 1,
    revision_calls: 0,
    call_details: [
      { id: "llm-1", sequence: 1, purpose: "reasoning" },
      { id: "llm-2", sequence: 2, purpose: "answer_generation" },
    ],
    tokens: { input: 6687, output: 1068, total: 7755 },
    duration_ms: 6700,
    cost_usd: 0.001018,
  },
  controls: {
    controls: [
      {
        control_code: "MAX_TOKENS_REACHED",
        severity: "WARNING",
        recovered: true,
        material_effect: false,
        params: { impact: "RECOVERED_NO_IMPACT" },
      },
    ],
    fallbacks: { events: [], material: false, classes: {} },
    generation_warnings: [],
  },
  verification: {
    status: "VERIFIED",
    explanation_codes: [{ code: "DOCUMENTARY_SUPPORT_CONFIRMED" }],
    checks: [{ key: "grounding", state: "ok" }],
    degradations: [],
    signals: { grounded: true, fallback_used: false, material_fallback: false },
    metrics: { quality: { value: 2.87, ref: "quality" } },
  },
  memory: { observed: false, available: null },
  timing: { wall_clock_ms: 18089, accumulated_ms: 24332, parallel: true, breakdown: [] },
  cost: { total_usd: 0.001018, breakdown: [] },
  diagnostics: {
    items: [
      {
        code: "PROBABILITY_MISMATCH",
        severity: "WARNING",
        dimension: "consistency",
        material_effect: false,
        meaning_code: "confidence_conflict",
        impact_code: "no_content_impact",
        fix_code: "separate_probability_confidence",
        params: { selected_probability: 0.75, confidence: 0.49, outcome_key: "none" },
      },
    ],
    dimensions: {
      execution: { status: "ok", severity: null, findings: 0 },
      evidence: { status: "ok", severity: null, findings: 0 },
      jev: { status: "ok", severity: null, findings: 0 },
      generation: { status: "notice", severity: "NOTICE", findings: 1 },
      verification: { status: "ok", severity: null, findings: 0 },
      metadata: { status: "ok", severity: null, findings: 0 },
      consistency: { status: "warning", severity: "WARNING", findings: 1 },
    },
    consistency: { status: "partial", findings: 1, response_quality: "VERIFIED" },
    overall: { status: "notice", severity: "NOTICE", findings: 2 },
  },
  presentation: {
    headline: { code: "RESPONSE_SUPPORTED", params: {} },
    support: {
      documents_used: 5,
      evidence_unique: 5,
      evidence_used: 4,
      evidence_cited: 4,
      collection: "complete",
    },
    journey: [
      {
        id: "journey:1:knowledge_searched",
        kind: "KNOWLEDGE_SEARCHED",
        sequence: 1,
        params: { retrieved: 8, deduplicated: 3, unique: 5 },
      },
      {
        id: "journey:2:jev_checked",
        kind: "JEV_CHECKED",
        sequence: 2,
        params: { checks: 4, material_intervention: false, changed_route: false },
      },
    ],
    explanations: [
      {
        code: "MAX_TOKENS_RECOVERY",
        params: { impact: "RECOVERED_NO_IMPACT" },
      },
    ],
    metric_refs: ["selected_probability", "confidence", "entropy"],
    glossary_refs: ["jev", "evidence"],
  },
  timeline: [],
};

describe("parseTraceabilityV2", () => {
  it("rechaza schemas que no son v2", () => {
    expect(parseTraceabilityV2(null)).toBeNull();
    expect(parseTraceabilityV2({ schema_version: 1 })).toBeNull();
    expect(parseTraceabilityV2({})).toBeNull();
  });

  it("normaliza conteos y deduplicación sin inventar ceros", () => {
    const trace = parseTraceabilityV2(TRACE);
    expect(trace).not.toBeNull();
    expect(trace?.counts.evidenceRetrieved).toBe(8);
    expect(trace?.counts.evidenceUnique).toBe(5);
    expect(trace?.counts.evidenceUsed).toBe(4);
    expect(trace?.counts.evidenceCited).toBe(4);
    expect(trace?.counts.evidenceSelected).toBe(5);
    const empty = parseTraceabilityV2({ schema_version: 2 });
    expect(empty?.counts.evidenceUnique).toBeNull();
  });

  it("mantiene probabilidad y confianza separadas", () => {
    const trace = parseTraceabilityV2(TRACE);
    const [judgment] = trace?.jev.judgments ?? [];
    expect(judgment.selectedProbability).toBe(0.75);
    expect(judgment.confidence).toBe(0.49);
    expect(judgment.margin).toBe(0.5);
    expect(judgment.entropy).toBe(0.81);
    expect(judgment.options.map((option) => option.key)).toEqual([
      "none",
      "search_knowledge",
    ]);
  });

  it("deriva resúmenes humanos desde el mismo dato", () => {
    const trace = parseTraceabilityV2(TRACE);
    expect(trace).not.toBeNull();
    if (!trace) return;
    expect(supportSummary(trace)).toBe("5 documentos · 5 evidencias únicas");
    expect(jevSummary(trace)).toBe("Revisó 4 decisiones y mantuvo el camino original");
    expect(fmtMs(18089)).toBe("18.1 s");
    expect(fmtMs(420)).toBe("420 ms");
    expect(fmtMs(null)).toBe("—");
    expect(fmtUsd(0.001018)).toBe("USD 0.001018");
    expect(fmtPercent(0.75)).toBe("75%");
    expect(fmtPercent(0.049)).toBe("4.9%");
  });

  it("expone diagnóstico con explicación en tres preguntas", () => {
    const trace = parseTraceabilityV2(TRACE);
    const [item] = trace?.diagnostics.items ?? [];
    expect(item.severity).toBe("WARNING");
    expect(item.dimension).toBe("consistency");
    const copy = diagnosticCopy(item.code);
    expect(copy.title).toBe("Probabilidad y confianza no coinciden");
    expect(copy.meaning(item.params)).toContain("75%");
    expect(copy.meaning(item.params)).toContain("49%");
    expect(copy.impact(item.params)).toContain("No afecta la respuesta");
    expect(copy.fix(item.params)).toContain("confianza derivada");
  });

  it("marca la degradación de max_tokens como estado del control", () => {
    const trace = parseTraceabilityV2(TRACE);
    const [control] = trace?.controls ?? [];
    expect(control.controlCode).toBe("MAX_TOKENS_REACHED");
    expect(control.materialEffect).toBe(false);
    expect(control.params.impact).toBe("RECOVERED_NO_IMPACT");
  });

  it("separa ejes de uso y juicios superados", () => {
    const raw = {
      ...TRACE,
      evidence: {
        ...TRACE.evidence,
        counts: {
          ...TRACE.evidence.counts,
          evidence_used_for_reasoning: 2,
          evidence_used_for_rule_compilation: 1,
          evidence_used_for_premise_closure: 1,
          evidence_used_for_decision: 3,
          documents_selected: 1,
          documents_used_for_decision: 1,
          documents_cited: 1,
        },
        canonical_evidence: [
          {
            ...TRACE.evidence.canonical_evidence[0],
            used_for_decision: true,
            used_for_reasoning: true,
            citation_only_context: false,
          },
        ],
      },
      jev: {
        ...TRACE.jev,
        requested_more_evidence: true,
        superseded_count: 2,
        resolution: {
          label: "DecisionEnvelope MATCH",
          authority: true,
          premise_closed: true,
        },
        judgments: TRACE.jev.judgments.map((judgment) => ({
          ...judgment,
          status: "SUPERSEDED",
          superseded_by: "DecisionEnvelope MATCH",
          sequence: 1,
          final_effect: "resolved_by_later_stage",
        })),
      },
    };
    const trace = parseTraceabilityV2(raw);
    expect(trace).not.toBeNull();
    if (!trace) return;
    expect(trace.counts.evidenceUsedForDecision).toBe(3);
    expect(trace.counts.documentsUsedForDecision).toBe(1);
    expect(trace.jev.supersededCount).toBe(2);
    expect(trace.jev.judgments[0].status).toBe("SUPERSEDED");
    expect(trace.jev.judgments[0].supersededBy).toBe("DecisionEnvelope MATCH");
    expect(trace.canonicalEvidence[0].usedForDecision).toBe(true);    expect(evidenceUsageSummary(trace)).toContain("3 usadas para la decisión");
    expect(evidenceUsageSummary(trace)).toContain("2 usadas para razonar");
    expect(jevSummary(trace)).toContain("superado por DecisionEnvelope MATCH");
  });

  it("expone el modo de ejecución y la telemetría del fast path", () => {
    const raw = {
      ...TRACE,
      execution: {
        ...TRACE.execution,
        mode: "DETERMINISTIC_FAST_PATH",
        fast_path: {
          eligible: true,
          reason: "SUPPORTED_DECISION",
          operation: "POSITIONAL_MATCH",
          result: "MATCH",
          execution_mode: "DETERMINISTIC_FAST_PATH",
          llm_calls: 0,
          llm_calls_avoided: 2,
          tokens_avoided: 3500,
          latency_ms: 85,
          verification: { status: "VERIFIED_DETERMINISTIC" },
        },
      },
    };
    const trace = parseTraceabilityV2(raw);
    expect(trace).not.toBeNull();
    if (!trace) return;
    expect(trace.execution.mode).toBe("DETERMINISTIC_FAST_PATH");
    expect(trace.execution.fastPath?.llmCalls).toBe(0);
    expect(trace.execution.fastPath?.llmCallsAvoided).toBe(2);
    expect(trace.execution.fastPath?.tokensAvoided).toBe(3500);
    expect(trace.execution.fastPath?.latencyMs).toBe(85);
    expect(trace.execution.fastPath?.verificationStatus).toBe("VERIFIED_DETERMINISTIC");
    expect(headlineMeta("RESPONSE_VERIFIED").title).toBe("Respuesta verificada");
  });

  it("traduce el titular desde el catálogo central", () => {
    expect(headlineMeta("RESPONSE_SUPPORTED").title).toBe("Respuesta respaldada");
    expect(headlineMeta("RESPONSE_PARTIALLY_SUPPORTED").title).toBe(
      "Respuesta con verificación parcial",
    );
    expect(headlineMeta("DESCONOCIDO").title).toBe("Ejecución sin estado canónico");
  });

  it("separa la decisión verificada de la narrativa parcial", () => {
    const raw = {
      ...TRACE,
      verification: {
        ...TRACE.verification,
        status: "PARTIALLY_VERIFIED",
        signals: { grounded: false, fallback_used: false, material_fallback: false },
        decision_verification: {
          status: "VERIFIED",
          authoritative: true,
          deterministic: true,
          operation: "POSITIONAL_MATCH",
          result: "MATCH",
          canonical_rule_ids: ["rule:atpco"],
          premise_status: "SATISFIED",
          evidence_refs: ["E1"],
          rule_verification: "SUPPORTED",
          conflicts: [],
        },
        narrative_verification: {
          status: "TRUNCATED",
          truncated: true,
          warnings: ["MAX_TOKENS_REACHED"],
          citations_valid: null,
          explanation_complete: false,
          grounding_complete: false,
        },
        decision_grounding: "CONFIRMED",
        narrative_grounding: "BLOCKED",
      },
    };
    const trace = parseTraceabilityV2(raw);
    expect(trace).not.toBeNull();
    if (!trace) return;
    expect(trace.verification.decisionVerification?.status).toBe("VERIFIED");
    expect(trace.verification.decisionVerification?.operation).toBe("POSITIONAL_MATCH");
    expect(trace.verification.narrativeVerification?.status).toBe("TRUNCATED");
    expect(trace.verification.decisionGrounding).toBe("CONFIRMED");
    expect(trace.verification.narrativeGrounding).toBe("BLOCKED");
    expect(verificationSummary(trace)).toBe(
      "Decisión verificada · explicación parcialmente verificada",
    );
    expect(headlineMeta("RESPONSE_DECISION_VERIFIED_NARRATIVE_PARTIAL").title).toBe(
      "Decisión verificada · explicación parcialmente verificada",
    );
    expect(headlineMeta("RESPONSE_DECISION_NOT_VERIFIED").title).toBe("Decisión no verificada");
  });

  it("no muestra 'sin respaldo' para una decisión verificada", () => {
    const raw = {
      ...TRACE,
      verification: {
        ...TRACE.verification,
        status: "PARTIALLY_VERIFIED",
        signals: { grounded: false, fallback_used: false, material_fallback: false },
        decision_verification: {
          status: "VERIFIED",
          authoritative: true,
          deterministic: true,
          operation: "POSITIONAL_MATCH",
          result: "MATCH",
        },
        narrative_verification: { status: "PARTIAL", warnings: ["GROUNDING_BLOCKED"] },
        decision_grounding: "CONFIRMED",
        narrative_grounding: "BLOCKED",
      },
    };
    const trace = parseTraceabilityV2(raw);
    if (!trace) return;
    expect(verificationSummary(trace)).not.toBe("Sin respaldo confirmado");
  });

  it("mantiene los conteos legacy como espejo", () => {
    const trace = parseTraceabilityV2(TRACE);
    expect(trace?.legacyCounts.documentsUsed).toBe(5);
    expect(trace?.legacyCounts.evidenceRetrieved).toBe(5);
  });
});
