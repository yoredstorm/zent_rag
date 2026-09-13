import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import WorkflowNewPage from "./WorkflowNew";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../auth", () => ({ useAuth: () => AUTH }));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowNewPage", () => {
  it("ofrece los tres modos y lista plantillas reales", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              templates: [
                { slug: "low-stock-alert", name: "Alerta de stock bajo", description: "", category: "operations", trigger_type: "schedule", steps: [] },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );
    render(
      <MemoryRouter>
        <WorkflowNewPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("wf-mode-ai")).toBeInTheDocument();
    expect(screen.getByTestId("wf-mode-manual")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("wf-mode-templates")).toHaveTextContent("Alerta de stock bajo"));
    expect(screen.getByTestId("wf-new-install-low-stock-alert")).toBeInTheDocument();
  });
});
