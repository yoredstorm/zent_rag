import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FlowDrawer from "./FlowDrawer";

const SESSION = { token: "rag_sess_t", organizationId: "org-1", companyName: "Demo" };

const FLOW = {
  flow_version: 2,
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
  sql: null,
  generation: { model: "deepseek-v3.2", prompt_tokens: 900, completion_tokens: 80, ms: 700 },
  timings: { total_ms: 1450 },
  steps: [],
  sources: [{ title: "gerente.pdf", document_id: "doc-1", score: 0.91 }],
  fallbacks: [],
  events: [
    {
      id: "e-1",
      phase: "understanding",
      kind: "reasoning_classification",
      status: "ok",
      metrics: { reasoning: { shape: "SIMPLE_LOOKUP", is_complex: false } },
    },
    {
      id: "e-2",
      phase: "evidence",
      kind: "sources",
      status: "ok",
      metrics: { sources: 1 },
      technical: {
        items: [{ ref: "doc-1", title: "gerente.pdf", relevance: 0.91, status: "USED" }],
      },
    },
    {
      id: "e-3",
      phase: "generation",
      kind: "generation",
      status: "ok",
      duration_ms: 700,
      metrics: { total_tokens: 980, cost_usd: 0.0002 },
      technical: { model: "deepseek-v3.2" },
    },
    {
      id: "e-4",
      phase: "verification",
      kind: "grounding",
      status: "ok",
      metrics: { grounded: true, score: 0.9 },
    },
  ],
};

const SQL_FLOW = {
  ...FLOW,
  verdict: { decider: "Reglas", route: "SQL" },
  sql: {
    query: "SELECT COUNT(*) FROM ventas",
    rows: 3,
    truncated: false,
    tables: ["ventas"],
    ms: 250,
  },
  events: [
    ...FLOW.events,
    { id: "e-5", phase: "evidence", kind: "sql", status: "ok", metrics: { rows: 3 } },
  ],
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
  it("muestra la historia por defecto, con fases en lenguaje humano", () => {
    render(
      <FlowDrawer open onOpenChange={() => {}} flow={FLOW} role="admin" session={SESSION} />,
    );
    expect(screen.getByText("Ver flujo")).toBeTruthy();
    expect(screen.getByText("Respuesta completada")).toBeTruthy();
    expect(screen.getByText("1. Entendió la pregunta")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Historia" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Técnico" })).toBeTruthy();
  });

  it("no muestra razonamiento en una consulta directa (§57)", () => {
    render(
      <FlowDrawer open onOpenChange={() => {}} flow={FLOW} role="customer" session={SESSION} />,
    );
    expect(screen.queryByText(/Reconstruyó el escenario/)).toBeNull();
    expect(screen.queryByText(/Contrastó explicaciones/)).toBeNull();
  });

  it("mantiene el SQL visible solo para admin", () => {
    const { unmount } = render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={SQL_FLOW}
        role="admin"
        session={SESSION}
      />,
    );
    expect(screen.getByText("SQL ejecutado")).toBeTruthy();
    unmount();
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={SQL_FLOW}
        role="customer"
        session={SESSION}
      />,
    );
    expect(screen.queryByText("SQL ejecutado")).toBeNull();
  });

  it("carga el flujo por queryId e integra memoria y replay", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/flow")) return json({ flow: FLOW });
      if (String(url).includes("/impact")) {
        return json({
          query_id: "q-1",
          truncated: false,
          counts: { used: 1, created: 0, reinforced: 0, contradicted: 0, validated: 0 },
          used: [],
          created: [],
          reinforced: [],
          contradicted: [],
          validated: [],
        });
      }
      return json({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={null}
        role="admin"
        queryId="q-1"
        question="¿qué es Carrier Code?"
        session={SESSION}
      />,
    );
    await waitFor(() => expect(screen.getByText("Respuesta completada")).toBeTruthy());
    expect(screen.getByText(/Experiencia previa utilizada/)).toBeTruthy();
    expect(screen.getByText(/Comparar con Zent actual/)).toBeTruthy();
  });

  it("explica qué falló cuando no puede cargar el flujo", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "boom" }, 500)),
    );
    render(
      <FlowDrawer
        open
        onOpenChange={() => {}}
        flow={null}
        role="admin"
        queryId="q-404"
        session={SESSION}
      />,
    );
    await waitFor(() => expect(screen.getByText(/No se pudo cargar el flujo/)).toBeTruthy());
  });
});
