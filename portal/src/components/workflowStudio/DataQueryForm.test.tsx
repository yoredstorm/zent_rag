import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { DataQueryForm } from "./DataQueryForm";

vi.mock("../../api", () => ({ api: vi.fn() }));
const { session } = vi.hoisted(() => ({
  session: { token: "test", organizationId: "org" },
}));
vi.mock("../../auth", () => ({
  useAuth: () => ({ session }),
}));

const mockedApi = vi.mocked(api);

const plan = {
  binding_ref: "binding-1",
  capability_ref: "p19.price.lookup",
  resource_ref: "public.p19_prices",
  resource_kind: "table",
  operation: "get_one",
  projection: ["sku", "price", "currency"],
  max_rows: 1,
  parameters: [
    {
      name: "sku",
      field: "sku",
      operator: "eq",
      type: "string",
      required: true,
      label: "sku",
    },
  ],
  ownership_required: false,
  pii_class: "internal",
};

function Harness({ dataSources }: { dataSources?: Parameters<typeof DataQueryForm>[0]["dataSources"] }) {
  const [config, setConfig] = useState<Record<string, unknown>>({ params: {} });
  return (
    <DataQueryForm
      config={config}
      onChange={(patch) => setConfig((current) => ({ ...current, ...patch }))}
      dataSources={dataSources}
    />
  );
}

describe("DataQueryForm", () => {
  beforeEach(() => {
    mockedApi.mockReset();
  });

  it("muestra un estado vacío accionable si no hay planes", async () => {
    mockedApi.mockResolvedValue({ plans: [] });
    render(<Harness />);
    expect(await screen.findByTestId("wf-dq-empty")).toBeInTheDocument();
    expect(screen.getByText(/No hay consultas publicadas/i)).toBeInTheDocument();
  });

  it("selecciona un plan, llena el parámetro y prueba la lectura", async () => {
    mockedApi.mockImplementation((path: string) => {
      if (path.includes("data-query/plans")) return Promise.resolve({ plans: [plan] });
      return Promise.resolve({
        preview: true,
        redacted_fields: [],
        result: {
          status: "FOUND",
          found: true,
          record: { sku: "ARR-001", price: "5.00", currency: "PEN" },
          row_count: 1,
          source_ref: "public.p19_prices",
          duration_ms: 12,
        },
      });
    });
    const user = userEvent.setup();
    render(<Harness />);

    const select = await screen.findByTestId("wf-dq-plan");
    await user.selectOptions(select, "binding-1");
    expect(await screen.findByText(/Devuelve: sku, price, currency/i)).toBeInTheDocument();

    const sku = await screen.findByTestId("wf-dq-param-sku");
    await user.type(sku, "ARR-001");
    await user.click(screen.getByRole("button", { name: /Probar lectura/i }));

    await waitFor(() => {
      expect(screen.getByTestId("wf-dq-preview-result")).toBeInTheDocument();
    });
    expect(screen.getByText(/FOUND/)).toBeInTheDocument();
    expect(screen.getAllByText(/public.p19_prices/).length).toBeGreaterThan(0);
  });

  it("inserta una referencia de otro nodo con un clic", async () => {
    mockedApi.mockResolvedValue({ plans: [plan] });
    const user = userEvent.setup();
    render(
      <Harness
        dataSources={[
          {
            id: "intent",
            label: "Identificar solicitud",
            kind: "node",
            fields: [
              {
                key: "sku",
                label: "SKU",
                ref: "{{nodes.intent.output.entities.sku}}",
                type: "text",
              },
            ],
          },
        ]}
      />,
    );
    const select = await screen.findByTestId("wf-dq-plan");
    await user.selectOptions(select, "binding-1");
    await user.click(await screen.findByTestId("wf-dq-pick-sku"));
    await user.click(await screen.findByTestId("wf-dq-pick-sku-field-intent-sku"));
    expect(screen.getByTestId("wf-dq-param-sku")).toHaveValue(
      "{{nodes.intent.output.entities.sku}}",
    );
  });
});
