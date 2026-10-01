import { describe, expect, it } from "vitest";
import {
  decisionAppliedCount,
  displayConfidenceLabel,
  documentDisplayName,
  evidenceLocation,
  evidenceUsageLabel,
  formatDisplayProbability,
  judgmentOutcomeLabel,
  parseTraceability,
  traceStepPresentation,
  verificationExplanationLines,
  visibleExecutionSteps,
  type Traceability,
} from "./experience";

function traceabilityFixture(): Traceability {
  const raw = {
    schema_version: 1,
    counts: {
      documents_consulted: 3,
      documents_used: 2,
      evidence_retrieved: 5,
      evidence_used: 4,
      evidence_cited: 2,
    },
    evidence: {
      documents: [
        {
          document_key: "document:docA",
          document_id: "docA",
          document_name: "Rec2_Rules.pdf",
          evidence_count: 2,
          used_count: 2,
          items: [
            {
              evidence_id: "E1",
              document_id: "docA",
              document_name: "Rec2_Rules.pdf",
              page: 18,
              section_path: ["Record 2"],
              excerpt: "Carrier Code ...",
              status: "USED",
              used_in_answer: true,
              cited: true,
            },
            {
              evidence_id: "E2",
              document_name: "Rec2_Rules.pdf",
              status: "USED",
              used_in_answer: true,
            },
          ],
        },
        {
          document_key: "document:unknown",
          document_name: "",
          evidence_count: 1,
          used_count: 0,
          items: [{ evidence_id: "E3", status: "RETRIEVED", used_in_answer: false }],
        },
      ],
      items: [],
    },
    retrieval: { rounds: [], expanded: false },
    decisions: [
      {
        decision_id: "decision:1:pre_generation",
        phase: "pre_generation",
        action: "retrieve_more",
        action_applied: true,
        classification: "ACTIONABLE",
        effect_codes: ["retrieval_round_requested"],
        reason_codes: ["gate_not_satisfied"],
        display: { outcome_key: "retrieve_more", confidence: 0.87, confidence_band: "high" },
        before_state: { evidence: 3, sufficient: false },
        after_state: { evidence: 5, sufficient: true },
        delta_evidence: 2,
      },
      {
        decision_id: "decision:2:pre_reasoning",
        phase: "pre_reasoning",
        action: "generate",
        action_applied: false,
        classification: "OBSERVATIONAL",
        display: { outcome_key: "generate" },
      },
    ],
    judgments: [
      {
        judgment_id: "pre_generation:next_action",
        phase: "pre_generation",
        question_code: "next_action",
        type: "choice",
        display: {
          outcome_key: "retrieve_more",
          probability: 0.87,
          confidence_band: "high",
        },
        alternatives: [
          { key: "retrieve_more", probability: 0.87 },
          { key: "generate", probability: 0.13 },
        ],
      },
    ],
    timeline: [
      {
        id: "trace:1",
        type: "QUERY_CLASSIFIED",
        sequence: 1,
        summary_code: "understood.query",
        summary_params: {},
        user_visible: true,
        status: "ok",
      },
      {
        id: "trace:2",
        type: "RETRIEVAL_COMPLETED",
        sequence: 2,
        summary_code: "retrieval.completed",
        summary_params: { chunks: 5, evidence_used: 4, documents_used: 2 },
        user_visible: true,
        status: "ok",
      },
      {
        id: "trace:3",
        type: "ROUTE_SELECTED",
        sequence: 3,
        summary_code: "route.selected",
        summary_params: {},
        user_visible: false,
        status: "ok",
      },
      {
        id: "trace:4",
        type: "RETRIEVAL_EXPANDED",
        sequence: 4,
        summary_code: "retrieval.expanded",
        summary_params: { before: 3, after: 5, delta: 2 },
        user_visible: true,
        status: "ok",
        decision_id: "decision:1:pre_generation",
      },
    ],
    verification: {
      status: "PARTIALLY_VERIFIED",
      explanation_codes: [
        { code: "DOCUMENTARY_SUPPORT_CONFIRMED" },
        { code: "SECONDARY_CHECK_UNAVAILABLE", check: "answer_gate" },
      ],
      checks: [{ key: "grounding", state: "ok" }],
      signals: { grounded: true, fallback_used: false, material_fallback: false },
      technical: {},
    },
    diagnostics: { invariants: [], gaps: [] },
  };
  const parsed = parseTraceability(raw);
  if (!parsed) throw new Error("fixture inválido");
  return parsed;
}

