import { describe, expect, it } from "vitest";
import { classifyPlannedEffects } from "./workflowEffects";

describe("classifyPlannedEffects", () => {
  it("marca un externo sin pinned como UNVERIFIED", () => {
    const result = classifyPlannedEffects([
      { node_id: "pay", node_type: "capability_call", planned: { kind: "capability" } },
    ]);
    expect(result.level).toBe("UNVERIFIED");
    expect(result.unverified.map((item) => item.node_id)).toEqual(["pay"]);
  });

  it("marca un pinned como DECLARED, no verificado", () => {
    const result = classifyPlannedEffects([
      { node_id: "pay", node_type: "capability_call", planned: { pinned: true } },
    ]);
    expect(result.level).toBe("DECLARED");
    expect(result.unverified).toEqual([]);
    expect(result.declared.map((item) => item.node_id)).toEqual(["pay"]);
  });

  it("marca un nodo interno como SIMULATED", () => {
    const result = classifyPlannedEffects([
      { node_id: "state", node_type: "state_set", planned: { kind: "state" } },
    ]);
    expect(result.level).toBe("SIMULATED");
    expect(result.unverified).toEqual([]);
  });

  it("marca ai_decision como SIMULATED, no como efecto externo", () => {
    const result = classifyPlannedEffects([
      {
        node_id: "decide",
        node_type: "ai_decision",
        planned: { kind: "yes_no", judge: "live_readonly" },
      },
    ]);
    expect(result.level).toBe("SIMULATED");
    expect(result.unverified).toEqual([]);
  });

  it("sin efectos queda NONE", () => {
    expect(classifyPlannedEffects(undefined).level).toBe("NONE");
    expect(classifyPlannedEffects([]).level).toBe("NONE");
  });

  it("mixto mantiene las listas separadas", () => {
    const result = classifyPlannedEffects([
      { node_id: "pay", node_type: "capability_call", planned: { pinned: true } },
      { node_id: "http", node_type: "api_call", planned: { kind: "http" } },
    ]);
    expect(result.level).toBe("UNVERIFIED");
    expect(result.unverified.map((item) => item.node_id)).toEqual(["http"]);
    expect(result.declared.map((item) => item.node_id)).toEqual(["pay"]);
  });
});
