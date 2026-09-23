// =============================================================================
// Execution Story del AGENTE — fidelidad del run real (§48-§52, §45-§47)
// =============================================================================
// Fixture: el flow canónico que el backend produce para la captura del Agent
// Playground (dos llamadas al LLM, tool routing JEV, search_knowledge con
// evidencia estructurada y gate de respuesta).
import { describe, expect, it } from "vitest";
import { buildExecutionStory } from "./executionStory";

const AGENT_FLOW = {
  flow_version: 2,
  method: "agent",
  status: "completed",
  execution: { kind: "agent_run", id: "run-42", agent_id: "a-1" },
  question: "¿aplica la cláusula?",
  verdict: { decider: "JEV", route: "Documentos" },
  decision: {
    evaluated: true,
    provider: "explicit_target",
    capability: "agent.execute",
    reason: "user_selected_agent",
    mode: "ReAct + JEV",
  },
  jev: { used: true, calls: 2, phases: ["tool_routing", "answer_gate"], verdict: "approve", grounded: true, complete: true, quality: 3, score: 0.87 },
  generation: {
    model: "zent-default",
    provider: "litellm",
    prompt_tokens: 1200,
    completion_tokens: 440,
    total_tokens: 1640,
    cost: 0.000381,
    ms: 5300,
    calls: 2,
    answer_calls: 1,
    reasoning_calls: 1,
  },
  verification: {
    overall: "verified",
    source: "agent_runtime",
    checks: [
      { key: "analysis_complete", state: "ok" },
      { key: "answer_gate", state: "ok", detail: "approve" },
      { key: "grounding", state: "ok" },
    ],
  },
  timings: { total_ms: 14380, llm_ms: 5300, tools_ms: 810, gates_ms: 96 },
  telemetry: {
    routing: "observed",
    tools: "observed",
    evidence: "observed",
    generation: "observed",
    verification: "observed",
    jev: "observed",
    cost: "observed",
    timings: "observed",
    reasoning: "not_applicable",
    memory: "not_observed",
  },
  sources: [
    { document_id: "d-1", source_id: "s-1", title: "contrato.pdf", score: 0.81, status: "USED" },
  ],
  steps: [
    { type: "llm", step: 0, model: "zent-default", action: { tool: "search_knowledge" }, tokens: 900, latency_ms: 3200 },
    {
      type: "tool_routing",
      mode: "jev",
      choice: "search_knowledge",
      confidence: 0.83,
      certainty: 0.66,
      needs_tool: true,
      score: 0.83,
      certain: true,
      alternatives: ["query_database"],
      latency_ms: 41,
    },
    {
      type: "tool_call",
      tool: "search_knowledge",
      latency_ms: 810,
      output: "[Doc 1 | source:s-1] Contenido",
      meta: {
        evidence: [
          { ref: "d-1", document_id: "d-1", source_id: "s-1", title: "contrato.pdf", score: 0.81, status: "USED" },
        ],
        retrieval: { chunks: 5, strategy: "hybrid", top_score: 0.81 },
      },
    },
    { type: "llm", step: 1, model: "zent-default", action: { answer: "..." }, tokens: 740, latency_ms: 2100 },
    {
      type: "answer_gate",
      verdict: "approve",
      score: 0.87,
      grounded: true,
      complete: true,
      quality: 3,
      provider: "jev",
      mode: "answer_gate",
      latency_ms: 55,
    },
    { type: "final", answer: "La cláusula aplica..." },
  ],
  events: [
    { id: "step-1", phase: "decision", kind: "tool_routing", status: "ok", duration_ms: 41, metrics: { choice: "search_knowledge", confidence: 0.83 } },
    { id: "step-2", phase: "evidence", kind: "tool_call", status: "ok", duration_ms: 810, technical: { tool: "search_knowledge" } },
    { id: "step-3", phase: "evidence", kind: "sources", status: "ok", metrics: { sources: 1 }, technical: { items: [{ ref: "d-1", title: "contrato.pdf", relevance: 0.81, status: "USED" }] } },
    { id: "step-4", phase: "generation", kind: "llm", status: "ok", duration_ms: 3200, technical: { model: "zent-default" } },
    { id: "step-5", phase: "generation", kind: "llm", status: "ok", duration_ms: 2100, technical: { model: "zent-default" } },
    { id: "step-6", phase: "generation", kind: "generation", status: "ok", duration_ms: 5300, metrics: { total_tokens: 1640, cost_usd: 0.000381 }, technical: { model: "zent-default", calls: 2, answer_calls: 1, reasoning_calls: 1 } },
    { id: "step-7", phase: "verification", kind: "answer_gate", status: "ok", metrics: { verdict: "approve", grounded: true, complete: true, quality: 3, provider: "jev" } },
    { id: "step-8", phase: "verification", kind: "verification", status: "ok", metrics: { overall: "verified", checks: [{ key: "answer_gate", state: "ok" }] } },
    { id: "step-9", phase: "generation", kind: "final", status: "ok" },
  ],
};

