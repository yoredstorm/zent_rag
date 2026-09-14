import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import IntegrationsPage from "./IntegrationsPage";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../auth", () => ({ useAuth: () => AUTH }));

const DRAFT = {
  draft_id: "draft-1",
  slug: "acme-commerce",
  name: "Acme Commerce",
  status: "draft",
  base_url: "https://example.com/api",
  source_kind: "document",
  actions: 1,
  auth: { kind: "none" },
};

const DRAFT_DETAIL = {
  ...DRAFT,
  report: { operations_total: 1, actions_generated: 1, warnings: [], skipped: [] },
  draft: {
    description: "",
    base_url: "https://example.com/api",
    auth: { kind: "none", notes: [] },
    capabilities: [
      {
        slug: "clientes",
        name: "Clientes",
        actions: [
          {
            action_id: "acme-commerce.getcustomerbyid",
            display_name: "Obtener cliente",
            method: "GET",
            path_template: "/customers/{id}",
            read_only: true,
            enabled: true,
          },
        ],
      },
    ],
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v1/integrations/installs")) return Promise.resolve(json({ installs: [] }));
      if (url.endsWith("/api/v1/integrations/drafts/draft-1")) {
        if (init?.method === "DELETE") return Promise.resolve(json({ discarded: true }));
        return Promise.resolve(json(DRAFT_DETAIL));
      }
      if (url.endsWith("/api/v1/integrations/drafts")) return Promise.resolve(json({ drafts: [DRAFT] }));
      if (url.endsWith("/api/v1/workflows/marketplace/context")) return Promise.resolve(json({ installed: [] }));
      if (url.endsWith("/api/v1/integrations/import/openapi")) {
        return Promise.resolve(json({ draft_id: "draft-1" }, 201));
      }
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("IntegrationsPage", () => {
  it("lista instalaciones vacías y borradores, y abre la revisión", async () => {
    stubApi();
    const user = userEvent.setup();
    render(<MemoryRouter><IntegrationsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("api-installed-empty")).toBeInTheDocument());

    await user.click(screen.getByTestId("api-tab-drafts"));
    await waitFor(() => expect(screen.getByTestId("api-draft-acme-commerce")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Revisar" }));
    await waitFor(() => expect(screen.getByTestId("api-review")).toBeInTheDocument());
    expect(screen.getByTestId("api-review-label-acme-commerce.getcustomerbyid")).toBeInTheDocument();
    expect(screen.queryByText("/customers/{id}")).toBeNull(); // técnico oculto por defecto
  });

  it("importa un documento OpenAPI y muestra el borrador", async () => {
    stubApi();
    const user = userEvent.setup();
    render(<MemoryRouter><IntegrationsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("api-import-open")).toBeInTheDocument());
    await user.click(screen.getByTestId("api-import-open"));
    await user.type(screen.getByTestId("api-import-url"), "https://example.com/openapi.json");
    await user.click(screen.getByTestId("api-import-submit"));
    await waitFor(() => expect(screen.getByTestId("api-review")).toBeInTheDocument());
  });
});
