import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../auth";
import StartModePage from "./StartMode";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("StartModePage", () => {
  it("provisiona el workspace vacío solo, sin preguntar nada", async () => {
    window.sessionStorage.setItem("rag_portal_token", "rag_sess_start");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");
    let startModeCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/me")) {
        return json({
          organization_id: "org-1",
          company_name: "Acme",
          email: "a@b.cl",
          roles: ["owner"],
          permissions: ["workspaces:write"],
          needs_start_mode: true,
          active_workspace_id: null,
          workspace_kind: null,
        });
      }
      if (url.includes("/onboarding/start-mode")) {
        startModeCalls += 1;
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ mode: "blank" });
        return json({
          workspace_id: "ws-blank",
          kind: "business",
          needs_start_mode: false,
        });
      }
      return json({ detail: url }, 500);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <AuthProvider>
          <StartModePage />
        </AuthProvider>
      </MemoryRouter>
    );

    // Sin elección: la pantalla muestra el estado de preparación y resuelve sola.
    expect(await screen.findByText(/Preparando tu espacio de trabajo/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(window.localStorage.getItem("rag_portal_workspace")).toBe("ws-blank");
      expect(window.localStorage.getItem("rag_portal_workspace_kind")).toBe("business");
    });
    expect(startModeCalls).toBe(1);
  });
});
