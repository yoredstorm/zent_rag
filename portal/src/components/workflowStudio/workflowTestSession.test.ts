import { describe, expect, it } from "vitest";
import {
  createInitialTestSessionState,
  isTestBusy,
  workflowTestSessionReducer,
} from "./workflowTestSession";
import type { TestReportOut } from "./workflowTestTypes";

const report: TestReportOut = {
  test_report_id: "test_1",
  requested_level: "simulation",
  effective_level: "simulation",
  provider_verified: false,
  result: "PASSED",
  executed_nodes: [
    { node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
  ],
};

const run = {
  id: "run_1",
  status: "succeeded",
  steps: [{ step_index: 0, step_type: "llm", node_id: "ask", status: "succeeded" }],
};

describe("workflowTestSessionReducer", () => {
  it("empieza en setup, simulation, sin resultado", () => {
    const state = createInitialTestSessionState();
    expect(state.view).toBe("setup");
    expect(state.requestedLevel).toBe("simulation");
    expect(state.operation).toBe("idle");
    expect(state.providerVerified).toBe(false);
  });

  it("abre resultado solo al completar el test", () => {
    let state = createInitialTestSessionState();
    state = workflowTestSessionReducer(state, { type: "start-test", level: "simulation", operationId: 1 });
    expect(state.view).toBe("setup");
    expect(state.operation).toBe("preparing");
    state = workflowTestSessionReducer(state, {
      type: "test-completed",
      report,
      run,
      operationId: 1,
    });
    expect(state.view).toBe("result");
    expect(state.operation).toBe("completed");
    expect(state.runKind).toBe("test_report");
    expect(state.providerVerified).toBe(false);
    expect(state.activeRunId).toBe("run_1");
  });

  it("conserva requested y effective distintos", () => {
    let state = createInitialTestSessionState();
    state = workflowTestSessionReducer(state, { type: "start-test", level: "provider", operationId: 4 });
    state = workflowTestSessionReducer(state, {
      type: "test-completed",
      operationId: 4,
      run: { ...run, id: "test_2", status: "unverified" },
      report: {
        ...report,
        requested_level: "provider",
        effective_level: "simulation",
        result: "UNVERIFIED",
        provider_verified: false,
        capped_reason: "provider_adapter_unavailable",
      },
    });
    expect(state.requestedLevel).toBe("provider");
    expect(state.effectiveLevel).toBe("simulation");
    expect(state.providerVerified).toBe(false);
    expect(state.resultCode).toBe("UNVERIFIED");
  });

  it("un run real no se marca como test report", () => {
    let state = createInitialTestSessionState();
    state = workflowTestSessionReducer(state, { type: "start-run", operationId: 9 });
    state = workflowTestSessionReducer(state, {
      type: "run-completed",
      run,
      plannedEffects: [],
      operationId: 9,
    });
    expect(state.runKind).toBe("execution_run");
    expect(state.report).toBeNull();
    expect(state.providerVerified).toBe(false);
  });

  it("una nueva prueba limpia el resultado anterior al preparar", () => {
    let state = createInitialTestSessionState();
    state = workflowTestSessionReducer(state, { type: "test-completed", report, run, operationId: 1 });
    state = workflowTestSessionReducer(state, { type: "start-test", level: "preview", operationId: 2 });
    expect(state.report).toBeNull();
    expect(state.run).toBeNull();
    expect(state.providerVerified).toBe(false);
  });

  it("un error sin resultado vuelve a setup", () => {
    let state = createInitialTestSessionState();
    state = workflowTestSessionReducer(state, { type: "start-test", level: "preview", operationId: 2 });
    state = workflowTestSessionReducer(state, {
      type: "failed",
      error: "No pude guardar",
      operationId: 2,
    });
    expect(state.view).toBe("setup");
    expect(state.operation).toBe("failed");
    expect(state.error).toBe("No pude guardar");
  });

  it("un histórico se marca como histórico", () => {
    let state = createInitialTestSessionState();
    state = workflowTestSessionReducer(state, {
      type: "historical-run",
      run,
      historicalHash: "hash-viejo",
    });
    expect(state.historicalRun).toBe(true);
    expect(state.historicalHash).toBe("hash-viejo");
    expect(state.selectedPane).toBe("path");
  });

  it("reset conserva el nivel elegido", () => {
    const state = workflowTestSessionReducer(createInitialTestSessionState("provider"), {
      type: "reset",
      level: "provider",
    });
    expect(state.requestedLevel).toBe("provider");
    expect(state.report).toBeNull();
  });

  it("bloquea cambio de nivel mientras corre", () => {
    const running = {
      ...createInitialTestSessionState(),
      operation: "preparing" as const,
      requestedLevel: "simulation" as const,
    };
    expect(isTestBusy(running.operation)).toBe(true);
    const next = workflowTestSessionReducer(running, { type: "select-level", level: "provider" });
    expect(next.requestedLevel).toBe("simulation");
  });
});
