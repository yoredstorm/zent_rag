// =============================================================================
// Knowledge Map — tests (FASE 33F)
// =============================================================================
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../auth";
import { ToastProvider } from "../../Toast";
import {
  computeLayout,
  type GraphEdge,
  type GraphNode,
} from "../../lib/knowledgeGraph";
import KnowledgeMapPage from "./Map";

const SOURCE = {
  source_id: "src-1",
  connector_id: "conn-1",
  engine: "postgres",
  connectivity: "healthy",
  phase: "COMPLETED",
  last_learning_at: "2026-09-10T10:00:00Z",
  scan_error: null,
  knowledge: { overall: 82, gate: "NEEDS_INPUT" },
  tables: { analyzed: 42, total: 42 },
  fields: { understood: 352, total: 387, documented: 120 },
  relationships: { discovered: 3, confirmed: 2 },
  pending_questions: 1,
  active_run: null,
};

function node(overrides: Partial<GraphNode> & { id: string; label: string; type: GraphNode["type"] }): GraphNode {
  return {
    description: "",
    confidence: 0.9,
    provenance: "INFERRED",
    status: "draft",
    source_id: "src-1",
    source_name: "postgres",
    last_learned_at: null,
    validation_state: "unvalidated",
    metadata: {},
    ...overrides,
  };
}

const GRAPH_NODES: GraphNode[] = [
  node({
    id: "datasource:src-1",
    type: "datasource",
    label: "postgres · src-1",
    provenance: "OBSERVED",
    validation_state: "validated",
  }),
  node({
    id: "entity:ent-1",
    type: "entity",
    label: "Customer",
    confidence: 0.94,
    provenance: "INFERRED",
    metadata: { table: "erp.TBL_CUST", fields_total: 12, fields_understood: 10 },
  }),
  node({
    id: "entity:ent-2",
    type: "entity",
    label: "Order",
    confidence: 0.88,
    provenance: "OBSERVED",
    status: "confirmed",
    validation_state: "validated",
    metadata: { table: "erp.TBL_ORD", fields_total: 8, fields_understood: 6 },
  }),
  node({
    id: "field:field-1",
    type: "field",
    label: "CustomerCode",
    metadata: { role: "IDENTIFIER" },
  }),
  node({
    id: "rule:rule-1",
    type: "rule",
    label: "Cliente activo",
    provenance: "APPROVED",
    validation_state: "validated",
  }),
];

const GRAPH_EDGES: GraphEdge[] = [
  {
    id: "relationship:rel-1",
    type: "relationship",
    from: "entity:ent-2",
    to: "entity:ent-1",
    label: "places",
    confidence: 0.98,
    provenance: "OBSERVED",
    status: "confirmed",
    cardinality: "N:1",
    evidence: ["FK física declarada"],
    evidence_detail: [],
    source_id: "src-1",
    last_learned_at: "2026-09-10T10:00:00Z",
  },
  {
    id: "edge-has-field",
    type: "has_field",
    from: "entity:ent-1",
    to: "field:field-1",
    label: "has field",
    confidence: 0.9,
    provenance: "INFERRED",
    status: "suggested",
    cardinality: null,
    evidence: [],
    evidence_detail: [],
    source_id: "src-1",
    last_learned_at: null,
  },
];

