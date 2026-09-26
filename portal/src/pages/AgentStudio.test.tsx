import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const SQL_SOURCE = {
  id: "s2",
  name: "Ventas DB",
  type: "sql",
  status: "ready",
  document_count: 0,
  last_sync: "2026-09-01T10:00:00Z",
  knowledge_base_id: null,
};

/** Agente legacy: valores propios que NO coinciden con ningún preset nuevo. */
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
    retrieval: { strategy: "vector", top_k: 8, score_threshold: 0.1 },
  },
};

const READINESS = {
  score: 80,
  items: [
    { key: "model", label: "Modelo configurado", met: true, weight: 15, detail: "zent-default" },
    { key: "prompt", label: "Prompt configurado", met: true, weight: 15, detail: "Prompt listo" },
    { key: "knowledge", label: "Knowledge configurada", met: true, weight: 20, detail: "KB vinculada" },
    { key: "version", label: "Versión lista", met: false, weight: 10, detail: "Sin versión" },
    { key: "deployment", label: "Deployment activo", met: false, weight: 10, detail: "Sin deployment" },
  ],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fetchRouter(agent: Record<string, unknown> = AGENT) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    if (url.includes("/auth/me"))
      return Promise.resolve(
        json({
          organization_id: "org-1",
          company_name: "Acme",
          email: "a@b.cl",
          roles: ["owner"],
          permissions: [],
        }),
      );
    if (url.includes("/api/v1/sources")) return Promise.resolve(json({ sources: [SOURCE, SQL_SOURCE] }));
    if (url.includes("/api/v1/jobs")) return Promise.resolve(json({ jobs: [] }));
    if (url.includes("/readiness")) return Promise.resolve(json(READINESS));
    if (url.includes("/versions") && method === "POST") return Promise.resolve(json({ id: "v1" }));
    if (url.includes("/versions")) return Promise.resolve(json({ versions: [] }));
    if (url.includes("/embed/token")) return Promise.resolve(json({ token: "tok-1", public_id: "pub-1" }));
    if (url.includes("/embed/revoke")) return Promise.resolve(json({ status: "revoked" }));
    if (url.includes("/deployments")) return Promise.resolve(json({ deployments: [] }));
    if (url.includes("/environments")) return Promise.resolve(json({ environments: [] }));
    if (url.includes("/gateway/routes")) return Promise.resolve(json({ routes: [] }));
    if (url.includes("/billing/entitlements")) return Promise.resolve(json({ entitlements: {} }));
    if (url.includes("/organizations/quality-gates"))
      return Promise.resolve(
        json({ gate: { thresholds: {}, max_hallucination: 0.3, max_regression_pct: 10 } }),
      );
    if (url.includes("/config/response-profile"))
      return Promise.resolve(json({ draft: { preset: "analytical", default_detail: "deep" } }));
    if (url.includes("/run/stream")) {
      const frame = [
        "event: done",
        'data: {"answer":"Listo.","status":"completed","steps":[],"total_latency_ms":12,"model":"zent-default"}',
        "",
        "",
      ].join("\n");
      return Promise.resolve(new Response(frame, { status: 200 }));
    }
    if (url.includes(`/agents/${agent.id}`) && (method === "PUT" || method === "POST")) {
      const body = JSON.parse(String(init?.body || "{}"));
      return Promise.resolve(json({ ...agent, ...body, config: { ...(agent.config as object), ...body.config } }));
    }
    if (url.includes(`/agents/${agent.id}`)) return Promise.resolve(json(agent));
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

async function renderStudio(path = "/agents/a1", agent: Record<string, unknown> = AGENT) {
  const fetchMock = fetchRouter(agent);
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

/** Último PUT enviado: el guardado se dispara más de una vez por test. */
function sentBody(fetchMock: ReturnType<typeof fetchRouter>) {
  const puts = fetchMock.mock.calls.filter(
    (entry) =>
      String(entry[0]).includes("/agents/a1") &&
      String(entry[1]?.method || "").toUpperCase() === "PUT",
  );
  const last = puts[puts.length - 1];
  return JSON.parse(String(last?.[1]?.body || "{}"));
}

/** Espera a que el Studio termine de cargar (la barra de etapas es fija). */
async function waitForStudio() {
  const nav = await screen.findByRole("tablist", { name: "Etapas del agente" });
  expect(nav).toBeInTheDocument();
  return nav;
}

/** Abre el grupo avanzado si su detalle está plegado. */
async function openGroup(user: ReturnType<typeof userEvent.setup>, id: string) {
  const group = screen.getByTestId(`agent-group-${id}`);
  const toggle = within(group).queryByRole("button", { name: "Personalizar" });
  if (toggle) await user.click(toggle);
  return group;
}

/** Los `input[type=number]` controlados se manejan mejor con change directo. */
function setNumber(label: string | RegExp, value: string, scope?: HTMLElement) {
  const input = scope
    ? within(scope).getByLabelText(label)
    : screen.getByLabelText(label);
  fireEvent.change(input, { target: { value } });
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

describe("AgentStudio · identidad y conocimiento", () => {
  it("muestra las cuatro decisiones esenciales y el playground", async () => {
    await renderStudio();
    expect(await screen.findByDisplayValue("Soporte")).toBeInTheDocument();
    expect(screen.getByLabelText("Propósito")).toHaveValue("Atender clientes");
    expect(screen.getByRole("heading", { name: /Conocimiento/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Comportamiento/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Inteligencia/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Probar" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Pregunta al agente…")).toBeInTheDocument();
  });

  it("las instrucciones adicionales arrancan plegadas", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    expect(screen.queryByLabelText("Texto libre")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Instrucciones adicionales/ }));
    expect(screen.getByLabelText("Texto libre")).toBeInTheDocument();
  });

  it("resume el conocimiento conectado y lo administra aparte", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    expect(screen.getByText("1 fuente conectada")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Políticas RRHH/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Administrar conocimiento" }));
    expect(screen.getByRole("checkbox", { name: /Políticas RRHH/ })).toBeChecked();
  });

  it("avisa y limpia las fuentes guardadas que ya no existen", async () => {
    const conFantasma = {
      ...AGENT,
      config: { ...AGENT.config, source_ids: ["s1", "fuente-borrada"] },
    };
    const { user } = await renderStudio("/agents/a1", conFantasma);
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("button", { name: "Administrar conocimiento" }));
    const aviso = await screen.findByTestId("source-missing-copy");
    expect(aviso).toHaveTextContent(/de 2 fuentes guardadas ya no existen/i);
    await user.click(screen.getByRole("button", { name: "Quitar las que faltan" }));
    expect(screen.queryByTestId("source-missing-copy")).toBeNull();
  });
});

