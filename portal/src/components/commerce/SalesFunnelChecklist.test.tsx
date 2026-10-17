import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SalesFunnelChecklist, type FunnelReadiness } from "./SalesFunnelChecklist";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const READINESS: FunnelReadiness = {
  title: "Configura tu embudo",
  ready: false,
  items: [
    {
      key: "catalog",
      label: "Catálogo",
      status: "ok",
      resolved: ["catalog.products.search"],
      missing: [],
      hint: "Conecta tus productos o una base gestionada con el catálogo.",
      action: null,
    },
    {
      key: "payment",
      label: "Pago",
      status: "attention",
      resolved: [],
      missing: ["payments.checkout.create", "payment.succeeded"],
      hint: "IZIPAY está disponible; configura tus credenciales para cobrar.",
      action: { kind: "marketplace", filter: "payments", label: "Configurar medio de pago" },
    },
  ],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi(body: unknown = READINESS, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(json(body, status)))
  );
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname + location.search}</span>;
}

function renderChecklist() {
  return render(
    <MemoryRouter initialEntries={["/workflows/wf-1"]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <SalesFunnelChecklist />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("SalesFunnelChecklist", () => {
  it("muestra los pasos con marca ✓/! y el hint humano, sin códigos técnicos", async () => {
    stubApi();
    renderChecklist();
    await waitFor(() => expect(screen.getByTestId("funnel-step-payment")).toBeInTheDocument());

    expect(screen.getByText("Configura tu embudo")).toBeInTheDocument();
    expect(screen.getByTestId("funnel-step-catalog")).toBeInTheDocument();
    expect(screen.getByTestId("funnel-step-status-catalog")).toHaveTextContent("✓");
    expect(screen.getByTestId("funnel-step-status-payment")).toHaveTextContent("!");
    expect(screen.getByText(/IZIPAY está disponible/)).toBeInTheDocument();
    expect(screen.getByText("1 paso pendiente")).toBeInTheDocument();

    // Nunca se exponen códigos de capacidad ni errores crudos.
    expect(screen.queryByText(/payments\.checkout\.create/)).toBeNull();
    expect(screen.queryByText(/catalog\.products\.search/)).toBeNull();
  });

  it("el CTA de un paso pendiente navega al Marketplace con el filtro de pagos", async () => {
    stubApi();
    const user = userEvent.setup();
    renderChecklist();
    const cta = await screen.findByTestId("funnel-cta-payment");
    expect(cta).toHaveTextContent("Configurar medio de pago");

    await user.click(cta);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/marketplace?applies_to=PAYMENTS&q=payment"
      )
    );
  });

  it("cuando todo está listo celebra y no deja CTAs pendientes", async () => {
    stubApi({
      title: "Configura tu embudo",
      ready: true,
      items: [
        {
          key: "catalog",
          label: "Catálogo",
          status: "ok",
          resolved: ["catalog.products.search"],
          missing: [],
          hint: "Conecta tus productos o una base gestionada con el catálogo.",
          action: null,
        },
      ],
    });
    renderChecklist();
    await waitFor(() => expect(screen.getByText("Listo para vender")).toBeInTheDocument());
    expect(screen.queryByTestId("funnel-cta-catalog")).toBeNull();
  });

  it("muestra un estado de carga legible", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {}))
    );
    renderChecklist();
    expect(screen.getByTestId("funnel-checklist")).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "Cargando configuración del embudo" })
    ).toBeInTheDocument();
  });

  it("en error muestra un mensaje humano y nunca el detalle técnico", async () => {
    stubApi({ detail: { error_code: "INTERNAL_ERROR", message: "Traceback (most recent call last)" } }, 500);
    renderChecklist();
    await waitFor(() =>
      expect(screen.getByText(/No pudimos cargar la configuración del embudo/)).toBeInTheDocument()
    );
    expect(screen.queryByText(/INTERNAL_ERROR/)).toBeNull();
    expect(screen.queryByText(/Traceback/)).toBeNull();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
