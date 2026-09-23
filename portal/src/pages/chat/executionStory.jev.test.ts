// =============================================================================
// Juicio previo (JEV) en la Execution Story — tests del builder
// =============================================================================
// Fija el contrato de §34-§44: packs agrupados, efectos, incertidumbre visible,
// impacto agregado y traducción a lenguaje humano (sin jerga técnica en la
// Historia; ids y distribuciones sólo en el modo técnico).
import { describe, expect, it } from "vitest";
import {
  buildExecutionStory,
  effectLabel,
  questionLabel,
  reasonText,
  storyEvents,
  toJudgmentPacks,
} from "./executionStory";

const PRE_GENERATION_EVENT = {
  id: "jev-3",
  phase: "decision",
  kind: "jev_pack",
  status: "ok",
  duration_ms: 36.4,
  metrics: {
    phase: "pre_generation",
    judgment_count: 3,
    effects: ["generation_tier_small", "expensive_model_avoided"],
    uncertain: [],
    readiness: {
      rows: [
        { key: "evidence", state: "ok", confidence: 0.94, source: "jev" },
        { key: "llm", state: "ok", detail: "small", source: "jev" },
      ],
    },
    questions: [
      {
        id: "analysis_complete",
        type: "noul",
        version: 1,
        decision: "yes",
        value: 0.96,
        certainty: 0.92,
        effect: "generation_allowed",
      },
      {
        id: "risk_of_wrong_answer",
        type: "score",
        version: 2,
        decision: "negligible",
        value: 0.4,
        confidence: 0.9,
      },
      {
        id: "generation_tier",
        type: "choice",
        version: 1,
        decision: "small",
        confidence: 0.88,
        distribution: {
          choice: "small",
          confidence: 0.88,
          probabilities: { small: 0.88, standard: 0.1 },
        },
        effect: "generation_tier_small",
      },
    ],
  },
  technical: { mode: "on", model: "jev-latest", cached: false, question_count: 3 },
  decision: {
    reason_codes: ["cheaper_tier_sufficient"],
    action: "generate_answer",
    tier: "small",
    allow_generation: true,
    applied: true,
    uncertain_critical: [],
  },
};

const JEV_FLOW = {
  flow_version: 2,
  status: "completed",
  verdict: { decider: "JEV", route: "Documentos" },
  decision: { evaluated: true, provider: "jev", confidence: 0.92, jev_used: true },
  generation: { model: "small-model", total_tokens: 120, cost: 0.00002, ms: 400 },
  timings: { total_ms: 1200 },
  steps: [],
  sources: [],
  jev: { used: true, score: 0.92 },
  jev_preflight: {
    mode: "on",
    summary: {
      mode: "on",
      calls: 2,
      judgments: 3,
      decisions_influenced: 1,
      uncertain_critical_judgments: 0,
      llm_escalations_avoided: 1,
      latency_ms: 61.4,
      cost_usd: 0.0004,
    },
    packs: [],
    decisions: [
      {
        phase: "pre_generation",
        action: "generate_answer",
        tier: "small",
        allow_generation: true,
        applied: true,
        reasons: ["cheaper_tier_sufficient"],
        uncertain_critical: [],
      },
    ],
  },
  events: [PRE_GENERATION_EVENT, { id: "e-1", phase: "generation", kind: "generation", status: "ok" }],
};

const UNCERTAIN_FLOW = {
  ...JEV_FLOW,
  jev_preflight: {
    ...JEV_FLOW.jev_preflight,
    summary: {
      ...JEV_FLOW.jev_preflight.summary,
      uncertain_critical_judgments: 1,
      llm_escalations_avoided: 0,
    },
  },
};

