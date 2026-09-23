// =============================================================================
// Execution Story — tests del builder puro (§57-§65)
// =============================================================================
import { describe, expect, it } from "vitest";
import {
  AUTHORITY_LABELS,
  buildExecutionStory,
  EVIDENCE_STATUS_LABELS,
  eventReasonsText,
  evidenceStatusLabel,
  authorityLabel,
  normalizeLegacyFlow,
  reasonText,
  shapeLabel,
  verdictLabel,
} from "./executionStory";

/** Flujo RAG simple: consulta directa sobre un concepto. */
const SIMPLE_FLOW = {
  flow_version: 2,
  query_id: "q-1",
  method: "rag",
  status: "completed",
  verdict: { decider: "Reglas", route: "Documentos" },
  decision: { evaluated: true, provider: "rules", confidence: 0.72, ms: 40 },
  generation: { model: "deepseek-v3.2", total_tokens: 400, cost: 0.0001, ms: 500 },
  timings: { total_ms: 900 },
  steps: [],
  sources: [{ title: "manual.pdf", document_id: "d-1", score: 0.8 }],
  fallbacks: [],
  events: [
    {
      id: "e-1",
      phase: "understanding",
      kind: "reasoning_classification",
      status: "ok",
      metrics: { reasoning: { shape: "SIMPLE_LOOKUP", is_complex: false } },
    },
    {
      id: "e-2",
      phase: "evidence",
      kind: "retrieval",
      status: "ok",
      duration_ms: 300,
      metrics: { chunks: 3, sources_total: 1, sources_used: 1, top_score: 0.8 },
    },
    {
      id: "e-3",
      phase: "evidence",
      kind: "sources",
      status: "ok",
      metrics: { sources: 1 },
      technical: { items: [{ ref: "d-1", title: "manual.pdf", relevance: 0.8, status: "USED" }] },
    },
    {
      id: "e-4",
      phase: "generation",
      kind: "generation",
      status: "ok",
      duration_ms: 500,
      metrics: { total_tokens: 400, cost_usd: 0.0001 },
    },
    {
      id: "e-5",
      phase: "verification",
      kind: "grounding",
      status: "ok",
      duration_ms: 40,
      metrics: { grounded: true, score: 0.9 },
    },
  ],
};

/** Flujo complejo: razonamiento sobre una secuencia de registros. */
const COMPLEX_FLOW = {
  flow_version: 2,
  query_id: "q-2",
  method: "agent",
  status: "completed",
  verdict: { decider: "JEV", route: "Herramientas" },
  decision: { evaluated: true, provider: "jev", confidence: 0.91, ms: 120 },
  generation: { model: "deepseek-v3.2", total_tokens: 1800, cost: 0.0004, ms: 900 },
  timings: { total_ms: 2400 },
  sources: [],
  fallbacks: [],
  events: [
    {
      id: "c-1",
      phase: "understanding",
      kind: "reasoning_classification",
      status: "ok",
      metrics: { reasoning: { shape: "STATE_TRANSITION", is_complex: true } },
    },
    {
      id: "c-2",
      phase: "context",
      kind: "company_context",
      status: "ok",
      metrics: { company_context: { concepts: 3, rules: 2, systems: 1, memories: 1 } },
    },
    {
      id: "c-3",
      phase: "planning",
      kind: "reasoning_plan",
      status: "ok",
      metrics: {
        plan: {
          shape: "STATE_TRANSITION",
          question_to_prove: "Determine whether the supplied event sequence requires an additional closing event.",
          operations: ["resolve_schema", "parse_events", "build_timeline"],
          requires: { sql: false, api: false },
        },
      },
    },
    {
      id: "c-4",
      phase: "evidence",
      kind: "retrieval",
      status: "ok",
      duration_ms: 400,
      metrics: { chunks: 4, sources_total: 4, sources_used: 3, sources_discarded: 1 },
    },
    {
      id: "c-5",
      phase: "reasoning",
      kind: "scenario_parse",
      status: "warn",
      metrics: {
        scenario: {
          events: 17,
          record_types: 2,
          schemas: 1,
          unparsed: 3,
          missing_requirements: [{ kind: "RECORD_LAYOUT_REQUIRED", subject: "scenario" }],
        },
      },
    },
    {
      id: "c-6",
      phase: "reasoning",
      kind: "state_reconstruction",
      status: "ok",
      metrics: {
        transitions: {
          total: 10,
          confirmed: 10,
          unresolved: 0,
          chain: [
            { from: "0005", to: "0006", status: "CONFIRMED" },
            { from: "0006", to: "0007", status: "CONFIRMED" },
          ],
        },
      },
    },
    {
      id: "c-7",
      phase: "reasoning",
      kind: "hypothesis_test",
      status: "ok",
      metrics: {
        hypotheses: {
          supported: 1,
          rejected: 1,
          unresolved: 0,
          items: [
            {
              id: "h-1",
              statement: "La renumeración abrió espacio de ordenamiento",
              verdict: "SUPPORTED",
              origin: "RULE",
              supporting: 4,
              contradicting: 0,
            },
            {
              id: "h-2",
              statement: "Falta un registro de cierre",
              verdict: "REJECTED",
              origin: "USER",
              supporting: 0,
              contradicting: 3,
              is_user_hypothesis: true,
            },
          ],
        },
      },
    },
    {
      id: "c-8",
      phase: "verification",
      kind: "inference_verification",
      status: "ok",
      metrics: {
        inference: {
          total: 1,
          supported: 1,
          premises: 3,
          verdicts: [{ conclusion: "No falta un cierre", verdict: "SUPPORTED" }],
        },
      },
    },
    {
      id: "c-9",
      phase: "verification",
      kind: "analysis_completion",
      status: "ok",
      metrics: {
        completion: { complete: true, blockers: [], reason_codes: [], checks: [] },
      },
    },
    {
      id: "c-10",
      phase: "generation",
      kind: "generation",
      status: "ok",
      duration_ms: 900,
      metrics: { total_tokens: 1800, cost_usd: 0.0004 },
    },
    {
      id: "c-11",
      phase: "verification",
      kind: "grounding",
      status: "ok",
      metrics: { grounded: true, score: 0.88 },
    },
  ],
};

