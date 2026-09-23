// =============================================================================
// ExecutionRef — una ejecución es una query, un agent run o un workflow run
// =============================================================================
import { describe, expect, it } from "vitest";
import { executionFlowPath, executionRefOf, memoryImpactPath, normalizeRunImpact } from "./executionRef";

describe("executionRefOf (§27)", () => {
  it("prefiere el run_id del agente cuando existe", () => {
    expect(executionRefOf({ queryId: "q-1", runId: "r-1", method: "agent" })).toEqual({
      kind: "agent",
      id: "r-1",
    });
  });

  it("marca el workflow cuando el método lo dice", () => {
    expect(executionRefOf({ runId: "r-2", method: "workflow" })).toEqual({
      kind: "workflow",
      id: "r-2",
    });
  });

  it("cae al query_id para respuestas RAG", () => {
    expect(executionRefOf({ queryId: "q-1" })).toEqual({ kind: "query", id: "q-1" });
  });

  it("sin referencias no hay ejecución", () => {
    expect(executionRefOf({})).toBeNull();
  });
});

describe("rutas de ejecución y memoria", () => {
  it("el flow sale del endpoint genérico", () => {
    expect(executionFlowPath({ kind: "agent", id: "r-1" })).toBe(
      "/api/v1/executions/agent/r-1/flow",
    );
  });

  it("la memoria se consulta por query o por run", () => {
    expect(memoryImpactPath({ kind: "query", id: "q-1" })).toBe(
      "/api/v1/memory/queries/q-1/impact",
    );
    expect(memoryImpactPath({ kind: "agent", id: "r-1" })).toBe(
      "/api/v1/memory/runs/r-1/impact",
    );
  });

  it("sin integración de memoria devuelve null (no 0)", () => {
    expect(memoryImpactPath({ kind: "workflow", id: "w-1" })).toBeNull();
  });
});

describe("normalizeRunImpact (§28, §51)", () => {
  it("cuenta los buckets del run y respeta los ceros reales", () => {
    const payload = normalizeRunImpact(
      {
        run_id: "r-1",
        used: [{ memory_id: "m1" }, { memory_id: "m2" }],
        created: [{ memory_id: "m3" }],
        reinforced: [],
        contradicted: [],
      },
      { kind: "agent", id: "r-1" },
    );
    expect(payload?.counts).toEqual({
      used: 2,
      created: 1,
      reinforced: 0,
      contradicted: 0,
      validated: 0,
    });
  });

  it("respuesta vacía del servidor no se convierte en ceros", () => {
    expect(normalizeRunImpact(null, { kind: "agent", id: "r-1" })).toBeNull();
    expect(normalizeRunImpact({}, { kind: "agent", id: "r-1" })).toBeNull();
  });

  it("acepta el shape de query impact sin tocarlo", () => {
    const query = {
      query_id: "q-1",
      truncated: false,
      counts: { used: 0, created: 0, reinforced: 0, contradicted: 0, validated: 0 },
      used: [],
      created: [],
      reinforced: [],
      contradicted: [],
      validated: [],
    };
    expect(normalizeRunImpact(query, { kind: "query", id: "q-1" })).toBe(query);
  });
});
