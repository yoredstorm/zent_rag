import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeHomePage from "./Home";
import type {
  KnowledgeDelta,
  KnowledgeGraphPayload,
  KnowledgeOverview,
} from "../../lib/knowledgeModel";

const fetchKnowledgeOverview = vi.hoisted(() => vi.fn());
const fetchKnowledgeDelta = vi.hoisted(() => vi.fn());
const fetchKnowledgeGraph = vi.hoisted(() => vi.fn());
const fetchKnowledgeFeed = vi.hoisted(() => vi.fn());

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return {
    ...actual,
    fetchKnowledgeOverview,
    fetchKnowledgeDelta,
    fetchKnowledgeGraph,
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
    headline: "Zent entiende 3 área(s) de tu negocio",
    generated_at: new Date().toISOString(),
    health: {
      overall: 94,
      measured_dimensions: 3,
      total_dimensions: 3,
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
    domains: [
      {
        name: "ATPCO",
        objects: 12431,
        verified: 9000,
        measured: true,
        avg_confidence: 0.91,
        sources: 7,
        edges: 2400,
        conflicts: 2,
        last_updated: new Date().toISOString(),
      },
    ],
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

function graphFixture(): KnowledgeGraphPayload {
  return {
    nodes: [
      {
        id: "n1",
        type: "entity",
        name: "Record 4",
        domain: "ATPCO",
        status: "verified",
        confidence: 0.9,
        evidence_count: 7,
        degree: 4,
      },
      {
        id: "n2",
        type: "entity",
        name: "Record 2",
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
        predicate: "modifies",
        relationship_type: "business",
        confidence: 0.8,
        status: "inferred",
        provenance: "APPROVED",
      },
    ],
    counts: { nodes: 2, edges: 1 },
    truncated: false,
    focus_id: null,
    depth: 1,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/knowledge"]}>
      <KnowledgeHomePage />
    </MemoryRouter>
  );
}

afterEach(() => {
  fetchKnowledgeOverview.mockReset();
  fetchKnowledgeDelta.mockReset();
  fetchKnowledgeGraph.mockReset();
  fetchKnowledgeFeed.mockReset();
});

describe("KnowledgeHomePage", () => {
  it("muestra el hero vivo con conteos reales, delta y salud interpretada", async () => {
    fetchKnowledgeOverview.mockResolvedValue(overviewFixture());
    fetchKnowledgeDelta.mockResolvedValue(deltaFixture());
    fetchKnowledgeGraph.mockResolvedValue(graphFixture());
    fetchKnowledgeFeed.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText("Tu conocimiento empresarial está creciendo")
      ).toBeInTheDocument()
    );
    expect(screen.getByText("Entidades")).toBeInTheDocument();
    expect(screen.getByText(/18[.,]616/)).toBeInTheDocument();
    expect(screen.getByText("+412 entidades")).toBeInTheDocument();
    expect(screen.getByText(/Knowledge OS está saludable/)).toBeInTheDocument();
    expect(screen.getByTestId("knowledge-pulse")).toBeInTheDocument();
    expect(screen.getByTestId("knowledge-domains")).toBeInTheDocument();
    expect(screen.getByText("ATPCO")).toBeInTheDocument();
  });

  it("en error muestra error con reintento y NO ceros", async () => {
    fetchKnowledgeOverview.mockRejectedValue(new Error("db down"));
    fetchKnowledgeDelta.mockRejectedValue(new Error("db down"));
    fetchKnowledgeGraph.mockRejectedValue(new Error("db down"));
    fetchKnowledgeFeed.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("knowledge-home-error")).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
    expect(screen.queryByText("Tu conocimiento empresarial está creciendo")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("en vacío explica los primeros pasos y muestra el pulse inicial", async () => {
    fetchKnowledgeOverview.mockResolvedValue(
      overviewFixture({
        state: "empty",
        headline: "Zent todavía no tiene conocimiento de tu negocio.",
        domains: [],
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
          by_type: {},
        },
      })
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
        conflicts_resolved: 0,
      },
    });
    fetchKnowledgeGraph.mockResolvedValue({
      nodes: [],
      edges: [],
      counts: { nodes: 0, edges: 0 },
      truncated: false,
      focus_id: null,
      depth: 1,
    });
    fetchKnowledgeFeed.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText("ZENT todavía no conoce tu negocio.")).toBeInTheDocument()
    );
    expect(screen.getByTestId("knowledge-first-steps")).toBeInTheDocument();
    expect(screen.getByTestId("knowledge-pulse-empty")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Añadir fuente/ }).length).toBeGreaterThan(
      0
    );
  });
});
