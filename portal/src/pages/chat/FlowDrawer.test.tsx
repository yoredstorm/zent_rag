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

  it("flujo de agente sin JEV: sin guiones y avisa que JEV no intervino", () => {
    const agentFlow = {
      method: "agent",
      verdict: { decider: "Agente", route: "Herramientas" },
      decision: {
        evaluated: true,
        provider: "agent",
        capability: null,
        confidence: 0,
        mode: "ReAct",
        acting: true,
      },
      jev: { used: false },
      generation: { total_tokens: 232, ms: 8927, cost: 0.0012, model: "deepseek-v3.2" },
      steps: [
        { name: "Modelo (razonamiento)", status: "ok", ms: 2761, detail: "tool" },
        { name: "search_knowledge", status: "ok", ms: 1006, detail: "tool_call" },
      ],
      timings: { total_ms: 11017 },
      sources: [],
      fallbacks: [],
    };
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={agentFlow}
        role="admin"
        session={SESSION}
      />,
    );
    expect(screen.getByText("Decidió Agente")).toBeInTheDocument();
    expect(screen.getByText("JEV no intervino en este run")).toBeInTheDocument();
    expect(screen.getByText("ReAct")).toBeInTheDocument();
    expect(screen.getByText("232")).toBeInTheDocument();
    expect(screen.getByText("Costo")).toBeInTheDocument();
    expect(screen.getByText("Costo / 1k tokens")).toBeInTheDocument();
    expect(screen.queryByText("Mejor score")).toBeNull();
    expect(screen.queryByText("Embedding")).toBeNull();
    expect(screen.queryByText("Búsqueda")).toBeNull();
  });

  it("flujo con verificador JEV muestra score y veredicto", () => {
    const gatedFlow = {
      method: "agent",
      verdict: { decider: "Agente", route: "Herramientas" },
      decision: {
        evaluated: true,
        provider: "agent",
        confidence: 0,
        mode: "ReAct + JEV",
        acting: true,
      },
      jev: { used: true, score: 0.9, verdict: "approve", grounded: true, complete: true },
      generation: { total_tokens: 1901, ms: 8800, cost: 0.0012, model: "deepseek" },
      steps: [
        { name: "JEV elige herramienta", status: "ok", ms: 790, detail: "search_knowledge · score 0.55" },
        { name: "JEV verifica respuesta", status: "ok", ms: 850, detail: "respaldada · completa · calidad 3/3 · aprobada" },
      ],
      timings: { total_ms: 11000, generation_ms: 8800 },
      sources: [],
      fallbacks: [],
    };
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={gatedFlow}
        role="admin"
        session={SESSION}
      />,
    );
    expect(screen.getByText("JEV intervino en este run")).toBeInTheDocument();
    expect(screen.getByText("Score JEV")).toBeInTheDocument();
    expect(screen.getByText(/0.90 · aprobada/)).toBeInTheDocument();
    expect(screen.getByText("JEV verifica respuesta")).toBeInTheDocument();
  });

  it("trae el flujo desde el servidor si el mensaje no lo tiene", async () => {    const fetchMock = vi.fn((input: RequestInfo | URL) => {
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

  it("pide el impacto de memoria al abrir, aunque el flujo ya venga en el mensaje", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/memory/queries/")) {
        return Promise.resolve(
          json({
            query_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            truncated: false,
            counts: { used: 0, created: 0, reinforced: 0, contradicted: 0, validated: 0 },
            used: [],
            created: [],
            reinforced: [],
            contradicted: [],
            validated: [],
          }),
        );
      }
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={FLOW}
        role="customer"
        queryId="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        session={SESSION}
      />,
    );
    expect(await screen.findByText("Esta respuesta no usó ni creó memoria.")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("/api/v1/memory/queries/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/impact"),
      ),
    ).toBe(true);
    expect(screen.queryByText("SQL ejecutado")).toBeNull();
  });
});
