import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import MarketplacePage from "./MarketplacePage";
import { NAV_GROUPS, navLeaves } from "../../lib/nav";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const PRODUCTS = [
  {
    id: "p-izipay",
    slug: "product-izipay",
    name: "IZIPAY Payments",
    short_description: "Cobros y pagos digitales para negocios en Perú.",
    product_type: "INTEGRATION",
    version: 2,
    status: "PUBLISHED",
    category: "payments",
    applies_to: ["WORKFLOWS", "AGENTS", "PAYMENTS"],
    capabilities: ["payments.checkout.create"],
    logo: null,
    certification: "zent",
    publisher: "IZIPAY",
    pricing: { model: "SUBSCRIPTION", amount: 29, currency: "PEN", interval: "MONTH" },
    published_at: null,
  },
  {
    id: "p-echo",
    slug: "product-demo-echo",
    name: "Demo Echo",
    short_description: "Integración de demostración sin credenciales.",
    product_type: "INTEGRATION",
    version: 1,
    status: "PUBLISHED",
    category: "demo",
    applies_to: ["WORKFLOWS"],
    capabilities: ["echo"],
    logo: null,
    certification: null,
    publisher: "Zent",
    pricing: { model: "FREE" },
    published_at: null,
  },
];

const INSTALLS = [
  {
    id: "inst-1",
    product_id: "p-echo",
    product_version: 1,
    status: "active",
    readiness: "READY",
    health: { state: "ok", workflows: 3, agents: 1, last_used_at: new Date().toISOString() },
    last_used_at: new Date().toISOString(),
    update_available: false,
    latest_version: 1,
    installed_assets: {},
    created_at: new Date().toISOString(),
    product: {
      slug: "product-demo-echo",
      name: "Demo Echo",
      product_type: "INTEGRATION",
      short_description: "Integración de demostración sin credenciales.",
      category: "demo",
      applies_to: ["WORKFLOWS"],
      logo: null,
      status: "PUBLISHED",
    },
  },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi(installs = INSTALLS) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/products/installs")) return Promise.resolve(json({ installs }));
      if (url.includes("/api/v1/products/categories")) {
        return Promise.resolve(
          json({
            categories: [
              { key: "payments", count: 1 },
              { key: "demo", count: 1 },
            ],
            applies_to: [
              { key: "WORKFLOWS", count: 2 },
              { key: "AGENTS", count: 1 },
            ],
            pricing_models: [{ key: "FREE", count: 1 }],
            product_types: [{ key: "INTEGRATION", count: 2 }],
          })
        );
      }
      if (url.includes("/api/v1/products/")) {
        const id = url.split("/api/v1/products/")[1]?.split("?")[0];
        const product = PRODUCTS.find((p) => p.id === id);
        if (init?.method === "POST") return Promise.resolve(json({ install_id: "inst-2", reused: false, status: "active", readiness: "READY" }));
        return Promise.resolve(json(product ?? {}));
      }
      if (url.includes("/api/v1/products")) return Promise.resolve(json({ products: PRODUCTS }));
      return Promise.resolve(json({}));
    })
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("MarketplacePage", () => {
  it("muestra el catálogo con precio real y estado de instalación", async () => {
    stubApi();
    render(
      <MemoryRouter>
        <MarketplacePage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("marketplace-grid")).toBeInTheDocument());
    expect(screen.getByText("IZIPAY Payments")).toBeInTheDocument();
    expect(screen.getByText("S/ 29 / mes")).toBeInTheDocument();
    expect(screen.getByText("Gratis")).toBeInTheDocument();
    expect(
      screen.getByText("Cobros y pagos digitales para negocios en Perú.")
    ).toBeInTheDocument();
  });

  it("filtra por búsqueda en la pestaña Todos", async () => {
    stubApi();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <MarketplacePage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("marketplace-grid")).toBeInTheDocument());
    await user.click(screen.getByRole("tab", { name: /Todos/ }));
    await user.type(screen.getByLabelText("Buscar productos"), "izipay");
    await waitFor(() => expect(screen.queryByText("Demo Echo")).toBeNull());
    expect(screen.getByText("IZIPAY Payments")).toBeInTheDocument();
  });

  it("instala desde la tarjeta y refleja la biblioteca de instalados", async () => {
    stubApi([]);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <MarketplacePage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("marketplace-grid")).toBeInTheDocument());
    const installButtons = screen.getAllByRole("button", { name: "Instalar" });
    await user.click(installButtons[0]!);
    await waitFor(() => {
      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) =>
        String(c[0])
      );
      expect(calls.some((u) => u.includes("/api/v1/products/") && u.includes("/install"))).toBe(true);
    });
  });

  it("la pestaña Instalados muestra salud real (uso y última llamada)", async () => {
    stubApi();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <MarketplacePage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("marketplace-grid")).toBeInTheDocument());
    await user.click(screen.getByRole("tab", { name: /Instalados/ }));
    await waitFor(() => expect(screen.getByTestId("marketplace-installed")).toBeInTheDocument());
    expect(screen.getByText(/Usado por 3 workflows · 1 agentes/)).toBeInTheDocument();
  });

  it("el nav principal tiene UNA sola entrada de marketplace y ninguna de /products", () => {
    const leaves = NAV_GROUPS.flatMap((group) => navLeaves(group));
    const marketplace = leaves.filter((leaf) => leaf.to === "/marketplace");
    expect(marketplace).toHaveLength(1);
    expect(leaves.some((leaf) => leaf.to === "/products")).toBe(false);
  });
});
