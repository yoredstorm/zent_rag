// =============================================================================
// Response Intelligence + Rendimiento en la Execution Story (§43-§54, §62-§64)
// =============================================================================
import { describe, expect, it } from "vitest";
import {
  BLUEPRINT_LABELS,
  buildExecutionStory,
  detailLabel,
  jevPurposeLabel,
  judgmentValueLabel,
  llmActionLabel,
  reasonText,
  responseShapeFor,
  sectionLabel,
  statusLabel,
} from "./executionStory";

/** Flow con contrato de respuesta, varias llamadas y spans solapados. */
const RICH_FLOW = {
  flow_version: 2,
  status: "completed",
  execution: { kind: "agent_run", id: "run-1" },
  verdict: { decider: "Agente", route: "Documentos" },
  decision: { evaluated: true, provider: "explicit_target", ms: 10 },
  generation: {
    model: "gpt-4o-mini",
    total_tokens: 1240,
    cost: 0.000695,
    ms: 10410,
    calls: 3,
    answer_calls: 1,
    reasoning_calls: 2,
  },
  timings: {
    total_ms: 18170,
    llm_ms: 10410,
    tools_ms: 3750,
    gates_ms: 2170,
    span_stages: { llm: 10410, tool: 3750, retrieval: 3750, gate: 2170, answer: 6000 },
  },
  retrieval: { used: true, chunks: 10, ms: 3750 },
  response_contract: {
    blueprint: "technical_explanation",
    detail: "detailed",
    conclusion_first: true,
    sections: ["direct_answer", "meaning", "practical_effect", "example"],
    formatting: { headings: true, table: true, numbered_steps: false },
    evidence: { citations_required: true, disclose_conflicts: true },
    decided_by: "jev",
    confidence: 0.88,
    hedging_required: false,
  },
  response: { contract: { blueprint: "technical_explanation" }, mode: "on", source: "jev" },
  sources: [
    { title: "manual.pdf", document_id: "d-1", score: 0.9 },
    { title: "apendice.pdf", document_id: "d-2", score: 0.7 },
  ],
  events: [
    {
      id: "e-1",
      phase: "planning",
      kind: "response_planning",
      status: "ok",
      metrics: {
        blueprint: "technical_explanation",
        detail_level: "detailed",
        decided_by: "jev",
        needs_example: true,
        needs_table: true,
        citations_required: true,
      },
    },
    {
      id: "e-2",
      phase: "evidence",
      kind: "retrieval",
      status: "ok",
      duration_ms: 2150,
      metrics: { chunks: 5, sources_total: 5, sources_used: 5 },
    },
    {
      id: "e-3",
      phase: "evidence",
      kind: "tool_call",
      status: "ok",
      duration_ms: 1600,
      metrics: { chunks: 5 },
      technical: { tool: "search_knowledge" },
    },
    {
      id: "e-4",
      phase: "evidence",
      kind: "sources",
      status: "ok",
      metrics: { sources: 9 },
      technical: {
        items: Array.from({ length: 9 }, (_, index) => ({
          ref: `d-${index}`,
          title: `doc-${index}.pdf`,
          status: "USED",
        })),
      },
    },
    {
      id: "e-5",
      phase: "planning",
      kind: "jev_pack",
      status: "ok",
      duration_ms: 1300,
      metrics: {
        phase: "response_composition",
        judgment_count: 10,
        questions: [
          {
            id: "response_blueprint",
            type: "choice",
            decision: "technical_explanation",
            confidence: 0.88,
            version: 1,
          },
          {
            id: "required_detail",
            type: "score",
            decision: "detailed",
            value: 2,
            confidence: 0.8,
            version: 1,
          },
        ],
      },
      technical: { model: "jev-mini", cached: false },
    },
    {
      id: "e-6",
      phase: "decision",
      kind: "jev_pack",
      status: "warn",
      metrics: {
        phase: "pre_generation",
        judgment_count: 3,
        uncertain: ["answer_readiness"],
        questions: [
          { id: "next_action", type: "choice", decision: "generate_answer", confidence: 0.78 },
        ],
      },
      decision: { action: "generate_answer", allow_generation: true },
      technical: { cached: true },
    },
    {
      id: "e-7",
      phase: "generation",
      kind: "llm",
      status: "ok",
      duration_ms: 2600,
      metrics: { tokens: 300 },
      technical: { step: 1, action: "plan_search", model: "gpt-4o-mini" },
    },
    {
      id: "e-8",
      phase: "generation",
      kind: "llm",
      status: "ok",
      duration_ms: 1750,
      metrics: { tokens: 220 },
      technical: { step: 2, action: "rewrite_query", model: "gpt-4o-mini" },
    },
    {
      id: "e-9",
      phase: "generation",
      kind: "generation",
      status: "ok",
      duration_ms: 6060,
      metrics: { total_tokens: 1240 },
      technical: { model: "gpt-4o-mini", calls: 3, answer_calls: 1, reasoning_calls: 2 },
    },
  ],
};

