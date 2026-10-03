// =============================================================================
// LearningPulse — nodos, conexiones y pulsos desde eventos reales
// =============================================================================
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SessionEvent, SessionGraph } from "../../lib/knowledgeSessions";
import { LearningPulse } from "./LearningPulse";

const graph: SessionGraph = {
  session_id: "sess-1",
  nodes: [
    { id: "n1", name: "Record 4", kind: "entity", known: false },
    { id: "n2", name: "Record 2", kind: "entity", known: true },
  ],
  edges: [
    { id: "e1", subject: "n1", object: "n2", predicate: "modifies" },
  ],
};

function event(seq: number, type: string, payload: Record<string, unknown>): SessionEvent {
  return {
    seq,
    session_id: "sess-1",
    source_id: "src-1",
    event_type: type,
    stage: "connecting",
    severity: "info",
    message: `evento ${type}`,
    payload,
    aggregate: false,
    created_at: new Date().toISOString(),
  };
}

describe("LearningPulse", () => {
  it("dibuja nodos y relaciones reales de la sesión", () => {
    render(
      <LearningPulse
        graph={graph}
        events={[event(1, "ENTITY_DISCOVERED", { name: "Record 4" })]}
        active
        metrics={{ entities: 2, relationships: 1 }}
      />
    );
    expect(
      screen.getByRole("group", { name: /2 nodos y 1 relaciones reales/ })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Record 4, nuevo, 1 conexiones/ })
    ).toBeInTheDocument();
  });

  it("abre el detalle de un nodo y pinta un pulso por evento real", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <LearningPulse
        graph={graph}
        events={[event(1, "ENTITY_DISCOVERED", { name: "Record 4" })]}
        active
        metrics={{}}
      />
    );
    expect(container.querySelectorAll(".ks-pulse-ring")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /Record 4/ }));
    expect(screen.getByTestId("learning-pulse-detail")).toHaveTextContent(
      "Nuevo en esta sesión"
    );
  });

  it("sin grafo explica que el conocimiento aparecerá en tiempo real", () => {
    render(
      <LearningPulse graph={null} events={[]} active metrics={{}} />
    );
    expect(
      screen.getByText(/El conocimiento aparecerá aquí en tiempo real/)
    ).toBeInTheDocument();
  });
});
