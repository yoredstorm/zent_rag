import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import AgentBuilderPage from "./AgentBuilder";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("AgentBuilder", () => {
  it("reexporta el estudio editable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/me"))
          return Promise.resolve(
            json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] }),
          );
        if (url.includes("/api/v1/sources")) return Promise.resolve(json({ sources: [] }));
        if (url.includes("/gateway/routes")) return Promise.resolve(json({ routes: [] }));
        if (url.includes("/billing/entitlements")) return Promise.resolve(json({ entitlements: {} }));
        return Promise.resolve(json({ detail: url }, 500));
      }),
    );
    window.localStorage.setItem("rag_portal_token", "rag_sess_t");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");
    function Loc() {
      const { pathname } = useLocation();
      return <span data-testid="loc">{pathname}</span>;
    }
    render(
      <MemoryRouter initialEntries={["/agents/new"]}>
        <AuthProvider>
          <Routes>
            <Route path="/agents/new" element={<AgentBuilderPage />} />
          </Routes>
          <Loc />
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByLabelText("Propósito")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Crear agente" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Probar" })).toBeInTheDocument();
  });
});
