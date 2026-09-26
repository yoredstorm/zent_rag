import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeOverviewPage from "./Overview";
import type { KnowledgeOverview } from "../../lib/knowledgeModel";

const fetchKnowledgeOverview = vi.hoisted(() => vi.fn());

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return { ...actual, fetchKnowledgeOverview };
});

vi.mock("../../auth", () => ({
  useAuth: () => ({
    session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"] },
  }),
}));

function overviewFixture(patch: Partial<KnowledgeOverview> = {}): KnowledgeOverview {
  return {
    state: "partial",
    headline: "Zent entiende 2 área(s) de tu negocio",
    generated_at: new Date().toISOString(),
    health: {
      overall: 81,
      measured_dimensions: 2,
      total_dimensions: 3,
      state: "partial",
      computed_at: new Date().toISOString(),
      dimensions: [
        {
          key: "coverage",
          label: "Cobertura empresarial",
          score: 88,
          weight: 0.2,
          measured: true,
          reason: "8 de 9 objetos tienen evidencia.",
          formula: "(objetos con evidencia / objetos) * 100",
          signals: {},
          missing: [],
          issues: [],
          updated_at: null,
          trend: null,
        },
        {
          key: "retrieval_quality",
          label: "Calidad de recuperación",
          score: null,
          weight: 0.15,
          measured: false,
          reason: "Sin evaluación RAG ejecutada.",
          formula: "composite_score * 100",
          signals: {},
          missing: ["evaluación RAG"],
          issues: [],
          updated_at: null,
          trend: null,
        },
        {
          key: "human_validation",
          label: "Validación humana",
          score: 54,
          weight: 0.1,
          measured: true,
          reason: "5 de 9 objetos verificados.",
          formula: "(verificados / objetos) * 100",
          signals: {},
          missing: [],
          issues: ["Ningún objeto verificado"],
          updated_at: null,
          trend: null,
        },
      ],
    },
    domains: [
      { name: "Ventas", objects: 12, verified: 4, measured: true, avg_confidence: 0.82, sources: 1 },
      { name: "Inventario", objects: 3, verified: 0, measured: true, avg_confidence: 0.6, sources: 1 },
    ],
    attention: [
      {
        kind: "conflict",
        severity: "high",
        count: 2,
        title: "2 conflicto(s) sin resolver",
        href: "/knowledge/quality?tab=conflicts",
      },
    ],
    counts: {
      objects: 15,
      verified: 4,
      inferred: 8,
      discovered: 3,
      assertions: 22,
      evidence: 30,
      edges: 18,
      sources: 2,
      by_type: {},
    },
    recent: [],
    last_learning: null,
    conflicts_preview: [],
    gaps_preview: [],
    materialized: true,
    ...patch,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/knowledge"]}>
      <KnowledgeOverviewPage />
    </MemoryRouter>
  );
}

afterEach(() => {
  fetchKnowledgeOverview.mockReset();
});

describe("KnowledgeOverviewPage", () => {
  it("muestra el command center con health explicable y dominios", async () => {
    fetchKnowledgeOverview.mockResolvedValue(overviewFixture());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Zent entiende 2 área/)).toBeInTheDocument()
    );
    expect(screen.getByText("81")).toBeInTheDocument();
    expect(screen.getByText("Ventas")).toBeInTheDocument();
    expect(screen.getByText("2 conflicto(s) sin resolver")).toBeInTheDocument();
    expect(screen.getByText(/15 objetos de negocio/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Explorar modelo" })).toHaveAttribute(
      "href",
      "/knowledge/model"
    );
  });

  it("muestra No medido cuando una dimensión no se midió (nunca 0)", async () => {
    fetchKnowledgeOverview.mockResolvedValue(overviewFixture());
    renderPage();
    await waitFor(() => expect(screen.getByText("No medido")).toBeInTheDocument());
    expect(screen.getByText(/Sin evaluación RAG ejecutada/)).toBeInTheDocument();
  });

  it("en error muestra estado de error y NO ceros", async () => {
    fetchKnowledgeOverview.mockRejectedValue(new Error("db down"));
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("knowledge-overview-error")).toBeInTheDocument()
    );
    expect(screen.queryByText(/0 objetos de negocio/)).toBeNull();
    expect(screen.queryByText(/Zent entiende/)).toBeNull();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("en vacío explica y ofrece añadir fuente", async () => {
    fetchKnowledgeOverview.mockResolvedValue(
      overviewFixture({
        state: "empty",
        headline: "Zent todavía no tiene conocimiento de tu negocio.",
        counts: {
          objects: 0,
          verified: 0,
          inferred: 0,
          discovered: 0,
          assertions: 0,
          evidence: 0,
          edges: 0,
          sources: 0,
          by_type: {},
        },
        domains: [],
        attention: [],
      })
    );
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByText("Zent todavía no tiene conocimiento de tu negocio")
      ).toBeInTheDocument()
    );
    expect(
      screen.getAllByRole("link", { name: "Añadir fuente" }).length
    ).toBeGreaterThanOrEqual(1);
  });
});
