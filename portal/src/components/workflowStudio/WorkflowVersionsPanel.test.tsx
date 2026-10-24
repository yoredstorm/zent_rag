import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkflowVersionsPanel } from "./WorkflowVersionsPanel";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowVersionsPanel — gate P01", () => {
  it("muestra bloqueos y no deja publicar sin certificado", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/release-gate")) {
          return Promise.resolve(
            json({
              allowed: false,
              state: "BLOCKED",
              risk_class: "internal",
              required_level: "DESIGN_VALID",
              blockers: [
                {
                  code: "certification_required",
                  message: "Falta un certificado emitido por el backend.",
                  mitigation: "Certifica el workflow.",
                },
              ],
            }),
          );
        }
        if (url.endsWith("/versions")) return Promise.resolve(json({ versions: [] }));
        return Promise.resolve(json({}));
      }),
    );

    render(
      <WorkflowVersionsPanel
        workflowId="wf-1"
        status="draft"
        onChanged={() => undefined}
      />,
    );

    await waitFor(() => expect(screen.getByTestId("wf-release-gate")).toBeTruthy());
    expect(screen.getByTestId("wf-release-blockers").textContent).toContain(
      "Falta un certificado",
    );
    expect((screen.getByTestId("wf-publish") as HTMLButtonElement).disabled).toBe(true);
  });
});
