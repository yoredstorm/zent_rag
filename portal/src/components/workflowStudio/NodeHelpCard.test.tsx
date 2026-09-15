import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { nodeMeta } from "../../lib/workflowGraph";
import { NodeHelpCard } from "./NodeHelpCard";

describe("NodeHelpCard", () => {
  it("muestra qué hace, cuándo usarlo, qué necesita y qué produce", () => {
    render(
      <NodeHelpCard
        meta={{
          ...nodeMeta("condition"),
          longDescription: "Continúa por caminos distintos según una regla.",
          whenToUse: ["una regla determinística decide el camino"],
          whatItNeeds: ["Dato a evaluar"],
          whatItProduces: ["Resultado"],
          example: { field: "risk", operator: "==", value: "HIGH" },
        }}
      />
    );
    expect(screen.getByTestId("wf-node-help-does")).toHaveTextContent("Continúa por caminos");
    expect(screen.getByTestId("wf-node-help-when")).toHaveTextContent("regla determinística");
    expect(screen.getByTestId("wf-node-help-needs")).toHaveTextContent("Dato a evaluar");
    expect(screen.getByTestId("wf-node-help-produces")).toHaveTextContent("Resultado");
    expect(screen.getByTestId("wf-node-help-example")).toHaveTextContent('"risk"');
  });

  it("sugiere siguientes pasos y los agrega al hacer clic", async () => {
    const onAdd = vi.fn();
    render(
      <NodeHelpCard
        meta={{
          ...nodeMeta("query_business_data"),
          longDescription: "Consulta datos.",
          recommendedNext: [{ node_type: "llm", label: "Preguntar a un agente" }],
        }}
        onAddSuggested={onAdd}
      />
    );
    await userEvent.click(screen.getByTestId("wf-next-llm"));
    expect(onAdd).toHaveBeenCalledWith("llm");
  });

  it("no renderiza nada sin ayuda", () => {
    render(<NodeHelpCard meta={nodeMeta("end")} />);
    expect(screen.queryByTestId("wf-node-help")).toBeNull();
  });
});