describe("buildExecutionStory — consulta simple (§57)", () => {
  const story = buildExecutionStory(SIMPLE_FLOW);

  it("muestra solo las fases que ocurrieron", () => {
    const ids = story.phases.map((phase) => phase.id);
    expect(ids).toEqual(["understanding", "evidence", "generation", "verification"]);
    // Sin escenario, hipótesis ni reconstrucción en una consulta directa.
    expect(ids).not.toContain("reasoning");
    expect(ids).not.toContain("planning");
    expect(ids).not.toContain("context");
  });

  it("resume la respuesta con lenguaje humano", () => {
    expect(story.headline).toBe("Respuesta completada");
    expect(story.narrative).toContain("buscó en el conocimiento");
    expect(story.routeLabel).toBe("Documentos");
    expect(story.outcomeLabel).toBe("Respaldada");
    expect(story.evidenceLabel).toBe("1 fuente");
    expect(story.confidenceLabel).toBe("Media");
    expect(story.totalMs).toBe(900);
  });

  it("no inventa razonamiento cuando no hubo", () => {
    expect(story.reasoningLabel).toBe("");
    expect(story.phases.flatMap((phase) => phase.events).some((event) => event.hypotheses.length))
      .toBe(false);
  });
});

describe("buildExecutionStory — razonamiento complejo (§58)", () => {
  const story = buildExecutionStory(COMPLEX_FLOW);

  it("orden las fases de forma canónica", () => {
    expect(story.phases.map((phase) => phase.id)).toEqual([
      "understanding",
      "context",
      "planning",
      "evidence",
      "reasoning",
      "generation",
      "verification",
    ]);
  });

  it("narra la reconstrucción del escenario", () => {
    expect(story.narrative).toContain("reconstruyó el escenario");
    expect(story.reasoningLabel).toBe("Análisis de secuencia");
    expect(story.routeLabel).toBe("Documentos + análisis secuencial");
  });

  it("resume contexto, escenario y transiciones en el subtítulo de la fase", () => {
    const context = story.phases.find((phase) => phase.id === "context");
    expect(context?.subtitle).toContain("3 conceptos");
    expect(context?.subtitle).toContain("2 reglas");
    const reasoning = story.phases.find((phase) => phase.id === "reasoning");
    expect(reasoning?.subtitle).toContain("17 eventos");
    expect(reasoning?.subtitle).toContain("2 transiciones");
    expect(reasoning?.subtitle).toContain("1 respaldada");
    expect(reasoning?.subtitle).toContain("1 descartada");
  });

  it("expone la pregunta operacional que intentó demostrar", () => {
    const plan = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "reasoning_plan");
    expect(String(plan?.plan?.question_to_prove)).toContain("additional closing event");
  });

  it("construye la cadena de estados desde las transiciones, no desde texto", () => {
    const reconstruction = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "state_reconstruction");
    expect(reconstruction?.transitions.map((link) => `${link.from}->${link.to}`)).toEqual([
      "0005->0006",
      "0006->0007",
    ]);
  });
});

