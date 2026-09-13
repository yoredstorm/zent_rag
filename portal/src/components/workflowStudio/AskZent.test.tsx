import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AskZent } from "./AskZent";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));
const NAVIGATE = vi.hoisted(() => vi.fn());

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => NAVIGATE };
});

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const PROPOSAL = {
  intent: { name: "Alerta de stock bajo", description: "Avisa a compras" },
  plan: { name: "Alerta de stock bajo", plan_version: 1 },
  summary: {
    when: "ocurra inventory.updated",
    conditions: "Stock disponible es menor que 10",
    analysis: [],
    actions: ["avisar por correo a Compras"],
    text: "Cuando ocurra inventory.updated, si Stock disponible es menor que 10, y avisar por correo a Compras.",
  },
  questions: [],
  issues: [],
  confidence: 0.9,
  source: "llm",
  notes: [],
  must_review: true,
};

const COMPILED = {
  graph: {
    workflow_version: 2,
    nodes: [{ type: "trigger_event" }, { type: "query_business_data" }, { type: "condition" }, { type: "notify" }],
    edges: [],
    variables: {},
    entrypoints: ["trigger"],
    metadata: {},
  },
  valid: true,
  issues: [],
  summary: PROPOSAL.summary,
};

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/copilot/intent")) return Promise.resolve(json(PROPOSAL));
      if (url.includes("/copilot/compile")) return Promise.resolve(json(COMPILED));
      if (url.endsWith("/api/v1/workflows") && (init?.method ?? "GET") === "POST") {
        return Promise.resolve(json({ workflow_id: "wf-9" }));
      }
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  NAVIGATE.mockReset();
});

describe("AskZent", () => {
  it("muestra la interpretación de negocio antes de crear nada", async () => {
    stubApi();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AskZent />
      </MemoryRouter>,
    );
    await user.type(
      screen.getByTestId("ask-prompt"),
      "Cuando el stock sea menor a 10 avisa por correo al equipo de compras",
    );
    await user.click(screen.getByTestId("ask-submit"));
    await waitFor(() => expect(screen.getByTestId("ask-understanding")).toBeInTheDocument());
    expect(screen.getByText("CUANDO")).toBeInTheDocument();
    expect(screen.getByText("SI")).toBeInTheDocument();
    expect(screen.getByText("DESPUÉS")).toBeInTheDocument();
    expect(screen.getByTestId("ask-confidence")).toHaveTextContent("90%");
    // No se creó nada todavía.
    expect(NAVIGATE).not.toHaveBeenCalled();
  });

  it("crea el borrador compilando el plan y navega al estudio", async () => {
    stubApi();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AskZent />
      </MemoryRouter>,
    );
    await user.type(screen.getByTestId("ask-prompt"), "Cuando el stock sea menor a 10 avisa por correo");
    await user.click(screen.getByTestId("ask-submit"));
    await waitFor(() => expect(screen.getByTestId("ask-create")).toBeInTheDocument());
    await user.click(screen.getByTestId("ask-create"));
    await waitFor(() => expect(NAVIGATE).toHaveBeenCalledWith("/workflows/wf-9", expect.anything()));
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.some((c) => String(c[0]).includes("/copilot/compile"))).toBe(true);
  });

  it("muestra preguntas pendientes en vez de inventar datos", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          json({
            ...PROPOSAL,
            confidence: 0.4,
            questions: ["¿Dónde está el inventario?"],
            issues: [
              { code: "notify.missing_recipients", severity: "warning", message: "Falta elegir a quién avisar." },
            ],
          }),
        ),
      ),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AskZent />
      </MemoryRouter>,
    );
    await user.type(screen.getByTestId("ask-prompt"), "avísame cuando haya stock bajo");
    await user.click(screen.getByTestId("ask-submit"));
    await waitFor(() => expect(screen.getByTestId("ask-questions")).toHaveTextContent("Falta elegir a quién avisar."));
    expect(screen.getByTestId("ask-questions")).toHaveTextContent("¿Dónde está el inventario?");
  });
});
