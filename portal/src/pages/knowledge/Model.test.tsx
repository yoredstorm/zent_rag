import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeModelPage from "./Model";
import type { KnowledgeObjectDetail } from "../../lib/knowledgeModel";

const fetchers = vi.hoisted(() => ({
  fetchKnowledgeObjects: vi.fn(),
  fetchKnowledgeObject: vi.fn(),
  fetchKnowledgeGraph: vi.fn(),
  verifyKnowledgeObject: vi.fn(),
}));

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return { ...actual, ...fetchers };
});

const OBJECT = {
  id: "obj-1",
  type: "entity",
  name: "Customer",
  display_name: "Cliente",
  description: "Persona que compra",
  domain: "Ventas",
  status: "inferred",
  provenance: "INFERRED",
  confidence: 0.9,
  confidence_label: "high",
  source_of_truth: "erp.customers",
  source_id: "src-1",
  authority_level: "high",
  evidence_count: 2,
  assertion_count: 1,
  verified_at: null,
  freshness_at: null,
  last_seen_at: null,
  metadata: {},
  created_at: null,
  updated_at: null,
} as const;

const DETAIL: KnowledgeObjectDetail = {
  object: { ...OBJECT },
  edges: [
    {
      id: "edge-1",
      subject_id: "obj-1",
      subject_name: "Customer",
      object_id: "obj-2",
      object_name: "Order",
      predicate: "references",
      relationship_type: "business",
      confidence: 0.99,
      status: "verified",
      provenance: "APPROVED",
      evidence: [],
      metadata: {},
      direction: "out",
    },
  ],
  assertions: [
    {
      id: "assert-1",
      subject_id: "obj-1",
      subject_label: "Customer",
      predicate: "mapped_to_table",
      object_id: null,
      object_value: "customers",
      assertion_type: "fact",
      confidence: 0.9,
      confidence_detail: {},
      status: "candidate",
      provenance: "OBSERVED",
      method: "schema",
      source_id: null,
      evidence_count: 1,
      version: 1,
      verified_at: null,
      stale_at: null,
      created_at: null,
      updated_at: null,
    },
  ],
  evidence: [
    {
      id: "ev-1",
      source_id: "src-1",
      document_id: null,
      page: null,
      section_path: [],
      locator: "catalog://entity/Customer",
      table_reference: "erp.customers",
      database_reference: null,
      excerpt: "La entidad Customer mapea a erp.customers.",
      evidence_type: "schema",
      strength: 0.95,
      authority: "high",
      retrieval_score: null,
      content_hash: "abc",
      created_at: null,
    },
  ],
  versions: [],
  lineage: { physical_refs: [], lineage: [], count: 0 },
  impact: {
    object: "obj-1",
    dependents: [
      { kind: "agent", id: "agent-1", type: "agent", name: "Sales Agent", via: "source_reference" },
    ],
    count: 1,
  },
  questions: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/knowledge/model"]}>
      <KnowledgeModelPage />
    </MemoryRouter>
  );
}

afterEach(() => {
  Object.values(fetchers).forEach((fn) => fn.mockReset());
});

describe("KnowledgeModelPage", () => {
  it("explora objetos y abre el detalle con evidencia", async () => {
    fetchers.fetchKnowledgeObjects.mockResolvedValue({
      items: [OBJECT],
      count: 1,
      total: 1,
    });
    fetchers.fetchKnowledgeObject.mockResolvedValue(DETAIL);
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Customer")).toBeInTheDocument());
    await user.click(screen.getByText("Customer"));

    await waitFor(() =>
      expect(screen.getByText("La entidad Customer mapea a erp.customers.")).toBeInTheDocument()
    );
    expect(screen.getByText(/catalog:\/\/entity\/Customer/)).toBeInTheDocument();
    expect(screen.getByText("Sales Agent")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verificar" })).toBeEnabled();
  });

  it("un error de API se muestra como error, nunca como 0 objetos", async () => {
    fetchers.fetchKnowledgeObjects.mockRejectedValue(new Error("db down"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/db down/)).toBeInTheDocument());
    expect(screen.queryByText(/0 de 0 objetos/)).toBeNull();
  });

  it("verificar llama a la API y refleja el estado verificado", async () => {
    fetchers.fetchKnowledgeObjects.mockResolvedValue({
      items: [OBJECT],
      count: 1,
      total: 1,
    });
    fetchers.fetchKnowledgeObject.mockResolvedValue(DETAIL);
    fetchers.verifyKnowledgeObject.mockResolvedValue({
      ...OBJECT,
      status: "verified",
      provenance: "APPROVED",
    });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Customer")).toBeInTheDocument());
    await user.click(screen.getByText("Customer"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Verificar" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Verificar" }));

    await waitFor(() => expect(fetchers.verifyKnowledgeObject).toHaveBeenCalledWith("obj-1"));
    await waitFor(() => expect(screen.getByText("Objeto verificado.")).toBeInTheDocument());
  });
});
