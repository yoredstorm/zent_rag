import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkflowPatchPanel } from "./WorkflowPatchPanel";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const PREVIEW = {
  patch: { summary: "Cambiar asunto", operations: [{ op: "set_field", target: "nodes.notify.config.title", value: "Stock crítico" }] },
  diff: [
    {
      op: "set_field",
      node_id: "nodes.notify.config.title",
      node_label: "Avisar",
      label: "title",
      before: "Stock bajo",
      after: "Stock crítico",
      description: "title",
    },
  ],
  issues: [],
  base_graph_hash: "abc",
  summary: "Cambiar asunto",
  questions: [],
  confidence: 0.9,
};

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/patch/preview")) {
        return Promise.resolve(
          new Response(JSON.stringify(PREVIEW), { status: 200, headers: { "Content-Type": "application/json" } }),
        );
      }
      if (url.includes("/patch/apply")) {
        return Promise.resolve(
          new Response(JSON.stringify({ status: "applied", diff: PREVIEW.diff }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowPatchPanel", () => {
  it("muestra el diff y aplica solo tras confirmar", async () => {
    stubApi();
    const user = userEvent.setup();
    const onApplied = vi.fn();
    render(<WorkflowPatchPanel workflowId="wf-1" onApplied={onApplied} onClose={() => undefined} />);

    await user.type(screen.getByTestId("wf-patch-prompt"), "Cambia el asunto a Stock crítico");
    await user.click(screen.getByTestId("wf-patch-preview"));

    await waitFor(() => expect(screen.getByTestId("wf-patch-diff")).toBeInTheDocument());
    expect(screen.getByText("Stock bajo")).toBeInTheDocument();
    expect(screen.getByText("Stock crítico")).toBeInTheDocument();
    expect(onApplied).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("wf-patch-apply"));
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
  });

  it("explica cuando no hay cambios aplicables", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ ...PREVIEW, patch: null, diff: [], summary: null }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );
    const user = userEvent.setup();
    render(<WorkflowPatchPanel workflowId="wf-1" onApplied={() => undefined} onClose={() => undefined} />);
    await user.type(screen.getByTestId("wf-patch-prompt"), "haz algo");
    await user.click(screen.getByTestId("wf-patch-preview"));
    await waitFor(() => expect(screen.getByTestId("wf-patch-empty")).toBeInTheDocument());
  });
});
