import { describe, expect, it } from "vitest";
import { flowFromAgentSteps } from "./runPlaygroundTurn";

describe("flowFromAgentSteps", () => {
  it("mapea pasos JEV y de herramienta con ms", () => {
    const flow = flowFromAgentSteps(
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
      "Modelo (razonamiento)",
      "search_knowledge",
      "JEV verifica cierre",
      "Respuesta final",
    ]);
    expect(steps[0].ms).toBe(120);
    expect(steps[0].detail).toContain("confianza 0.90");
    expect(flow.jev).toEqual({ used: true });
    expect((flow.decision as { mode: string }).mode).toBe("ReAct + JEV");
    expect((flow.generation as { total_tokens: number }).total_tokens).toBe(180);
  });

  it("sin pasos JEV deja used=false y modo ReAct", () => {
    const flow = flowFromAgentSteps(
      [
        { type: "llm", tokens: 100, latency_ms: 900 },
        { type: "tool_call", tool: "call_api", latency_ms: 300, error: "blocked" },
      ],
      1500,
    );
    expect(flow.jev).toEqual({ used: false });
    expect((flow.decision as { mode: string }).mode).toBe("ReAct");
    const steps = flow.steps as { name: string; status: string }[];
    expect(steps[1].name).toBe("call_api");
    expect(steps[1].status).toBe("warn");
  });

  it("incluye modelo, costo y tiempo de razonamiento del run", () => {
    const flow = flowFromAgentSteps(
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
    expect((flow.timings as { generation_ms: number }).generation_ms).toBe(8800);
  });
});
