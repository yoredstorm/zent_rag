import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlatformAuthProvider, usePlatformAuth } from "./platformAuth";

function Probe({ onReady }: { onReady: (a: ReturnType<typeof usePlatformAuth>) => void }) {
  const auth = usePlatformAuth();
  useEffect(() => {
    onReady(auth);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth]);
  return <span data-testid="session">{auth.session ? auth.session.email : "none"}</span>;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("PlatformAuthProvider (Control Center)", () => {
  it("carga la sesión desde localStorage", () => {
    window.localStorage.setItem("rag_platform_token", "rag_sess_plat");
    window.localStorage.setItem("rag_platform_email", "admin@zent.dev");
    render(
      <PlatformAuthProvider>
        <Probe onReady={() => {}} />
      </PlatformAuthProvider>
    );
    expect(screen.getByTestId("session").textContent).toBe("admin@zent.dev");
  });

  it("login de plataforma persiste token y email", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        json({ access_token: "rag_sess_plat2", email: "admin@zent.dev" })
      )
    );
    let captured: ReturnType<typeof usePlatformAuth> | null = null;
    render(
      <PlatformAuthProvider>
        <Probe onReady={(a) => (captured = a)} />
      </PlatformAuthProvider>
    );
    expect(captured).not.toBeNull();

    await captured!.login("admin@zent.dev", "secret");
    expect(window.localStorage.getItem("rag_platform_token")).toBe("rag_sess_plat2");
    await waitFor(() => expect(screen.getByTestId("session").textContent).toBe("admin@zent.dev"));
  });

  it("logout limpia la sesión de plataforma", async () => {
    window.localStorage.setItem("rag_platform_token", "rag_sess_plat");
    window.localStorage.setItem("rag_platform_email", "admin@zent.dev");
    let captured: ReturnType<typeof usePlatformAuth> | null = null;
    render(
      <PlatformAuthProvider>
        <Probe onReady={(a) => (captured = a)} />
      </PlatformAuthProvider>
    );
    expect(captured).not.toBeNull();

    await captured!.logout();
    expect(window.localStorage.getItem("rag_platform_token")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("session").textContent).toBe("none"));
  });
});