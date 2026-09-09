import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  it("elige blank y persiste el workspace business", async () => {
    window.sessionStorage.setItem("rag_portal_token", "rag_sess_start");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");
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

    await screen.findByRole("button", { name: /Empezar de cero/i });
    await userEvent.click(screen.getByTestId("start-mode-blank"));
    await waitFor(() => {
      expect(window.localStorage.getItem("rag_portal_workspace")).toBe("ws-blank");
      expect(window.localStorage.getItem("rag_portal_workspace_kind")).toBe("business");
    });
  });
});
