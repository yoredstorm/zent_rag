import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import AgentBuilderPage from "./AgentBuilder";

const AGENT = {
  id: "a1",
  name: "Soporte",
  description: "Atención al cliente",
  system_prompt: "Responde con amabilidad.",
  tools: ["search_knowledge"],
  model: "zent-default",
  is_active: true,
  created_at: "2026-09-01T10:00:00Z",
  workspace_id: "w1",
  config: {
    purpose: "Atender clientes",
    temperature: 0.2,
    tone: "professional",
    knowledge_base_ids: [],
    limits: { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 },
    security: { sql_enabled: false, api_calls_enabled: false },
    retrieval: { strategy: "vector", top_k: 8, score_threshold: 0 },
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function fetchRouter() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/auth/me"))
      return Promise.resolve(json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] }));
    if (url.includes("/agents/a1/readiness"))
      return Promise.resolve(json({ score: 80, items: [{ key: "model", label: "Modelo", met: true, weight: 15, detail: "ok" }] }));
    if (url.includes("/agents/a1/versions"))
      return Promise.resolve(json({ versions: [{ id: "v1", version_number: 1, status: "draft", notes: null, created_at: "2026-09-01T10:00:00Z" }] }));
    if (url.includes("/agents/a1"))
      return Promise.resolve(json(AGENT));
    if (url.includes("/workspaces")) return Promise.resolve(json({ workspaces: [{ id: "w1", name: "Producción" }] }));
    if (url.includes("/knowledge-bases")) return Promise.resolve(json({ knowledge_bases: [] }));
    if (url.includes("/gateway/routes")) return Promise.resolve(json({ routes: [] }));
    if (url.includes("/billing/entitlements")) return Promise.resolve(json({ entitlements: {} }));
    if (url.includes("/deployments")) return Promise.resolve(json({ deployments: [] }));
    if (url.includes("/environments")) return Promise.resolve(json({ environments: [] }));
    return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
  });
}

function LocationProbe() {
  const { search, pathname } = useLocation();
  return <span data-testid="loc">{pathname + search}</span>;
}

async function renderBuilder() {
  const fetchMock = fetchRouter();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.setItem("rag_portal_token", "rag_sess_t");
  window.localStorage.setItem("rag_portal_org", "org-1");
  window.localStorage.setItem("rag_portal_company", "Acme");
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/agents/a1/builder?tab=instructions&stage=configure"]}>
      <AuthProvider>
        <Routes>
          <Route path="/agents/:id/builder" element={<AgentBuilderPage />} />
          <Route path="/agents/new" element={<AgentBuilderPage />} />
        </Routes>
        <LocationProbe />
      </AuthProvider>
    </MemoryRouter>
  );
  try {
    await screen.findByDisplayValue("Soporte");
  } catch (e) {
    console.log("FETCH CALLS:", fetchMock.mock.calls.map((c) => String(c[0])));
    console.log("BODY:", document.body.innerHTML.slice(0, 600));
    throw e;
  }
  return { user, fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("AgentBuilder — estado y flujo de etapas", () => {
  it("navega entre etapas actualizando la URL", async () => {
    const { user } = await renderBuilder();
    await user.click(screen.getByRole("button", { name: /Test/ }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("stage=test"));
    expect(screen.getByTestId("loc").textContent).toContain("tab=playground");
  });

  it("detecta cambios sin guardar al editar el nombre", async () => {
    const { user } = await renderBuilder();
    expect(screen.queryByText("Cambios sin guardar")).toBeNull();
    const nameInput = screen.getByDisplayValue("Soporte");
    await user.clear(nameInput);
    await user.type(nameInput, "Soporte v2");
    await waitFor(() => expect(screen.getByText("Cambios sin guardar")).toBeInTheDocument());
  });

  it("muestra el breadcrumb con la etapa actual", async () => {
    await renderBuilder();
    expect(screen.getByLabelText("Miga de pan")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agentes" })).toHaveAttribute("href", "/agents");
  });

  it("renderiza el readiness en la etapa Test", async () => {
    const { user } = await renderBuilder();
    await user.click(screen.getByRole("button", { name: /Test/ }));
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Readiness" })).toBeInTheDocument()
    );
    await user.click(screen.getByRole("tab", { name: "Readiness" }));
    await waitFor(() => expect(screen.getByText("Production Readiness")).toBeInTheDocument());
    expect(within(screen.getByText("Production Readiness").closest(".panel")!).getByText("80%")).toBeInTheDocument();
  });
});