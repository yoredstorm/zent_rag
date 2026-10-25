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

  it("distingue versión publicada de borrador con cambios", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/release-gate")) {
          return Promise.resolve(
            json({
              allowed: true,
              state: "READY_TO_PUBLISH",
              risk_class: "internal",
              required_level: "DESIGN_VALID",
              blockers: [],
            }),
          );
        }
        if (url.endsWith("/versions")) {
          return Promise.resolve(
            json({
              versions: [
                {
                  id: "v1",
                  workflow_id: "wf-1",
                  version_number: 1,
                  status: "production",
                  notes: null,
                  created_at: "2026-10-25T00:00:00Z",
                  config_snapshot: { graph: { nodes: [{ id: "a" }, { id: "b" }] } },
                },
              ],
            }),
          );
        }
        if (url.endsWith("/workflows/wf-1")) {
          return Promise.resolve(
            json({
              id: "wf-1",
              name: "WF",
              description: null,
              trigger_type: "webhook",
              trigger_config: {},
              steps: [],
              status: "active",
              graph: { nodes: [{ id: "a" }, { id: "b" }, { id: "c" }] },
              published_version_id: "v1",
              published_version_number: 1,
              draft_changed: true,
              draft_revision: 2,
              deployment_generation: 1,
            }),
          );
        }
        return Promise.resolve(json({}));
      }),
    );

    render(
      <WorkflowVersionsPanel
        workflowId="wf-1"
        status="active"
        onChanged={() => undefined}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("wf-published-banner").textContent).toContain(
        "Versión activa v1",
      ),
    );
    expect(screen.getByTestId("wf-published-banner").textContent).toContain(
      "cambios sin publicar",
    );
    expect(screen.getByTestId("wf-draft-diff").textContent).toContain("c");
  });
});
