import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NodeLibrary, type MarketplaceContext } from "./NodeLibrary";

const MKT: MarketplaceContext = {
  installed: [
    {
      install_id: "i1",
      integration: { slug: "sunat", name: "SUNAT" },
      installed_version: 1,
      manifest_version: 2,
      status: ["connected", "version_update"],
      actions: [
        { action_id: "peru.taxpayer.lookup", display_name: "Lookup Taxpayer", description: null, cost: { model: "PER_CALL", price: 0.02, currency: "PEN" }, renderer: "taxpayer_verification" },
      ],
    },
  ],
  available: [
    {
      slug: "reniec-verification",
      name: "RENIEC Identity Verification",
      description: "Verifica identidad en Perú.",
      requires_credentials: true,
      actions: [{ action_id: "peru.identity.verify", display_name: "Verify Identity", description: null, cost: { model: "PER_CALL", price: 0.05, currency: "PEN" }, renderer: "identity_verification" }],
    },
  ],
  recommendations: [
    { action_id: "peru.taxpayer.lookup", integration_slug: "sunat", reason: "El grafo menciona RUC.", require_install: true },
  ],
  costs: [],
};

describe("NodeLibrary marketplace", () => {
  it("muestra Installed con estado, costo y versión disponible", () => {
    render(<NodeLibrary onAdd={() => undefined} usedTypes={[]} marketplace={MKT} />);
    expect(screen.getByTestId("wf-mkt-section")).toBeInTheDocument();
    expect(screen.getByText("SUNAT")).toBeInTheDocument();
    expect(screen.getByText("conectado")).toBeInTheDocument();
    expect(screen.getByText(/v1 · v2 disponible/)).toBeInTheDocument();
    expect(screen.getByTestId("wf-mkt-action-peru.taxpayer.lookup")).toHaveTextContent(/S\/ 0.02/);
  });

  it("añade la acción instalada al canvas", async () => {
    const onAdd = vi.fn();
    render(<NodeLibrary onAdd={() => undefined} usedTypes={[]} marketplace={MKT} onAddMarketplaceAction={onAdd} />);
    await userEvent.click(screen.getByTestId("wf-mkt-action-peru.taxpayer.lookup"));
    expect(onAdd).toHaveBeenCalledWith("i1", expect.objectContaining({ action_id: "peru.taxpayer.lookup" }));
  });

  it("abre el drawer para una capacidad disponible", async () => {
    const onInstall = vi.fn();
    render(<NodeLibrary onAdd={() => undefined} usedTypes={[]} marketplace={MKT} onInstall={onInstall} />);
    expect(screen.getByTestId("wf-mkt-available")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("wf-mkt-install-reniec-verification"));
    expect(onInstall).toHaveBeenCalledWith("reniec-verification");
  });

  it("muestra la recomendación del grafo", () => {
    render(<NodeLibrary onAdd={() => undefined} usedTypes={[]} marketplace={MKT} />);
    expect(screen.getByTestId("wf-mkt-recommend")).toBeInTheDocument();
    expect(screen.getByText("Recomendado")).toBeInTheDocument();
    expect(screen.getByTestId("wf-mkt-add-peru.taxpayer.lookup")).toBeInTheDocument();
  });

  it("muestra el nodo business en su sección y busca por término de marketplace (taxpayer)", async () => {
    const onAddMx = vi.fn();
    render(<NodeLibrary onAdd={() => undefined} usedTypes={[]} marketplace={MKT} onAddMarketplaceAction={onAddMx} />);
    expect(screen.getByTestId("wf-add-business_node")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Buscar nodo, RUC, SUNAT…"), "taxpayer");
    expect(screen.getByTestId("wf-mkt-section")).toBeInTheDocument();
    await user.click(screen.getByTestId("wf-mkt-action-peru.taxpayer.lookup"));
    expect(onAddMx).toHaveBeenCalled();
  });
});