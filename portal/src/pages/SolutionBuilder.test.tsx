import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import SolutionBuilderPage from "./SolutionBuilder";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));
vi.mock("../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SolutionBuilderPage", () => {
  it("compila, exige revisión y materializa el borrador", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/solutions/compile")) {
          return Promise.resolve(
            json({
              compilation_hash: "hash-1",
              status: "READY_TO_MATERIALIZE",
              can_materialize: true,
              template_id: "mentor",
              plan: {
                role: { name: "Mentor", action: "reuse_or_create" },
                agent: { name: "Mentor de Python", action: "create" },
                workflow: { name: "Ciclo de mentoría", action: "create_draft", will_create: true },
                sources: [],
              },
              requirements: [],
              blockers: [],
              scenarios: [{ scenario_id: "primer_dia" }],
            }),
          );
        }
        if (url.endsWith("/solutions/materialize")) {
          return Promise.resolve(
            json({
              solution_id: "sol-1",
              status: "READY",
              artifacts: {
                workflow: { id: "wf-1", created: true },
                agent: { id: "ag-1", created: true },
                role: { id: "role-1", created: true },
              },
              blockers: [],
            }),
          );
        }
        return Promise.resolve(json({}));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/solutions/new?brief=Mentor%20de%20Python"]}>
        <SolutionBuilderPage />
      </MemoryRouter>,
    );

    await user.click(screen.getByTestId("solution-compile"));
    await waitFor(() => expect(screen.getByTestId("solution-plan")).toBeTruthy());
    expect(screen.getByTestId("solution-resources").textContent).toContain("Mentor de Python");

    const materialize = screen.getByTestId("solution-materialize") as HTMLButtonElement;
    expect(materialize.disabled).toBe(true);
    await user.click(screen.getByTestId("solution-reviewed"));
    expect(materialize.disabled).toBe(false);
    await user.click(materialize);

    await waitFor(() => expect(screen.getByTestId("solution-result")).toBeTruthy());
    expect(screen.getByTestId("solution-result").textContent).toContain("Solución preparada");
    expect(screen.getByTestId("solution-open-workflow").getAttribute("href")).toBe("/workflows/wf-1");
  });
});
