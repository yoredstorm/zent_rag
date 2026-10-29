import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgeExplorerPage from "./Explorer";
import type {
  KnowledgeObject,
  KnowledgeExplorerInsightPayload,
} from "../../lib/knowledgeModel";

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

function insightFixture(
  patch: Partial<KnowledgeExplorerInsightPayload> = {},
): KnowledgeExplorerInsightPayload {
  return {
    contract: "knowledge_explorer_insight/v2",
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
    counts: {
      objects_total: 3,
      objects_visible: 1,
      objects_hidden: 2,
      passages_available: 215,
      revisions: 2,
    },
    ...patch,
  };
}

function renderPage(path = "/knowledge/explorer") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <KnowledgeExplorerPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  fetchKnowledgeDomains.mockResolvedValue({ domains: [], count: 0 });
  fetchKnowledgeObjects.mockResolvedValue({ items: [], count: 0, total: 0 });
  fetchKnowledgeGraph.mockResolvedValue({
    nodes: [],
    edges: [],
    counts: { nodes: 0, edges: 0 },
    truncated: false,
  });
  fetchKnowledgeCorpora.mockResolvedValue({ corpora: [], count: 0 });
  fetchKnowledgeSources.mockResolvedValue({ sources: [] });
  fetchKnowledgeSourceInsight.mockResolvedValue(insightFixture());
});

afterEach(() => {
  localStorage.clear();
  fetchKnowledgeDomains.mockReset();
  fetchKnowledgeObjects.mockReset();
  fetchKnowledgeGraph.mockReset();
  fetchKnowledgeCorpora.mockReset();
  fetchKnowledgeSources.mockReset();
  fetchKnowledgeSourceInsight.mockReset();
});

