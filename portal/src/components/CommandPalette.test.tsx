import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandPaletteRoot } from "./CommandPalette";

const SESSION = {
  token: "rag_sess_t",
  organizationId: "org-1",
  companyName: "Acme",
  email: "a@b.cl",
  roles: ["owner"],
  permissions: [],
};

vi.mock("../auth", () => ({
  useAuth: () => ({ session: SESSION }),
}));

vi.mock("../platformAuth", () => ({
  usePlatformAuth: () => ({ session: null }),
}));

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="path">{location.pathname}</span>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CommandPaletteRoot (modo tenant)", () => {
  it("abre con Ctrl+K y permite navegar con Enter", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("entitlements")) return Promise.resolve(json({ entitlements: { eval_ui: true } }));
        if (url.includes("/agents")) return Promise.resolve(json({ agents: [{ id: "a1", name: "Soporte" }] }));
        if (url.includes("/sources")) return Promise.resolve(json({ sources: [] }));
        if (url.includes("/deployments")) return Promise.resolve(json({ deployments: [] }));
        return Promise.resolve(json({}));
      })
    );

    render(
      <MemoryRouter initialEntries={["/"]}>
        <CommandPaletteRoot mode="tenant" />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.keyboard("{Control>}k{/Control}");
    const input = await screen.findByPlaceholderText(/Buscar páginas, agentes/);
    await user.type(input, "Soporte");
    await waitFor(() => expect(screen.getByRole("option")).toHaveTextContent("Soporte"));
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("path").textContent).toBe("/agents/a1"));
  });

  it("Escape cierra la paleta", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json({ agents: [], sources: [], deployments: [], entitlements: {} }))));
    render(
      <MemoryRouter>
        <CommandPaletteRoot mode="tenant" />
      </MemoryRouter>
    );
    await user.keyboard("{Control>}k{/Control}");
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});