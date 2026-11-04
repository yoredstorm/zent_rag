import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { makeNode, type WorkflowGraph } from "../../lib/workflowGraph";
import type { RunDetail } from "../WorkflowRunInspector";
import { RunTracePane, SimulatorDock, type SimulatorState } from "./SimulatorDock";

const graph: WorkflowGraph = {
  workflow_version: 2,
  nodes: [
    { ...makeNode("trigger_webhook"), id: "t1", label: "Pedido recibido" },
    { ...makeNode("notify"), id: "n1", label: "Avisar al cliente" },
  ],
  edges: [],
  variables: {},
  entrypoints: ["t1"],
  metadata: {},
};

const run: RunDetail = {
  id: "run-42",
  status: "failed",
  duration_ms: 120,
  simulated: true,
  context: { pedido: { id: "P-1" } },
  steps: [
    { step_index: 0, step_type: "node", node_id: "t1", status: "succeeded", duration_ms: 3 },
    { step_index: 1, step_type: "node", node_id: "n1", status: "failed", error: "Falta el correo del cliente" },
  ],
};

describe("RunTracePane", () => {
  it("sin run explica qué aparecerá", () => {
    render(<RunTracePane run={null} graph={graph} selectedNodeId={null} onPickNode={vi.fn()} />);
    expect(screen.getByTestId("wf-trace-empty")).toBeInTheDocument();
  });

  it("abre en errores cuando algo falló y cada paso lleva a su nodo", async () => {
    const onPickNode = vi.fn();
    const user = userEvent.setup();
    render(<RunTracePane run={run} graph={graph} selectedNodeId="n1" onPickNode={onPickNode} />);
    expect(screen.getByTestId("wf-trace-tab-errors")).toHaveAttribute("data-state", "active");
    const failedStep = screen.getByTestId("wf-trace-step");
    expect(failedStep).toHaveTextContent("Avisar al cliente");
    expect(failedStep).toHaveTextContent("Falta el correo del cliente");
    expect(failedStep).toHaveAttribute("aria-current", "true");
    await user.click(failedStep);
    expect(onPickNode).toHaveBeenCalledWith("n1");

    await user.click(screen.getByTestId("wf-trace-tab-trace"));
    expect(screen.getAllByTestId("wf-trace-step").map((s) => s.dataset.nodeId)).toEqual(["t1", "n1"]);

    await user.click(screen.getByTestId("wf-trace-tab-state"));
    expect(screen.getByTestId("wf-trace-state")).toHaveTextContent("Simulación");
    expect(screen.getByTestId("wf-trace-state")).toHaveTextContent("run-42");
  });
});

function DockHarness({ initial = "open" as SimulatorState }) {
  const [state, setState] = useState<SimulatorState>(initial);
  const [height, setHeight] = useState(320);
  return (
    <SimulatorDock
      state={state}
      onStateChange={setState}
      height={height}
      onHeightChange={setHeight}
      availableHeight={800}
      run={run}
      trace={<p>traza</p>}
    >
      <textarea aria-label="Mensaje de prueba" />
    </SimulatorDock>
  );
}

describe("SimulatorDock", () => {
  it("minimizar y cerrar no desmontan el borrador de prueba", async () => {
    const user = userEvent.setup();
    render(<DockHarness />);
    const dock = screen.getByTestId("wf-simulator");
    expect(dock).toHaveAttribute("data-state", "open");
    expect(dock).toHaveStyle({ height: "320px" });
    expect(dock).toHaveTextContent("1 paso(s) con error");

    await user.type(screen.getByLabelText("Mensaje de prueba"), "hola");
    await user.click(screen.getByTestId("wf-simulator-collapse"));
    expect(dock).toHaveAttribute("data-state", "collapsed");
    expect(screen.queryByTestId("wf-simulator-resize")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("wf-simulator-toggle"));
    await user.click(screen.getByTestId("wf-simulator-close"));
    expect(dock).toHaveAttribute("data-state", "closed");
    expect(screen.getByLabelText("Mensaje de prueba")).toHaveValue("hola");
  });

  it("el alto se limita al 70 % del espacio disponible", async () => {
    const user = userEvent.setup();
    render(<DockHarness />);
    const handle = screen.getByTestId("wf-simulator-resize");
    expect(handle).toHaveAttribute("aria-valuemax", "560");
    handle.focus();
    await user.keyboard("{End}");
    expect(screen.getByTestId("wf-simulator")).toHaveStyle({ height: "560px" });
  });
});
