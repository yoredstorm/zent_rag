import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { PublishQueryModal } from "./PublishQueryModal";

vi.mock("../../api", () => ({ api: vi.fn() }));
const { session } = vi.hoisted(() => ({
  session: { token: "test", organizationId: "org" },
}));
vi.mock("../../auth", () => ({
  useAuth: () => ({ session }),
}));

const mockedApi = vi.mocked(api);

describe("PublishQueryModal", () => {
  beforeEach(() => {
    mockedApi.mockReset();
  });

  it("no preselecciona columnas al elegir una tabla", async () => {
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/v1/connectors") {
        return Promise.resolve({
          connectors: [{ id: "c-1", name: "ERP", type: "postgres", status: "active" }],
        });
      }
      if (path.includes("/discover")) {
        return Promise.resolve({
          tables: [
            {
              schema: "catalog",
              name: "product_prices",
              is_view: false,
              columns: [
                { name: "sku", data_type: "text", is_primary_key: true },
                { name: "price", data_type: "numeric", is_primary_key: false },
              ],
            },
          ],
        });
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render(<PublishQueryModal open onOpenChange={() => undefined} onPublished={() => undefined} />);

    const connector = await screen.findByRole("combobox");
    await user.click(connector);
    await screen.findByRole("option", { name: "ERP" });
    await user.selectOptions(connector, "c-1");
    await user.click(screen.getByRole("button", { name: /Descubrir tablas/i }));

    const table = (await screen.findAllByRole("combobox")).at(-1) as HTMLSelectElement;
    await user.selectOptions(table, "catalog.product_prices");

    await waitFor(() => {
      expect(screen.getAllByText("sku").length).toBeGreaterThan(0);
      expect(screen.getAllByText("price").length).toBeGreaterThan(0);
    });
    const checks = screen.getAllByRole("checkbox");
    expect(checks.every((item) => !(item as HTMLInputElement).checked)).toBe(true);
  });
});
