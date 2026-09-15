import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { nodeMeta } from "../../lib/workflowGraph";
import { WorkflowContextPanel } from "./WorkflowContextPanel";

const SOURCES = [
  {
    id: "trigger",
    kind: "trigger" as const,
    label: "Cuando ocurre el evento",
    fields: [{ key: "message", label: "Mensaje recibido", ref: "{{trigger.message}}" }],
  },
  {
    id: "q",
    kind: "node" as const,
    label: "Consulta de datos",
    node_type: "query_business_data",
    fields: [
      { key: "rows", label: "Resultados", ref: "{{nodes.q.output.rows}}" },
      { key: "answer", label: "Respuesta", ref: "{{nodes.q.output.answer}}" },
    ],
  },
];

const CONTRIBUTIONS = [
  { section: "data", node_id: "q", node_type: "query_business_data", payload: { label: "Consulta" } },
  { section: "evidence_refs", node_id: "kb", node_type: "kb_query", payload: { label: "política" } },
  { section: "evidence_refs", node_id: "kb", node_type: "kb_query" },
];

describe("WorkflowContextPanel", () => {
  it("muestra datos disponibles, aportes por nodo y contribuciones del run", () => {
    render(
      <WorkflowContextPanel
        sources={SOURCES}
        contributions={CONTRIBUTIONS}
        nodes={{
          query_business_data: {
            ...nodeMeta("query_business_data"),
            label: "Consulta",
            contextWrites: ["data", "evidence"],
          },
          llm: nodeMeta("llm"),
        }}
      />
    );
    expect(screen.getByTestId("wf-context-panel")).toBeInTheDocument();
    expect(screen.getByTestId("wf-context-source-q")).toHaveTextContent("2 datos");
    expect(screen.getByTestId("wf-context-writes-query_business_data")).toHaveTextContent("data, evidence");
    expect(screen.getByTestId("wf-context-run-sections")).toHaveTextContent("evidence_refs · 2");
    expect(screen.getByTestId("wf-context-run-sections")).toHaveTextContent("data · 1");
  });

  it("muestra vacíos y permite cerrar", () => {
    const onClose = vi.fn();
    render(<WorkflowContextPanel onClose={onClose} />);
    expect(screen.getByText(/Sin datos todavía/)).toBeInTheDocument();
    expect(screen.getByText(/Ningún nodo aporta/)).toBeInTheDocument();
    expect(screen.getByText(/Sin contribuciones/)).toBeInTheDocument();
    screen.getByTestId("wf-context-close").click();
    expect(onClose).toHaveBeenCalled();
  });
});
