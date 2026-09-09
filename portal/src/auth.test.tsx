import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./auth";
import type { ReactNode } from "react";

function fetchRouter(routes: Record<string, (_init: RequestInit) => Response>) {
  return vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    for (const [pattern, handler] of Object.entries(routes)) {
      if (url.includes(pattern)) return handler(_init || {});
    }
    return new Response(JSON.stringify({ detail: "not mocked: " + url }), { status: 500 });
  });
}

function Probe({ onReady }: { onReady: (auth: ReturnType<typeof useAuth>) => void }) {
  const auth = useAuth();
  useEffect(() => {
    onReady(auth);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth]);
  return <span data-testid="session">{auth.session ? auth.session.email || "sess" : "none"}</span>;
}

function wrap(node: ReactNode) {
  return <AuthProvider>{node}</AuthProvider>;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("AuthProvider", () => {
  it("revalida la sesión existente contra /me al montar", async () => {
    window.localStorage.setItem("rag_portal_token", "rag_sess_valid");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");
    const fetchMock = fetchRouter({
      "/auth/me": () => json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: ["*"] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(wrap(<Probe onReady={() => {}} />));
    await waitFor(() => expect(screen.getByTestId("session").textContent).toBe("a@b.cl"));
    expect(window.localStorage.getItem("rag_portal_roles")).toContain("owner");
  });

  it("borra la sesión cuando /me falla (token inválido o revocado)", async () => {
    window.localStorage.setItem("rag_portal_token", "rag_sess_expired");
    window.localStorage.setItem("rag_portal_org", "org-1");
    vi.stubGlobal("fetch", fetchRouter({ "/auth/me": () => json({ detail: "invalid" }, 401) }));

    render(wrap(<Probe onReady={() => {}} />));
    await waitFor(() => expect(screen.getByTestId("session").textContent).toBe("none"));
    expect(window.localStorage.getItem("rag_portal_token")).toBeNull();
  });

  it("login: intercambia credenciales por sesión y persiste roles", async () => {
    const fetchMock = fetchRouter({
      "/auth/login": () => json({ access_token: "rag_sess_new", organization_id: "org-9", company_name: "Beta", email: "u@b.cl" }),
      "/auth/me": () => json({ organization_id: "org-9", company_name: "Beta", email: "u@b.cl", roles: ["admin"], permissions: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    let captured: ReturnType<typeof useAuth> | null = null;
    render(wrap(<Probe onReady={(a) => (captured = a)} />));
    expect(captured).not.toBeNull();
    expect(captured!.login).toBeTypeOf("function");

    // Llamamos login directamente vía el test
    const auth = captured!;
    await auth.login("u@b.cl", "password123");
    await waitFor(() => expect(screen.getByTestId("session").textContent).toBe("u@b.cl"));
    expect(window.sessionStorage.getItem("rag_portal_token")).toBe("rag_sess_new");
    expect(window.localStorage.getItem("rag_portal_org")).toBe("org-9");
    expect(window.localStorage.getItem("rag_portal_roles")).toContain("admin");
  });

  it("logout: revoca en el servidor y limpia el almacenamiento", async () => {
    window.localStorage.setItem("rag_portal_token", "rag_sess_x");
    window.localStorage.setItem("rag_portal_org", "org-1");
    const logoutCalled = vi.fn();
    const fetchMock = fetchRouter({
      "/auth/me": () => json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] }),
      "/auth/logout": (_init) => {
        logoutCalled();
        return json({ status: "logged_out" });
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    let captured: ReturnType<typeof useAuth> | null = null;
    render(wrap(<Probe onReady={(a) => (captured = a)} />));
    expect(captured).not.toBeNull();

    await captured!.logout();
    expect(logoutCalled).toHaveBeenCalled();
    expect(window.localStorage.getItem("rag_portal_token")).toBeNull();
  });

  it("signup: guarda la API key one-time en sessionStorage", async () => {
    const fetchMock = fetchRouter({
      "/auth/signup": () =>
        json({ access_token: "rag_sess_su", organization_id: "org-2", company_name: "Nueva", email: "n@b.cl", api_key: "zent_sk_live_secret" }),
      "/auth/me": () =>
        json({
          organization_id: "org-2",
          company_name: "Nueva",
          email: "n@b.cl",
          roles: ["owner"],
          permissions: [],
          needs_start_mode: true,
          active_workspace_id: null,
          workspace_kind: null,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    let captured: ReturnType<typeof useAuth> | null = null;
    render(wrap(<Probe onReady={(a) => (captured = a)} />));
    expect(captured).not.toBeNull();

    await captured!.signup("Nueva", "n@b.cl", "password123");
    expect(window.sessionStorage.getItem("zent_signup_api_key")).toBe("zent_sk_live_secret");
    expect(window.sessionStorage.getItem("rag_portal_token")).toBe("rag_sess_su");
    await waitFor(() => expect(captured!.session?.needsStartMode).toBe(true));
  });
});