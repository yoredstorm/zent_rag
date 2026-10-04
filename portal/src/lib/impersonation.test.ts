import { afterEach, describe, expect, it, vi } from "vitest";
import { clearSession, loadSession } from "../api";
import { IMPERSONATING_KEY, PLATFORM_TOKEN_KEY } from "../platformAuth";
import {
  closeTenantSession,
  enterTenantSession,
  exitImpersonationToPlatform,
  hasPlatformSession,
  isImpersonating,
} from "./impersonation";

function enterAsAcme(navigate = vi.fn()) {
  enterTenantSession({
    token: "rag_sess_test",
    organizationId: "org-1",
    companyName: "Acme",
    email: "admin@acme.test",
    reason: "pruebas",
    expiresSeconds: 60,
    navigate,
  });
  return navigate;
}

function stubExited() {
  return vi.fn(async (_url: string, _init: RequestInit) => {
    return new Response(JSON.stringify({ status: "exited" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
}

describe("cambio de pantalla Control Center ⇄ portal", () => {
  afterEach(() => {
    clearSession();
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("enterTenantSession guarda la sesión portal, el banner y navega a /", () => {
    const navigate = enterAsAcme();

    expect(sessionStorage.getItem("rag_portal_token")).toBe("rag_sess_test");
    expect(loadSession()?.organizationId).toBe("org-1");
    expect(loadSession()?.companyName).toBe("Acme");
    expect(sessionStorage.getItem(IMPERSONATING_KEY)).toBe("Acme");
    expect(isImpersonating()).toBe("Acme");
    expect(navigate).toHaveBeenCalledWith("/");
  });

  it("exitImpersonationToPlatform revoca, limpia y vuelve al Control Center", async () => {
    enterAsAcme();
    const fetchMock = stubExited();
    vi.stubGlobal("fetch", fetchMock);
    const navigate = vi.fn();

    await exitImpersonationToPlatform({
      returnTo: "/control-center/settings",
      navigate,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/impersonation/exit");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer rag_sess_test");
    expect(loadSession()).toBeNull();
    expect(isImpersonating()).toBeNull();
    expect(navigate).toHaveBeenCalledWith("/control-center/settings");
  });

  it("closeTenantSession cierra solo el portal y conserva la sesión de plataforma", async () => {
    localStorage.setItem(PLATFORM_TOKEN_KEY, "rag_platform_test");
    enterAsAcme();
    const fetchMock = stubExited();
    vi.stubGlobal("fetch", fetchMock);

    await closeTenantSession();

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/logout");
    expect(loadSession()).toBeNull();
    expect(isImpersonating()).toBeNull();
    expect(hasPlatformSession()).toBe(true);
  });

  it("hasPlatformSession refleja el token de plataforma", () => {
    expect(hasPlatformSession()).toBe(false);
    localStorage.setItem(PLATFORM_TOKEN_KEY, "rag_platform_test");
    expect(hasPlatformSession()).toBe(true);
  });
});
