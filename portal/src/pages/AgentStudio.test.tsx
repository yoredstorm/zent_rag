import type { ReactNode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { sourceIdsFromSteps, toolErrorsFromSteps } from "../components/agentStudio/types";
import { AgentBuilderRedirect } from "./AgentEntry";
import AgentStudioPage from "./AgentStudio";

const SOURCE = {
  id: "s1",
  name: "Políticas RRHH",
  type: "file",
  status: "ready",
  document_count: 4,
  last_sync: "2026-09-01T10:00:00Z",
  knowledge_base_id: "kb1",
};

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
    knowledge_base_ids: ["kb1"],
    source_ids: ["s1"],
    limits: { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 },
    security: { sql_enabled: false, api_calls_enabled: false },
    retrieval: { strategy: "vector", top_k: 8, score_threshold: 0 },
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function fetchRouter() {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    if (url.includes("/auth/me"))
      return Promise.resolve(json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] }));
    if (url.includes("/api/v1/sources")) return Promise.resolve(json({ sources: [SOURCE] }));
    if (url.includes("/api/v1/jobs")) return Promise.resolve(json({ jobs: [] }));
    if (url.includes("/agents/a1/readiness"))
      return Promise.resolve(json({ score: 80, items: [{ key: "model", label: "Modelo", met: true, weight: 15, detail: "ok" }] }));
    if (url.includes("/agents/a1/versions")) return Promise.resolve(json({ versions: [] }));
    if (url.includes("/agents/a1") && method === "PUT") {
      const body = JSON.parse(String(init?.body || "{}"));
      return Promise.resolve(json({ ...AGENT, ...body, config: { ...AGENT.config, ...body.config } }));
    }
    if (url.includes("/agents/a1")) return Promise.resolve(json(AGENT));
    if (url.includes("/gateway/routes")) return Promise.resolve(json({ routes: [] }));
    if (url.includes("/billing/entitlements")) return Promise.resolve(json({ entitlements: {} }));
    if (url.includes("/deployments")) return Promise.resolve(json({ deployments: [] }));
    if (url.includes("/environments")) return Promise.resolve(json({ environments: [] }));
    if (url.includes("/organizations/quality-gates"))
      return Promise.resolve(json({ gate: { thresholds: {}, max_hallucination: 0.3, max_regression_pct: 10 } }));
    return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
  });
}

function LocationProbe() {
  const { search, pathname } = useLocation();
  return <span data-testid="loc">{pathname + search}</span>;
}

function authShell(ui: ReactNode) {
  window.localStorage.setItem("rag_portal_token", "rag_sess_t");
  window.localStorage.setItem("rag_portal_org", "org-1");
  window.localStorage.setItem("rag_portal_company", "Acme");
  return <AuthProvider>{ui}</AuthProvider>;
}

