import { describe, expect, it } from "vitest";
import { parseExecutionNarrative } from "./executionNarrative";

const NARRATIVE = {
  schema_version: 1,
  outcome: {
    code: "ANSWERED_WITH_LIMITS",
    reason_code: "verification_partial",
    evidence_state: "complete",
    verification_state: "partial",
    answer_delivered: true,
  },
  summary: { decisions_influenced: 1, judgment_count: 4, total_ms: 27500, cost_usd: 0.00176 },
  understanding: {
    application: "Aplicar la regla al fare basis de ejemplo",
    fields: ["FCLAS"],
    rules: ["&&&F"],
    examples: ["QNNF0SME"],
  },
  requirements: [
    { id: "field", label: "FCLAS", kind: "DOCUMENTABLE", status: "FOUND", source_required: true },
    { id: "example", label: "QNNF0SME", kind: "USER_INPUT", status: "PROVIDED", source_required: false },
  ],
  journey: [{ id: "j1", kind: "QUERY_UNDERSTOOD", sequence: 1 }],
  judgments: [
    {
      id: "needs_more_evidence",
      question_code: "needs_more_evidence",
      type: "NOUL",
      answer: "yes",
      probability: 0.72,
      certainty: 0.51,
      confidence_band: "medium",
      applied_decision_id: "decision:1",
      alternatives: [],
    },
  ],
  applied_decisions: [
    { id: "decision:1", action: "retrieve_more", decider: "JEV", impact_code: "retrieve_more" },
  ],
  evidence: {
    complete: true,
    missing_documentable_evidence: [],
    document_count: 2,
    passage_count: 5,
    documents: [],
    searches: [],
  },
  model_calls: [
    { id: "llm-1", sequence: 1, purpose: "ANALYSIS" },
    { id: "llm-2", sequence: 2, purpose: "ANSWER" },
  ],
  verification: { overall: "partial", checks: [], fallback_used: true, fallback_code: "backup" },
  response_shape: {},
  learning: {},
  diagnostics: [],
};

describe("parseExecutionNarrative", () => {
  it("normaliza el contrato semántico sin recalcular decisiones", () => {
    const result = parseExecutionNarrative(NARRATIVE);

    expect(result?.outcome.code).toBe("ANSWERED_WITH_LIMITS");
    expect(result?.evidence.complete).toBe(true);
    expect(result?.appliedDecisions).toHaveLength(1);
    expect(result?.summary.decisionsInfluenced).toBe(1);
    expect(result?.modelCalls.map((call) => call.purpose)).toEqual(["ANALYSIS", "ANSWER"]);
  });

  it("mantiene probabilidad y certeza como conceptos distintos", () => {
    const judgment = parseExecutionNarrative(NARRATIVE)?.judgments[0];

    expect(judgment?.probability).toBe(0.72);
    expect(judgment?.certainty).toBe(0.51);
    expect(judgment?.confidenceBand).toBe("medium");
  });

  it("rechaza narrativa ausente o con versión desconocida", () => {
    expect(parseExecutionNarrative(null)).toBeNull();
    expect(parseExecutionNarrative({ ...NARRATIVE, schema_version: 99 })).toBeNull();
  });

  it("no convierte datos ausentes en ceros inventados", () => {
    const result = parseExecutionNarrative({
      ...NARRATIVE,
      summary: { ...NARRATIVE.summary, total_ms: null, cost_usd: null },
      judgments: [
        { ...NARRATIVE.judgments[0], probability: null, certainty: null },
      ],
    });

    expect(result?.summary.totalMs).toBeUndefined();
    expect(result?.summary.costUsd).toBeUndefined();
    expect(result?.judgments[0].probability).toBeUndefined();
    expect(result?.judgments[0].certainty).toBeUndefined();
  });
});
