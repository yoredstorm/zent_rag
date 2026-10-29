import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeExplorerPage from "./Explorer";
import type { KnowledgeObject } from "../../lib/knowledgeModel";

const fetchKnowledgeDomains = vi.hoisted(() => vi.fn());
const fetchKnowledgeObjects = vi.hoisted(() => vi.fn());
const fetchKnowledgeGraph = vi.hoisted(() => vi.fn());
const fetchKnowledgeCorpora = vi.hoisted(() => vi.fn());
const fetchKnowledgeSources = vi.hoisted(() => vi.fn());
const fetchKnowledgeSourceInsight = vi.hoisted(() => vi.fn());

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return {
    ...actual,
    fetchKnowledgeDomains,
    fetchKnowledgeObjects,
    fetchKnowledgeGraph,
    fetchKnowledgeCorpora,
    fetchKnowledgeSources,
    fetchKnowledgeSourceInsight,
  };
});

function objectFixture(patch: Partial<KnowledgeObject> = {}): KnowledgeObject {
  return {
    id: "obj-1",
    type: "entity",
    name: "Record 4",
    display_name: "Record 4",
    description: "Registro de renumbering de ATPCO.",
    domain: "ATPCO",
    status: "inferred",
    provenance: "INFERRED",
    confidence: 0.78,
    confidence_label: "media",
    source_of_truth: null,
    source_id: null,
    authority_level: null,
    evidence_count: 7,
    assertion_count: 3,
    verified_at: null,
    freshness_at: null,
    last_seen_at: null,
    metadata: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...patch,
  };
}

function renderPage(path = "/knowledge/explorer") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <KnowledgeExplorerPage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  fetchKnowledgeCorpora.mockResolvedValue({ corpora: [], count: 0 });
  fetchKnowledgeSources.mockResolvedValue({ sources: [] });
  fetchKnowledgeSourceInsight.mockResolvedValue(null);
});

afterEach(() => {
  fetchKnowledgeDomains.mockReset();
  fetchKnowledgeObjects.mockReset();
  fetchKnowledgeGraph.mockReset();
  fetchKnowledgeCorpora.mockReset();
  fetchKnowledgeSources.mockReset();
  fetchKnowledgeSourceInsight.mockReset();
});

describe("KnowledgeExplorerPage", () => {
  it("lista objetos reales con su dominio y total", async () => {
    fetchKnowledgeDomains.mockResolvedValue({
      domains: [
        {
          name: "ATPCO",
          objects: 12431,
          verified: 9000,
          measured: true,
          avg_confidence: 0.9,
          sources: 7,
          by_type: [
            { type: "entity", total: 8, verified: 4 },
            { type: "business_rule", total: 2, verified: 0 },
          ],
        },
      ],
      count: 1,
    });
    fetchKnowledgeObjects.mockResolvedValue({
      items: [objectFixture()],
      count: 1,
      total: 1,
    });

    renderPage();

    await waitFor(() => expect(screen.getByText("Record 4")).toBeInTheDocument());
    expect(screen.getAllByText("ATPCO").length).toBeGreaterThan(0);
    expect(screen.getByText("1 de 1 objetos")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Record 4/ })
    ).toHaveAttribute("href", "/knowledge/objects/obj-1");
  });

  it("filtra por dominio al hacer click en el sidebar", async () => {
    fetchKnowledgeDomains.mockResolvedValue({
      domains: [
        {
          name: "ATPCO",
          objects: 10,
          verified: 4,
          measured: true,
          avg_confidence: 0.8,
          sources: 2,
        },
      ],
      count: 1,
    });
    fetchKnowledgeObjects.mockResolvedValue({ items: [], count: 0, total: 0 });

    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(fetchKnowledgeObjects).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: /ATPCO/ }));
    await waitFor(() =>
      expect(fetchKnowledgeObjects).toHaveBeenLastCalledWith(
        expect.objectContaining({ domain: "ATPCO" })
      )
    );
  });

  it("muestra los temas del dominio y filtra por tema", async () => {
    fetchKnowledgeDomains.mockResolvedValue({
      domains: [
        {
          name: "ATPCO",
          objects: 10,
          verified: 4,
          measured: true,
          avg_confidence: 0.8,
          sources: 2,
          by_type: [
            { type: "entity", total: 8, verified: 4 },
            { type: "business_rule", total: 2, verified: 0 },
          ],
        },
      ],
      count: 1,
    });
    fetchKnowledgeObjects.mockResolvedValue({ items: [], count: 0, total: 0 });

    const user = userEvent.setup();
    renderPage("/knowledge/explorer?domain=ATPCO");
    await waitFor(() =>
      expect(screen.getByTestId("knowledge-topics")).toBeInTheDocument()
    );
    expect(screen.getByText("Temas de ATPCO")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Entidad/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Regla de negocio/ }));
    await waitFor(() =>
      expect(fetchKnowledgeObjects).toHaveBeenLastCalledWith(
        expect.objectContaining({ domain: "ATPCO", type: "business_rule" })
      )
    );
  });

  it("muestra el resumen documental con pasaje y límites de certeza", async () => {
    fetchKnowledgeDomains.mockResolvedValue({ domains: [], count: 0 });
    fetchKnowledgeObjects.mockResolvedValue({ items: [], count: 0, total: 0 });
    fetchKnowledgeCorpora.mockResolvedValue({
      corpora: [{ id: "corpus-1", name: "Principal", slug: "principal" }],
      count: 1,
    });
    fetchKnowledgeSources.mockResolvedValue({
      sources: [
        { id: "src-1", name: "el_principito.pdf", type: "file", status: "indexed" },
      ],
    });
    fetchKnowledgeSourceInsight.mockResolvedValue({
      contract: "knowledge_explorer_insight/v1",
      source: {
        source_id: "src-1",
        name: "el_principito.pdf",
        genre: "narrative",
        genre_confidence: 0.71,
        pages: 104,
        sections: 8,
        tables: 0,
      },
      summary: "Documento de naturaleza narrativa.",
      topics: [
        {
          id: "personajes",
          label: "Personajes, temas y elementos",
          summary: "Elementos reconocidos en la narración.",
          count: 1,
          insights: [
            {
              kind: "concept",
              object_id: "obj-1",
              name: "El principito",
              claim_text: "Personaje que conversa con el narrador.",
              grounded_excerpt: "—¿Recuerdas? —preguntó el principito.",
              evidence_ids: ["ev-1"],
              source_locator: { page: 12, section_path: ["Capítulo 1"] },
              verification_state: "discovered",
              uncertainty: "media",
            },
          ],
        },
      ],
      warnings: [
        {
          code: "HIDDEN_CANDIDATES",
          message: "2 candidatos de baja utilidad se conservan en revisión.",
          severity: "info",
        },
      ],
      counts: { objects_total: 3, objects_visible: 1, objects_hidden: 2 },
    });

    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("knowledge-document-insight")).toBeInTheDocument()
    );
    expect(screen.getByText("El principito")).toBeInTheDocument();
    expect(
      screen.getByText(/¿Recuerdas\? —preguntó el principito/)
    ).toBeInTheDocument();
    expect(screen.getByText(/2 candidatos de baja utilidad/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Ver hallazgo y pasaje" })
    ).toHaveAttribute("href", "/knowledge/objects/obj-1");
  });
});
