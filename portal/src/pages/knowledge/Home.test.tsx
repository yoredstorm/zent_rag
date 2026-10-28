import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeHomePage from "./Home";
import type {
  KnowledgeDelta,
  KnowledgeOverview,
} from "../../lib/knowledgeModel";

const fetchKnowledgeOverview = vi.hoisted(() => vi.fn());
const fetchKnowledgeDelta = vi.hoisted(() => vi.fn());
const fetchKnowledgeFeed = vi.hoisted(() => vi.fn());

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return {
    ...actual,
    fetchKnowledgeOverview,
    fetchKnowledgeDelta,
    fetchKnowledgeGraph: vi.fn(),
  };
});

vi.mock("../../lib/knowledgeActivity", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeActivity")>();
  return {
    ...actual,
    fetchKnowledgeFeed,
    streamKnowledgeEvents: () => ({ close: () => {} }),
  };
});

function overviewFixture(patch: Partial<KnowledgeOverview> = {}): KnowledgeOverview {
  return {
    state: "ready",
    headline: "Zent entiende 3 áreas de tu negocio",
    generated_at: new Date().toISOString(),
    health: {
      overall: 94,
      measured_dimensions: 3,
      total_dimensions: 5,
      state: "ready",
      computed_at: new Date().toISOString(),
      dimensions: [
        {
          key: "coverage",
          label: "Cobertura empresarial",
          score: 96,
          weight: 0.2,
          measured: true,
          reason: "96 de 100 objetos tienen evidencia.",
          formula: "(objetos con evidencia / objetos) * 100",
          signals: {},
          missing: [],
          issues: [],
          updated_at: null,
          trend: null,
        },
      ],
    },
    domains: [],
    attention: [],
    counts: {
      objects: 1816,
      verified: 1200,
      inferred: 400,
      discovered: 216,
      assertions: 141664,
      evidence: 72084,
      edges: 72084,
      sources: 2418,
      indexed_sources: 40,
      indexed_documents: 900,
      sources_ready: 37,
      by_type: {
        entity: { total: 18616, verified: 9000, inferred: 400 },
        business_rule: { total: 9218, verified: 3000, inferred: 200 },
      },
    },
    recent: [],
    last_learning: null,
    conflicts_preview: [],
    gaps_preview: [],
    materialized: true,
    ...patch,
  };
}

function deltaFixture(): KnowledgeDelta {
  return {
    window: "24h",
    since: new Date(Date.now() - 86_400_000).toISOString(),
    until: new Date().toISOString(),
    bucket: "hour",
    totals: {
      objects: 412,
      entities: 412,
      concepts: 0,
      relationships: 763,
      facts: 1842,
      rules: 96,
      metrics: 0,
      terms: 0,
      processes: 0,
      evidence: 300,
      sources: 2,
      conflicts_resolved: 1,
      conflicts_detected: 0,
    },
    by_type: [],
    enriched: [],
    enriched_total: 0,
    by_domain: [],
    timeline: [],
    computed_at: new Date().toISOString(),
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/knowledge"]}>
      <KnowledgeHomePage />
    </MemoryRouter>,
  );
}

afterEach(() => {
  fetchKnowledgeOverview.mockReset();
  fetchKnowledgeDelta.mockReset();
  fetchKnowledgeFeed.mockReset();
});

describe("KnowledgeHomePage", () => {
  it("muestra estado factual, tres señales y una acción principal", async () => {
    fetchKnowledgeOverview.mockResolvedValue(overviewFixture());
    fetchKnowledgeDelta.mockResolvedValue(deltaFixture());
    fetchKnowledgeFeed.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Zent entiende 3 áreas de tu negocio")).toBeInTheDocument(),
    );
    expect(screen.getByText("Documentos listos")).toBeInTheDocument();
    expect(screen.getByText("Fuentes con contenido")).toBeInTheDocument();
    expect(screen.getByText("Señales de atención")).toBeInTheDocument();
    expect(screen.getByText("+412 entidades")).toBeInTheDocument();
    expect(screen.queryByText(/está creciendo/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("knowledge-pulse")).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("knowledge-hero")).getByRole("link", {
        name: "Preguntar",
      }),
    ).toHaveAttribute("href", "/knowledge/ask");
    expect(screen.queryByTestId("knowledge-quick-actions")).not.toBeInTheDocument();
    expect(screen.getByTestId("knowledge-recent-activity")).toBeInTheDocument();
  });

  it("tolera que falle delta sin ocultar el estado durable", async () => {
    fetchKnowledgeOverview.mockResolvedValue(overviewFixture());
    fetchKnowledgeDelta.mockRejectedValue(new Error("delta down"));
    fetchKnowledgeFeed.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Zent entiende 3 áreas de tu negocio")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("knowledge-home-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("knowledge-next-step")).toBeInTheDocument();
  });

  it("en error muestra reintento y no inventa ceros", async () => {
    fetchKnowledgeOverview.mockRejectedValue(new Error("db down"));
    fetchKnowledgeDelta.mockRejectedValue(new Error("db down"));
    fetchKnowledgeFeed.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("knowledge-home-error")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
    expect(screen.queryByText("Documentos listos")).not.toBeInTheDocument();
  });

  it("en vacío ofrece un único camino para añadir información", async () => {
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
          indexed_sources: 0,
          indexed_documents: 0,
          sources_ready: 0,
          by_type: {},
        },
      }),
    );
    fetchKnowledgeDelta.mockResolvedValue({
      ...deltaFixture(),
      totals: {
        ...deltaFixture().totals,
        objects: 0,
        entities: 0,
        relationships: 0,
        facts: 0,
        rules: 0,
        evidence: 0,
        sources: 0,
      },
    });
    fetchKnowledgeFeed.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText("Todavía no hay información lista para responder."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Añadir información" })).toHaveAttribute(
      "href",
      "/knowledge/sources?new=1",
    );
    expect(screen.queryByTestId("knowledge-first-steps")).not.toBeInTheDocument();
  });
});