describe("forma de respuesta (§51-§54)", () => {
  it("lee el contrato y decide cómo se anuncia la generación", () => {
    const story = buildExecutionStory(RICH_FLOW);
    expect(story.response).not.toBeNull();
    expect(story.response?.blueprint).toBe("technical_explanation");
    expect(story.response?.label).toBe(BLUEPRINT_LABELS.technical_explanation);
    expect(story.response?.detailLabel).toBe("Detallado");
    expect(story.response?.needsExample).toBe(true);
    expect(story.response?.needsTable).toBe(true);
    expect(story.response?.citationsRequired).toBe(true);
    expect(story.response?.generationTitle).toBe("Explicó la conclusión");
  });

  it("nombra el paso de generación por la forma elegida", () => {
    const story = buildExecutionStory(RICH_FLOW);
    const generation = story.phases.find((phase) => phase.id === "generation");
    expect(generation?.title).toBe("Explicó la conclusión");
    expect(generation?.subtitle).toContain("Explicación técnica");
    expect(generation?.subtitle).toContain("1240 tokens");
  });

  it("sin contrato no inventa una forma", () => {
    expect(responseShapeFor({}, [])).toBeNull();
    const story = buildExecutionStory({ flow_version: 2, events: [] });
    expect(story.response).toBeNull();
    const generation = story.phases.find((phase) => phase.id === "generation");
    expect(generation).toBeUndefined();
  });

  it("traduce secciones y formas al lenguaje humano", () => {
    expect(sectionLabel("practical_effect")).toBe("Qué implica en la práctica");
    expect(sectionLabel("desconocida")).toBe("desconocida");
    expect(detailLabel("brief")).toBe("Breve");
  });
});

describe("rendimiento (§43-§47)", () => {
  it("usa wall-clock como base y reparte por lo realmente medido", () => {
    const story = buildExecutionStory(RICH_FLOW);
    const performance = story.performance;
    expect(performance.totalMs).toBe(18170);
    const keys = performance.segments.map((segment) => segment.key);
    expect(keys).toContain("llm");
    expect(keys).toContain("retrieval");
    expect(keys).toContain("jev");
    const llm = performance.segments.find((segment) => segment.key === "llm");
    expect(llm?.ms).toBe(10410);
    expect(performance.attributedMs).toBeLessThanOrEqual(performance.totalMs);
    expect(performance.unattributedMs).toBeGreaterThan(0);
  });

  it("declara el solapamiento cuando los spans superan el tiempo real (§44)", () => {
    const story = buildExecutionStory(RICH_FLOW);
    expect(story.performance.cumulativeSpanMs).toBe(26080);
    expect(story.performance.overlaps).toBe(true);
    expect(story.performance.note).toContain("solapa");
  });

  it("desglosa las llamadas al modelo por acción (§45)", () => {
    const story = buildExecutionStory(RICH_FLOW);
    expect(story.performance.llmCallCount).toBe(3);
    const labels = story.performance.llmCalls.map((call) => call.label);
    expect(labels).toEqual(["Preparó la búsqueda", "Refinó la búsqueda"]);
    expect(llmActionLabel("answer")).toBe("Redactó la respuesta");
    expect(llmActionLabel("")).toBe("Llamada al modelo");
  });

  it("desglosa las búsquedas y la evidencia única (§46)", () => {
    const story = buildExecutionStory(RICH_FLOW);
    expect(story.performance.searches.length).toBe(2);
    expect(story.performance.searches[0].chunks).toBe(5);
    expect(story.performance.uniqueEvidence).toBe(9);
  });

  it("traduce el propósito de cada decisión JEV sin repetir la misma frase (§47)", () => {
    const story = buildExecutionStory(RICH_FLOW);
    const labels = story.performance.jevDecisions.map((decision) => decision.label);
    expect(labels).toEqual(["Eligió cómo explicarlo", "Decidió cómo responder"]);
    expect(new Set(labels).size).toBe(labels.length);
    expect(jevPurposeLabel("post_generation")).toBe("Verificó la respuesta");
    expect(jevPurposeLabel("phase_desconocida")).toBe("Juicio previo");
    const reused = story.performance.jevDecisions.find((decision) => decision.cached);
    expect(reused).toBeDefined();
    expect(story.performance.reusedJudgments).toBe(1);
  });

  it("sin telemetría de tiempos no inventa un 18 s", () => {
    const story = buildExecutionStory({ flow_version: 2, events: [] });
    expect(story.performance.totalMs).toBe(0);
    expect(story.performance.segments).toEqual([]);
    expect(story.performance.llmCallCount).toBeNull();
  });
});