describe("KnowledgeExplorerPage — modos excluyentes", () => {
  it("en vista por documento no dispara el listado técnico ni duplica contenido", async () => {
    fetchKnowledgeCorpora.mockResolvedValue({
      corpora: [{ id: "corpus-1", name: "Principal", slug: "principal" }],
      count: 1,
    });
    fetchKnowledgeSources.mockResolvedValue({
      sources: [
        {
          id: "src-1",
          name: "el_principito.pdf",
          type: "file",
          status: "indexed",
        },
      ],
    });

    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("knowledge-document-insight")).toBeInTheDocument(),
    );
    expect(screen.getByText("El principito")).toBeInTheDocument();
    expect(fetchKnowledgeObjects).not.toHaveBeenCalled();
    expect(screen.queryByTestId("technical-view-banner")).not.toBeInTheDocument();
    expect(
      screen.getByText(/1 hallazgos con evidencia/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/3 objetos canónicos históricos/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/215 pasajes recuperables/),
    ).toBeInTheDocument();
  });

  it("un documento histórico con 110 ocultos muestra cero temas y una ruta a pasajes", async () => {
    fetchKnowledgeCorpora.mockResolvedValue({
      corpora: [{ id: "corpus-1", name: "Principal", slug: "principal" }],
      count: 1,
    });
    fetchKnowledgeSources.mockResolvedValue({
      sources: [
        {
          id: "src-1",
          name: "el_principito.pdf",
          type: "file",
          status: "indexed",
        },
      ],
    });
    fetchKnowledgeSourceInsight.mockResolvedValue(
      insightFixture({
        topics: [],
        summary:
          "Solo se identificaron secciones y pasajes; no podemos afirmar temas con certeza.",
        counts: {
          objects_total: 110,
          objects_visible: 0,
          objects_hidden: 110,
          passages_available: 215,
          revisions: 110,
        },
      }),
    );

    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("document-insight-empty")).toBeInTheDocument(),
    );
    expect(screen.getByText("No hay temas verificables todavía")).toBeInTheDocument();
    expect(
      screen.getAllByText(/110 objetos canónicos históricos/).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: "Abrir fuente y pasajes" }),
    ).toHaveAttribute("href", "/knowledge/sources/src-1");
    expect(
      screen.getByRole("link", { name: "Preguntar sobre este documento" }),
    ).toHaveAttribute(
      "href",
      "/knowledge/ask?corpus=corpus-1&source_ids=src-1",
    );
    expect(fetchKnowledgeObjects).not.toHaveBeenCalled();
    expect(screen.queryByText("Record 4")).not.toBeInTheDocument();
  });

  it("al cambiar a todos los hallazgos carga la vista técnica y resetea filtros incompatibles", async () => {
    const user = userEvent.setup();
    renderPage("/knowledge/explorer?mode=document&type=business_rule&q=algo");

    await user.click(screen.getByRole("button", { name: "Todos los hallazgos" }));

    await waitFor(() => expect(fetchKnowledgeObjects).toHaveBeenCalled());
    expect(fetchKnowledgeObjects).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: undefined, q: undefined, exclude_hidden: true }),
    );
    expect(await screen.findByTestId("technical-view-banner")).toBeInTheDocument();
    expect(screen.getByText("Vista técnica")).toBeInTheDocument();
    expect(screen.queryByTestId("knowledge-document-insight")).not.toBeInTheDocument();
  });

  it("muestra temas solo en la vista avanzada y filtra por tema", async () => {
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

    const user = userEvent.setup();
    renderPage("/knowledge/explorer?mode=all&domain=ATPCO");

    await waitFor(() =>
      expect(screen.getByTestId("knowledge-topics")).toBeInTheDocument(),
    );
    expect(screen.getByText("Temas de ATPCO")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Regla de negocio/ }));
    await waitFor(() =>
      expect(fetchKnowledgeObjects).toHaveBeenLastCalledWith(
        expect.objectContaining({ domain: "ATPCO", type: "business_rule" }),
      ),
    );
  });

  it("solo ofrece revisión de ocultos a un rol autorizado", async () => {
    const user = userEvent.setup();
    localStorage.setItem("rag_portal_org", "org-1");
    localStorage.setItem("rag_portal_permissions", JSON.stringify(["knowledge:write"]));
    renderPage("/knowledge/explorer?mode=all");

    await waitFor(() =>
      expect(screen.getByTestId("technical-view-banner")).toBeInTheDocument(),
    );
    const toggle = screen.getByLabelText("Incluir ocultos en revisión");
    expect(toggle).toBeInTheDocument();

    await user.click(toggle);
    await waitFor(() =>
      expect(fetchKnowledgeObjects).toHaveBeenLastCalledWith(
        expect.objectContaining({ exclude_hidden: false }),
      ),
    );
  });

  it("en la vista técnica lista objetos canónicos con estado humano", async () => {
    fetchKnowledgeObjects.mockResolvedValue({
      items: [objectFixture()],
      count: 1,
      total: 1,
    });

    renderPage("/knowledge/explorer?mode=all");

    await waitFor(() => expect(screen.getByText("Record 4")).toBeInTheDocument());
    expect(screen.getByText("1 de 1 objetos")).toBeInTheDocument();
    expect(screen.getByText("Inferido con evidencia")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Record 4/ }),
    ).toHaveAttribute("href", "/knowledge/objects/obj-1");
  });

  it("muestra la etiqueta humana del estado, no el código interno", async () => {
    fetchKnowledgeCorpora.mockResolvedValue({
      corpora: [{ id: "corpus-1", name: "Principal", slug: "principal" }],
      count: 1,
    });
    fetchKnowledgeSources.mockResolvedValue({
      sources: [
        { id: "src-1", name: "doc.pdf", type: "file", status: "indexed" },
      ],
    });

    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("knowledge-document-insight")).toBeInTheDocument(),
    );
    expect(screen.getByText("Detectado, sin verificar")).toBeInTheDocument();
    expect(screen.queryByText("discovered")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Confianza de clasificación 71% \(no mide comprensión\)/),
    ).toBeInTheDocument();
  });
});
