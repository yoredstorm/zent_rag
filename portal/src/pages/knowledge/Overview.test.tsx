import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeOverviewPage from "./Overview";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const SOURCE = {
  id: "src-1",
  name: "Inventario",
  type: "file",
  status: "ready",
  last_sync: new Date().toISOString(),
  last_error: null,
  document_count: 4,
  error_count: 0,
};

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stubApi(sources: unknown[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/sources")) return Promise.resolve(json({ sources }));
      if (url.includes("/api/v1/jobs")) return Promise.resolve(json({ jobs: [] }));
      if (url.includes("/api/v1/billing/usage/storage")) {
        return Promise.resolve(json({ vector_points: sources.length ? 12 : 0 }));
      }
      if (url.includes("/api/v1/data-onboarding/gate")) {
        return Promise.resolve(json({ has_real_data: sources.length > 0, resume_session_id: null }));
      }
      if (url.includes("/api/v1/data-onboarding/sessions")) {
        return Promise.resolve(json({ sessions: [] }));
      }
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderOverview() {
  return render(
    <MemoryRouter initialEntries={["/knowledge"]}>
      <KnowledgeOverviewPage />
    </MemoryRouter>,
  );
}

describe("KnowledgeOverviewPage", () => {
  it("con 0 fuentes no dice que está listo y ofrece Añadir fuente", async () => {
    stubApi([]);
    renderOverview();
    await waitFor(() => expect(screen.getByTestId("knowledge-empty")).toBeInTheDocument());
    expect(screen.queryByTestId("knowledge-ready")).toBeNull();
    expect(screen.queryByText(/está listo/)).toBeNull();
    expect(screen.queryByText(/están listas/)).toBeNull();
    expect(screen.queryByText("Knowledge Workspaces")).toBeNull();
    expect(screen.queryByText("Pregúntale a Zent")).toBeNull();
    expect(screen.getAllByRole("link", { name: "Añadir fuente" }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/El conocimiento son las fuentes/)).toBeInTheDocument();
  });

  it("con fuentes muestra Playground y Crear agente", async () => {
    stubApi([SOURCE]);
    renderOverview();
    await waitFor(() => expect(screen.getByTestId("knowledge-ready")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Probar en Playground" })).toHaveAttribute(
      "href",
      "/chat?target=knowledge",
    );
    expect(screen.getByRole("link", { name: "Crear agente" })).toHaveAttribute("href", "/agents/new");
    expect(screen.getByRole("link", { name: "Ver fuentes" })).toHaveAttribute("href", "/knowledge/sources");
    expect(screen.queryByText("Pregúntale a Zent")).toBeNull();
    expect(screen.queryByText("Knowledge Workspaces")).toBeNull();
  });
});
