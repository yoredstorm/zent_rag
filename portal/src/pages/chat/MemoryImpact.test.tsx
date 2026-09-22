import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DecisionSignals, MemoryImpact, type ImpactItem, type QueryImpact } from "./MemoryImpact";

function item(overrides: Partial<ImpactItem> = {}): ImpactItem {
  return {
    memory_id: "11111111-1111-1111-1111-111111111111",
    display_id: "11111111",
    title: "Consulta exacta ATPCO",
    memory_type: "operational",
    status: "active",
    confidence: 0.92,
    support_count: 84,
    success_rate: 0.971,
    phase: "pre_retrieval",
    outcome: "knowledge.answer",
    needs_evidence: false,
    previous_support: null,
    previous_confidence: null,
    support_after: null,
    confidence_after: null,
    ...overrides,
  };
}

function impact(overrides: Partial<QueryImpact> = {}): QueryImpact {
  return {
    query_id: "q",
    truncated: false,
    counts: { used: 1, created: 0, reinforced: 0, contradicted: 0, validated: 0 },
    used: [item()],
    created: [],
    reinforced: [],
    contradicted: [],
    validated: [],
    ...overrides,
  };
}

describe("MemoryImpact", () => {
  it("muestra conteos, incluido un cero", () => {
    render(<MemoryImpact state="ready" impact={impact()} />);
    expect(screen.getByText("Usadas")).toBeInTheDocument();
    expect(screen.getByText("Contradichas")).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Consulta exacta ATPCO")).toBeInTheDocument();
    expect(screen.getByText("Estado actual de la memoria")).toBeInTheDocument();
    expect(screen.getByText(/97\.1%/)).toBeInTheDocument();
    expect(screen.getByText(/Estrategia de búsqueda/)).toBeInTheDocument();
  });

  it("vacío", () => {
    render(
      <MemoryImpact
        state="ready"
        impact={impact({
          counts: { used: 0, created: 0, reinforced: 0, contradicted: 0, validated: 0 },
          used: [],
        })}
      />,
    );
    expect(screen.getByText("Esta respuesta no usó ni creó memoria.")).toBeInTheDocument();
  });

  it("observación creada pide más evidencia", () => {
    render(
      <MemoryImpact
        state="ready"
        impact={impact({
          counts: { used: 0, created: 1, reinforced: 0, contradicted: 0, validated: 0 },
          used: [],
          created: [
            item({
              status: "observed",
              needs_evidence: true,
              confidence: null,
              support_count: null,
              success_rate: null,
              confidence_after: 0.56,
              support_after: 1,
            }),
          ],
        })}
      />,
    );
    expect(
      screen.getByText("Esta observación necesita más evidencia antes de influir en producción."),
    ).toBeInTheDocument();
    expect(screen.getByText("Observada")).toBeInTheDocument();
    expect(screen.getByText(/0\.56/)).toBeInTheDocument();
  });

  it("refuerzo con anterior y posterior", () => {
    render(
      <MemoryImpact
        state="ready"
        impact={impact({
          counts: { used: 0, created: 0, reinforced: 1, contradicted: 0, validated: 0 },
          used: [],
          reinforced: [
            item({
              status: "reinforced",
              confidence: null,
              support_count: null,
              success_rate: null,
              previous_support: 83,
              support_after: 84,
              previous_confidence: 0.91,
              confidence_after: 0.92,
            }),
          ],
        })}
      />,
    );
    expect(screen.getByText(/83 a/)).toBeInTheDocument();
    expect(screen.getByText("84")).toBeInTheDocument();
    expect(screen.getByText(/0\.91 a/)).toBeInTheDocument();
    expect(screen.getByText("0.92")).toBeInTheDocument();
  });

  it("refuerzo sin anterior no dibuja la flecha", () => {
    render(
      <MemoryImpact
        state="ready"
        impact={impact({
          counts: { used: 0, created: 0, reinforced: 1, contradicted: 0, validated: 0 },
          used: [],
          reinforced: [
            item({
              status: "reinforced",
              confidence: null,
              support_count: null,
              success_rate: null,
              previous_support: null,
              support_after: 84,
              previous_confidence: null,
              confidence_after: 0.92,
            }),
          ],
        })}
      />,
    );
    expect(screen.queryByText(/ a /)).toBeNull();
    expect(screen.getByText("84")).toBeInTheDocument();
    expect(screen.getByText("0.92")).toBeInTheDocument();
  });

  it("muestra memoria contradicha", () => {
    render(
      <MemoryImpact
        state="ready"
        impact={impact({
          counts: { used: 0, created: 0, reinforced: 0, contradicted: 1, validated: 0 },
          used: [],
          contradicted: [item({ title: "Patrón en conflicto", status: "contradicted" })],
        })}
      />,
    );
    expect(screen.getByText("Patrón en conflicto")).toBeInTheDocument();
    expect(screen.getByText("Contradicha")).toBeInTheDocument();
  });

  it("oculta el grupo validada cuando el conteo es cero", () => {
    render(<MemoryImpact state="ready" impact={impact()} />);
    expect(screen.queryByRole("heading", { name: "Validadas en esta respuesta" })).toBeNull();
  });

  it("muestra validadas cuando el conteo es mayor que cero", () => {
    render(
      <MemoryImpact
        state="ready"
        impact={impact({
          counts: { used: 0, created: 0, reinforced: 0, contradicted: 0, validated: 1 },
          used: [],
          validated: [item({ title: "Lookup validado", status: "validated" })],
        })}
      />,
    );
    expect(screen.getByRole("heading", { name: "Validadas en esta respuesta" })).toBeInTheDocument();
    expect(screen.getByText("Validada")).toBeInTheDocument();
  });

  it("error de carga", () => {
    render(<MemoryImpact state="error" impact={null} />);
    expect(screen.getByText("No se pudo cargar la memoria de esta respuesta.")).toBeInTheDocument();
  });
});

describe("DecisionSignals", () => {
  it("lista ruta, JEV y memoria, y no pinta chain-of-thought", () => {
    render(
      <DecisionSignals
        flow={{
          verdict: { route: "Documentos" },
          jev: { used: true, score: 0.92, verdict: "approve" },
          reasoning: "NO-MOSTRAR-CADENA",
          prompt: "hidden prompt",
          chain_of_thought: "paso interno",
        }}
        used={[item()]}
        impactReady
      />,
    );
    expect(screen.getByText("Ruta Documentos")).toBeInTheDocument();
    expect(screen.getByText("0.92")).toBeInTheDocument();
    expect(screen.getByText(/aprobada/)).toBeInTheDocument();
    expect(screen.getByText("Consulta exacta ATPCO")).toBeInTheDocument();
    expect(screen.getByText(/97\.1%/)).toBeInTheDocument();
    expect(screen.queryByText("NO-MOSTRAR-CADENA")).toBeNull();
    expect(screen.queryByText("hidden prompt")).toBeNull();
    expect(screen.queryByText("paso interno")).toBeNull();
  });

  it("no lista memorias mientras el impacto carga o falla", () => {
    const { rerender } = render(
      <DecisionSignals
        flow={{ verdict: { route: "SQL" } }}
        used={[item({ title: "No debe verse" })]}
        impactReady={false}
      />,
    );
    expect(screen.queryByText("No debe verse")).toBeNull();
    rerender(
      <DecisionSignals
        flow={{ verdict: { route: "SQL" }, reasoning: "NO-MOSTRAR-CADENA" }}
        used={[item({ title: "No debe verse" })]}
        impactReady={false}
      />,
    );
    expect(screen.queryByText("NO-MOSTRAR-CADENA")).toBeNull();
  });
});
