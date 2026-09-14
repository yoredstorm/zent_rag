import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import AssistantDetailPage from "./AssistantDetailPage";
import AssistantsPage from "./AssistantsPage";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));
const NAVIGATE = vi.hoisted(() => vi.fn());

vi.mock("../auth", () => ({ useAuth: () => AUTH }));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => NAVIGATE };
});

const ASSISTANTS = [
  {
    id: "agent-1",
    name: "Asistente de Inventario",
    description: "Vigila el stock",
    status: "configured",
    is_active: true,
    automations: 2,
    active: 2,
    actions_today: 7,
    last_activity: new Date(Date.now() - 8 * 60_000).toISOString(),
    health: "healthy",
    watches: ["El stock bajó del mínimo", "Todos los días a las 09:00"],
    automation_names: ["Stock bajo", "Brief diario"],
  },
];

const AGENT = {
  id: "agent-1",
  name: "Asistente de Inventario",
  description: "Vigila el stock",
  status: "configured",
  is_active: true,
  model: "zent-default",
  tools: [],
  config: { purpose: "Vigilar inventario", knowledge_base_ids: [] },
};

const AUTOMATIONS = {
  summary: { automations: 1, active: 1, actions_today: 3, last_activity: new Date().toISOString(), health: "healthy" },
  automations: [
    {
      workflow_id: "wf-1",
      name: "Stock bajo",
      status: "active",
      when: "El stock bajó del mínimo",
      runs_7d: 4,
      failed_runs: 0,
      success_rate: 100,
      last_activity: new Date().toISOString(),
    },
  ],
};

const ACTIVITY = {
  items: [
    {
      kind: "análisis",
      title: "El agente analizó la información",
      detail: "Recomiendo reponer 40 unidades.",
      at: new Date().toISOString(),
      status: "succeeded",
      tech: { run_id: "run-9", node_id: "n1", duration_ms: 3200, correlation_id: "corr-1" },
    },
  ],
  run_count: 1,
  automation_count: 1,
};

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/agents/assistants")) return Promise.resolve(json({ assistants: ASSISTANTS }));
      if (url.endsWith("/api/v1/agents/agent-1/automations")) return Promise.resolve(json(AUTOMATIONS));
      if (url.endsWith("/api/v1/agents/agent-1/activity")) return Promise.resolve(json(ACTIVITY));
      if (url.endsWith("/api/v1/agents/agent-1/permissions")) return Promise.resolve(json({ permissions: [] }));
      if (url.endsWith("/api/v1/knowledge-bases")) return Promise.resolve(json({ knowledge_bases: [] }));
      if (url.endsWith("/api/v1/agents/agent-1")) return Promise.resolve(json(AGENT));
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  NAVIGATE.mockReset();
});

describe("AssistantsPage", () => {
  it("muestra las tarjetas de asistente con salud y vigilancia", async () => {
    stubApi();
    render(<MemoryRouter><AssistantsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("assistant-agent-1")).toBeInTheDocument());
    expect(screen.getByText("Asistente de Inventario")).toBeInTheDocument();
    expect(screen.getByText(/El stock bajó del mínimo/)).toBeInTheDocument();
    expect(screen.getByText(/7/)).toBeInTheDocument();
  });
});

describe("AssistantDetailPage", () => {
  function renderDetail() {
    return render(
      <MemoryRouter initialEntries={["/assistants/agent-1"]}>
        <Routes>
          <Route path="/assistants/:id" element={<AssistantDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("muestra actividad legible con detalles técnicos bajo demanda", async () => {
    stubApi();
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("assistant-overview")).toBeInTheDocument());
    await user.click(screen.getByTestId("assistant-tab-actividad"));
    await waitFor(() => expect(screen.getByText("El agente analizó la información")).toBeInTheDocument());
    expect(screen.queryByText("run-9")).toBeNull();
    await user.click(screen.getByTestId("assistant-tech-0"));
    expect(screen.getByText("run-9")).toBeInTheDocument();
    expect(screen.getByText("corr-1")).toBeInTheDocument();
  });

  it("agrega automatización llevando el prompt al copiloto con el agente", async () => {
    stubApi();
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("assistant-tab-automatizaciones")).toBeInTheDocument());
    await user.click(screen.getByTestId("assistant-tab-automatizaciones"));
    await user.type(
      screen.getByTestId("assistant-automation-prompt"),
      "Cuando un producto se quede sin stock, avisa al gerente.",
    );
    await user.click(screen.getByTestId("assistant-add-automation"));
    expect(NAVIGATE).toHaveBeenCalledWith(
      expect.stringContaining("/workflows/new/ask?agent=agent-1"),
    );
    expect(NAVIGATE.mock.calls[0][0]).toContain("q=Cuando");
  });
});
