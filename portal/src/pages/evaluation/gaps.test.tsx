// =============================================================================
// Context Gaps / Impacto — el cliente debe mandar la sesión tenant
// =============================================================================
// Regresión: estas páginas llamaban api() sin token ni organizationId y el
// backend respondía 401 missing_token (cookie no siempre disponible).
// =============================================================================
import type { ReactNode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../auth";
import GapsPage from "./Gaps";
import ImpactPage from "./Impact";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function authShell(ui: ReactNode) {
  window.localStorage.setItem("rag_portal_token", "rag_sess_t");
  window.localStorage.setItem("rag_portal_org", "org-1");
  window.localStorage.setItem("rag_portal_company", "Acme");
  return <AuthProvider>{ui}</AuthProvider>;
}

function meResponse() {
  return json({
    organization_id: "org-1",
    company_name: "Acme",
    email: "a@b.cl",
    roles: ["owner"],
    permissions: [],
  });
}

const GAP = {
  id: "g1",
  gap_type: "MISSING_SOURCE",
  concept: "IVA deducible",
  question: "¿Cómo se calcula el IVA deducible?",
  occurrences: 3,
  impact: { query_count_30d: 3, users: 2 },
  status: "OPEN",
  evidence_hints: ["ventas.facturas"],
  last_seen_at: "2026-09-29T04:00:00Z",
};

const TRENDS = {
  days: 30,
  total_queries: 0,
  answerable_queries: 0,
  abstained_queries: 0,
  answerability_rate: 0,
  unsupported_question_rate: 0,
  context_gaps_open: 0,
  context_gaps_resolved: 0,
  gap_resolution_rate: 0,
  improvements_open: 0,
  most_impactful_missing_concepts: [],
  knowledge_approvals_30d: 0,
  evaluation_replays: { total: 0, pass: 0, warn: 0, fail: 0, unknown: 0 },
};

function headersOf(
  fetchMock: ReturnType<typeof vi.fn>,
  urlPart: string,
  method = "GET",
): Headers | null {
  const call = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url).includes(urlPart) &&
      String((init as RequestInit | undefined)?.method || "GET").toUpperCase() === method,
  );
  if (!call) return null;
  return new Headers((call[1] as RequestInit | undefined)?.headers);
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("Evaluación · Context Gaps", () => {
  it("pide los gaps con la sesión tenant", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/api/v1/learning/gaps")) return Promise.resolve(json([GAP]));
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/evaluation/gaps"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/gaps" element={<GapsPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    expect(await screen.findByText("IVA deducible")).toBeInTheDocument();
    const headers = headersOf(fetchMock, "/api/v1/learning/gaps");
    expect(headers?.get("Authorization")).toBe("Bearer rag_sess_t");
    expect(headers?.get("X-Organization-Id")).toBe("org-1");
  });

  it("resolver un gap manda POST autenticado", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/resolve") && method === "POST")
        return Promise.resolve(json({ resolved: "g1" }));
      if (url.includes("/api/v1/learning/gaps")) return Promise.resolve(json([GAP]));
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/evaluation/gaps"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/gaps" element={<GapsPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    await screen.findByText("IVA deducible");
    await user.click(screen.getByRole("button", { name: "Resolver" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Resolver" }));

    await waitFor(() => {
      const headers = headersOf(fetchMock, "/api/v1/learning/gaps/g1/resolve", "POST");
      expect(headers?.get("Authorization")).toBe("Bearer rag_sess_t");
      expect(headers?.get("X-Organization-Id")).toBe("org-1");
    });
  });
});

describe("Evaluación · Impacto", () => {
  it("pide las tendencias con la sesión tenant", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/api/v1/learning/analytics")) return Promise.resolve(json(TRENDS));
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/evaluation/impact"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/impact" element={<ImpactPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    await waitFor(() => {
      const headers = headersOf(fetchMock, "/api/v1/learning/analytics");
      expect(headers?.get("Authorization")).toBe("Bearer rag_sess_t");
      expect(headers?.get("X-Organization-Id")).toBe("org-1");
    });
    expect(screen.queryByText(/missing_token/)).not.toBeInTheDocument();
  });
});