async function renderStudio(path = "/agents/a1") {
  const fetchMock = fetchRouter();
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={[path]}>
      {authShell(
        <>
          <Routes>
            <Route path="/agents/new" element={<AgentStudioPage />} />
            <Route path="/agents/:id" element={<AgentStudioPage />} />
            <Route path="/agents" element={<p>lista</p>} />
          </Routes>
          <LocationProbe />
        </>,
      )}
    </MemoryRouter>,
  );
  return { user, fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("sourceIdsFromSteps", () => {
  it("extrae source_id únicos de tool_call.meta", () => {
    expect(
      sourceIdsFromSteps([
        { type: "tool_call", meta: { source_ids: ["s1", "s1", "s2"] } },
        { type: "llm", meta: { source_ids: ["s9"] } },
      ]),
    ).toEqual(["s1", "s2"]);
  });
});

describe("toolErrorsFromSteps", () => {
  it("extrae errores de tool_call", () => {
    expect(
      toolErrorsFromSteps([
        { type: "tool_call", error: "VectorRetriever requires query_embedding" },
        { type: "tool_call", error: "VectorRetriever requires query_embedding" },
        { type: "final", error: "no" },
      ]),
    ).toEqual(["VectorRetriever requires query_embedding"]);
  });
});

describe("AgentStudio", () => {
  it("muestra propósito, fuentes y chat de prueba", async () => {
    await renderStudio();
    expect(await screen.findByDisplayValue("Soporte")).toBeInTheDocument();
    expect(screen.getByLabelText("Propósito")).toHaveValue("Atender clientes");
    expect(screen.getByText("Fuentes que ya cargaste")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Políticas RRHH/ })).toBeChecked();
    expect(screen.getByRole("heading", { name: "Probar" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Pregunta al agente…")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Probar en Playground" })).toHaveAttribute(
      "href",
      "/chat?target=agent&id=a1",
    );
  });

  it("no marca dirty al cargar un agente guardado", async () => {
    await renderStudio();
    await screen.findByDisplayValue("Soporte");
    expect(screen.queryByText("Cambios sin guardar")).toBeNull();
  });

  it("marca cambios sin guardar al editar el nombre", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    const nameInput = await screen.findByLabelText("Nombre");
    expect(screen.queryByText("Cambios sin guardar")).toBeNull();
    await user.clear(nameInput);
    await user.type(nameInput, "Soporte v2");
    await waitFor(() => expect(screen.getByText("Cambios sin guardar")).toBeInTheDocument());
  });

  it("muestra breadcrumb hacia la lista", async () => {
    await renderStudio();
    await screen.findByDisplayValue("Soporte");
    expect(screen.getByLabelText("Miga de pan")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agentes" })).toHaveAttribute("href", "/agents");
  });

  it("abre Ajustes extra en Publicar con un tab antiguo y muestra readiness", async () => {
    await renderStudio("/agents/a1?panel=advanced&tab=readiness");
    await screen.findByDisplayValue("Soporte");
    expect(screen.getByText("Ajustes extra")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Publicar" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(screen.getByText("Listo para producción")).toBeInTheDocument());
    expect(
      within(screen.getByText("Listo para producción").closest(".panel")!).getByText("80%"),
    ).toBeInTheDocument();
  });

  it("explica el modelo y la creatividad en Cómo responde", async () => {
    const { user } = await renderStudio("/agents/a1?panel=advanced");
    await screen.findByDisplayValue("Soporte");
    expect(screen.getByLabelText("Qué modelo usar")).toHaveValue("zent-default");
    expect(screen.getByRole("option", { name: /Equilibrado \(recomendado\) · zent-default/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/Creatividad \(0\.20\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Qué puede hacer" }));
    expect(screen.getByRole("checkbox", { name: /Buscar en el conocimiento/ })).toBeChecked();
    expect(screen.getByLabelText("Fragmentos a usar")).toHaveValue(8);
  });

  it("guarda los permisos elegidos en Qué puede hacer", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=tools");
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("checkbox", { name: /Consultar la base de datos/ }));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (call) => String(call[0]).includes("/agents/a1") && String(call[1]?.method || "").toUpperCase() === "PUT",
      );
      const body = JSON.parse(String(put?.[1]?.body || "{}"));
      expect(body.tools).toContain("query_database");
      expect(body.config.security.sql_enabled).toBe(true);
    });
  });

  it("cambia a panel test en mobile tabs", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("tab", { name: "Probar" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("panel=test"));
  });

  it("permite apagar JEV por agente y lo guarda en runtime", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=tools");
    await screen.findByDisplayValue("Soporte");
    await user.selectOptions(screen.getByLabelText(/JEV en este agente/), "off");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (call) =>
          String(call[0]).includes("/agents/a1") &&
          String(call[1]?.method || "").toUpperCase() === "PUT",
      );
      const body = JSON.parse(String(put?.[1]?.body || "{}"));
      expect(body.config.runtime).toEqual({
        tool_routing: false,
        termination_gate: false,
      });
    });
  });

  it("Activar todas enciende las tres herramientas", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=tools");
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("button", { name: "Activar todas" }));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (call) =>
          String(call[0]).includes("/agents/a1") &&
          String(call[1]?.method || "").toUpperCase() === "PUT",
      );
      const body = JSON.parse(String(put?.[1]?.body || "{}"));
      expect(body.tools).toEqual(
        expect.arrayContaining(["search_knowledge", "query_database", "call_api"]),
      );
      expect(body.config.security).toEqual({
        sql_enabled: true,
        api_calls_enabled: true,
      });
    });
  });

  it("permite apagar el verificador de JEV por agente", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=tools");
    await screen.findByDisplayValue("Soporte");
    await user.selectOptions(screen.getByLabelText(/JEV verifica la respuesta/), "off");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (call) =>
          String(call[0]).includes("/agents/a1") &&
          String(call[1]?.method || "").toUpperCase() === "PUT",
      );
      const body = JSON.parse(String(put?.[1]?.body || "{}"));
      expect(body.config.runtime.answer_gate).toBe(false);
    });
  });

  it("persiste source_ids al guardar", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1");
    const checkbox = await screen.findByRole("checkbox", { name: /Políticas RRHH/ });
    expect(checkbox).toBeChecked();
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (call) => String(call[0]).includes("/agents/a1") && String(call[1]?.method || "").toUpperCase() === "PUT",
      );
      expect(put).toBeTruthy();
      const body = JSON.parse(String(put?.[1]?.body || "{}"));
      expect(body.config.source_ids).toEqual([]);
    });
  });
});

describe("AgentBuilderRedirect", () => {
  it("playground va al chat de prueba", async () => {
    render(
      <MemoryRouter initialEntries={["/agents/a1/builder?tab=playground"]}>
        <Routes>
          <Route path="/agents/:id/builder" element={<AgentBuilderRedirect />} />
          <Route path="/agents/:id" element={<p>studio</p>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/agents/a1?panel=test"));
  });

  it("tab de versiones abre Avanzado", async () => {
    render(
      <MemoryRouter initialEntries={["/agents/a1/builder?tab=versions"]}>
        <Routes>
          <Route path="/agents/:id/builder" element={<AgentBuilderRedirect />} />
          <Route path="/agents/:id" element={<p>studio</p>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loc").textContent).toBe("/agents/a1?panel=advanced&tab=versions"),
    );
  });
});
