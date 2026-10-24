import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SubflowLibraryPanel } from "./SubflowLibraryPanel";

const SUBFLOW = {
  name: "consultar_conocimiento",
  version: 1,
  status: "published",
  capability_ref: "subflow.consultar_conocimiento",
  durable: false,
  runnable_inline: true,
  output_ports: ["success", "not_found", "invalid_input", "timeout", "needs_human"],
  node_config: { workflow_ref: "consultar_conocimiento", version: 1 },
};

describe("SubflowLibraryPanel", () => {
  it("inserta solo definiciones publicadas con su config congelada", async () => {
    const onInsert = vi.fn();
    render(
      <SubflowLibraryPanel
        loadLibrary={async () => [SUBFLOW]}
        onInsert={onInsert}
      />
    );
    expect(await screen.findByTestId("wf-subflow-consultar_conocimiento")).toHaveTextContent(
      "published"
    );
    fireEvent.click(screen.getByTestId("wf-subflow-insert-consultar_conocimiento"));
    expect(onInsert).toHaveBeenCalledWith(SUBFLOW);
  });

  it("bloquea visualmente un subflujo durable inline", async () => {
    render(
      <SubflowLibraryPanel
        loadLibrary={async () => [
          {
            ...SUBFLOW,
            name: "solicitar_aprobacion",
            durable: true,
            runnable_inline: false,
          },
        ]}
        onInsert={vi.fn()}
      />
    );
    expect(await screen.findByTestId("wf-subflow-solicitar_aprobacion")).toHaveTextContent(
      "debe vivir en el proceso padre"
    );
  });
});