const story = buildExecutionStory(AGENT_FLOW);

describe("story del agente — fidelidad (§48)", () => {
  it("es Flow v2 y NO lleva el badge histórico", () => {
    expect(story.version).toBe(2);
    expect(story.legacy).toBe(false);
    expect(story.telemetry.quality).not.toBe("legacy");
  });

  it("muestra las fases reales: decidió, consultó conocimiento y finalizó", () => {
    const ids = story.phases.map((phase) => phase.id);
    expect(ids).toContain("decision");
    expect(ids).toContain("evidence");
    expect(ids).toContain("generation");
    expect(ids).toContain("verification");
    expect(story.narrative).toContain("buscó en el conocimiento");
  });

  it("JEV intervino sin un score global inventado", () => {
    expect(story.jevImpact).toBeNull(); // sin packs de preflight, no hay tarjeta
    expect(story.technical.jevUsed).toBe(true);
    // El score del gate pertenece al gate: la fila técnica existe, pero no hay
    // un "Score JEV" agregado fabricado.
    expect(story.technical.jevScore).toBe(0.87);
  });

  it("reporta tokens y costo reales", () => {
    expect(story.technical.tokens).toEqual({ prompt: 1200, completion: 440, total: 1640 });
    expect(story.costUsd).toBeCloseTo(0.000381);
    expect(story.technical.model).toBe("zent-default");
    expect(story.totalMs).toBe(14380);
  });

  it("la verificación es un conjunto de comprobaciones, no un booleano", () => {
    expect(story.verification.overall).toBe("verified");
    expect(story.verification.label).toBe("Verificada");
    expect(story.verification.checks.length).toBeGreaterThanOrEqual(3);
  });

  it("distingue varias llamadas al modelo (razonamiento vs respuesta)", () => {
    const generation = story.phases.find((phase) => phase.id === "generation");
    expect(generation?.subtitle).toContain("2 llamadas al modelo");
    expect(generation?.subtitle).toContain("1 de razonamiento");
    expect(generation?.subtitle).toContain("1 de respuesta");
    expect(story.llmCalls).toBe(2);
  });

  it("expone la ejecución y la procedencia de la decisión", () => {
    expect(story.runId).toBe("run-42");
    expect(story.technical.provider).toBe("explicit_target");
    expect(story.technical.confidence).toBeNull();
    expect(story.confidenceLabel).toBe("");
  });

  it("cuenta eventos canónicos contra steps crudos (§36)", () => {
    expect(story.counts.canonicalEvents).toBe(AGENT_FLOW.events.length);
    expect(story.counts.rawSteps).toBe(AGENT_FLOW.steps.length);
    expect(story.counts.unmapped).toBe(0);
    expect(story.counts.mapped).toBe(AGENT_FLOW.events.length);
  });

  it("no convierte la telemetría faltante en warning (§47)", () => {
    expect(story.headline).toBe("Respuesta completada");
    expect(story.headlineStatus).toBe("ok");
    expect(story.outcomeTone).toBe("ok");
    expect(story.telemetry.missing).toContain("memory");
  });
});

