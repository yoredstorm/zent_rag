import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlatformAuthProvider } from "../../platformAuth";
import SecurityPage from "./Security";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ROLES = {
  roles: [
    { id: "r1", name: "super_admin", description: null, is_system: true, permissions: ["*"] },
    { id: "r2", name: "read_only", description: null, is_system: true, permissions: ["tenant.read"] },
    { id: "r3", name: "support", description: null, is_system: true, permissions: ["tenant.read", "support.impersonate"] },
  ],
  count: 3,
};

const USERS = {
  users: [
    {
      id: "u-admin",
      email: "admin@zent.dev",
      is_platform_admin: true,
      roles: ["super_admin"],
      disabled_at: null,
    },
    {
      id: "u-read",
      email: "reader@zent.dev",
      is_platform_admin: true,
      roles: ["read_only"],
      disabled_at: null,
    },
  ],
  count: 2,
};

function fetchRouter() {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || "GET";
    if (url.includes("/auth/me")) return Promise.resolve(json({ permissions: ["*"], email: "admin@zent.dev" }));
    if (url.includes("/platform/users") && method === "POST" && !url.includes("/roles") && !url.includes("/deactivate") && !url.includes("/activate") && !url.includes("/password-reset")) {
      return Promise.resolve(json({ user_id: "u-new", email: "new@zent.dev", reset_token: "reset-token-once" }));
    }
    if (url.includes("/platform/roles")) return Promise.resolve(json(ROLES));
    if (url.includes("/platform/users")) return Promise.resolve(json(USERS));
    if (url.includes("/deactivate") || url.includes("/activate") || url.includes("/password-reset") || url.includes("/roles")) {
      return Promise.resolve(json({ ok: true, reset_token: "reset-token-once" }));
    }
    return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
  });
}

async function renderSecurity() {
  const fetchMock = fetchRouter();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.setItem("rag_platform_token", "rag_sess_plat");
  window.localStorage.setItem("rag_platform_email", "admin@zent.dev");
  render(
    <MemoryRouter initialEntries={["/control-center/security"]}>
      <PlatformAuthProvider>
        <Routes>
          <Route path="/control-center/security" element={<SecurityPage />} />
        </Routes>
      </PlatformAuthProvider>
    </MemoryRouter>
  );
  await screen.findByText("reader@zent.dev");
  return { user: userEvent.setup(), fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Security (Control Center)", () => {
  it("lista usuarios y muestra estado activo", async () => {
    await renderSecurity();
    expect(screen.getByText("reader@zent.dev")).toBeInTheDocument();
    expect(screen.getAllByText(/Activo/).length).toBeGreaterThan(0);
  });

  it("crea un usuario de plataforma y muestra el reset token", async () => {
    const { user, fetchMock } = await renderSecurity();
    // Selecciona el rol read_only primero para evitar required vacío.
    await user.selectOptions(screen.getByLabelText("Rol inicial"), "read_only");
    await user.type(screen.getByPlaceholderText("usuario@zent.dev"), "new@zent.dev");
    await user.click(screen.getByRole("button", { name: "Crear usuario" }));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url, init]) =>
        String(url).endsWith("/platform/users") && (init?.method || "GET") === "POST"
      );
      expect(calls.length).toBe(1);
      expect(JSON.parse(String(calls[0][1]?.body || "{}"))).toEqual({
        email: "new@zent.dev",
        role_name: "read_only",
      });
    });
    expect(screen.getByText(/reset-token-once/)).toBeInTheDocument();
  });

  it("desactiva un usuario y lo marca como suspendido", async () => {
    const { user } = await renderSecurity();
    const actionsButtons = screen.getAllByRole("button", { name: "Acciones" });
    expect(actionsButtons.length).toBe(2);
    await user.click(actionsButtons[1]); // reader@zent.dev
    await user.click(await screen.findByRole("menuitem", { name: /Desactivar/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/Desactivar a reader@zent.dev/);
    await user.click(within(dialog).getByRole("button", { name: "Desactivar" }));
    await waitFor(() => expect(screen.getByText(/reader@zent.dev desactivado/)).toBeInTheDocument());
  });

  it("asigna un rol abriendo el diálogo de selección", async () => {
    const { user } = await renderSecurity();
    const actionsButtons = screen.getAllByRole("button", { name: "Acciones" });
    await user.click(actionsButtons[1]);
    await user.click(await screen.findByRole("menuitem", { name: /Asignar rol/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/Asignar rol a reader@zent.dev/);
  });
});
