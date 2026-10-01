// =============================================================================
// WizardLearningPanel — el asistente también observa el aprendizaje real
// =============================================================================
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WizardLearningPanel } from "./WizardLearningPanel";

const state = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock("./useLearningSession", () => ({
  useLearningSession: () => state.current,
}));

function renderPanel() {
  return render(
    <MemoryRouter>
      <WizardLearningPanel sessionId="sess-1" />
    </MemoryRouter>,
  );
}

describe("WizardLearningPanel", () => {
  beforeEach(() => {
    state.current = {
      detail: {
        session_id: "sess-1",
        status: "learning",
        sources: [
          {
            id: "row-1",
            name: "Rec4_dapp_C.pdf",
            status: "learning",
            stage: "connecting",
            stage_label: "Conectando",
            stats: {},
          },
        ],
      },
      metrics: { entities: 286, relationships: 731, facts: 1428, rules: 119, evidence: 2094 },
      discoveries: [
        {
          event_type: "ENTITY_DISCOVERED",
          severity: "info",
          stage: "connecting",
          source_id: null,
          message: "ZENT reconoció una entidad nueva: Record 4",
          count: 1,
          items: [],
          seq: 3,
          at: new Date().toISOString(),
        },
      ],
      stage: "connecting",
      connected: true,
      active: true,
    };
  });

  it("muestra contadores reales, etapa y enlace a la sesión completa", () => {
    renderPanel();
    expect(screen.getByTestId("wizard-learning-panel")).toBeInTheDocument();
    expect(screen.getByText("ZENT está aprendiendo")).toBeInTheDocument();
    expect(screen.getByText("286")).toBeInTheDocument();
    expect(screen.getByText("Conectando")).toBeInTheDocument();
    expect(screen.getByText("Rec4_dapp_C.pdf")).toBeInTheDocument();
    expect(
      screen.getByText("ZENT reconoció una entidad nueva: Record 4"),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Ver aprendizaje en vivo/ });
    expect(link).toHaveAttribute("href", "/knowledge/sessions/sess-1");
  });

  it("no renderiza nada si la sesión aún no existe", () => {
    state.current = { ...state.current, detail: null };
    const { container } = renderPanel();
    expect(container.firstChild).toBeNull();
  });
});