describe("unknown no es cero (§7, §50)", () => {
  const minimal = buildExecutionStory({
    flow_version: 2,
    method: "agent",
    status: "completed",
    execution: { kind: "agent_run", id: "run-1" },
    decision: { evaluated: true, provider: "explicit_target" },
    jev: { used: false, calls: 0 },
    generation: { model: "zent-default" },
    steps: [{ type: "final", answer: "ok" }],
    events: [{ id: "e-1", phase: "generation", kind: "final", status: "ok" }],
  });

  it("no hay fila de confianza si no existe confianza", () => {
    expect(minimal.confidenceLabel).toBe("");
    expect(minimal.technical.confidence).toBeNull();
  });

  it("no hay score JEV si el juicio no produjo uno", () => {
    expect(minimal.technical.jevScore).toBeNull();
    expect(minimal.technical.jevUsed).toBe(false);
  });

  it("no hay tokens inventados", () => {
    expect(minimal.technical.tokens).toBeUndefined();
  });

  it("el costo desconocido no se muestra como 0", () => {
    expect(minimal.costUsd).toBeNull();
  });

  it("declara la telemetría que falta en vez de fingirla", () => {
    expect(minimal.telemetry.quality).toBe("partial");
    expect(minimal.telemetry.missing).toContain("cost");
    expect(minimal.telemetry.missing).toContain("verification");
    const memory = minimal.telemetry.dimensions.find((item) => item.key === "memory");
    expect(memory?.stateLabel).toBe("No observado");
    // "No aplica" no es lo mismo que "faltante": tools/evidence no corrieron.
    const tools = minimal.telemetry.dimensions.find((item) => item.key === "tools");
    expect(tools?.state).toBe("not_applicable");
    const evidence = minimal.telemetry.dimensions.find((item) => item.key === "evidence");
    expect(evidence?.state).toBe("not_applicable");
    expect(minimal.telemetry.missing).not.toContain("tools");
  });
});

describe("verificación parcial y bloqueada (§20, §21)", () => {
  it("sin respaldo declarado queda en verificación parcial", () => {
    const partial = buildExecutionStory({
      ...AGENT_FLOW,
      verification: {
        overall: "partial",
        checks: [
          { key: "analysis_complete", state: "ok" },
          { key: "answer_gate", state: "ok", detail: "approve" },
        ],
      },
    });
    expect(partial.outcomeLabel).toBe("Verificada parcialmente");
    expect(partial.outcomeTone).toBe("neutral");
    expect(partial.headlineStatus).toBe("ok");
  });

  it("una abstención se nombra como retención por seguridad", () => {
    const blocked = buildExecutionStory({
      ...AGENT_FLOW,
      verification: {
        overall: "blocked",
        checks: [{ key: "answer_gate", state: "blocked", detail: "abstain" }],
      },
    });
    expect(blocked.outcomeLabel).toBe("Retenida por seguridad");
    expect(blocked.outcomeTone).toBe("warn");
    expect(blocked.headlineStatus).toBe("warn");
  });

  it("análisis incompleto se declara como tal", () => {
    const incomplete = buildExecutionStory({
      ...AGENT_FLOW,
      verification: {
        overall: "blocked",
        checks: [{ key: "analysis_complete", state: "blocked" }],
      },
    });
    expect(incomplete.outcomeLabel).toBe("Análisis incompleto");
  });
});

describe("pasos sin mapping (§36, §37)", () => {
  it("cuenta los no mapeados y los deja visibles", () => {
    const withUnknown = buildExecutionStory({
      ...AGENT_FLOW,
      events: [
        ...AGENT_FLOW.events,
        {
          id: "step-10",
          phase: "decision",
          kind: "paso_futuro",
          status: "ok",
          metrics: { payload: { x: 1 } },
          technical: { unmapped: true },
        },
      ],
    });
    expect(withUnknown.counts.unmapped).toBe(1);
    expect(withUnknown.counts.mapped).toBe(AGENT_FLOW.events.length);
    const unknown = withUnknown.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "paso_futuro");
    expect(unknown?.metrics.payload).toEqual({ x: 1 });
  });
});
