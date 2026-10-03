import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { KnowledgePulse } from "./KnowledgePulse";
import type { KnowledgeGraphPayload } from "../../lib/knowledgeModel";
import type { KnowledgeFeedItem } from "../../lib/knowledgeActivity";

const graph: KnowledgeGraphPayload = {
  nodes: [
    {
      id: "n1",
      type: "entity",
      name: "Record 4",
      domain: "ATPCO",
      status: "verified",
      confidence: 0.92,
      evidence_count: 7,
      degree: 5,
    },
    {
      id: "n2",
      type: "business_rule",
      name: "Renumber Category Control",
      domain: "ATPCO",
      status: "inferred",
      confidence: 0.7,
      evidence_count: 3,
      degree: 2,
    },
  ],
  edges: [
    {
      id: "e1",
      source: "n1",
      target: "n2",
      predicate: "uses",
      relationship_type: "business",
      confidence: 0.8,
      status: "inferred",
      provenance: "INFERRED",
    },
  ],
  counts: { nodes: 2, edges: 1 },
  truncated: false,
  focus_id: null,
  depth: 1,
};

const events: KnowledgeFeedItem[] = [
  {
    id: "ev-1",
    kind: "learning",
    at: new Date().toISOString(),
    title: "ZENT enriqueció Record 4 con 3 evidencias nuevas",
    category: "discovery",
    severity: "success",
    repeat: 1,
  },
];

describe("KnowledgePulse", () => {
  it("dibuja nodos y relaciones reales y describe el grafo", () => {
    render(<KnowledgePulse graph={graph} events={events} />);
    expect(
      screen.getByRole("group", { name: /2 nodos y 1 relaciones reales/ })
    ).toBeInTheDocument();
    expect(screen.getByText("2 nodos · 1 relaciones visibles")).toBeInTheDocument();
  });

  it("abre el detalle de un nodo con teclado o click", async () => {
    const user = userEvent.setup();
    render(<KnowledgePulse graph={graph} events={events} />);
    await user.click(
      screen.getByRole("button", { name: /Record 4, Entidad, 5 conexiones/ })
    );
    const detail = screen.getByTestId("knowledge-pulse-detail");
    expect(detail).toBeInTheDocument();
    expect(detail.textContent).toMatch(/5 conexiones/);
  });

  it("sin grafo muestra el estado inicial, nunca partículas falsas", () => {
    render(<KnowledgePulse graph={null} events={[]} />);
    expect(screen.getByTestId("knowledge-pulse-empty")).toBeInTheDocument();
    expect(
      screen.getByText(/El pulso aparecerá cuando ZENT reconozca/)
    ).toBeInTheDocument();
  });
});
