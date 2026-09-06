import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../auth";
import { PlatformAuthProvider } from "../../platformAuth";
import CustomerDetailPage from "./CustomerDetail";

const ORG = {
  id: "org-1",
  name: "Acme Corp",
  company_name: "Acme Corp",
  email: "acme@corp.cl",
  status: "active",
  plan: "pro",
  subscription_status: "active",
  started: "2026-01-01T00:00:00Z",
  mrr_cents: 9900,
  users: 5,
  agents: 2,
  requests_30d: 12000,
  ai_cost_30d: 12.5,
  margin: 45,
  payment_provider: "manual",
  amount_due_cents: 0,
  next_renewal_at: "2026-10-01T00:00:00Z",
};

const FINOPS = {
  revenue_cents: 9900,
  costs: { llm: 10, embedding: 2.5, storage: 0.4, infra: 1 },
  gross_profit: 85,
  gross_margin_pct: 45.2,
};

const HEALTH = {
  score: 87,
  label: "HEALTHY",
  requests_30d: 12000,
  tokens_30d: 90000,
  cost_30d: 12.5,
  errors_7d: 0,
  subscription_status: "active",
  organization_status: "active",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function fetchRouter() {
  return vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/impersonate")) return Promise.resolve(json({ access_token: "rag_sess_imp" }));
    if (url.includes("/suspend") || url.includes("/pause") || url.includes("/cancel") || url.includes("/usage/reset"))
      return Promise.resolve(json({ ok: true }));
    if (url.includes("/organizations/org-1/users")) return Promise.resolve(json({ users: [] }));
    if (url.includes("/organizations/org-1/agents")) return Promise.resolve(json({ agents: [] }));
    if (url.includes("/organizations/org-1/sources")) return Promise.resolve(json({ sources: [], knowledge_bases: [] }));
    if (url.includes("/organizations/org-1/billing")) return Promise.resolve(json({ subscription: null, invoices: [] }));
    if (url.includes("/organizations/org-1/security")) return Promise.resolve(json({ api_keys: [] }));
    if (url.includes("/organizations/org-1/audit")) return Promise.resolve(json({ entries: [] }));
    if (url.includes("/finops/organizations/org-1")) return Promise.resolve(json(FINOPS));
    if (url.includes("/tenants/org-1/health")) return Promise.resolve(json(HEALTH));
    if (url.includes("/organizations/org-1")) return Promise.resolve(json(ORG));
    if (url.includes("/operations")) return Promise.resolve(json({ jobs: [] }));
    if (url.includes("/notifications")) return Promise.resolve(json({ notifications: [] }));
    return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
  });
}

async function renderDetail() {
  const fetchMock = fetchRouter();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.setItem("rag_platform_token", "rag_sess_plat");
  window.localStorage.setItem("rag_platform_email", "admin@zent.dev");

  render(
    <MemoryRouter initialEntries={["/control-center/tenants/org-1"]}>
      <AuthProvider>
        <PlatformAuthProvider>
          <Routes>
            <Route path="/control-center/tenants/:orgId" element={<CustomerDetailPage />} />
          </Routes>
        </PlatformAuthProvider>
      </AuthProvider>
    </MemoryRouter>
  );
  await screen.findByText("Acme Corp");
  return { user: userEvent.setup(), fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Tenant 360 (CustomerDetail)", () => {
  it("muestra el header con plan, health y métricas", async () => {
    await renderDetail();
    expect(screen.getByText(/Plan: pro/)).toBeInTheDocument();
    expect(screen.getByText(/HEALTHY/)).toBeInTheDocument();
    expect(screen.getAllByText(/MRR/).length).toBeGreaterThan(0);
    expect(screen.getByText(/12000 requests 30d/)).toBeInTheDocument();
  });

  it("abre More actions y exige confirmación para suspender", async () => {
    const { user } = await renderDetail();
    await user.click(screen.getByRole("button", { name: /More actions/ }));
    await user.click(screen.getByRole("menuitem", { name: /Suspend/ }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(/Esta acción afecta al tenant/)).toBeInTheDocument();
  });

  it("impersonate pide confirmación, motivo y está marcado como privilegiado", async () => {
    const { user } = await renderDetail();
    await user.click(screen.getByRole("button", { name: /Impersonar.*privilegiada/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("operación privilegiada");

    // El motivo es obligatorio: confirmar sin motivo no impersona.
    await user.click(within(dialog).getByRole("button", { name: "Impersonar" }));
    expect(window.sessionStorage.getItem("rag_portal_token")).toBeNull();

    await user.type(within(dialog).getByPlaceholderText(/Soporte/), "Prueba de motivo");
    await user.click(within(dialog).getByRole("button", { name: "Impersonar" }));
    await waitFor(() =>
      expect(window.sessionStorage.getItem("rag_portal_token")).toBe("rag_sess_imp")
    );
  });

  it("muestra el timeline del tenant con datos reales", async () => {
    const { user } = await renderDetail();
    await user.click(screen.getByRole("tab", { name: "Timeline" }));
    await waitFor(() => expect(screen.getByText("Timeline del tenant")).toBeInTheDocument());
    expect(screen.getByText("Sin actividad registrada.")).toBeInTheDocument();
  });
});