import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SalesFunnelKpis, type FunnelKpis } from "./SalesFunnelKpis";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const KPIS: FunnelKpis = {
  instances: {
    active: 3,
    waiting_customers: 2,
    completed: 5,
    failed: 1,
    expired: 0,
    cancelled: 0,
    by_status: { RUNNING: 3, WAITING: 2, COMPLETED: 5, FAILED: 1 },
  },
  orders: {
    draft: 1,
    awaiting_confirmation: 0,
    awaiting_payment: 2,
    paid: 4,
    fulfilled: 4,
    cancelled: 0,
    expired: 1,
    abandoned: 3,
    by_status: {},
  },
  sales: { revenue_paid: { PEN: 11.4 } },
  average_completion_seconds: 42.1,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi(body: unknown = KPIS, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(json(body, status)))
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("SalesFunnelKpis", () => {
  it("muestra instancias, pedidos, tiempo medio y cobros por moneda", async () => {
    stubApi();
    render(<SalesFunnelKpis />);
    await waitFor(() => expect(screen.getByTestId("funnel-kpi-instances-active")).toBeInTheDocument());

    expect(screen.getByTestId("funnel-kpis")).toBeInTheDocument();
    expect(screen.getByTestId("funnel-kpi-instances-active")).toHaveTextContent("3");
    expect(screen.getByTestId("funnel-kpi-waiting-customers")).toHaveTextContent("2");
    expect(screen.getByTestId("funnel-kpi-awaiting-payment")).toHaveTextContent("2");
    expect(screen.getByTestId("funnel-kpi-completed-sales")).toHaveTextContent("4");
    expect(screen.getByTestId("funnel-kpi-abandoned")).toHaveTextContent("3");
    expect(screen.getByTestId("funnel-kpi-failed")).toHaveTextContent("1");
    expect(screen.getByTestId("funnel-kpi-avg-completion")).toHaveTextContent("42 s");
    expect(screen.getByTestId("funnel-kpi-revenue-paid")).toHaveTextContent(/11[.,]40/);
    expect(screen.getByTestId("funnel-kpi-revenue-paid")).toHaveTextContent(/S\//);
  });

  it("aclara que son KPIs del workflow y no analytics completos", async () => {
    stubApi();
    render(<SalesFunnelKpis />);
    await waitFor(() => expect(screen.getByTestId("funnel-kpis")).toBeInTheDocument());
    expect(screen.getByText(/no analytics completos/i)).toBeInTheDocument();
  });

  it("formatea tiempos largos y muestra — sin cobros", async () => {
    stubApi({
      ...KPIS,
      sales: { revenue_paid: {} },
      average_completion_seconds: 3725,
    });
    render(<SalesFunnelKpis />);
    await waitFor(() =>
      expect(screen.getByTestId("funnel-kpi-avg-completion")).toHaveTextContent("1 h 2 min")
    );
    expect(screen.getByTestId("funnel-kpi-revenue-paid")).toHaveTextContent("—");
  });

  it("en error muestra un mensaje humano y permite reintentar", async () => {
    stubApi({ detail: { error_code: "INTERNAL_ERROR", message: "Traceback (most recent call last)" } }, 500);
    render(<SalesFunnelKpis />);
    await waitFor(() =>
      expect(screen.getByText(/No pudimos cargar los KPIs del embudo/)).toBeInTheDocument()
    );
    expect(screen.queryByText(/INTERNAL_ERROR/)).toBeNull();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
