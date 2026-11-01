import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { IntentRouteForm } from "./IntentRouteForm";

vi.mock("../../api", () => ({ api: vi.fn() }));
const { session } = vi.hoisted(() => ({
  session: { token: "test", organizationId: "org" },
}));
vi.mock("../../auth", () => ({ useAuth: () => ({ session }) }));

const mockedApi = vi.mocked(api);

function Harness() {
  const [config, setConfig] = useState<Record<string, unknown>>({});
  return (
    <IntentRouteForm
      config={config}
      onChange={(patch) => setConfig((current) => ({ ...current, ...patch }))}
    />
  );
}

describe("IntentRouteForm", () => {
  beforeEach(() => mockedApi.mockReset());

  it("muestra las rutas cerradas y prueba una frase", async () => {
    mockedApi.mockResolvedValue({
      intent: "price_lookup",
      confidence: 0.9,
      entities: { product_name: "arroz" },
      missing_slots: [],
      route: "price_lookup",
      decision_source: "rules",
      reason_codes: ["RULES_MATCH"],
      requires_identity_verification: false,
    });
    const user = userEvent.setup();
    render(<Harness />);

    expect(screen.getByLabelText("Reconocer price_lookup")).toBeInTheDocument();
    expect(screen.getByLabelText("Reconocer order_status")).toBeInTheDocument();

    await user.type(screen.getByTestId("wf-intent-text"), "¿Cuánto cuesta el arroz?");
    await user.click(screen.getByTestId("wf-intent-test"));

    await waitFor(() => expect(screen.getByTestId("wf-intent-result")).toBeInTheDocument());
    expect(screen.getAllByText("price_lookup").length).toBeGreaterThan(0);
    expect(screen.getByText(/RULES_MATCH/)).toBeInTheDocument();
  });
});
