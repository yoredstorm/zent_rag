import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { CognitiveTechnicalCard } from "./CognitiveTechnicalCard";

describe("CognitiveTechnicalCard", () => {
  it("no renderiza nada con el shape vacío del backend", () => {
    const { container } = render(
      <CognitiveTechnicalCard
        raw={{
          cognitive_story: {
            schema_version: 1,
            normal: [],
            expanded: {},
            raw: {},
          },
        }}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renderiza modo y budget cuando hay datos", () => {
    render(
      <CognitiveTechnicalCard
        raw={{
          cognitive_story: {
            schema_version: 1,
            normal: [
              { kind: "cognitive_plan", phase: "planning", status: "ok", metrics: {} },
            ],
            expanded: { budget: { within_budget: true } },
            raw: { mode: "active", run_id: "run-1" },
          },
        }}
      />,
    );
    expect(screen.getByText("Runtime cognitivo")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("dentro")).toBeInTheDocument();
  });

  it("muestra — cuando falta within_budget", () => {
    render(
      <CognitiveTechnicalCard
        raw={{
          cognitive_story: {
            schema_version: 1,
            normal: [
              { kind: "cognitive_plan", phase: "planning", status: "ok", metrics: {} },
            ],
            expanded: { budget: {} },
            raw: { mode: "shadow" },
          },
        }}
      />,
    );
    const budgetRow = screen.getByText("Budget").closest("div");
    expect(budgetRow).not.toBeNull();
    expect(within(budgetRow as HTMLElement).getByText("—")).toBeInTheDocument();
  });
});
