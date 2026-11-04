import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CATEGORY_META, NODE_LIBRARY, nodeMeta } from "../lib/workflowGraph";
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

describe("NodeLibrary", () => {
  it("pone AI primero y el nodo de agente al tope de su grupo", () => {
    render(<NodeLibrary onAdd={() => undefined} usedTypes={[]} />);
    const buttons = screen.getAllByRole("button");
    const labels = buttons.map((b) => b.getAttribute("data-testid")).filter(Boolean);
    expect(labels[0]).toBe("wf-add-llm");
  });

  it("usa el catálogo backend: etiqueta y nodo deshabilitado con razón", () => {
    render(
      <NodeLibrary
        onAdd={() => undefined}
        usedTypes={[]}
        nodes={{
          ...NODE_LIBRARY,
          llm: {
            ...nodeMeta("llm"),
            label: "Agente backend",
            available: false,
            unavailableReason: "No hay agentes disponibles.",
          },
        }}
        categoryLabels={{ ai: "Inteligencia (backend)" }}
      />
    );
    const button = screen.getByTestId("wf-add-llm");
    expect(button).toHaveTextContent("Agente backend");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "No hay agentes disponibles.");
    expect(screen.getByRole("region", { name: "Inteligencia (backend)" })).toBeInTheDocument();
  });

  it("modo negocio agrupa por propósito y avanzado por categoría", () => {
    const { rerender } = render(
      <NodeLibrary onAdd={() => undefined} usedTypes={["trigger_webhook"]} businessMode />
    );
    expect(screen.getByRole("region", { name: "Entender" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Consultar" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Esperar" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Finalizar" })).toBeInTheDocument();
    expect(screen.queryByText("Empezar")).toBeNull();

    rerender(<NodeLibrary onAdd={() => undefined} usedTypes={["trigger_webhook"]} />);
    expect(screen.getByRole("region", { name: "AI & Agents" })).toBeInTheDocument();
  });
});

describe("NodeLibrary catálogo contextual", () => {
  beforeEach(() => window.localStorage.clear());

  it("filtra por categoría y busca también en la descripción", async () => {
    const user = userEvent.setup();
    const nodes = {
      ...NODE_LIBRARY,
      condition: { ...nodeMeta("condition"), description: "Bifurca según una regla de negocio" },
    };
    render(<NodeLibrary onAdd={() => undefined} usedTypes={["trigger_webhook"]} nodes={nodes} />);
    await user.click(screen.getByRole("button", { name: "AI & Agents" }));
    expect(screen.getByRole("region", { name: "AI & Agents" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: CATEGORY_META.logic.label })).toBeNull();
    await user.click(screen.getByRole("button", { name: "AI & Agents" }));
    await user.type(screen.getByLabelText("Buscar nodo"), "bifurca");
    expect(screen.getByTestId("wf-add-condition")).toHaveTextContent("Bifurca según una regla de negocio");
    expect(screen.queryByTestId("wf-add-llm")).toBeNull();
  });

  it("recuerda recientes y favoritos entre aperturas", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    const { unmount } = render(<NodeLibrary onAdd={onAdd} usedTypes={["trigger_webhook"]} />);
    await user.click(screen.getByTestId("wf-add-llm"));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ type: "llm" }));
    await user.click(screen.getByRole("button", { name: `Marcar ${nodeMeta("condition").label} como favorito` }));
    unmount();

    render(<NodeLibrary onAdd={onAdd} usedTypes={["trigger_webhook"]} />);
    expect(screen.getByTestId("wf-recent-llm")).toBeInTheDocument();
    expect(screen.getByTestId("wf-fav-condition")).toBeInTheDocument();
  });

  it("los nodos se arrastran con el tipo MIME del lienzo y Esc cierra el flyout", async () => {
    const onClose = vi.fn();
    render(<NodeLibrary onAdd={() => undefined} usedTypes={["trigger_webhook"]} onClose={onClose} autoFocus />);
    expect(screen.getByLabelText("Buscar nodo")).toHaveFocus();
    const setData = vi.fn();
    fireEvent.dragStart(screen.getByTestId("wf-add-llm"), { dataTransfer: { setData, effectAllowed: "" } });
    expect(setData).toHaveBeenCalledWith("application/x-zent-node", "llm");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});

describe("NodeLibrary marketplace", () => {
  it("muestra Installed con estado, costo y versión disponible", () => {
    render(<NodeLibrary onAdd={() => undefined} usedTypes={[]} marketplace={MKT} />);
    expect(screen.getByTestId("wf-capabilities")).toBeInTheDocument();
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

  it("una capacidad no instalada abre el Marketplace global", () => {
    render(
      <NodeLibrary
        onAdd={() => undefined}
        usedTypes={[]}
        marketplace={MKT}
        returnTo="/workflows/wf-1"
        nodeId="nodo-1"
      />
    );
    const link = screen.getByTestId("wf-mkt-install-reniec-verification");
    expect(link).toHaveTextContent("Resolver en Marketplace global");
    expect(link).toHaveAttribute("href", expect.stringContaining("/marketplace?"));
    expect(link.getAttribute("href")).toContain("return_to");
    expect(link.getAttribute("href")).not.toContain("http");
    expect(screen.queryByText("Agregar desde Marketplace")).toBeNull();
    expect(screen.getByText("Capacidades")).toBeInTheDocument();
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
    await user.type(screen.getByLabelText("Buscar nodo"), "taxpayer");
    expect(screen.getByTestId("wf-capabilities")).toBeInTheDocument();
    await user.click(screen.getByTestId("wf-mkt-action-peru.taxpayer.lookup"));
    expect(onAddMx).toHaveBeenCalled();
  });
});