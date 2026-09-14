import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { NodeConfigPanel } from "./NodeConfigPanel";
import type { GraphNode, WorkflowGraph } from "../lib/workflowGraph";
import type { RunDetail } from "./WorkflowRunInspector";

vi.mock("../auth", () => ({
  useAuth: () => ({ session: { token: "t", organizationId: "org" } }),
}));

function node(partial: Partial<GraphNode> & { id: string; type: string }): GraphNode {
  return {
    version: 1,
    label: partial.type,
    position: { x: 0, y: 0 },
    config: {},
    input_ports: [{ name: "in", type: "json" }],
    output_ports: [{ name: "out", type: "json" }],
    retry_policy: { max_attempts: 1 },
    timeout_ms: 60000,
    error_policy: "fail",
    metadata: {},
    ...partial,
  };
}

const NOTIFY = node({ id: "n1", type: "notify", label: "Avisar", config: { channel: "in_app", title: "Stock bajo" } });
const GRAPH: WorkflowGraph = {
  workflow_version: 2,
  nodes: [node({ id: "t", type: "trigger_webhook" }), NOTIFY],
  edges: [{ id: "e1", from_node: "t", from_port: "out", to_node: "n1", to_port: "in" }],
  variables: {},
  entrypoints: ["t"],
  metadata: {},
};

const RUN: RunDetail = {
  id: "run-1",
  status: "succeeded",
  duration_ms: 284,
  steps: [
    {
      step_index: 1,
      step_type: "notify",
      node_id: "n1",
      node_type: "notify",
      status: "succeeded",
      input: { channel: "in_app", title: "Stock bajo" },
      output: { sent: true, channel: "in_app" },
      duration_ms: 120,
      retries: 0,
    },
  ],
};

function renderPanel(props: Record<string, unknown> = {}) {
  return render(
    <MemoryRouter>
      <NodeConfigPanel
        graph={GRAPH}
        node={NOTIFY}
        edge={null}
        onChange={() => undefined}
        onDeleteNode={() => undefined}
        onDeleteEdge={() => undefined}
        kbs={[]}
        agents={[]}
        run={RUN}
        {...props}
      />
    </MemoryRouter>,
  );
}

describe("NodeConfigPanel tabs", () => {
  it("muestra Configurar por defecto y Avanzado colapsado", async () => {
    renderPanel();
    expect(screen.getByTestId("wf-tab-config")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("wf-advanced")).toBeInTheDocument();
    expect(screen.getByTestId("wf-advanced")).not.toHaveAttribute("open");
  });

  it("Output muestra la salida real del último run y no JSON crudo", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("wf-tab-output"));
    expect(screen.getByTestId("wf-output-view")).toHaveTextContent("Enviado");
    expect(screen.getByTestId("wf-output-view")).toHaveTextContent("Sí");
    expect(screen.queryByTestId("wf-output-view-json")).toBeNull();
  });

  it("Run muestra estado, duración y acciones parciales", async () => {
    const user = userEvent.setup();
    const onRunPartial = vi.fn();
    renderPanel({ onRunPartial });
    await user.click(screen.getByTestId("wf-tab-run"));
    expect(screen.getByTestId("wf-node-run")).toHaveTextContent("succeeded");
    expect(screen.getByTestId("wf-node-run")).toHaveTextContent("120 ms");
    await user.click(screen.getByTestId("wf-run-node"));
    expect(onRunPartial).toHaveBeenCalledWith("n1", "node");
    await user.click(screen.getByTestId("wf-run-until"));
    expect(onRunPartial).toHaveBeenCalledWith("n1", "until_node");
    await user.click(screen.getByTestId("wf-run-from"));
    expect(onRunPartial).toHaveBeenCalledWith("n1", "from_node");
  });

  it("Input muestra la entrada registrada del run", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("wf-tab-input"));
    expect(screen.getByTestId("wf-node-input")).toHaveTextContent("Canal");
    expect(screen.getByTestId("wf-node-input")).toHaveTextContent("Stock bajo");
  });

  it("Output permite fijar datos para pruebas", async () => {
    const user = userEvent.setup();
    const onPinData = vi.fn();
    renderPanel({ onPinData });
    await user.click(screen.getByTestId("wf-tab-output"));
    await user.click(screen.getByTestId("wf-pin-data"));
    expect(onPinData).toHaveBeenCalledWith("n1", { sent: true, channel: "in_app" });
  });

  it("muestra el badge de datos fijados y permite quitarlos", async () => {
    const user = userEvent.setup();
    const onUnpinData = vi.fn();
    renderPanel({ pinned: true, onUnpinData });
    await user.click(screen.getByTestId("wf-tab-output"));
    expect(screen.getByTestId("wf-pinned-badge")).toHaveTextContent("Datos fijados");
    await user.click(screen.getByTestId("wf-unpin-data"));
    expect(onUnpinData).toHaveBeenCalledWith("n1");
  });
});
