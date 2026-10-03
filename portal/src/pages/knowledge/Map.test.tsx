import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeMapPage from "./Map";
import type { KnowledgeDomain } from "../../lib/knowledgeModel";

const fetchKnowledgeDomains = vi.hoisted(() => vi.fn());
const fetchKnowledgeGraph = vi.hoisted(() => vi.fn());
const fetchKnowledgeConflicts = vi.hoisted(() => vi.fn());
const fetchKnowledgeDelta = vi.hoisted(() => vi.fn());

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return {
    ...actual,
    fetchKnowledgeDomains,
    fetchKnowledgeGraph,
    fetchKnowledgeConflicts,
    fetchKnowledgeDelta,
  };
});

vi.mock("../../components/knowledgeMap/MapRail", () => ({
  MapRail: () => <div data-testid="map-rail" />,
}));

vi.mock("../../components/knowledgeMap/MapInspector", () => ({
  MapInspector: () => <div data-testid="map-inspector" />,
}));

const DOMAIN: KnowledgeDomain = {
  name: "ATPCO",
  objects: 12431,
  verified: 9000,
  measured: true,
  avg_confidence: 0.9,
  sources: 7,
  edges: 2400,
  conflicts: 0,
  last_updated: new Date().toISOString(),
  by_type: [
    { type: "entity", total: 800, verified: 400 },
    { type: "business_rule", total: 120, verified: 40 },
  ],
};

function renderPage(path = "/knowledge/map") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <KnowledgeMapPage />
    </MemoryRouter>
  );
}

afterEach(() => {
  fetchKnowledgeDomains.mockReset();
  fetchKnowledgeGraph.mockReset();
  fetchKnowledgeConflicts.mockReset();
  fetchKnowledgeDelta.mockReset();
});

describe("KnowledgeMapPage", () => {
  it("muestra los dominios como clusters y profundiza a temas", async () => {
    fetchKnowledgeDomains.mockResolvedValue({ domains: [DOMAIN], count: 1 });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /ATPCO, 12[.,]431 objetos/ })
      ).toBeInTheDocument()
    );
    await user.click(screen.getByRole("button", { name: /ATPCO/ }));

    expect(
      await screen.findByRole("button", { name: /Entidades, 800 objetos/ })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: /3 nodos y 2 relaciones/ })
    ).toBeInTheDocument();
  });

  it("en nivel objetos dibuja el grafo real y ofrece filtros avanzados", async () => {
    fetchKnowledgeDomains.mockResolvedValue({ domains: [DOMAIN], count: 1 });
    fetchKnowledgeGraph.mockResolvedValue({
      nodes: [
        {
          id: "obj-1",
          type: "entity",
          name: "Record 4",
          domain: "ATPCO",
          status: "inferred",
          confidence: 0.8,
          evidence_count: 3,
          degree: 5,
        },
      ],
      edges: [],
      counts: { nodes: 1, edges: 0 },
      truncated: false,
      focus_id: null,
      depth: 1,
    });

    const user = userEvent.setup();
    renderPage("/knowledge/map?level=objects&domain=ATPCO&topic=entity");

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Record 4, 5 conexiones/ })
      ).toBeInTheDocument()
    );
    await user.click(screen.getByTestId("map-advanced"));
    expect(screen.getByLabelText("Solo conflictos")).toBeInTheDocument();
    expect(screen.getByLabelText("Cambios recientes (7d)")).toBeInTheDocument();
  });
});