describe("hipótesis (§19, §59)", () => {
  const story = buildExecutionStory(COMPLEX_FLOW);
  const hypotheses = story.phases
    .flatMap((phase) => phase.events)
    .flatMap((event) => event.hypotheses);

  it("traduce veredictos a lenguaje humano", () => {
    expect(verdictLabel("SUPPORTED")).toBe("Respaldada");
    expect(verdictLabel("REJECTED")).toBe("Descartada");
    expect(verdictLabel("UNRESOLVED")).toBe("Sin resolver");
  });

  it("cuenta respaldadas y descartadas, sin llamarlas aciertos o errores", () => {
    expect(hypotheses.map((item) => item.verdict)).toEqual(["SUPPORTED", "REJECTED"]);
    const test = story.phases.find((phase) => phase.id === "reasoning");
    expect(test?.subtitle).toContain("1 respaldada · 1 descartada");
  });

  it("marca la hipótesis del usuario y sus evidencias en contra", () => {
    const user = hypotheses.find((item) => item.isUser);
    expect(user?.statement).toContain("Falta un registro");
    expect(user?.contradicting).toBe(3);
  });
});

describe("esquema desconocido (§60)", () => {
  const story = buildExecutionStory({
    ...COMPLEX_FLOW,
    events: [
      COMPLEX_FLOW.events[0],
      {
        id: "u-1",
        phase: "reasoning",
        kind: "scenario_parse",
        status: "warn",
        metrics: {
          scenario: {
            events: 0,
            unparsed: 4,
            missing_requirements: [{ kind: "RECORD_LAYOUT_REQUIRED" }],
          },
        },
      },
      {
        id: "u-2",
        phase: "verification",
        kind: "analysis_completion",
        status: "warn",
        metrics: {
          completion: {
            complete: false,
            blockers: ["scenario_incomplete"],
            reason_codes: ["SCHEMA_REQUIRED", "ANALYSIS_INCOMPLETE"],
          },
        },
      },
    ],
  });

  it("no presenta el caso como un fallo genérico", () => {
    expect(story.headline).toBe("Respuesta con análisis incompleto");
    const completion = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "analysis_completion");
    expect(eventReasonsText(completion!)).toContain("el layout de los registros");
  });

  it("declara cuántos elementos no pudo interpretar", () => {
    const scenario = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "scenario_parse");
    expect(scenario?.status).toBe("warn");
    expect(eventReasonsText(scenario!)).toContain("el layout de los registros");
  });
});

describe("memoria (§27, §28, §62)", () => {
  it("distingue memoria usada de memoria creada", () => {
    const story = buildExecutionStory(COMPLEX_FLOW);
    const contextEvent = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "company_context");
    expect(contextEvent?.metrics.company_context).toMatchObject({ memories: 1 });
  });
});

describe("authority y evidencia (§11, §12, §42, §43)", () => {
  it("traduce niveles de autoridad y estados de evidencia", () => {
    expect(authorityLabel("authoritative")).toBe("Autoritativa");
    expect(authorityLabel("primary")).toBe("Principal");
    expect(authorityLabel("informational")).toBe("Informativa");
    expect(Object.keys(AUTHORITY_LABELS)).toHaveLength(5);
  });

  it("traduce los veredictos del passage judge", () => {
    expect(evidenceStatusLabel("KEEP")).toBe("Utilizada");
    expect(evidenceStatusLabel("DROP_IRRELEVANT")).toBe("No relevante");
    expect(evidenceStatusLabel("DROP_WEAK")).toBe("Evidencia débil");
    expect(evidenceStatusLabel("FLAG_CONTRADICTION")).toBe("En conflicto");
    expect(evidenceStatusLabel("DROP_INJECTION")).toBe("Contenido inseguro bloqueado");
    expect(EVIDENCE_STATUS_LABELS.INJECTION_BLOCKED).toBe("Contenido inseguro bloqueado");
  });

  it("conserva autoridad y estado por fuente", () => {
    const story = buildExecutionStory({
      ...SIMPLE_FLOW,
      events: [
        ...SIMPLE_FLOW.events.filter((event) => event.kind !== "sources"),
        {
          id: "s-1",
          phase: "evidence",
          kind: "sources",
          status: "ok",
          metrics: { sources: 3, authority_counts: { authoritative: 1, primary: 2 } },
          technical: {
            items: [
              { ref: "a", title: "spec", status: "USED", authority: "authoritative" },
              { ref: "b", title: "memo", status: "DISCARDED", authority: "informational" },
            ],
          },
        },
      ],
    });
    const sources = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "sources");
    expect(sources?.evidence[0].authority).toBe("authoritative");
    expect(sources?.evidence[0].status).toBe("USED");
    expect(sources?.evidence[1].status).toBe("DISCARDED");
    expect(sources?.metrics.authority_counts).toEqual({ authoritative: 1, primary: 2 });
  });
});

