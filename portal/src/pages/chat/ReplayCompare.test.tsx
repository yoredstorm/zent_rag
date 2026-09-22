import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReplayCompare, type ReplayResult } from "./ReplayCompare";

const RESULT: ReplayResult = {
  replay_id: "r1",
  source_query_id: "s1",
  replay_query_id: "c1",
  original_unchanged: true,
  comparison: {
    fields: {
      route: { original: "Documentos", current: "Documentos" },
      retrieval_strategy: { original: "vector", current: "structured_exact" },
      sources: { original: ["ATPCO_Record2.xlsx"], current: ["ATPCO_Record2.xlsx"] },
      grounding: { original: null, current: null },
      cost: { original: 0.0041, current: 0.0008 },
      latency_ms: { original: 1800, current: 600 },
      outcome: { original: "insufficient", current: "grounded" },
    },
    improvement: { quality: null, cost: -0.8049 },
  },
  what_changed: [
    {
      kind: "memory",
      memory_id: "93800000-0000-0000-0000-000000000938",
      display_id: "93800000",
      title: "Structured field lookup",
    },
    { kind: "retrieval_strategy", original: "vector", current: "structured_exact" },
  ],
};

describe("ReplayCompare", () => {
  it("compara original y actual y no inventa causas", () => {
    render(<ReplayCompare result={RESULT} error="" pending={false} onReplay={() => {}} />);
    expect(screen.getByText("Original")).toBeInTheDocument();
    expect(screen.getByText("Actual")).toBeInTheDocument();
    expect(screen.getAllByText("N/A").length).toBeGreaterThan(0);
    expect(screen.getByText("vector")).toBeInTheDocument();
    expect(screen.getByText("structured_exact")).toBeInTheDocument();
    expect(screen.getByText(/Structured field lookup/)).toBeInTheDocument();
    expect(screen.getByText(/Costo -80.5%/)).toBeInTheDocument();
    expect(screen.queryByText(/Calidad/)).toBeNull();
    expect(screen.queryByText("Passage Judge")).toBeNull();
    expect(screen.queryByText(/política de retrieval/)).toBeNull();
  });

  it("pide el replay sin mostrar una comparación vacía como mejora", async () => {
    const onReplay = vi.fn();
    render(<ReplayCompare result={null} error="" pending={false} onReplay={onReplay} />);
    await userEvent.click(screen.getByRole("button", { name: "Reejecutar con el sistema actual" }));
    expect(onReplay).toHaveBeenCalledOnce();
    expect(screen.queryByText("Qué cambió")).toBeNull();
  });

  it("muestra el bloqueo", () => {
    render(
      <ReplayCompare
        result={null}
        error="send_email requires mock, dry_run, or simulation during replay"
        pending={false}
        onReplay={() => {}}
      />,
    );
    expect(screen.getByText(/send_email/)).toBeInTheDocument();
  });
});