describe("parseTraceability", () => {
  it("devuelve null para flows históricos sin contrato", () => {
    expect(parseTraceability(undefined)).toBeNull();
    expect(parseTraceability({})).toBeNull();
    expect(parseTraceability({ schema_version: 1 })).not.toBeNull();
  });

  it("normaliza conteos y decisiones aplicadas", () => {
    const traceability = traceabilityFixture();
    expect(traceability.counts.evidenceUsed).toBe(4);
    expect(decisionAppliedCount(traceability)).toBe(1);
  });

  it("no fabrica excerpt cuando el backend no lo entrega", () => {
    const traceability = traceabilityFixture();
    const item = traceability.documents[0].items[1];
    expect(item.excerpt).toBeUndefined();
  });

  it("agrupa documentos y usa fallback humano sin inventar título", () => {
    const traceability = traceabilityFixture();
    expect(documentDisplayName(traceability.documents[0])).toBe("Rec2_Rules.pdf");
    expect(documentDisplayName(traceability.documents[1])).toBe("Fuente sin nombre");
  });
});

describe("transformación única de probabilidades", () => {
  it("formatea sólo desde display y nunca muestra 'No clasificada'", () => {
    const traceability = traceabilityFixture();
    const judgment = traceability.judgments[0];
    expect(formatDisplayProbability(judgment.display)).toBe("87%");
    expect(displayConfidenceLabel(judgment.display)).toBe("Alta");
    expect(judgmentOutcomeLabel(judgment.type, judgment.display)).toBe("Buscar más evidencia");
    // Sin dato => vacío, jamás "No clasificada".
    expect(formatDisplayProbability({})).toBe("");
    expect(displayConfidenceLabel({})).toBe("");
    expect(judgmentOutcomeLabel("noul", {})).toBe("");
  });
});

describe("pasos visibles de ejecución", () => {
  it("sólo muestra eventos user_visible y traduce los códigos", () => {
    const traceability = traceabilityFixture();
    const steps = visibleExecutionSteps(traceability);
    expect(steps.map((step) => step.event.type)).toEqual([
      "QUERY_CLASSIFIED",
      "RETRIEVAL_COMPLETED",
      "RETRIEVAL_EXPANDED",
    ]);
    const retrieval = steps[1].presentation;
    expect(retrieval.title).toBe("Buscó evidencia");
    expect(retrieval.detail).toContain("5 fragmentos recuperados");
    expect(retrieval.detail).toContain("4 utilizadas");
    const expanded = steps[2].presentation;
    expect(expanded.title).toBe("JEV pidió ampliar la búsqueda");
    expect(expanded.detail).toBe("La búsqueda pasó de 3 a 5 evidencias.");
  });

  it("traduce un paso JEV con su decisión real", () => {
    const traceability = traceabilityFixture();
    const event = {
      id: "trace:9",
      type: "JEV_DECISION",
      sequence: 9,
      summaryCode: "jev.decision",
      summaryParams: {},
      userVisible: true,
      status: "ok",
      metrics: {},
      sourceEventIds: [],
      decisionId: "decision:1:pre_generation",
    };
    const presentation = traceStepPresentation(event, traceability.decisions);
    expect(presentation.title).toBe("JEV intervino: Buscar más evidencia");
    expect(presentation.detail).toBe("pidió otra ronda de búsqueda");
  });
});

describe("verificación explicada", () => {
  it("explica el estado parcial con la comprobación que faltó", () => {
    const traceability = traceabilityFixture();
    const lines = verificationExplanationLines(traceability.verification);
    expect(lines[0].text).toBe("Respaldo documental confirmado");
    expect(lines[1].text).toBe("La verificación de respuesta no estuvo disponible");
  });
});

describe("evidencia explicada", () => {
  it("compone localización y uso sin inventar", () => {
    const traceability = traceabilityFixture();
    const item = traceability.documents[0].items[0];
    expect(evidenceLocation(item)).toBe("Página 18 · Record 2");
    expect(evidenceUsageLabel(item)).toBe("Citada en la respuesta");
    const unused = traceability.documents[1].items[0];
    expect(evidenceUsageLabel(unused)).toBe("Recuperada, no utilizada");
    expect(evidenceLocation(unused)).toBe("");
  });
});
