import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./Settings";

const AUTH = vi.hoisted(() => ({
  session: {
    token: "rag_sess_t",
    organizationId: "org-1",
    roles: ["owner"],
    permissions: [],
  },
  logout: vi.fn(),
}));

vi.mock("../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi(handlers: Array<[string, unknown]>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      for (const [fragment, body] of handlers) {
        if (url.includes(fragment)) return Promise.resolve(json(body));
      }
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const ORG_PROFILE = {
  name: "Omnio dev",
  company_name: "Omnio",
  country: "PE",
  email: "hola@omnio.pe",
  phone: "",
};

async function openWorkspaceTab() {
  const user = userEvent.setup();
  const tab = await screen.findByRole("tab", { name: /workspace/i });
  await user.click(tab);
  return user;
}

describe("SelfPurgePanel", () => {
  it("no aparece cuando el email no está en la allowlist", async () => {
    stubApi([
      ["/api/v1/organizations", ORG_PROFILE],
      ["/self-purge/status", { enabled: false, allowed: false, email: null }],
    ]);
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );
    await openWorkspaceTab();
    await waitFor(() =>
      expect(screen.getByText("Reinicio de datos")).toBeTruthy(),
    );
    expect(screen.queryByText("Borrado total de mi rastro")).toBeNull();
  });

  it("aparece, muestra el impacto y exige el email exacto", async () => {
    stubApi([
      ["/api/v1/organizations", ORG_PROFILE],
      [
        "/self-purge/status",
        { enabled: true, allowed: true, email: "ppimentel@omnio.pe" },
      ],
      [
        "/self-purge/preview",
        {
          tables: { company_entities: 17, audit_logs: 42 },
          tables_total: 2,
          truncated: false,
          total_rows: 59,
          uploads_bytes: 2048,
          dsr_artifacts: 0,
        },
      ],
    ]);
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );
    const user = await openWorkspaceTab();
    await waitFor(() =>
      expect(screen.getByText("Borrado total de mi rastro")).toBeTruthy(),
    );

    const button = screen.getByRole("button", { name: /borrar todo mi rastro/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);

    await user.click(screen.getByRole("button", { name: /ver impacto/i }));
    await waitFor(() => expect(screen.getByText("company_entities")).toBeTruthy());
    expect(screen.getByText("59 filas en 2 tablas · uploads 2.0 KB · artefactos DSR 0")).toBeTruthy();

    const input = screen.getByPlaceholderText("ppimentel@omnio.pe");
    await user.type(input, "ppimentel@omnio.pe");
    await waitFor(() =>
      expect((button as HTMLButtonElement).disabled).toBe(false),
    );
  });
});
