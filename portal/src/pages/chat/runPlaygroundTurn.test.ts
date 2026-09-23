// =============================================================================
// runPlaygroundTurn — el portal NO reconstruye la verdad del run (§1, §33, §34)
// =============================================================================
// El flow canónico lo construye el backend y viaja en el `done`. El builder
// local queda como fallback legacy explícito y no inventa NADA: ni confianza,
// ni score JEV, ni verificación, ni memoria.
import { afterEach, describe, expect, it, vi } from "vitest";
import { flowFromAgentStepsLegacy, runAgentTurn } from "./runPlaygroundTurn";

describe("flowFromAgentStepsLegacy", () => {
  it("mapea el timeline mínimo sin inventar señales JEV", () => {
    const flow = flowFromAgentStepsLegacy(
      [
        { type: "tool_routing", choice: "search_knowledge", confidence: 0.9, latency_ms: 120 },
        { type: "llm", tokens: 180, latency_ms: 2761, action: { tool: "search_knowledge" } },
        { type: "tool_call", tool: "search_knowledge", latency_ms: 1006 },
        { type: "termination_gate", stop: true, latency_ms: 80 },
        { type: "final", answer: "ok" },
      ],
      5000,
    );
    const steps = flow.steps as { name: string; ms: number; detail: string }[];
    expect(steps.map((step) => step.name)).toEqual([
      "JEV elige herramienta",
      "LLM (razonamiento)",
      "search_knowledge",
      "JEV verifica cierre",
      "Respuesta final",
    ]);
    expect(steps[0].ms).toBe(120);
    // Sin flow canónico no hay veredictos ni scores: sólo lo que el step dice.
    expect(steps[0].detail).toBe("search_knowledge");
    expect(flow.jev).toBeUndefined();
    expect(flow.confidence).toBeUndefined();
    expect(flow.flow_version).toBe(1);
    expect(flow.legacy).toBe(true);
  });

  it("no declara JEV cuando el router no lo consultó", () => {
    const flow = flowFromAgentStepsLegacy(
      [
        {
          type: "tool_routing",
          mode: "passthrough",
          skip_reason: "too_few_tools",
          tools_count: 1,
          latency_ms: 0.2,
        },
        { type: "llm", tokens: 100, latency_ms: 900 },
        { type: "final" },
      ],
      3000,
    );
    const steps = flow.steps as { name: string; detail: string }[];
    expect(steps[0].name).toBe("JEV elige herramienta");
    expect(steps[0].detail).toBe("JEV no consultado");
    expect(flow.jev).toBeUndefined();
  });

  it("marca warning sólo cuando el step falló", () => {
    const flow = flowFromAgentStepsLegacy(
      [
        { type: "llm", tokens: 100, latency_ms: 900 },
        { type: "tool_call", tool: "call_api", latency_ms: 300, error: "blocked" },
      ],
      1500,
    );
    const steps = flow.steps as { name: string; status: string }[];
    expect(steps[1].name).toBe("call_api");
    expect(steps[1].status).toBe("warn");
  });

  it("conserva modelo, costo y tokens reales del run", () => {
    const flow = flowFromAgentStepsLegacy(
      [
        { type: "llm", tokens: 1200, latency_ms: 2700 },
        { type: "llm", tokens: 701, latency_ms: 6100 },
      ],
      9900,
      { model: "openai/deepseek/deepseek-v3.2", cost: 0.0012, totalTokens: 1901 },
    );
    const generation = flow.generation as {
      model: string;
      cost: number;
      ms: number;
      total_tokens: number;
    };
    expect(generation.model).toBe("openai/deepseek/deepseek-v3.2");
    expect(generation.cost).toBe(0.0012);
    expect(generation.ms).toBe(8800);
    expect(generation.total_tokens).toBe(1901);
    // Sin datos no se escribe la clave (unknown != 0).
    const empty = flowFromAgentStepsLegacy([{ type: "final" }], 1000);
    expect(empty.generation).toEqual({});
  });

  it("mapea herramientas omitidas por fuentes del agente", () => {
    const flow = flowFromAgentStepsLegacy(
      [
        {
          type: "tool_filter",
          omitted: [
            { tool: "query_database", reason: "no_data_sources" },
            { tool: "call_api", reason: "no_api_allowlist" },
          ],
        },
        { type: "llm", tokens: 100, latency_ms: 900 },
        { type: "final" },
      ],
      2000,
    );
    const steps = flow.steps as { name: string; status: string; detail: string }[];
    expect(steps[0].name).toBe("Herramientas omitidas");
    expect(steps[0].status).toBe("warn");
    expect(steps[0].detail).toContain("query_database (el agente no tiene fuentes de datos)");
    expect(steps[0].detail).toContain("call_api (no hay APIs permitidas configuradas)");
  });
});

// ---------------------------------------------------------------------------
// §53: con flow del backend el portal NO reconstruye nada
// ---------------------------------------------------------------------------

const BACKEND_FLOW = {
  flow_version: 2,
  method: "agent",
  status: "completed",
  execution: { kind: "agent_run", id: "run-1" },
  events: [
    { id: "e-1", phase: "decision", kind: "tool_routing", status: "ok" },
    { id: "e-2", phase: "generation", kind: "llm", status: "ok" },
  ],
  jev: { used: true, calls: 2 },
  generation: { model: "zent-default", prompt_tokens: 1200, completion_tokens: 440 },
};

function sseResponse(frames: string) {
  return new Response(frames, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("runAgentTurn", () => {
  it("usa el flow canónico del backend y conserva el run_id", async () => {
    const body =
      "event: status\ndata: {\"phase\":\"running\"}\n\n" +
      `event: done\ndata: ${JSON.stringify({
        run_id: "run-1",
        status: "completed",
        answer: "listo",
        steps: [{ type: "final" }],
        flow: BACKEND_FLOW,
        total_latency_ms: 14380,
        total_tokens: 1640,
        prompt_tokens: 1200,
        completion_tokens: 440,
        cost: 0.000381,
        model: "zent-default",
      })}\n\n`;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sseResponse(body)),
    );

    const result = await runAgentTurn({
      agentId: "a-1",
      message: "¿aplica?",
      conversationId: null,
      auth: { token: "t", organizationId: "o" },
    });

    expect(result.flowSource).toBe("backend");
    expect(result.flow?.flow_version).toBe(2);
    expect(result.runId).toBe("run-1");
    expect(result.latencyMs).toBe(14380);
  });

  it("sin flow del backend cae al fallback legacy y lo marca", async () => {
    const body = `event: done\ndata: ${JSON.stringify({
      run_id: "run-2",
      status: "completed",
      answer: "ok",
      steps: [{ type: "llm", tokens: 10, latency_ms: 5 }],
      flow: null,
    })}\n\n`;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sseResponse(body)),
    );

    const result = await runAgentTurn({
      agentId: "a-1",
      message: "hola",
      conversationId: null,
      auth: { token: "t", organizationId: "o" },
    });

    expect(result.flowSource).toBe("legacy");
    expect(result.flow?.flow_version).toBe(1);
    expect(result.flow?.jev).toBeUndefined();
    expect(result.runId).toBe("run-2");
  });
});