describe("incertidumbre (§42)", () => {
  it("un juicio incierto no dice Requiere atención", () => {
    const story = buildExecutionStory(RICH_FLOW);
    const pack = story.phases.flatMap((phase) => phase.events).find((event) => event.id === "e-6");
    expect(pack?.status).toBe("uncertain");
    expect(statusLabel("uncertain")).toBe("Confianza moderada");
    expect(statusLabel("warn")).toBe("Requiere atención");
    expect(story.incidents.some((incident) => incident.id === "e-6-incident")).toBe(false);
  });

  it("un juicio incierto que bloquea sí es un aviso", () => {
    const flow = {
      ...RICH_FLOW,
      events: [
        {
          id: "e-1",
          phase: "decision",
          kind: "jev_pack",
          status: "warn",
          metrics: { phase: "pre_generation", judgment_count: 2, uncertain: ["answer_readiness"] },
          decision: { action: "abstain", allow_generation: false },
        },
      ],
    };
    const story = buildExecutionStory(flow);
    expect(story.phases.flatMap((phase) => phase.events)[0].status).toBe("warn");
  });
});

describe("§64 sin cadena de pensamiento", () => {
  it("la historia no expone razonamiento privado", () => {
    const story = buildExecutionStory(RICH_FLOW);
    const serialized = JSON.stringify(story).toLowerCase();
    for (const marker of [
      "primero pensé",
      "después razoné",
      "chain of thought",
      "chain-of-thought",
      "pensamiento interno",
    ]) {
      expect(serialized).not.toContain(marker);
    }
  });
});

// ---------------------------------------------------------------------------
// Agent JEV Loop: el juicio del paso y la re-consulta quedan en la historia
// ---------------------------------------------------------------------------

const LOOP_FLOW = {
  flow_version: 2,
  status: "completed",
  verdict: { decider: "JEV", route: "Documentos" },
  timings: { total_ms: 5200 },
  generation: { model: "zent-default", total_tokens: 900, ms: 2100 },
  jev_preflight: {
    mode: "on",
    packs: [
      {
        phase: "agent_step",
        mode: "on",
        status: "ok",
        question_count: 4,
        latency_ms: 120,
        questions: [
          { id: "needs_more_evidence", type: "noul", decision: "yes", confidence: 0.9 },
        ],
      },
    ],
    decisions: [
      { phase: "agent_step", action: "retrieve_more", reasons: ["evidence_gap"], applied: true },
    ],
    summary: { calls: 1, judgments: 4, decisions_influenced: 1, latency_ms: 120 },
  },
  events: [
    {
      id: "l-1",
      phase: "evidence",
      kind: "tool_call",
      status: "ok",
      duration_ms: 810,
      metrics: {
        coverage_gap: "La evidencia consultada no menciona: categoría 31.",
      },
      technical: { tool: "search_knowledge" },
    },
    {
      id: "l-2",
      phase: "decision",
      kind: "agent_step",
      status: "ok",
      duration_ms: 120,
      metrics: {
        questions: ["needs_tool", "tool", "needs_more_evidence", "satisfied"],
        next_action: "retrieve_more",
        action_reason: "evidence_gap",
        uncovered_entities: ["categoría 31"],
      },
      decision: { action: "retrieve_more", reason_codes: ["evidence_gap"], applied: true },
    },
    {
      id: "l-3",
      phase: "evidence",
      kind: "jev_retrieval",
      status: "ok",
      duration_ms: 700,
      metrics: { query: "cat 31 cat31", round: 1, reason: "evidence_gap" },
      technical: { tool: "search_knowledge" },
    },
    {
      // El pack del paso, tal como lo emite `with_story` desde jev_preflight.
      id: "jev-1",
      phase: "decision",
      kind: "jev_pack",
      status: "ok",
      duration_ms: 120,
      metrics: {
        phase: "agent_step",
        judgment_count: 4,
        questions: [
          {
            id: "needs_more_evidence",
            type: "noul",
            decision: "yes",
            confidence: 0.9,
            version: 1,
          },
        ],
      },
      technical: { mode: "on", model: "jev-test", question_count: 4 },
    },
  ],
};

describe("Agent JEV Loop en la historia", () => {
  it("nombra el juicio del paso y la búsqueda que pidió", () => {
    const story = buildExecutionStory(LOOP_FLOW);
    const events = story.phases.flatMap((phase) => phase.events);
    const step = events.find((event) => event.kind === "agent_step");
    const retry = events.find((event) => event.kind === "jev_retrieval");
    expect(step?.title).toBe("JEV juzgó el paso");
    expect(step?.phase).toBe("decision");
    expect(step?.decisionAction).toBe("retrieve_more");
    expect(retry?.title).toBe("Volvió a buscar: faltaba evidencia");
    expect(retry?.phase).toBe("evidence");
    expect(retry?.metrics.coverage_gap).toBeUndefined();
    // La cobertura faltante viaja como dato, no como incidente.
    expect(events.some((event) => event.metrics.coverage_gap)).toBe(true);
  });

  it("traduce el veredicto y el motivo a lenguaje humano", () => {
    expect(judgmentValueLabel("retrieve_more")).toBe("Buscar más evidencia");
    expect(reasonText("evidence_gap")).toBe("faltaba evidencia para lo que se preguntó");
  });

  it("el pack del paso JEV se muestra como una llamada con N preguntas", () => {
    const story = buildExecutionStory(LOOP_FLOW);
    expect(story.performance.jevDecisions.map((decision) => decision.label)).toContain(
      "Eligió el siguiente paso",
    );
  });
});
