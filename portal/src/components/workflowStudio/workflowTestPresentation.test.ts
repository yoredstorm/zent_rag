import { describe, expect, it } from "vitest";
import {
  buildTestRun,
  cappedReasonLabel,
  effectBoundary,
  generateSampleForGraph,
  isJsonObject,
  providerSummary,
  requestedEffectiveSentence,
  resultHeadline,
} from "./workflowTestPresentation";
import type { TestReportOut } from "./workflowTestTypes";

const base: TestReportOut = {
  requested_level: "simulation",
  effective_level: "simulation",
  provider_verified: false,
  result: "PASSED",
};

describe("workflowTestPresentation", () => {
  it("no confunde un PASSED de simulación con proveedor", () => {
    const headline = resultHeadline(base, null, "test_report");
    expect(headline.label).toBe("Simulación completada");
    expect(headline.detail).toContain("No certifica proveedor real");
  });

  it("un sandbox capeado no se presenta como sandbox aprobado", () => {
    const headline = resultHeadline(
      {
        ...base,
        requested_level: "sandbox",
        effective_level: "simulation",
        capped_reason: "sandbox_adapter_unavailable",
      },
      null,
      "test_report",
    );
    expect(headline.tone).toBe("warn");
    expect(headline.label).toBe("Nivel ajustado por el servidor");
    expect(headline.detail).toContain("sandbox");
    expect(headline.detail.toLowerCase()).toContain("simulación");
  });

  it("provider verificado solo con flag backend y nivel provider", () => {
    const report = {
      ...base,
      requested_level: "provider",
      effective_level: "provider",
      provider_verified: true,
      result: "PASSED",
    };
    expect(resultHeadline(report, null, "test_report").label).toBe(
      "Verificación con proveedor completada",
    );
    expect(providerSummary(report).label).toBe("Verificado por proveedor");
  });

  it("provider no conectado queda UNVERIFIED", () => {
    const report = {
      ...base,
      requested_level: "provider",
      effective_level: "simulation",
      result: "UNVERIFIED",
      capped_reason: "provider_adapter_unavailable",
    };
    expect(resultHeadline(report, null, "test_report").label).toBe(
      "Sin verificación de proveedor",
    );
    expect(providerSummary(report).label).toBe("Proveedor no conectado");
  });

  it("WAITING no se presenta como éxito", () => {
    const run = { id: "r", status: "waiting", steps: [] };
    const headline = resultHeadline(null, run, "execution_run");
    expect(headline.tone).toBe("warn");
    expect(headline.label).toBe("Esperando mensaje");
  });

  it("traduce capped_reason y conserva códigos desconocidos", () => {
    expect(cappedReasonLabel("provider_adapter_unavailable")).toContain("proveedor real");
    expect(cappedReasonLabel("custom_reason")).toBe("custom reason");
  });

  it("detecta JSON objeto y no arrays", () => {
    expect(isJsonObject('{"message":"hola"}')).toBe(true);
    expect(isJsonObject("[1,2]")).toBe(false);
    expect(isJsonObject("{no es json}")).toBe(false);
  });

  it("construye el run sintético del test sin inventar pasos", () => {
    const run = buildTestRun({
      ...base,
      test_report_id: "test_1",
      executed_nodes: [{ node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } }],
    });
    expect(run.id).toBe("test_1");
    expect(run.steps?.[0]).toMatchObject({ node_id: "ask", status: "succeeded" });
  });

  it("genera ejemplo según los nodos reales del grafo", () => {
    const message = generateSampleForGraph({
      workflow_version: 2,
      nodes: [
        {
          id: "kb",
          type: "kb_query",
          version: 1,
          label: "Buscar",
          position: { x: 0, y: 0 },
          config: {},
          input_ports: [],
          output_ports: [],
          retry_policy: { max_attempts: 1 },
          timeout_ms: 1,
          error_policy: "fail",
          metadata: {},
        },
      ],
      edges: [],
      entrypoints: [],
      variables: {},
      metadata: {},
    });
    expect(message).toContain("base de conocimiento");
  });

  it("la explicación de simulation no promete efectos ficticios", () => {
    expect(effectBoundary("simulation")).toContain("lecturas reales");
    expect(effectBoundary("simulation")).toContain("escrituras");
  });

  it("requested/effective se muestran juntos cuando difieren", () => {
    const sentence = requestedEffectiveSentence({
      ...base,
      requested_level: "provider",
      effective_level: "simulation",
    });
    expect(sentence).toContain("Solicitaste Proveedor");
    expect(sentence).toContain("ejecutó Simulación");
  });
});
