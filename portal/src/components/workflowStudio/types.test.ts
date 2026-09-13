import { describe, expect, it } from "vitest";
import { answerFromSteps, hookCurl, hookFetch, isStudioDrawer, normalizeTestPayload } from "./types";

describe("normalizeTestPayload", () => {
  it("pasa un objeto JSON tal cual", () => {
    const out = normalizeTestPayload('{"stock": 3, "sku": "ABC"}');
    expect(out.wrapped).toBe(false);
    expect(out.payload).toEqual({ stock: 3, sku: "ABC" });
  });

  it("envuelve texto libre en message y query", () => {
    const out = normalizeTestPayload("quien es el gerente");
    expect(out.wrapped).toBe(true);
    expect(out.payload).toEqual({ message: "quien es el gerente", query: "quien es el gerente" });
  });

  it("envuelve JSON inválido como el que escribe la gente entre llaves", () => {
    const out = normalizeTestPayload("{quien es el gerente}");
    expect(out.wrapped).toBe(true);
    expect(out.payload).toEqual({
      message: "{quien es el gerente}",
      query: "{quien es el gerente}",
    });
  });

  it("envuelve arrays y escalares (el trigger necesita un objeto)", () => {
    expect(normalizeTestPayload("[1,2]").wrapped).toBe(true);
    expect(normalizeTestPayload("42").payload).toEqual({ message: "42", query: "42" });
  });

  it("vacío es un payload vacío sin envolver", () => {
    expect(normalizeTestPayload("   ")).toEqual({ payload: {}, wrapped: false });
  });
});

describe("isStudioDrawer", () => {
  it("solo API y Avanzado son drawers; el editor ya no es una pestaña", () => {
    expect(isStudioDrawer("api")).toBe(true);
    expect(isStudioDrawer("advanced")).toBe(true);
    expect(isStudioDrawer("editor")).toBe(false);
    expect(isStudioDrawer("test")).toBe(false);
    expect(isStudioDrawer(null)).toBe(false);
  });
});

describe("answerFromSteps", () => {
  it("devuelve el último output.text como respuesta del agente", () => {
    const out = answerFromSteps([
      { node_id: "n1", node_type: "kb_query", status: "succeeded", output: { count: 2 } },
      { node_id: "n2", node_type: "llm", status: "succeeded", output: { text: "El gerente es Ana." } },
    ]);
    expect(out).toEqual({ text: "El gerente es Ana.", node_id: "n2", echo: false, error: null });
  });

  it("marca el eco cuando el nodo llm corrió sin agente", () => {
    const out = answerFromSteps([
      { node_id: "n2", node_type: "llm", status: "succeeded", output: { text: "[gpt-4o-mini] hola", echo: true } },
    ]);
    expect(out?.echo).toBe(true);
  });

  it("prioriza el error del paso fallido sobre cualquier texto", () => {
    const out = answerFromSteps([
      { node_id: "n1", node_type: "llm", status: "succeeded", output: { text: "viejo" } },
      { node_id: "n2", node_type: "llm", status: "failed", output: {}, error: "el agente falló: boom" },
    ]);
    expect(out).toEqual({
      text: "el agente falló: boom",
      node_id: "n2",
      echo: false,
      error: "el agente falló: boom",
    });
  });

  it("cae al campo answer de query_business_data", () => {
    const out = answerFromSteps([
      { node_id: "n1", node_type: "query_business_data", status: "succeeded", output: { answer: "42 ventas" } },
    ]);
    expect(out?.text).toBe("42 ventas");
  });

  it("sin pasos con texto no hay respuesta", () => {
    expect(answerFromSteps([])).toBeNull();
    expect(answerFromSteps(undefined)).toBeNull();
    expect(
      answerFromSteps([{ node_id: "n1", node_type: "notify", status: "simulated", output: { simulated: true } }]),
    ).toBeNull();
  });
});

describe("snippets del hook", () => {
  const url = "https://app.example/api/v1/public/workflows/abc/hook";

  it("curl lleva el header del secret y la URL", () => {
    const code = hookCurl(url, "s3cret");
    expect(code).toContain(url);
    expect(code).toContain("X-Zent-Workflow-Secret: s3cret");
    expect(code).toContain("-X POST");
  });

  it("fetch lleva el header del secret y la URL", () => {
    const code = hookFetch(url, "s3cret");
    expect(code).toContain(url);
    expect(code).toContain('"X-Zent-Workflow-Secret": "s3cret"');
  });
});
