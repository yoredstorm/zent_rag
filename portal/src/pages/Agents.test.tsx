import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import AgentsPage from "./Agents";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("Agents list", () => {
  it("muestra propósito, fuentes, Editar y Probar; sin pilares de Knowledge", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/me"))
          return Promise.resolve(
            json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] }),
          );
        if (url.includes("/api/v1/agents"))
          return Promise.resolve(
            json({
              agents: [
                {
                  id: "a1",
                  name: "Gizmo",
                  description: "Ayuda interna",
                  tools: ["search_knowledge"],
                  model: "zent-default",
                  is_active: true,
                  created_at: "2026-09-01T10:00:00Z",
                  config: { purpose: "Responder RRHH", source_ids: ["s1", "s2"] },
                },
              ],
            }),
          );
        if (url.includes("/billing/entitlements")) return Promise.resolve(json({ entitlements: { max_agents: 10 } }));
        return Promise.resolve(json({ detail: url }, 500));
      }),
    );
    window.localStorage.setItem("rag_portal_token", "rag_sess_t");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");
    render(
      <MemoryRouter>
        <AuthProvider>
          <AgentsPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Gizmo")).toBeInTheDocument());
    expect(screen.queryByTestId("knowledge-pillar-links")).not.toBeInTheDocument();
    expect(screen.getByText("Responder RRHH")).toBeInTheDocument();
    expect(screen.getByText("2 fuentes")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Editar" })).toHaveAttribute("href", "/agents/a1");
    expect(screen.getByRole("link", { name: "Probar" })).toHaveAttribute("href", "/agents/a1?panel=test");
  });
});
