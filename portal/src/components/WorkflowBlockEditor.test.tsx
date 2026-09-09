import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WorkflowBlockEditor } from "./WorkflowBlockEditor";
import { makeBlock } from "../lib/workflowIr";

describe("WorkflowBlockEditor", () => {
  it("muestra toolbox, canvas y datos a mano", () => {
    render(
      <WorkflowBlockEditor
        root={makeBlock("hat_schedule", { every_minutes: "5" })}
        onChange={() => {}}
        kbs={[{ id: "kb1", name: "Políticas" }]}
        agents={[{ id: "a1", name: "Agente stock" }]}
      />
    );
    expect(screen.getByTestId("workflow-block-editor")).toBeInTheDocument();
    expect(screen.getByTestId("wf-block-hat_schedule")).toBeInTheDocument();
    expect(screen.getByTestId("wf-hand-panel")).toBeInTheDocument();
    expect(screen.getByText("Políticas")).toBeInTheDocument();
    expect(screen.getByText("Agente stock")).toBeInTheDocument();
  });
});
