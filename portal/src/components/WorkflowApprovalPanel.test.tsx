import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowApprovalPanel } from "./WorkflowApprovalPanel";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));

vi.mock("../api", () => ({ api: apiMock }));
vi.mock("../auth", () => {
  const session = { token: "test-token", organizationId: "org-1" };
  return { useAuth: () => ({ session }) };
});

const APPROVAL = {
  id: "a1",
  run_id: "r1",
  status: "pending",
  action: "Aprobar pago",
  summary: "Riesgo alto detectado por el agente",
  context: {
    decisions: [{ risk: "HIGH", reason: "mora", decision_result: { decision: "HIGH" } }],
    evidence_refs: [{ evidence_id: "e1", label: "politica.pdf" }],
    claim_refs: [{ claim_id: "c1", text: "descuento 15%", status: "proposed" }],
    citations: [{ document_name: "politica.pdf", page: 3, excerpt: "descuento máximo 15%" }],
    data_summary: { q: { keys: ["total"], answer: "54000" } },
  },
};

describe("WorkflowApprovalPanel", () => {
  beforeEach(() => {
    apiMock.mockReset();
    apiMock.mockImplementation((path: unknown) => {
      if (String(path).endsWith("/decide")) {
        return Promise.resolve({ approved: true });
      }
      return Promise.resolve({ approvals: [APPROVAL] });
    });
  });

  it("muestra decisión, evidencia y citas, y decide la aprobación", async () => {
    render(<WorkflowApprovalPanel runId="r1" />);

    await screen.findByTestId("wf-approval-a1");
    expect(screen.getByTestId("wf-approval-decision")).toBeInTheDocument();
    expect(screen.getByTestId("wf-approval-evidence")).toHaveTextContent("1 fuente");
    expect(screen.getByTestId("wf-approval-claims")).toHaveTextContent("1");
    expect(screen.getByTestId("wf-approval-citations")).toHaveTextContent("politica.pdf");
    expect(screen.getByTestId("wf-approval-data")).toHaveTextContent("q");

    await userEvent.click(screen.getByTestId("wf-approval-approve-a1"));
    const decideCall = await waitFor(() => {
      const call = apiMock.mock.calls.find(([path]) => String(path).endsWith("/decide"));
      expect(call).toBeTruthy();
      return call;
    });
    expect(String(decideCall?.[0])).toBe("/api/v1/workflows/runs/r1/approvals/a1/decide");
    const options = decideCall?.[1] as { method?: string; body?: string };
    expect(options.method).toBe("POST");
    expect(JSON.parse(String(options.body)).decision).toBe("approved");

    await waitFor(() => expect(screen.queryByTestId("wf-approval-a1")).toBeNull());
  });

  it("no renderiza nada sin aprobaciones pendientes", async () => {
    apiMock.mockImplementation(() => Promise.resolve({ approvals: [] }));
    render(<WorkflowApprovalPanel runId="r1" />);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    expect(screen.queryByTestId("wf-approval-panel")).toBeNull();
  });
});