describe("AgentStudio · creación simple", () => {
  it("crea un agente con sólo nombre, propósito y fuentes", async () => {
    const fetchMock = fetchRouter();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/agents/new"]}>
        {authShell(
          <>
            <Routes>
              <Route path="/agents/new" element={<AgentStudioPage />} />
            </Routes>
            <LocationProbe />
          </>,
        )}
      </MemoryRouter>,
    );
    await screen.findByText("Identidad");
    await user.type(screen.getByLabelText("Nombre"), "Mesa de ayuda");
    await user.type(screen.getByLabelText("Propósito"), "Responder dudas de RRHH");
    await user.click(screen.getByRole("button", { name: "Administrar conocimiento" }));
    await user.click(screen.getByRole("checkbox", { name: /Políticas RRHH/ }));
    await user.click(screen.getByRole("button", { name: "Crear agente" }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (entry) => String(entry[0]).endsWith("/api/v1/agents") && entry[1]?.method === "POST",
      );
      expect(post).toBeTruthy();
      const body = JSON.parse(String(post?.[1]?.body || "{}"));
      expect(body.name).toBe("Mesa de ayuda");
      expect(body.description).toBe("Responder dudas de RRHH");
      expect(body.config.purpose).toBe("Responder dudas de RRHH");
      expect(body.config.source_ids).toEqual(["s1"]);
      expect(body.tools).toEqual(expect.arrayContaining(["search_knowledge"]));
      // El payload sigue llevando la forma histórica completa.
      expect(body.config.retrieval).toEqual({ strategy: "hybrid", top_k: 10, score_threshold: 0 });
      expect(body.config.tone).toBe("professional");
    });
  });
});

