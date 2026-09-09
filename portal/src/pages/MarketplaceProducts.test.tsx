import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import MarketplaceProductsPage from "./MarketplaceProducts";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function fetchRouter() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/auth/me"))
      return Promise.resolve(
        json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] })
      );
    if (url.includes("/api/v1/products/installs"))
      return Promise.resolve(json({ installs: [] }));
    if (url.includes("/api/v1/products") && !url.includes("/installs"))
      return Promise.resolve(
        json({
          products: [
            {
              id: "p1",
              slug: "peru-verification-pack",
              name: "Verifica un negocio en Perú",
              short_description: "Check taxpayer status and company information.",
              product_type: "BUSINESS_PACK",
              version: 1,
              status: "PUBLISHED",
              category: "operations",
              pricing: { model: "FREE" },
              created_at: null,
              published_at: null,
            },
          ],
        })
      );
    return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
  });
}

describe("MarketplaceProducts", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchRouter());
  });

  it("muestra el catálogo de productos publicados (outcome first)", async () => {
    window.localStorage.setItem("rag_portal_token", "rag_sess_t");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");
    render(
      <MemoryRouter>
        <AuthProvider>
          <MarketplaceProductsPage />
        </AuthProvider>
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("product-catalog")).toBeInTheDocument());
    expect(screen.getByText("Verifica un negocio en Perú")).toBeInTheDocument();
    expect(screen.getByText("Check taxpayer status and company information.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Instalar/ })).toBeInTheDocument();
  });

  it("muestra la pestaña Instalados con el conteo del tab", async () => {
    const fetchMock = fetchRouter();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/me"))
        return Promise.resolve(
          json({ organization_id: "org-1", company_name: "Acme", email: "a@b.cl", roles: ["owner"], permissions: [] })
        );
      if (url.includes("/api/v1/products/installs"))
        return Promise.resolve(
          json({
            installs: [
              {
                id: "i1",
                product_id: "p1",
                product_version: 1,
                status: "active",
                installed_assets: { "dependency.integration.echo.install_id": "ins-1" },
                install_answers: {},
                created_at: "2026-09-09T10:00:00Z",
                product: { slug: "pack", name: "Pack Demo", product_type: "BUSINESS_PACK", short_description: null },
              },
            ],
          })
        );
      return Promise.resolve(json({ products: [] }));
    });
    vi.stubGlobal("fetch", fetchMock);

    window.localStorage.setItem("rag_portal_token", "rag_sess_t");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");
    render(
      <MemoryRouter>
        <AuthProvider>
          <MarketplaceProductsPage />
        </AuthProvider>
      </MemoryRouter>
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Instalados/ }));
    await waitFor(() => expect(screen.getByTestId("product-installs")).toBeInTheDocument());
    expect(screen.getByText("Pack Demo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Desinstalar/ })).toBeInTheDocument();
  });
});