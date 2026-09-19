import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FlowDrawer from "./FlowDrawer";

const SESSION = { token: "rag_sess_t", organizationId: "org-1", companyName: "Demo" };

const FLOW = {
  query_id: "q-1",
  method: "rag",
  status: "completed",
  verdict: { decider: "JEV", route: "Documentos" },
  decision: {
    evaluated: true,
    provider: "jev",
    capability: "knowledge.answer",
    confidence: 0.93,
    fallback_used: false,
    acting: true,
    mode: "jev",
    jev_used: true,
    ms: 120,
  },
  retrieval: { chunks: 2, top_score: 0.91, ms: 340 },
  sql: null,
  evidence: { sufficient: true, score: 0.8, ms: 60 },
  grounding: null,
  generation: { model: "deepseek-v3.2", prompt_tokens: 900, completion_tokens: 80, ms: 700 },
  timings: {
    decision_ms: 120,
    retrieval_ms: 340,
    embedding_ms: 45,
    generation_ms: 700,
    total_ms: 1450,
  },
  steps: [
    { name: "Decisión", status: "ok", ms: 120, detail: "jev · knowledge.answer" },
    { name: "Búsqueda", status: "ok", ms: 340, detail: "2 fragmentos" },
    { name: "Respuesta", status: "ok", ms: 700, detail: "deepseek-v3.2" },
  ],
  sources: [{ title: "gerente.pdf", document_id: "doc-1", score: 0.91 }],
  fallbacks: [],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FlowDrawer", () => {
  it("muestra veredicto, pasos con ms, SQL y fuentes al admin", () => {
    const sqlFlow = {
      ...FLOW,
      verdict: { decider: "Reglas", route: "SQL" },
      sql: { query: "SELECT COUNT(*) FROM ventas", rows: 3, truncated: false, tables: ["ventas"], ms: 250 },
    };
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={sqlFlow}
        role="admin"
        session={SESSION}
      />,
    );
    expect(screen.getByText("Decidió Reglas")).toBeInTheDocument();
    expect(screen.getByText("SQL")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getAllByText(/1450 ms/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Decisión").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Búsqueda").length).toBeGreaterThan(0);
    expect(screen.getByText("SELECT COUNT(*) FROM ventas")).toBeInTheDocument();
    expect(screen.getByText("gerente.pdf")).toBeInTheDocument();
  });

  it("oculta el SQL al customer", () => {
    const sqlFlow = {
      ...FLOW,
      sql: { query: "SELECT secret FROM tabla", rows: 1, ms: 10 },
    };
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={sqlFlow}
        role="customer"
        session={SESSION}
      />,
    );
    expect(screen.queryByText("SELECT secret FROM tabla")).toBeNull();
    expect(screen.queryByText("SQL ejecutado")).toBeNull();
  });

  it("trae el flujo desde el servidor si el mensaje no lo tiene", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/rag/queries/q-1/flow")) {
        return Promise.resolve(json({ flow: FLOW }));
      }
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onFetched = vi.fn();
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={null}
        role="admin"
        queryId="q-1"
        session={SESSION}
        onFetched={onFetched}
      />,
    );
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/v1/rag/queries/q-1/flow"))).toBe(true);
    });
    expect(await screen.findByText("Decidió JEV")).toBeInTheDocument();
    expect(onFetched).toHaveBeenCalled();
  });
});