describe("AgentStudio · agente legacy", () => {
  it("no marca cambios sin guardar al cargar y respeta sus valores propios", async () => {
    const { user } = await renderStudio();
    await waitForStudio();
    expect(screen.queryByText("Cambios sin guardar")).toBeNull();
    // sin response_profile guardado → el perfil por defecto, no "personalizado"
    expect(screen.getByRole("button", { name: /Equilibrado/ })).toHaveAttribute("aria-pressed", "true");
    // retrieval propio (vector/8/0.1) → no es el recomendado
    await user.click(screen.getByRole("button", { name: /Configuración avanzada/ }));
    expect(await screen.findByTestId("agent-group-retrieval-summary")).toHaveTextContent(
      "Personalizada · por significado · 8 fragmentos · similitud mínima 0.1",
    );
  });

  it("clasifica un perfil guardado que no coincide con ningún preset como Personalizado", async () => {
    const legacy = {
      ...AGENT,
      config: {
        ...AGENT.config,
        response_profile: { preset: "executive", tone: "didactic", default_detail: "deep" },
      },
    };
    await renderStudio("/agents/a1", legacy);
    await screen.findByDisplayValue("Soporte");
    expect(screen.getByTestId("agent-behavior")).toHaveTextContent("Personalizado");
    expect(screen.getByTestId("agent-behavior-summary")).toHaveTextContent(/didáctico/);
    // No se pisa el perfil guardado.
    expect(screen.getByRole("button", { name: /Equilibrado/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /Ejecutivo/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("marca cambios sin guardar al editar el nombre", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    const nameInput = screen.getByLabelText("Nombre");
    await user.clear(nameInput);
    await user.type(nameInput, "Soporte v2");
    await waitFor(() => expect(screen.getByText("Cambios sin guardar")).toBeInTheDocument());
  });
});

describe("AgentStudio · etapas y URLs", () => {
  it("navega entre Desarrollar, Probar y Publicar con tabs accesibles", async () => {
    const { user } = await renderStudio();
    const nav = await waitForStudio();
    expect(within(nav).getAllByRole("tab")).toHaveLength(3);
    expect(within(nav).getByRole("tab", { name: "Desarrollar" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.click(within(nav).getByRole("tab", { name: "Publicar" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("panel=publish"));
    expect(await screen.findByText("Listo para producción")).toBeInTheDocument();
  });

  it("una pestaña antigua de publicación abre la etapa Publicar", async () => {
    await renderStudio("/agents/a1?panel=advanced&tab=versions");
    await waitForStudio();
    expect(screen.getByRole("tab", { name: "Publicar" })).toHaveAttribute("aria-selected", "true");
    // El panel de versiones está presente aunque todavía no haya ninguna.
    expect(screen.getAllByText("Sin versiones").length).toBeGreaterThan(0);
  });

  it("una pestaña antigua de configuración abre su grupo avanzado", async () => {
    await renderStudio("/agents/a1?panel=advanced&tab=retrieval");
    await waitForStudio();
    const group = await screen.findByTestId("agent-group-retrieval");
    expect(within(group).getByLabelText("Fragmentos a usar")).toHaveValue(8);
  });
});

describe("AgentStudio · comportamiento", () => {
  it("aplica un preset y lo persiste aplanado en el perfil", async () => {
    const { user, fetchMock } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("button", { name: /Ejecutivo/ }));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const body = sentBody(fetchMock);
      expect(body.config.response_profile.preset).toBe("executive");
      expect(body.config.response_profile.tone).toBe("executive");
      expect(body.config.response_profile.audience).toBe("business");
      expect(body.config.response_profile.use_examples).toBe(false);
    });
  });

  it("abre los controles detallados sólo al personalizar", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    expect(screen.queryByLabelText("Nivel de detalle")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Personalizar comportamiento" }));
    expect(screen.getByLabelText("Nivel de detalle")).toBeInTheDocument();
    expect(screen.getByLabelText("Instrucciones de estilo")).toBeInTheDocument();
  });

  it("pide un borrador de estilo con IA y avisa que es un borrador", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("button", { name: /Crear configuración con IA/ }));
    const panel = await screen.findByTestId("agent-ai-suggestion");
    expect(within(panel).getByTestId("agent-ai-decisions")).toHaveTextContent("Equilibrado");
    await user.click(within(panel).getByRole("button", { name: "Pedir borrador de estilo con IA" }));
    expect(await within(panel).findByText(/datos reales del agente/)).toBeInTheDocument();
  });

  it("sin agente guardado no simula la generación con IA", async () => {
    const fetchMock = fetchRouter();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/agents/new"]}>
        {authShell(
          <Routes>
            <Route path="/agents/new" element={<AgentStudioPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );
    await screen.findByText("Identidad");
    await user.click(screen.getByRole("button", { name: /Crear configuración con IA/ }));
    const panel = await screen.findByTestId("agent-ai-suggestion");
    await user.click(within(panel).getByRole("button", { name: "Pedir borrador de estilo con IA" }));
    expect(await within(panel).findByText(/Guardá el agente primero/)).toBeInTheDocument();
  });
});

describe("AgentStudio · configuración avanzada", () => {
  it("el modelo arranca Automático y se puede fijar una prioridad", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=model");
    await screen.findByDisplayValue("Soporte");
    const group = screen.getByTestId("agent-group-model");
    expect(within(group).getByTestId("agent-group-model-summary")).toHaveTextContent(
      "Automático · Zent elige el motor",
    );
    await user.selectOptions(within(group).getByLabelText("Prioridad del motor"), "zent-quality");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).model).toBe("zent-quality"));
  });

  it("vuelve a Automático con el radiogroup", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=model", {
      ...AGENT,
      model: "zent-quality",
    });
    await screen.findByDisplayValue("Soporte");
    const group = screen.getByTestId("agent-group-model");
    expect(within(group).getByTestId("agent-group-model-summary")).toHaveTextContent("Priorizar calidad");
    await user.click(within(group).getByRole("radio", { name: /Automático \(recomendado\)/ }));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).model).toBe("zent-default"));
  });

  it("nunca activa una capacidad incompatible con las fuentes", async () => {
    await renderStudio("/agents/a1?panel=advanced&tab=tools");
    await screen.findByDisplayValue("Soporte");
    const group = screen.getByTestId("agent-group-tools");
    expect(within(group).getByRole("checkbox", { name: /Consultar datos/ })).toBeDisabled();
    expect(
      within(group).getByText(/Tus fuentes no incluyen base de datos/),
    ).toBeInTheDocument();
  });

  it("habilita Consultar datos cuando hay fuentes SQL y lo persiste", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=tools");
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("button", { name: "Administrar conocimiento" }));
    await user.click(screen.getByRole("checkbox", { name: /Ventas DB/ }));
    const group = screen.getByTestId("agent-group-tools");
    const data = within(group).getByRole("checkbox", { name: /Consultar datos/ });
    expect(data).toBeEnabled();
    await user.click(data);
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const body = sentBody(fetchMock);
      expect(body.tools).toContain("query_database");
      expect(body.config.security.sql_enabled).toBe(true);
    });
  });

  it("hereda JEV por defecto y permite override por campo", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=intelligence");
    await waitForStudio();
    const group = screen.getByTestId("agent-group-intelligence");
    expect(within(group).getByTestId("agent-group-intelligence-summary")).toHaveTextContent(
      "Ruteo de herramientas: heredado",
    );
    await user.selectOptions(within(group).getByLabelText("Ruteo de herramientas"), "off");
    await user.selectOptions(
      within(group).getByLabelText("Verificación de la respuesta"),
      "on",
    );
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => {
      const runtime = sentBody(fetchMock).config.runtime;
      expect(runtime.tool_routing).toBe(false);
      expect(runtime.answer_gate).toBe(true);
      expect(runtime.termination_gate).toBeUndefined();
    });
  });

  it("Answer Gate se puede apagar en el agente", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=intelligence");
    await waitForStudio();
    const group = screen.getByTestId("agent-group-intelligence");
    await user.selectOptions(within(group).getByLabelText("Verificación de la respuesta"), "off");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).config.runtime.answer_gate).toBe(false));
  });

  it("vuelve a heredar la inteligencia de Zent", async () => {
    const conOverride = {
      ...AGENT,
      config: {
        ...AGENT.config,
        runtime: { tool_routing: false, termination_gate: false, answer_gate: true },
      },
    };
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=intelligence", conOverride);
    await screen.findByDisplayValue("Soporte");
    const group = screen.getByTestId("agent-group-intelligence");
    await user.click(within(group).getByRole("radio", { name: /Heredar inteligencia de Zent/ }));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).config.runtime).toBeUndefined());
  });

  it("permite retrieval avanzado y lo restaura a lo recomendado", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=retrieval");
    await waitForStudio();
    const group = screen.getByTestId("agent-group-retrieval");
    await user.selectOptions(within(group).getByLabelText("Forma de buscar"), "lexical");
    setNumber("Fragmentos a usar", "4", group);
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).config.retrieval.strategy).toBe("lexical"));
    expect(sentBody(fetchMock).config.retrieval.top_k).toBe(4);

    await user.click(within(group).getByRole("button", { name: "Restaurar valores recomendados" }));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() =>
      expect(sentBody(fetchMock).config.retrieval).toEqual({
        strategy: "hybrid",
        top_k: 10,
        score_threshold: 0,
      }),
    );
  });

  it("mantiene los topes personalizables y los restaura", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=limits");
    await waitForStudio();
    const group = screen.getByTestId("agent-group-limits");
    expect(within(group).getByTestId("agent-group-limits-summary")).toHaveTextContent(
      "Protección automática",
    );
    setNumber("Tope de pasos", "12", group);
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).config.limits.max_steps).toBe(12));
    expect(sentBody(fetchMock).config.limits.max_cost_usd).toBe(0.5);

    await user.click(within(group).getByRole("button", { name: "Restaurar valores recomendados" }));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).config.limits.max_steps).toBe(8));
  });

  it("guarda la salida estructurada y rechaza un JSON inválido", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=advanced&tab=integration");
    await waitForStudio();
    const group = await openGroup(user, "integration");
    const editor = within(group).getByLabelText(/Formato de respuesta/);
    fireEvent.change(editor, { target: { value: '{"producto": "string"' } });
    expect(within(group).getByText(/JSON inválido/)).toBeInTheDocument();
    fireEvent.change(editor, { target: { value: '{"producto": "string"}' } });
    expect(within(group).queryByText(/JSON inválido/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(sentBody(fetchMock).config.output_schema).toEqual({ producto: "string" }));
  });

  it("una pestaña sin tab deja todos los grupos con su resumen", async () => {
    await renderStudio("/agents/a1?panel=advanced");
    await waitForStudio();
    expect(screen.getByTestId("agent-group-model-summary")).toBeInTheDocument();
    expect(screen.getByTestId("agent-group-limits-summary")).toBeInTheDocument();
    expect(screen.queryByLabelText("Fragmentos a usar")).toBeNull();
  });
});

