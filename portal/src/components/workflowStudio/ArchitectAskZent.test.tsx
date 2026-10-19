import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArchitectAskZent } from "./ArchitectAskZent";
import type { ArchitectProposal } from "./workflowArchitect";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));
const NAVIGATE = vi.hoisted(() => vi.fn());

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => NAVIGATE };
});

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const BASE: ArchitectProposal = {
  session_id: "ds_test",
  state: "DRAFT_READY",
  planner: { version: "architect/1.2.0", provider: "FakeProvider", model: "fake-1", source: "llm" },
  phases: [
    { name: "discovery", duration_ms: 3 },
    { name: "intent", duration_ms: 10 },
    { name: "planning", duration_ms: 20 },
    { name: "validation", duration_ms: 2 },
    { name: "compilation", duration_ms: 4 },
    { name: "readiness", duration_ms: 1 },
  ],
  fallback: null,
  plan_hash: "a".repeat(64),
  publishable: true,
  blockers: [],
  source: "llm",
  intent: { goal: "Aviso de stock" },
  plan: { goal: "Aviso de stock", steps: [{ id: "t", type: "trigger_event" }] },
  issues: [],
  preview: [
    { kind: "when", step_id: "t", text: "Cuando ocurra inventory.stock.low." },
    { kind: "if", step_id: "d", text: "¿El stock es menor que 10?" },
    { kind: "then", step_id: "n", text: "Avisar a Compras." },
    { kind: "then", step_id: "m", text: "Avisar al gerente." },
  ],
  graph: {
    workflow_version: 2,
    nodes: [
      { id: "t", type: "trigger_event" },
      { id: "d", type: "condition" },
      { id: "n", type: "notify" },
      { id: "m", type: "notify" },
    ],
    edges: [
      { from_node: "t", from_port: "out", to_node: "d" },
      { from_node: "d", from_port: "then", to_node: "n" },
      { from_node: "d", from_port: "else", to_node: "m" },
    ],
    entrypoints: ["t"],
  },
  cost: { per_run: 0.02, monthly: 0.6, calls_per_run: 1, ai_calls_per_run: 0, currency: "PEN" },
  assumptions: [],
  questions: [],
  clarifications: [],
  requirements: [],
  readiness: { ready: true, passed: 5, warnings: 0, errors: 0, total: 5, checks: [] },
  capability_snapshot: {
    snapshot_hash: "c".repeat(64),
    generated_at: "2026-10-19T00:00:00Z",
    counts: { capabilities: 63, resources: 3, events: 37 },
    coverage: { total_capabilities: 63, business_capabilities: 34, business_complete: 25, business_completeness: 0.7353 },
  },
  simulation: null,
  matches: [
    {
      need: "buscar productos",
      capability_ref: "catalog.products.search",
      version: 1,
      reason: "Cubre la búsqueda del catálogo.",
      availability: "AVAILABLE",
      alternatives: ["inventory.stock.get"],
    },
  ],
  trace: {
    path: ["NECESIDAD", "BÚSQUEDA", "INSPECCIÓN", "SELECCIÓN", "PLAN", "VALIDACIÓN", "REPARACIÓN"],
    stages: [
      { name: "UNDERSTAND", duration_ms: 10 },
      { name: "BÚSQUEDA", duration_ms: 4 },
      { name: "VALIDACIÓN", duration_ms: 2 },
    ],
    tool_calls: [
      { tool: "capability.search", ok: true, duration_ms: 4 },
      { tool: "danger.delete", ok: false, error: "tool_not_allowed" },
    ],
    repair_attempts: 1,
  },
  usage: {
    llm_calls: 3,
    tool_calls: 2,
    prompt_tokens: 120,
    completion_tokens: 80,
    total_tokens: 200,
    estimated_cost_usd: 0,
    duration_ms: 40,
    repairs: 1,
    cancelled: false,
  },
  requires_durable_instance: false,
  notes: [],
};

