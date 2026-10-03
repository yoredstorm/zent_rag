import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeObjectPage from "./ObjectView";
import type { KnowledgeObjectDetail } from "../../lib/knowledgeModel";

const fetchKnowledgeObject = vi.hoisted(() => vi.fn());
const fetchKnowledgeConflicts = vi.hoisted(() => vi.fn());
const verifyKnowledgeObject = vi.hoisted(() => vi.fn());
const verifyKnowledgeAssertion = vi.hoisted(() => vi.fn());

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return {
    ...actual,
    fetchKnowledgeObject,
    fetchKnowledgeConflicts,
    verifyKnowledgeObject,
    verifyKnowledgeAssertion,
  };
});

vi.mock("../../auth", () => ({
  useAuth: () => ({
    session: {
      token: "rag_sess_t",
      organizationId: "org-1",
      roles: ["owner"],
      permissions: ["knowledge:read", "knowledge:validate"],
    },
  }),
}));

function detailFixture(): KnowledgeObjectDetail {
  const now = new Date().toISOString();
  return {
    object: {
      id: "obj-1",
      type: "concept",
      name: "Record 4",
      display_name: "Record 4",
      description: "ZENT entiende Record 4 como el registro de control de renumbering.",
      domain: "ATPCO",
      status: "inferred",
      provenance: "INFERRED",
      confidence: 0.82,
      confidence_label: "alta",
      source_of_truth: "Rec4_dapp_C.pdf",
      source_id: "src-1",
      authority_level: "primary",
      evidence_count: 26,
      assertion_count: 5,
      verified_at: null,
      freshness_at: null,
      last_seen_at: now,
      metadata: {},
      created_at: now,
      updated_at: now,
    },
    edges: [
      {
        id: "edge-1",
        subject_id: "obj-1",
        subject_name: "Record 4",
        predicate: "modifies",
        object_id: "obj-2",
        object_name: "Record 2",
        direction: "out",
        relationship_type: "business",
        confidence: 0.8,
        status: "inferred",
        provenance: "INFERRED",
        evidence: [],
        metadata: {},
      },
    ],
    assertions: [
      {
        id: "assert-1",
        subject_id: "obj-1",
        subject_label: "Record 4",
        predicate: "has_field",
        object_id: null,
        object_value: "Sequence Number",
        assertion_type: "structural",
        confidence: 0.8,
        confidence_detail: {},
        status: "candidate",
        provenance: "INFERRED",
        method: "compiler",
        source_id: null,
        evidence_count: 2,
        version: 1,
        verified_at: null,
        stale_at: null,
        created_at: now,
        updated_at: now,
      },
    ],
    evidence: [
      {
        id: "ev-1",
        source_id: "src-1",
        document_id: "doc-1",
        page: 12,
        section_path: ["Record 4"],
        locator: "p12",
        table_reference: null,
        database_reference: null,
        excerpt: "Record 4 controla el renumbering de categorías.",
        evidence_type: "document",
        strength: 0.9,
        authority: "primary",
        retrieval_score: null,
        content_hash: "hash",
        created_at: now,
      },
    ],
    versions: [
      {
        version: 1,
        change_kind: "created",
        snapshot: {},
        changed_by: null,
        reason: "Compilado desde Rec4_dapp_C.pdf",
        created_at: now,
      },
    ],
    lineage: { physical_refs: [], lineage: [], count: 0 },
    impact: {
      object: "Record 4",
      dependents: [
        {
          kind: "object",
          id: "obj-2",
          type: "concept",
          name: "Record 2",
          via: "modifies",
          status: "inferred",
          confidence: 0.7,
        },
      ],
      count: 1,
    },
    questions: [],
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/knowledge/objects/obj-1"]}>
      <Routes>
        <Route path="/knowledge/objects/:objectId" element={<KnowledgeObjectPage />} />
      </Routes>
    </MemoryRouter>
  );
}

afterEach(() => {
  fetchKnowledgeObject.mockReset();
  fetchKnowledgeConflicts.mockReset();
  verifyKnowledgeObject.mockReset();
});

describe("KnowledgeObjectPage", () => {
  it("muestra el objeto con sus relaciones, hechos y evidencia", async () => {
    fetchKnowledgeObject.mockResolvedValue(detailFixture());
    fetchKnowledgeConflicts.mockResolvedValue({ conflicts: [], count: 0 });

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("Record 4")).toBeInTheDocument());
    expect(screen.getByText(/ZENT entiende Record 4/)).toBeInTheDocument();
    expect(screen.getByText(/26 evidencias/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Relaciones" }));
    expect(await screen.findByText("modifies")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Hechos" }));
    expect(await screen.findByText("Sequence Number")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Evidencia" }));
    expect(
      await screen.findByText("Record 4 controla el renumbering de categorías.")
    ).toBeInTheDocument();
    const sourceLinks = screen.getAllByRole("link", { name: /Ver fuente/ });
    expect(
      sourceLinks.some(
        (link) => link.getAttribute("href") === "/knowledge/sources/src-1"
      )
    ).toBe(true);
  });

  it("permite verificar el objeto y recarga el detalle", async () => {
    fetchKnowledgeObject.mockResolvedValue(detailFixture());
    fetchKnowledgeConflicts.mockResolvedValue({ conflicts: [], count: 0 });
    verifyKnowledgeObject.mockResolvedValue({});

    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Record 4")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Verificar objeto" }));
    await waitFor(() => expect(verifyKnowledgeObject).toHaveBeenCalledWith("obj-1"));
    expect(await screen.findByText("Objeto verificado.")).toBeInTheDocument();
  });
});
