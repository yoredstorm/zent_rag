import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import OperationsPage from "./Operations";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../auth", () => ({ useAuth: () => AUTH }));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OperationsPage", () => {
  it("muestra el estado derivado y no inventa uno guardado", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              instances: [
                {
                  id: "i1",
                  status: "WAITING",
                  view_status: "pending_approval",
                  business_key: "pedido-1",
                  workflow_version: 3,
                },
              ],
              total: 1,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );
    render(<OperationsPage />);
    await waitFor(() => expect(screen.getByTestId("ops-list")).toHaveTextContent("pending_approval"));
    expect(screen.getByTestId("ops-list")).toHaveTextContent("pedido-1");
  });
});