function stubApi(overrides: Partial<ArchitectProposal> = {}, draft = true) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/architect/config")) {
      return Promise.resolve(
        json({ enabled: true, planner_version: "architect/1.2.0", states: [] }),
      );
    }
    if (url.includes("/architect/agentic-plan")) return Promise.resolve(json({ ...BASE, ...overrides }));
    if (url.includes("/architect/patch")) {
      return Promise.resolve(
        json({
          ...BASE,
          ...overrides,
          plan_hash: "b".repeat(64),
          patch: { summary: "Umbral actualizado", operations: [{ kind: "set_param" }] },
        }),
      );
    }
    if (url.includes("/architect/draft") && draft) {
      return Promise.resolve(json({ workflow_id: "wf-1", state: "DRAFT_READY", session_id: "ds_test" }));
    }
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function typeAndSubmit(prompt = "Cuando el stock sea menor a 10 avisa a compras") {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <ArchitectAskZent />
    </MemoryRouter>,
  );
  await user.type(await screen.findByTestId("ask-prompt"), prompt);
  await user.click(screen.getByTestId("ask-submit"));
  return user;
}

afterEach(() => {
  vi.unstubAllGlobals();
  NAVIGATE.mockReset();
});

describe("ArchitectAskZent", () => {
  it("muestra el estado, las fases y el preview antes de crear", async () => {
    stubApi();
    await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-understanding")).toBeInTheDocument());
    expect(screen.getByTestId("ask-state")).toHaveAttribute("data-state", "DRAFT_READY");
    expect(screen.getByTestId("ask-planner")).toHaveTextContent("planificado con IA");
    expect(screen.getByTestId("ask-phases")).toHaveTextContent("Capacidades");
    expect(screen.getByTestId("ask-understanding")).toHaveTextContent("CUANDO");
    expect(screen.getByTestId("ask-checks")).toHaveTextContent("Sin bloqueos");
    expect(screen.getByTestId("ask-catalog")).toHaveTextContent("63 capacidades");
    expect(screen.getByTestId("ask-matches")).toHaveTextContent("catalog.products.search");
    expect(screen.getByTestId("ask-trace")).toHaveTextContent("tool_not_allowed");
    expect(screen.queryByTestId("ask-durable")).not.toBeInTheDocument();
    expect(NAVIGATE).not.toHaveBeenCalled();
  });

  it("crea el borrador re-validado (plan, sin grafo) y navega", async () => {
    const fetchMock = stubApi();
    const user = await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-create")).toBeInTheDocument());
    await user.click(screen.getByTestId("ask-create"));
    await waitFor(() => expect(NAVIGATE).toHaveBeenCalledWith("/workflows/wf-1", expect.anything()));

    const saveCall = fetchMock.mock.calls.find((call) => String(call[0]).includes("/architect/draft"));
    expect(saveCall).toBeTruthy();
    const body = JSON.parse(String((saveCall?.[1] as RequestInit)?.body ?? "{}"));
    expect(body.plan).toBeTruthy();
    expect(body.plan_hash).toBe("a".repeat(64));
    expect(body.capability_snapshot_hash).toBe("c".repeat(64));
    expect(body.graph).toBeUndefined();
  });

  it("muestra el flujo avanzado con las dos ramas", async () => {
    stubApi();
    const user = await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-advanced")).toBeInTheDocument());
    await user.click(screen.getByTestId("ask-advanced"));
    expect(screen.getByTestId("ask-flow-preview")).toHaveTextContent("condition");
    expect((screen.getByTestId("ask-flow-preview").textContent?.match(/notify/g) ?? []).length).toBe(2);
  });

  it("pide aclaración y reinterpreta con los datos confirmados", async () => {
    const fetchMock = stubApi({
      state: "NEEDS_CLARIFICATION",
      publishable: false,
      clarifications: [
        {
          question: "¿A qué correo enviamos el reporte?",
          impact: "high",
          code: "missing.recipient",
        },
      ],
    });
    const user = await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-questions")).toBeInTheDocument());
    expect(screen.queryByTestId("ask-create")).not.toBeInTheDocument();
    await user.type(screen.getByTestId("ask-clarify-answer"), "compras@zent.test");
    await user.click(screen.getByTestId("ask-clarify-submit"));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter((call) => String(call[0]).includes("/architect/agentic-plan"));
      expect(calls.length).toBe(2);
      const body = JSON.parse(String((calls[1][1] as RequestInit)?.body ?? "{}"));
      expect(body.prompt).toContain("Datos confirmados por el usuario: compras@zent.test");
    });
  });

  it("muestra dependencias ausentes sin ofrecer crear como listo", async () => {
    stubApi({
      state: "NEEDS_CONFIGURATION",
      publishable: false,
      graph: null,
      requirements: [
        {
          requirement: "integration:slack",
          code: "missing.notification_channel",
          message: "Para esto primero necesitas conectar Slack.",
          resolved: false,
        },
      ],
      blockers: [
        {
          kind: "requirement",
          code: "missing.notification_channel",
          message: "Para esto primero necesitas conectar Slack.",
          requirement: "integration:slack",
        },
      ],
    });
    await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-requirements")).toBeInTheDocument());
    expect(screen.getByTestId("ask-requirements")).toHaveTextContent("conectar Slack");
    expect(screen.getByTestId("ask-integrations")).toHaveAttribute("href", "/integrations");
    expect(screen.queryByTestId("ask-create")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-save-draft")).not.toBeInTheDocument();
  });

  it("informa el fallback heurístico y no lo presenta como listo", async () => {
    stubApi({
      state: "NEEDS_CLARIFICATION",
      publishable: false,
      planner: { version: "architect/1.2.0", provider: null, model: null, source: "heuristics" },
      fallback: {
        used: true,
        reason_code: "llm_unavailable",
        limitations: ["El plan se generó con reglas determinísticas."],
        requires_review: true,
        publishable: false,
        preserved_requirement: "Cuando el stock sea menor a 10 avisa a compras",
      },
    });
    await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-fallback")).toBeInTheDocument());
    expect(screen.getByTestId("ask-fallback")).toHaveTextContent("No reemplaza el pedido original");
    expect(screen.getByTestId("ask-planner")).toHaveTextContent("borrador por reglas");
    expect(screen.queryByTestId("ask-create")).not.toBeInTheDocument();
    expect(screen.getByTestId("ask-save-draft")).toBeInTheDocument();
  });

  it("aplica un cambio semántico conservando el plan y su hash", async () => {
    const fetchMock = stubApi();
    const user = await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-change")).toBeInTheDocument());
    await user.click(screen.getByTestId("ask-change"));
    await user.type(screen.getByTestId("ask-patch-text"), "cambia el umbral a 50000");
    await user.click(screen.getByTestId("ask-patch-submit"));
    await waitFor(() => expect(screen.getByTestId("ask-patch-note")).toBeInTheDocument());
    const patchCall = fetchMock.mock.calls.find((call) => String(call[0]).includes("/architect/patch"));
    const body = JSON.parse(String((patchCall?.[1] as RequestInit)?.body ?? "{}"));
    expect(body.plan_hash).toBe("a".repeat(64));
    expect(body.session_id).toBe("ds_test");
    expect(body.instruction).toBe("cambia el umbral a 50000");
  });

  it("bloquea el guardado y ofrece reintentar cuando el diseño está BLOCKED", async () => {
    stubApi({ state: "BLOCKED", publishable: false, graph: null });
    await typeAndSubmit();
    await waitFor(() => expect(screen.getByTestId("ask-state")).toHaveAttribute("data-state", "BLOCKED"));
    expect(screen.queryByTestId("ask-create")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-save-draft")).not.toBeInTheDocument();
    expect(screen.getByTestId("ask-retry")).toBeInTheDocument();
  });
});
