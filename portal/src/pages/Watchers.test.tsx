import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import WatchersPage from "./Watchers";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../auth", () => ({ useAuth: () => AUTH }));

const WATCHER = {
  id: "w1",
  name: "Stock bajo",
  entity: "producto",
  strategy: "watermark_polling",
  table_name: "inventory",
  primary_key: "id",
  timestamp_field: null,
  selected_fields: ["stock"],
  condition: { field: "stock", operator: "<", value: 10 },
  transition_mode: "on_enter",
  interval_seconds: 300,
  cooldown_seconds: 3600,
  debounce_seconds: 0,
  event_type: "inventory.stock.low",
  workflow_id: "wf-1",
  status: "listening",
  last_check_at: null,
};

const STATE = {
  last_value: { stock: 8 },
  last_condition_result: true,
  last_triggered_at: "2026-09-13T13:44:00Z",
  cooldown_until: null,
  failure_count: 0,
  last_error: null,
  check_count: 3,
  trigger_count: 1,
};

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stubApi(outcome: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/workflows/watchers") && method === "GET") return Promise.resolve(json({ watchers: [WATCHER] }));
      if (url.includes("/workflows/watchers/w1/state")) return Promise.resolve(json(STATE));
      if (url.includes("/workflows/watchers/w1/check") && method === "POST") return Promise.resolve(json(outcome));
      if (url.endsWith("/api/v1/workflows")) return Promise.resolve(json({ workflows: [{ id: "wf-1", name: "Alerta stock", status: "active" }] }));
      if (url.includes("/event-catalog")) {
        return Promise.resolve(
          json({
            categories: [
              {
                key: "inventario",
                label: "Inventario",
                events: [{ id: "inventory.stock.low", business_name: "El stock bajó del mínimo" }],
              },
            ],
          }),
        );
      }
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WatchersPage", () => {
  it("lista vigilancias con condición legible y estado", async () => {
    stubApi({ status: "triggered", reason: "Workflow activado: la condición empezó a cumplirse.", triggered: true, transition: "false_to_true", after: { stock: 8 } });
    render(<MemoryRouter><WatchersPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("watcher-card")).toBeInTheDocument());
    expect(screen.getByText(/stock es menor que 10/)).toBeInTheDocument();
    expect(screen.getByText(/Activaciones: 1/)).toBeInTheDocument();
  });

  it("Revisar ahora muestra el motivo humano", async () => {
    stubApi({ status: "condition_false", reason: "No se ejecutó porque la condición no se cumple.", triggered: false, transition: null, after: { stock: 12 } });
    const user = userEvent.setup();
    render(<MemoryRouter><WatchersPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("watcher-check-w1")).toBeInTheDocument());
    await user.click(screen.getByTestId("watcher-check-w1"));
    await waitFor(() =>
      expect(screen.getByTestId("watcher-outcome")).toHaveTextContent("No se ejecutó porque la condición no se cumple."),
    );
  });

  it("abre el formulario de nueva vigilancia", async () => {
    stubApi({ status: "no_change", reason: "", triggered: false, transition: null, after: {} });
    const user = userEvent.setup();
    render(<MemoryRouter><WatchersPage /></MemoryRouter>);
    await user.click(screen.getByTestId("watcher-new"));
    expect(screen.getByTestId("watcher-form")).toBeInTheDocument();
    expect(screen.getByTestId("watcher-field")).toHaveValue("stock");
  });
});
