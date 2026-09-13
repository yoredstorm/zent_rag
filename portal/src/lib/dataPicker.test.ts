import { describe, expect, it } from "vitest";
import { buildDataSources } from "./dataPicker";
import type { NodeBusinessSchema } from "./businessSchema";
import type { WorkflowGraph } from "./workflowGraph";

const graph: WorkflowGraph = {
  workflow_version: 2,
  nodes: [
    {
      id: "t", type: "trigger_event", version: 1, label: "Cuando ocurra algo", position: { x: 0, y: 0 },
      config: {}, input_ports: [], output_ports: [], retry_policy: {}, timeout_ms: 60000, error_policy: "fail", metadata: {},
    },
    {
      id: "q", type: "query_business_data", version: 1, label: "Consulta de ventas", position: { x: 0, y: 0 },
      config: {}, input_ports: [], output_ports: [], retry_policy: {}, timeout_ms: 60000, error_policy: "fail", metadata: {},
    },
  ],
  edges: [],
  variables: {},
  entrypoints: ["t"],
  metadata: {},
};

const schemas: Record<string, NodeBusinessSchema> = {
  query_business_data: {
    node_type: "query_business_data",
    label: "Consultar datos de negocio",
    category: "data",
    risk_level: "normal",
    parameters: [],
    outputs: [
      { key: "rows", label: "Resultados", type: "record_list" },
      { key: "answer", label: "Respuesta", type: "text" },
    ],
  },
};

describe("buildDataSources", () => {
  it("incluye trigger y nodos con labels de negocio y refs internas", () => {
    const sources = buildDataSources(graph, schemas, {
      trigger_payload: { message: "stock bajo", monto: 1200 },
      nodes: {
        q: { status: "succeeded", output: { answer: "Hay 7 unidades", rows: [{ producto: "MacBook", stock: 7 }] } },
      },
    });
    const trigger = sources.find((s) => s.id === "trigger");
    expect(trigger?.fields.some((f) => f.ref === "{{trigger.message}}" && f.sample === "stock bajo")).toBe(true);
    expect(trigger?.fields.some((f) => f.ref === "{{trigger.monto}}" && f.type === "number")).toBe(true);

    const query = sources.find((s) => s.id === "q");
    expect(query?.label).toBe("Consulta de ventas");
    const answer = query?.fields.find((f) => f.key === "answer");
    expect(answer?.label).toBe("Respuesta");
    expect(answer?.ref).toBe("{{nodes.q.output.answer}}");
    expect(answer?.sample).toBe("Hay 7 unidades");

    const product = query?.fields.find((f) => f.key === "rows.0.producto");
    expect(product?.label).toBe("Producto");
    expect(product?.ref).toBe("{{nodes.q.output.rows.0.producto}}");
    expect(product?.sample).toBe("MacBook");
  });

  it("nunca inventa datos cuando no hay sample", () => {
    const sources = buildDataSources(graph, schemas, null);
    const query = sources.find((s) => s.id === "q");
    expect(query?.fields.map((f) => f.key)).toEqual(["rows", "answer"]);
    expect(query?.fields.every((f) => f.sample === undefined)).toBe(true);
  });

  it("excluye el nodo seleccionado y los scaffolds", () => {
    const sources = buildDataSources(graph, schemas, null, "q");
    expect(sources.some((s) => s.id === "q")).toBe(false);
    expect(sources.some((s) => s.id === "t")).toBe(false);
  });
});
