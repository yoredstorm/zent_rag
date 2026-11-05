import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { RunDetail } from "../WorkflowRunInspector";
import { SimulatorDock, type SimulatorState } from "./SimulatorDock";

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