const GRAPH = {
  nodes: GRAPH_NODES,
  edges: GRAPH_EDGES,
  counts: { nodes: 5, edges: 2, by_type: { entity: 2 } },
  truncated: false,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setupFetch(options: { graph?: unknown; empty?: boolean } = {}) {
  const calls: string[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/knowledge/learning/sources"))
      return Promise.resolve(json([SOURCE]));
    if (url.includes("/knowledge/learning/graph"))
      return Promise.resolve(json(options.graph ?? GRAPH));
    if (url.includes("/knowledge/learning/questions"))
      return Promise.resolve(
        json({
          questions: [{ id: "q1", title: '¿Qué significa CUST_STS = "A"?', status: "pending" }],
          count: 1,
          pending: 1,
          blocking: 1,
        })
      );
    if (url.includes("/auth/me"))
      return Promise.resolve(
        json({
          organization_id: "org-1",
          company_name: "Acme",
          email: "a@b.cl",
          roles: ["owner"],
          permissions: [],
        })
      );
    return Promise.resolve(json({ detail: `not mocked: ${url}` }, 500));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

async function renderMap(options: Parameters<typeof setupFetch>[0] = {}) {
  const harness = setupFetch(options);
  window.localStorage.setItem("rag_portal_token", "rag_sess_t");
  window.localStorage.setItem("rag_portal_org", "org-1");
  window.localStorage.setItem("rag_portal_company", "Acme");
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/knowledge/map"]}>
      <AuthProvider>
        <ToastProvider>
          <KnowledgeMapPage />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>
  );
  return { user, ...harness };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("computeLayout", () => {
  it("coloca todos los nodos con coordenadas finitas", () => {
    const positioned = computeLayout(GRAPH_NODES, GRAPH_EDGES, { iterations: 5 });
    expect(positioned).toHaveLength(GRAPH_NODES.length);
    for (const item of positioned) {
      expect(Number.isFinite(item.x)).toBe(true);
      expect(Number.isFinite(item.y)).toBe(true);
    }
    const ids = new Set(positioned.map((item) => item.id));
    for (const edge of GRAPH_EDGES) {
      expect(ids.has(edge.from)).toBe(true);
      expect(ids.has(edge.to)).toBe(true);
    }
  });

  it("coloca entidades en órbita central y datos en columna izquierda", () => {
    const positioned = computeLayout(GRAPH_NODES, GRAPH_EDGES, { iterations: 2 });
    const entities = positioned.filter((item) => item.type === "entity");
    const datasource = positioned.find((item) => item.id === "datasource:src-1");
    expect(entities.length).toBeGreaterThanOrEqual(2);
    expect(datasource).toBeTruthy();
    const entityX = entities.map((item) => item.x);
    expect(Math.max(...entityX) - Math.min(...entityX)).toBeGreaterThan(50);
  });
});

describe("Knowledge Map", () => {
  it("muestra la vista vacía sin nodos", async () => {
    await renderMap({ graph: { nodes: [], edges: [], counts: {}, truncated: false } });
    expect(await screen.findByText("Mapa vacío")).toBeInTheDocument();
  });

  it("renderiza nodos y aristas con filtros", async () => {
    await renderMap();
    expect(await screen.findByTestId("graph-canvas")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("graph-node-entity:ent-1")).toBeInTheDocument();
      expect(screen.getByTestId("graph-node-entity:ent-2")).toBeInTheDocument();
      expect(screen.getByTestId("graph-node-datasource:src-1")).toBeInTheDocument();
    });
    // Campos ocultos por defecto; al activarlos aumenta el conteo visible.
    const counts = screen.getByText(/\d+ de \d+ nodos/);
    expect(counts.textContent).toContain("de");
    await userEvent.click(screen.getByTestId("map-show-fields"));
    await waitFor(() => {
      expect(screen.getByText(/\d+ de \d+ nodos/).textContent).toContain("5");
    });
    // Quitar un tipo reduce el conteo.
    await userEvent.click(screen.getByTestId("map-type-rule"));
    await waitFor(() => {
      expect(screen.getByText(/\d+ de \d+ nodos/).textContent).toContain("4");
    });
  });

  it("busca y reduce los nodos visibles", async () => {
    const { user } = await renderMap();
    await screen.findByTestId("graph-node-entity:ent-1");
    const search = screen.getByTestId("map-search");
    await user.type(search, "Order");
    await waitFor(() => {
      const counts = screen.getByText(/\d+ de \d+ nodos/);
      expect(counts.textContent).toContain("1");
    });
  });

  it("selecciona un nodo y muestra su detalle real", async () => {
    const { user } = await renderMap();
    await screen.findByTestId("graph-node-entity:ent-2");
    await user.click(screen.getByTestId("graph-node-entity:ent-2"));
    const detail = await screen.findByTestId("node-detail");
    expect(detail).toHaveTextContent("Order");
    expect(detail).toHaveTextContent("88%");
    expect(detail).toHaveTextContent("OBSERVED");
    expect(detail).toHaveTextContent("erp.TBL_ORD");
    expect(detail).toHaveTextContent("Customer");
    expect(detail).toHaveTextContent("places");
    expect(detail).toHaveTextContent("N:1");
    // Preguntas abiertas de la entidad (fetch real).
    expect(await screen.findByText('¿Qué significa CUST_STS = "A"?')).toBeInTheDocument();
  });

  it("acerca y reinicia la vista", async () => {
    const { user } = await renderMap();
    await screen.findByTestId("graph-canvas");
    await user.click(screen.getByTestId("map-zoom-in"));
    await user.click(screen.getByTestId("map-zoom-out"));
    await user.click(screen.getByTestId("map-reset"));
    expect(screen.getByTestId("graph-canvas")).toBeInTheDocument();
  });
});