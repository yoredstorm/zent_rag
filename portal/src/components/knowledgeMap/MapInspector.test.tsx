import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MapInspector } from "./MapInspector";
import type { KnowledgeObjectDetail } from "../../lib/knowledgeModel";

const fetchKnowledgeObject = vi.hoisted(() => vi.fn());
const fetchKnowledgeConflicts = vi.hoisted(() => vi.fn());

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return { ...actual, fetchKnowledgeObject, fetchKnowledgeConflicts };
});

const now = new Date().toISOString();

const DETAIL: KnowledgeObjectDetail = {
  object: {
    id: "obj-1",
    type: "concept",
    name: "Record 4",
    display_name: "Record 4",
    description: "Registro de control de renumbering.",
    domain: "ATPCO",
    status: "inferred",
    provenance: "INFERRED",
    confidence: 0.82,
    confidence_label: "alta",
    source_of_truth: null,
    source_id: "src-1",
    authority_level: null,
    evidence_count: 26,
    assertion_count: 3,
    verified_at: null,
    freshness_at: null,
    last_seen_at: null,
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
      confidence_detail: {
        components: {
          evidence_strength: 0.9,
          source_reliability: 0.8,
          corroboration: 0.7,
          semantic_certainty: 0.6,
          freshness: 1,
        },
      },
      status: "candidate",
      provenance: "INFERRED",
      method: "compiler",
      source_id: "src-1",
      evidence_count: 2,
      version: 1,
      verified_at: null,
      stale_at: null,
      valid_from: "2025-01-01T00:00:00+00:00",
      valid_to: null,
      created_at: now,
      updated_at: now,
    },
  ],
  evidence: [
    {
      id: "ev-1",
      source_id: "src-1",
      document_id: "doc-1",
      page: 7,
      section_path: ["Record 4"],
      locator: "p7",
      table_reference: null,
      database_reference: null,
      excerpt: "Record 4 controla el renumbering.",
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
      version: 2,
      change_kind: "updated",
      snapshot: {},
      changed_by: null,
      reason: "Nueva versión 2026",
      created_at: now,
    },
  ],
  lineage: { physical_refs: [], lineage: [], count: 0 },
  impact: { object: "Record 4", dependents: [], count: 0 },
  questions: [],
};

function renderInspector() {
  return render(
    <MemoryRouter>
      <MapInspector objectId="obj-1" />
    </MemoryRouter>
  );
}

afterEach(() => {
  fetchKnowledgeObject.mockReset();
  fetchKnowledgeConflicts.mockReset();
  vi.unstubAllGlobals();
});

describe("MapInspector", () => {
  it("muestra la ficha, strength explicable y relaciones", async () => {
    fetchKnowledgeObject.mockResolvedValue(DETAIL);
    fetchKnowledgeConflicts.mockResolvedValue({ conflicts: [], count: 0 });
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ name: "Rec4_dapp_C.pdf" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        )
      )
    );

    const user = userEvent.setup();
    renderInspector();

    await waitFor(() => expect(screen.getByText("Record 4")).toBeInTheDocument());
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Evidencia" })).toBeInTheDocument();
    expect(screen.getByText("sin conflictos")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Relaciones" }));
    expect(screen.getByText("modifies")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Evidencia" }));
    const path = await screen.findByTestId("evidence-path");
    expect(path).toHaveTextContent("Rec4_dapp_C.pdf");
    expect(path).toHaveTextContent("Página 7");

    await user.click(screen.getByRole("button", { name: "Timeline" }));
    expect(await screen.findByTestId("knowledge-timeline")).toHaveTextContent(
      "Nueva versión 2026"
    );
  });

  it("sin objeto invita a seleccionar un nodo", () => {
    render(
      <MemoryRouter>
        <MapInspector objectId={null} />
      </MemoryRouter>
    );
    expect(
      screen.getByText(/Selecciona un nodo para inspeccionar/)
    ).toBeInTheDocument();
  });
});