describe("fallbacks en su etapa (§46, §63)", () => {
  const story = buildExecutionStory({
    ...SIMPLE_FLOW,
    events: [
      ...SIMPLE_FLOW.events,
      {
        id: "f-1",
        phase: "verification",
        kind: "fallback",
        status: "warn",
        summary: "grounding_failed",
      },
    ],
  });

  it("aparece dentro de la etapa donde ocurrió y suma una incidencia", () => {
    const verification = story.phases.find((phase) => phase.id === "verification");
    expect(verification?.status).toBe("warn");
    expect(story.incidents.some((incident) => incident.phase === "verification")).toBe(true);
    expect(story.incidents[0].detail).toContain("no quedó respaldada");
  });

  it("la respuesta sigue reportada como completada", () => {
    expect(story.status).toBe("completed");
    expect(story.headline).toBe("Respuesta completada");
  });
});

describe("flows históricos (§64)", () => {
  const legacy = {
    query_id: "old-1",
    method: "rag",
    status: "completed",
    verdict: { decider: "JEV", route: "Documentos" },
    decision: { evaluated: true, provider: "jev", confidence: 0.9, ms: 100 },
    retrieval: { used: true, chunks: 2, top_score: 0.8, ms: 300 },
    generation: { model: "gpt-4o-mini", total_tokens: 500, ms: 600 },
    grounding: { grounded: true, score: 0.85 },
    timings: { total_ms: 1200 },
    steps: [{ name: "Decisión", status: "ok", ms: 100 }],
    sources: [{ title: "viejo.pdf", document_id: "d-old", score: 0.8 }],
    fallbacks: [],
  };

  it("sin flow_version se normaliza a eventos canónicos", () => {
    const events = normalizeLegacyFlow(legacy);
    expect(events.length).toBeGreaterThan(0);
    expect(events.map((event) => event.kind)).toContain("retrieval");
    expect(events.map((event) => event.kind)).toContain("sources");
  });

  it("la historia se construye igual y se marca como histórica", () => {
    const story = buildExecutionStory(legacy);
    expect(story.legacy).toBe(true);
    expect(story.version).toBe(1);
    expect(story.phases.map((phase) => phase.id)).toEqual([
      "evidence",
      "decision",
      "generation",
      "verification",
    ]);
    expect(story.evidenceLabel).toBe("1 fuente");
  });
});

describe("modo técnico (§32, §33)", () => {
  const story = buildExecutionStory(COMPLEX_FLOW);

  it("expone proveedor, modelo, tokens, costo y confianza", () => {
    expect(story.technical.provider).toBe("jev");
    expect(story.technical.model).toBe("deepseek-v3.2");
    expect(story.technical.tokens?.total).toBe(1800);
    expect(story.technical.confidence).toBeCloseTo(0.91);
    expect(story.costUsd).toBeCloseTo(0.0004);
    expect(story.technical.raw).toBe(COMPLEX_FLOW);
  });

  it("la distribución de tiempo usa fases reales", () => {
    expect(story.breakdown.length).toBeGreaterThan(1);
    expect(story.breakdown.some((row) => row.label === "Reconstruyó el escenario")).toBe(true);
  });
});

describe("respuestas seguras (§2)", () => {
  it("nunca expone cadena de pensamiento", () => {
    const blob = JSON.stringify(buildExecutionStory(COMPLEX_FLOW)).toLowerCase();
    for (const forbidden of ["chain-of-thought", "scratchpad", "let me think", "internal reasoning"]) {
      expect(blob).not.toContain(forbidden);
    }
  });

  it("no fabrica razones: sin señales no hay motivos", () => {
    const story = buildExecutionStory({ steps: [], sources: [] });
    expect(story.phases).toHaveLength(0);
    expect(story.narrative).toContain("Sin pasos registrados");
    expect(reasonText("ALGO_DESCONOCIDO")).toBe("algo desconocido");
  });

  it("tolera un flow nulo", () => {
    const story = buildExecutionStory(null);
    expect(story.phases).toHaveLength(0);
    expect(story.headline).toBe("Respuesta completada");
  });

  it("traduce formas de razonamiento", () => {
    expect(shapeLabel("STATE_TRANSITION")).toBe("Análisis de secuencia");
    expect(shapeLabel("GRAPH_REASONING")).toBe("Dependencias");
    expect(shapeLabel(undefined)).toBe("");
  });
});
