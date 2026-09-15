import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { ToastProvider } from "../Toast";
import ChatPage from "./Chat";
import { LAST_USED_KEY } from "./chat/playgroundTargets";

const AGENT = {
  id: "a1",
  name: "Soporte",
  is_active: true,
  description: "Atención",
  config: { purpose: "Atender clientes", source_ids: ["s1"] },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function sse(frames: { event: string; data: unknown }[]) {
  const body = frames.map((f) => `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function fetchRouter() {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    if (url.includes("/auth/me")) {
      return Promise.resolve(
        json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] }),
      );
    }
    if (url.includes("/api/v1/agents/a1/run/stream") && method === "POST") {
      const body = JSON.parse(String(init?.body || "{}")) as { message?: string };
      return Promise.resolve(
        sse([
          { event: "status", data: { phase: "running" } },
          { event: "done", data: { answer: `eco:${body.message}`, status: "completed", steps: [] } },
        ]),
      );
    }
    if (url.includes("/api/v1/agents") && method === "GET") {
      return Promise.resolve(json({ agents: [AGENT], count: 1 }));
    }
    if (url.includes("/api/v1/workflows") && method === "GET") {
      return Promise.resolve(json({ workflows: [{ id: "w1", name: "Stock bajo", status: "active" }] }));
    }
    if (url.includes("/api/v1/rag/query/stream")) {
      return Promise.resolve(
        sse([
          { event: "sources", data: { sources: [], method: "vector", sql_query: null, lazy_ingested: false } },
          { event: "delta", data: { text: "hola rag" } },
          { event: "done", data: { conversation_id: "c1", query_id: "q1", usage: {}, latency_ms: 12 } },
        ]),
      );
    }
    return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
  });
}

function authShell(ui: ReactNode) {
  window.localStorage.setItem("rag_portal_token", "rag_sess_t");
  window.sessionStorage.setItem("rag_portal_token", "rag_sess_t");
  window.localStorage.setItem("rag_portal_org", "org-1");
  window.localStorage.setItem("rag_portal_company", "Acme");
  return (
    <AuthProvider>
      <ToastProvider>{ui}</ToastProvider>
    </AuthProvider>
  );
}

async function renderChat(path = "/chat") {
  const fetchMock = fetchRouter();
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={[path]}>
      {authShell(
        <Routes>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/agents/:id" element={<p>studio</p>} />
          <Route path="/agents/new" element={<p>nuevo agente</p>} />
          <Route path="/workflows/:id" element={<p>flujo</p>} />
        </Routes>,
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

describe("Playground Chat", () => {
  it("elige el primer agente activo y dispara run/stream", async () => {
    const { user, fetchMock } = await renderChat();
    expect(await screen.findByTestId("playground-target-bar")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Agente a probar")).toHaveValue("a1"));
    expect(screen.getByRole("heading", { name: "Pregunta a Soporte" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Tu pregunta" }), "hola");
    await user.click(screen.getByRole("button", { name: "Enviar pregunta" }));
    await waitFor(() => expect(screen.getByText("eco:hola")).toBeInTheDocument());
    const streamCall = fetchMock.mock.calls.find((call) => String(call[0]).includes("/agents/a1/run/stream"));
    expect(streamCall).toBeTruthy();
    expect(String(streamCall?.[1]?.method || "POST").toUpperCase()).toBe("POST");
  });

  it("en conocimiento muestra Vista y pega al RAG", async () => {
    const { user, fetchMock } = await renderChat("/chat?target=knowledge");
    await screen.findByTestId("playground-target-bar");
    expect(await screen.findByLabelText("Vista")).toBeInTheDocument();
    expect(screen.getByTestId("knowledge-pillar-links")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Tu pregunta" }), "stock");
    await user.click(screen.getByRole("button", { name: "Enviar pregunta" }));
    await waitFor(() => expect(screen.getByText("hola rag")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/rag/query/stream"))).toBe(true);
  });

  it("cambia a flujo y oculta Vista Equipo", async () => {
    const { user } = await renderChat("/chat?target=agent&id=a1");
    await screen.findByLabelText("Agente a probar");
    await user.selectOptions(screen.getByLabelText("Qué probar"), "workflow");
    await waitFor(() => expect(screen.getByLabelText("Flujo a probar")).toHaveValue("w1"));
    expect(screen.queryByLabelText("Vista")).toBeNull();
    expect(screen.getByText("Simulación")).toBeInTheDocument();
  });
});

describe("last-used no filtra este archivo", () => {
  it("limpia la clave entre tests", () => {
    expect(window.localStorage.getItem(LAST_USED_KEY)).toBeNull();
  });
});