describe("juicio previo en la historia", () => {
  it("agrupa los juicios por pack con su efecto", () => {
    const story = buildExecutionStory(JEV_FLOW);
    expect(story.judgmentPacks).toHaveLength(1);
    const [pack] = story.judgmentPacks;
    expect(pack.title).toBe("Antes de generar");
    expect(pack.judgmentCount).toBe(3);
    expect(pack.judgments.map((judgment) => judgment.label)).toContain(
      "¿El análisis está completo?",
    );
    expect(pack.effectLabels).toContain("usó el modelo pequeño");
    expect(pack.tierLabel).toBe("Modelo pequeño");
    expect(pack.readiness.map((row) => row.label)).toEqual(["Evidencia", "LLM"]);
  });

  it("traduce cada primitiva a lenguaje humano", () => {
    const story = buildExecutionStory(JEV_FLOW);
    const judgments = story.judgmentPacks[0].judgments;
    const noul = judgments.find((judgment) => judgment.id === "analysis_complete");
    const score = judgments.find((judgment) => judgment.id === "risk_of_wrong_answer");
    const choice = judgments.find((judgment) => judgment.id === "generation_tier");
    expect(noul?.typeLabel).toBe("Sí/No");
    expect(noul?.decisionLabel).toBe("Sí");
    expect(noul?.certainty).toBeCloseTo(0.92);
    expect(score?.decisionLabel).toContain("Despreciable");
    expect(choice?.decisionLabel).toBe("Modelo pequeño");
    // La distribución sólo se expone como dato, no se inventa un veredicto.
    expect(choice?.distribution?.probabilities).toEqual({ small: 0.88, standard: 0.1 });
  });

  it("publica el impacto del juicio previo (§43)", () => {
    const story = buildExecutionStory(JEV_FLOW);
    expect(story.jevImpact).not.toBeNull();
    expect(story.jevImpact?.headline).toContain("3 comprobaciones");
    expect(story.jevImpact?.calls).toBe(2);
    expect(story.jevImpact?.escalationsAvoided).toBe(1);
    expect(story.jevImpact?.expensiveModelAvoided).toBe(true);
    expect(story.jevImpact?.facts.some((fact) => fact.label === "Costo del juicio")).toBe(true);
  });

  it("marca la incertidumbre en lugar de disfrazarla (§44)", () => {
    const story = buildExecutionStory(UNCERTAIN_FLOW);
    expect(story.jevImpact?.uncertainCritical).toBe(1);
    expect(story.jevImpact?.escalationsAvoided).toBe(0);
  });

  it("sin juicio previo no hay sección", () => {
    const story = buildExecutionStory({
      flow_version: 2,
      status: "completed",
      verdict: { decider: "Reglas", route: "Directa" },
      decision: { evaluated: true, provider: "rules" },
      steps: [],
    });
    expect(story.judgmentPacks).toEqual([]);
    expect(story.jevImpact).toBeNull();
  });

  it("usa los eventos como única fuente de los packs", () => {
    const events = [
      PRE_GENERATION_EVENT,
      { id: "e-2", phase: "generation", kind: "generation", status: "ok" },
    ];
    const packs = toJudgmentPacks(storyEvents({ events }).events);
    expect(packs).toHaveLength(1);
    expect(packs[0].phase).toBe("pre_generation");
    expect(packs[0].applied).toBe(true);
    expect(packs[0].reasonCodes).toEqual(["cheaper_tier_sufficient"]);
    expect(reasonText("cheaper_tier_sufficient")).toBe("el modelo pequeño bastaba");
  });

  it("explica los motivos del juicio por pregunta, no por id crudo", () => {
    expect(reasonText("unsatisfied_analysis_complete")).toBe(
      "faltaba: ¿El análisis está completo?",
    );
    expect(reasonText("action_abstain")).toBe("decidió abstenerse");
    expect(reasonText("jev_only_signal")).toBe("sólo el juicio lo indicaba");
  });

  it("traduce preguntas y efectos con fallback legible", () => {
    expect(questionLabel("next_action")).toBe("¿Qué corresponde hacer ahora?");
    expect(questionLabel("una_pregunta_nueva")).toBe("una pregunta nueva");
    expect(effectLabel("timeline_required")).toBe("activó la línea de tiempo");
    expect(effectLabel("efecto_desconocido")).toBe("efecto desconocido");
  });
});