describe("AgentStudio · playground", () => {
  it("sugiere preguntas y las ejecuta al clic", async () => {
    const { user, fetchMock } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    expect(screen.getByText("Preguntale a Soporte")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Resumí lo más importante en 3 puntos/ }));
    await waitFor(() => {
      const stream = fetchMock.mock.calls.find((call) => String(call[0]).includes("/run/stream"));
      expect(stream).toBeTruthy();
      expect(JSON.parse(String(stream?.[1]?.body || "{}")).message).toBe(
        "Resumí lo más importante en 3 puntos.",
      );
    });
  });

  it("la conversación de prueba se puede limpiar", async () => {
    const { user } = await renderStudio();
    await screen.findByDisplayValue("Soporte");
    await user.click(screen.getByRole("button", { name: /¿Qué cubre la documentación/ }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Limpiar conversación de prueba" }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "Limpiar conversación de prueba" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /¿Qué cubre la documentación/ })).toBeInTheDocument(),
    );
  });
});

describe("AgentStudio · publicación", () => {
  it("crea una versión desde Publicar", async () => {
    const { user, fetchMock } = await renderStudio("/agents/a1?panel=publish");
    await waitForStudio();
    await user.click(screen.getByRole("button", { name: "Crear versión" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          (call) => String(call[0]).includes("/agents/a1/versions") && call[1]?.method === "POST",
        ),
      ).toBe(true),
    );
  });

  it("genera el token del widget desde Publicar", async () => {
    const { user } = await renderStudio("/agents/a1?tab=embed");
    await waitForStudio();
    await user.click(screen.getByRole("button", { name: "Crear token" }));
    expect(await screen.findByText("tok-1")).toBeInTheDocument();
  });
});

describe("AgentBuilderRedirect", () => {
  it("playground va al panel de prueba", async () => {
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

  it("una pestaña de publicación va a la etapa Publicar", async () => {
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
      expect(screen.getByTestId("loc").textContent).toBe("/agents/a1?panel=publish&tab=versions"),
    );
  });

  it("una pestaña de configuración va a su grupo avanzado", async () => {
    render(
      <MemoryRouter initialEntries={["/agents/a1/builder?tab=retrieval"]}>
        <Routes>
          <Route path="/agents/:id/builder" element={<AgentBuilderRedirect />} />
          <Route path="/agents/:id" element={<p>studio</p>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loc").textContent).toBe("/agents/a1?panel=advanced&tab=retrieval"),
    );
  });
});
